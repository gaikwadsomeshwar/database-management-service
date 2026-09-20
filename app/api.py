"""Authenticated Flask REST API for querying student records across per-state SQL servers."""

import concurrent.futures
import logging
import os
import threading
import time
from functools import wraps
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    verify_jwt_in_request,
)
from flask_jwt_extended.exceptions import (
    InvalidHeaderError,
    JWTDecodeError,
    NoAuthorizationError,
)
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from flask_restful import Api, Resource
from flask_swagger_ui import get_swaggerui_blueprint
from prometheus_client import Counter, Gauge, Histogram, generate_latest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

import sys
sys.path.insert(0, str(PROJECT_ROOT / "app"))

from cluster_status import get_scaling_snapshot  # noqa: E402
from state_populations import STATE_POPULATIONS  # noqa: E402
from sql_executor import database_url, execute_sql_script, resolve_mysql_host  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

API_REQUESTS = Counter(
    "student_api_requests_total",
    "Total HTTP requests received by the student API.",
    ("method", "endpoint", "status"),
)
API_RESPONSE_TIME = Histogram(
    "student_api_response_duration_seconds",
    "HTTP response time for the student API.",
    ("method", "endpoint"),
)
# Proxy for request "queue depth": requests currently being handled, used by
# the proactive scaler's horizontal recommendation as an immediate load signal.
ACTIVE_REQUESTS = Gauge(
    "student_api_active_requests",
    "Number of HTTP requests currently being processed by this pod.",
)

app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY")
if not app.config["JWT_SECRET_KEY"]:
    raise RuntimeError("JWT_SECRET_KEY must be configured.")

app.config["JWT_ACCESS_TOKEN_EXPIRES"] = int(
    os.getenv("JWT_ACCESS_TOKEN_EXPIRES_MINUTES", "60")
) * 60
# Register JWT validation and token creation with the Flask application.
JWTManager(app)
api = Api(app)


@app.before_request
def start_request_metrics():
    """Start the timer used by the request response-time histogram."""
    request.environ["student_api_request_started"] = time.perf_counter()
    ACTIVE_REQUESTS.inc()


@app.after_request
def record_request_metrics(response):
    """Record method, route, status code, and response duration for requests."""
    started = request.environ.get("student_api_request_started")
    duration = time.perf_counter() - started if started else 0
    endpoint = request.url_rule.rule if request.url_rule else request.path
    API_REQUESTS.labels(request.method, endpoint, str(response.status_code)).inc()
    API_RESPONSE_TIME.labels(request.method, endpoint).observe(duration)
    return response


@app.teardown_request
def stop_request_metrics(exception=None):
    """Decrement the in-flight gauge even if the request raised an exception."""
    ACTIVE_REQUESTS.dec()


def jwt_required_json(function):
    """Protect a resource method while keeping JWT errors JSON formatted."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            verify_jwt_in_request()
        except ExpiredSignatureError:
            return {"message": "JWT has expired"}, 401
        except (
            NoAuthorizationError,
            InvalidHeaderError,
            JWTDecodeError,
            InvalidTokenError,
        ):
            return {"message": "A valid Bearer JWT is required"}, 401
        return function(*args, **kwargs)

    return wrapped


SWAGGER_URL = "/api/docs"
API_URL = "/swagger.json"
swagger_blueprint = get_swaggerui_blueprint(
    SWAGGER_URL,
    API_URL,
    config={"app_name": "Student Database API"},
)
app.register_blueprint(swagger_blueprint, url_prefix=SWAGGER_URL)


# ----------------------------------------------------------------------
# Distributed Per-State Database Engine Management
# ----------------------------------------------------------------------
_ENGINES = {}
_ENGINES_LOCK = threading.Lock()


def build_database_url_for_state(state_code=None):
    """Build MySQL SQLAlchemy connection URL targeting a specific state's database & host."""
    base_database = os.getenv("MYSQL_DATABASE", "students_db")
    return database_url(base_database, state=state_code)


def get_engine_for_state(state_code=None):
    """Retrieve or create a cached SQLAlchemy engine for a state's SQL server."""
    key = state_code.strip().lower() if state_code else "__default__"
    with _ENGINES_LOCK:
        if key not in _ENGINES:
            url = build_database_url_for_state(state_code)
            _ENGINES[key] = create_engine(
                url,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=10,
                pool_recycle=1800,
            )
        return _ENGINES[key]


# Columns returned by every state table and exposed by the API.
STUDENT_FIELDS = (
    "student_id",
    "first_name",
    "last_name",
    "date_of_birth",
    "email",
    "phone_number",
    "city",
    "state",
    "enrollment_date",
    "created_at",
)
# Only these columns may be used in ORDER BY to prevent SQL injection.
SORT_FIELDS = set(STUDENT_FIELDS)
SELECT_STUDENT_FIELDS = "SELECT " + ", ".join(STUDENT_FIELDS)
JWT_ERROR_DESCRIPTION = "Missing or invalid JWT"
# Map public state codes to fixed table names; only this allow-list is queried.
STATE_TABLES = {
    state_code: f"student_{state_code}"
    for state_code in STATE_POPULATIONS
}


def state_table(state_code):
    """Resolve a safe state code to its generated table name."""
    if state_code is None:
        return None
    return STATE_TABLES.get(state_code.strip().lower())


def serialize_student(row):
    """Convert a database row into a JSON-safe student object."""
    student = dict(row._mapping)
    for field in ("date_of_birth", "enrollment_date", "created_at"):
        if student[field] is not None:
            student[field] = student[field].isoformat()
    return student


class LoginResource(Resource):
    """Issue a JWT for the configured API user.

    Send JSON containing API_USERNAME and API_PASSWORD values to receive a token.
    The token must be sent as `Authorization: Bearer <token>` to protected routes.
    """

    def post(self):
        credentials = request.get_json(silent=True) or {}
        expected_username = os.getenv("API_USERNAME")
        expected_password = os.getenv("API_PASSWORD")

        if (
            not expected_username
            or expected_password is None
            or credentials.get("username") != expected_username
            or credentials.get("password") != expected_password
        ):
            logger.warning("Rejected API login attempt")
            return {"message": "Invalid credentials"}, 401

        token = create_access_token(identity=expected_username)
        return {"access_token": token}, 200


def query_state_students(state_code, table_name, where_clause, parameters, order_by_clause, limit):
    """Query count and top rows from one state's dedicated SQL server."""
    eng = get_engine_for_state(state_code)
    count_sql = text(f"SELECT COUNT(*) FROM `{table_name}` {where_clause}")
    data_sql = text(
        SELECT_STUDENT_FIELDS
        + f" FROM `{table_name}` {where_clause} {order_by_clause} LIMIT :limit"
    )
    with eng.connect() as conn:
        count = conn.execute(count_sql, parameters).scalar_one()
        rows = conn.execute(data_sql, {**parameters, "limit": limit}).fetchall()
        return count, rows


class StudentListResource(Resource):
    """Return a paginated, filtered, and sorted student collection.

    Use the `state` query parameter (e.g. `maharashtra`) to query that state's
    dedicated SQL server directly. Omit `state` to query across all 28 state
    servers concurrently with parallel fan-out.
    """

    @jwt_required_json
    def get(self):
        try:
            page = request.args.get("page", 1, type=int)
            per_page = request.args.get("per_page", 50, type=int)
            selected_state = request.args.get("state")
            sort_by = request.args.get("sort_by", "student_id")
            sort_order = request.args.get("sort_order", "asc").lower()

            if page < 1 or per_page < 1 or per_page > 1000:
                return {"message": "page must be >= 1 and per_page must be 1-1000"}, 400
            if sort_by not in SORT_FIELDS:
                return {"message": f"Unsupported sort_by: {sort_by}"}, 400
            if sort_order not in {"asc", "desc"}:
                return {"message": "sort_order must be asc or desc"}, 400

            conditions = []
            parameters = {}
            filter_fields = ("first_name", "last_name", "email", "city")
            for field in filter_fields:
                value = request.args.get(field)
                if value:
                    conditions.append(f"{field} LIKE :{field}")
                    parameters[field] = f"%{value}%"

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            order_sql = "DESC" if sort_order == "desc" else "ASC"
            order_by_clause = f"ORDER BY {sort_by} {order_sql}"

            # ------------------------------------------------------------------
            # Scenario A: Targeted single-state query -> direct to that state's SQL server
            # ------------------------------------------------------------------
            if selected_state:
                table = state_table(selected_state)
                if not table:
                    return {"message": f"Unsupported state: {selected_state}"}, 400

                state_code = selected_state.strip().lower()
                eng = get_engine_for_state(state_code)
                offset = (page - 1) * per_page
                state_params = {**parameters, "limit": per_page, "offset": offset}

                count_query = text(f"SELECT COUNT(*) FROM `{table}` {where_clause}")
                data_query = text(
                    SELECT_STUDENT_FIELDS
                    + f" FROM `{table}` {where_clause} {order_by_clause} LIMIT :limit OFFSET :offset"
                )

                with eng.connect() as connection:
                    total = connection.execute(count_query, state_params).scalar_one()
                    rows = connection.execute(data_query, state_params).fetchall()

                return {
                    "data": [serialize_student(row) for row in rows],
                    "pagination": {
                        "page": page,
                        "per_page": per_page,
                        "total": total,
                        "pages": (total + per_page - 1) // per_page,
                    },
                }, 200

            # ------------------------------------------------------------------
            # Scenario B: Global query across all 28 state SQL servers (parallel fan-out)
            # ------------------------------------------------------------------
            total = 0
            all_rows = []
            max_fetch_per_state = page * per_page

            with concurrent.futures.ThreadPoolExecutor(max_workers=min(28, len(STATE_TABLES))) as executor:
                futures = {
                    executor.submit(
                        query_state_students,
                        state_code,
                        tbl,
                        where_clause,
                        parameters,
                        order_by_clause,
                        max_fetch_per_state,
                    ): state_code
                    for state_code, tbl in STATE_TABLES.items()
                }
                for future in concurrent.futures.as_completed(futures):
                    try:
                        st_count, st_rows = future.result()
                        total += st_count
                        all_rows.extend(st_rows)
                    except Exception:
                        st_code = futures[future]
                        logger.warning("Failed to query state %s during fan-out", st_code, exc_info=True)

            # Sort combined results in Python
            reverse = (sort_order == "desc")
            all_rows.sort(
                key=lambda r: getattr(r, sort_by) or "",
                reverse=reverse,
            )

            offset = (page - 1) * per_page
            paged_rows = all_rows[offset : offset + per_page]

            return {
                "data": [serialize_student(row) for row in paged_rows],
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total": total,
                    "pages": (total + per_page - 1) // per_page if total else 1,
                },
            }, 200

        except SQLAlchemyError:
            logger.exception("Failed to query students")
            return {"message": "Database query failed"}, 503


class StudentResource(Resource):
    """Return one student by numeric ID from a selected state's dedicated SQL server."""

    @jwt_required_json
    def get(self, student_id):
        selected_state = request.args.get("state")
        if not selected_state:
            return {"message": "state query parameter is required"}, 400

        table = state_table(selected_state)
        if not table:
            return {"message": f"Unsupported state: {selected_state}"}, 400

        state_code = selected_state.strip().lower()
        try:
            eng = get_engine_for_state(state_code)
            with eng.connect() as connection:
                row = connection.execute(
                    text(
                        SELECT_STUDENT_FIELDS
                        + f" FROM `{table}` WHERE student_id = :student_id"
                    ),
                    {"student_id": student_id},
                ).fetchone()
            if row is None:
                return {"message": "Student not found"}, 404
            return serialize_student(row), 200
        except SQLAlchemyError:
            logger.exception("Failed to query student %s for state %s", student_id, selected_state)
            return {"message": "Database query failed"}, 503


class SqlExecutionResource(Resource):
    """Execute a safe SQL script against a state's dedicated SQL server.

    JSON body: ``database``, ``sql``, optional ``state``, ``rollback``, and ``rollback_sql``.
    Automatically routes to the target state's SQL server if ``state`` is provided
    or if the SQL statements reference a ``student_<state>`` table.
    """

    @jwt_required_json
    def post(self):
        payload = request.get_json(silent=True) or {}
        database = payload.get("database")
        sql_content = payload.get("sql")
        state = payload.get("state")
        rollback = payload.get("rollback", False)
        rollback_sql = payload.get("rollback_sql")

        if not isinstance(database, str) or not database.strip():
            return {"message": "database is required"}, 400
        if not isinstance(sql_content, str) or not sql_content.strip():
            return {"message": "sql is required"}, 400
        if not isinstance(rollback, bool):
            return {"message": "rollback must be boolean"}, 400

        try:
            result = execute_sql_script(
                database=database.strip(),
                sql_content=sql_content,
                rollback=rollback,
                rollback_sql=rollback_sql,
                state=state.strip().lower() if isinstance(state, str) and state.strip() else None,
            )
            return result, 200
        except ValueError as error:
            logger.warning("Rejected SQL execution request: %s", error)
            return {"message": str(error)}, 400
        except SQLAlchemyError:
            logger.exception("Database SQL execution failed")
            return {"message": "Database execution failed"}, 503
        except Exception:
            logger.exception("Unexpected SQL execution failure")
            return {"message": "SQL execution failed"}, 500


api.add_resource(LoginResource, "/api/auth/login")
api.add_resource(StudentListResource, "/api/students")
api.add_resource(StudentResource, "/api/students/<int:student_id>")
api.add_resource(SqlExecutionResource, "/api/sql/execute")


@app.get("/swagger.json")
@app.get("/static/swagger.json")
def swagger_spec():
    """Serve the OpenAPI document used by Swagger UI."""
    return jsonify(SWAGGER_SPEC)


@app.get("/docs")
@app.get("/docs/")
@app.get("/api/docs")
def docs_redirect():
    """Redirect alternative documentation routes to /api/docs/."""
    return redirect("/api/docs/")


@app.get("/metrics")
def metrics():
    """Expose Prometheus metrics for scraping."""
    return generate_latest(), 200, {"Content-Type": "text/plain; version=0.0.4; charset=utf-8"}


@app.get("/dashboard")
def dashboard():
    """Serve the reactive-vs-proactive autoscaling comparison dashboard."""
    return render_template("dashboard.html")


@app.get("/api/scaling/status")
def scaling_status():
    """Return a live snapshot comparing reactive HPA and proactive KEDA scaling."""
    return jsonify(get_scaling_snapshot()), 200


@app.get("/health")
def health():
    """Return API and database availability without requiring authentication."""
    try:
        # Check database connectivity against default or sample state SQL server
        sample_state = next(iter(STATE_POPULATIONS.keys()))
        eng = get_engine_for_state(sample_state)
        with eng.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok"}, 200
    except SQLAlchemyError:
        logger.exception("Health check database failure")
        return {"status": "database unavailable"}, 503


SWAGGER_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "Student Database API",
        "version": "2.0.0",
        "description": "JWT-protected API for querying distributed per-state Indian student SQL servers.",
    },
    "servers": [{"url": "http://localhost:5000"}],
    "components": {
        "securitySchemes": {
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            }
        }
    },
    "paths": {
        "/health": {
            "get": {
                "summary": "Check API and database health",
                "responses": {"200": {"description": "Healthy"}},
            }
        },
        "/metrics": {
            "get": {
                "summary": "Expose Prometheus metrics",
                "responses": {"200": {"description": "Prometheus text format metrics"}},
            }
        },
        "/api/auth/login": {
            "post": {
                "summary": "Get a JWT access token",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["username", "password"],
                                "properties": {
                                    "username": {"type": "string"},
                                    "password": {"type": "string", "format": "password"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "JWT token returned"},
                    "401": {"description": "Invalid credentials"},
                },
            }
        },
        "/api/students": {
            "get": {
                "summary": "List, filter, and sort students across per-state SQL servers",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                    {"name": "per_page", "in": "query", "schema": {"type": "integer", "default": 50, "maximum": 1000}},
                    {"name": "state", "in": "query", "description": "State code to query dedicated SQL server (e.g. maharashtra). Omit to query all state servers.", "schema": {"type": "string"}},
                    {"name": "first_name", "in": "query", "schema": {"type": "string"}},
                    {"name": "last_name", "in": "query", "schema": {"type": "string"}},
                    {"name": "email", "in": "query", "schema": {"type": "string"}},
                    {"name": "city", "in": "query", "schema": {"type": "string"}},
                    {"name": "sort_by", "in": "query", "schema": {"type": "string", "default": "student_id"}},
                    {"name": "sort_order", "in": "query", "schema": {"type": "string", "enum": ["asc", "desc"], "default": "asc"}},
                ],
                "responses": {
                    "200": {"description": "Student page returned"},
                    "401": {"description": JWT_ERROR_DESCRIPTION},
                },
            }
        },
        "/api/students/{student_id}": {
            "get": {
                "summary": "Get one student from a specific state's SQL server",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    {"name": "student_id", "in": "path", "required": True, "schema": {"type": "integer"}},
                    {"name": "state", "in": "query", "required": True, "description": "State code (e.g. maharashtra).", "schema": {"type": "string"}},
                ],
                "responses": {
                    "200": {"description": "Student returned"},
                    "404": {"description": "Student not found"},
                    "401": {"description": JWT_ERROR_DESCRIPTION},
                },
            }
        },
        "/api/sql/execute": {
            "post": {
                "summary": "Execute a safe SQL script against a state's dedicated SQL server",
                "description": "Requires database and sql. Optional state targets specific SQL server. Auto-detected from student_<state> table if omitted. DROP and DELETE are rejected.",
                "security": [{"bearerAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["database", "sql"],
                                "properties": {
                                    "database": {"type": "string", "example": "students_db"},
                                    "state": {"type": "string", "example": "maharashtra"},
                                    "sql": {"type": "string", "example": "ALTER TABLE student_maharashtra RENAME COLUMN city TO city_name;"},
                                    "rollback": {"type": "boolean", "default": False},
                                    "rollback_sql": {"type": "string", "example": "ALTER TABLE student_maharashtra RENAME COLUMN city_name TO city;"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "SQL executed with host, timing, and status"},
                    "400": {"description": "Invalid or forbidden SQL"},
                    "401": {"description": JWT_ERROR_DESCRIPTION},
                    "503": {"description": "Database execution failure"},
                },
            }
        },
    },
}


if __name__ == "__main__":
    app.run(
        host=os.getenv("API_HOST", "127.0.0.1"),
        port=int(os.getenv("API_PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
    )
