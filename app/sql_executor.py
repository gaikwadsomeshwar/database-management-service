"""Safe, logged MySQL script execution with per-state database routing.

Supports distributed multi-server architecture with one SQL server per Indian
state. Scripts targeting a specific state table (e.g. `student_maharashtra`) are
automatically routed to that state's dedicated SQL server (e.g. `mysql-maharashtra`).
"""

import configparser
import logging
import os
import re
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "app"))
from urllib.parse import quote_plus
from dotenv import load_dotenv
from state_populations import STATE_SERVER_MAP  # noqa: E402
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")
logger = logging.getLogger(__name__)

# MySQL identifiers cannot be bound as query parameters, so validate database
# names before inserting them into a connection URL.
IDENTIFIER_PATTERN = re.compile(r"^\w+$", re.ASCII)
ALTER_TABLE_PATTERN = re.compile(
    r"^\s*ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?`?(\w+)`?",
    re.IGNORECASE,
)
FORBIDDEN_PATTERN = re.compile(
    r"\b(DROP\s+(?:DATABASE|TABLE)|DELETE)\b",
    re.IGNORECASE,
)
CREATE_PROCEDURE_PATTERN = re.compile(
    r"\bCREATE\s+PROCEDURE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(\w+)`?",
    re.IGNORECASE,
)
CREATE_TRIGGER_PATTERN = re.compile(
    r"\bCREATE\s+TRIGGER\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(\w+)`?",
    re.IGNORECASE,
)
STUDENT_TABLE_PATTERN = re.compile(r"\bstudent_([a-z_]+)\b", re.IGNORECASE)
TABLE_LOCKS = defaultdict(threading.Lock)


def parse_sql_statements(sql_content):
    """Split a MySQL script into statements, including DELIMITER blocks."""
    statements = []
    buffer = []
    delimiter = ";"

    for line in sql_content.splitlines(keepends=True):
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and parts[0].upper() == "DELIMITER":
            if buffer and "".join(buffer).strip():
                raise ValueError("DELIMITER found before statement completion")
            delimiter = parts[1].strip()
            continue

        buffer.append(line)
        current = "".join(buffer).rstrip()
        if current.endswith(delimiter):
            statement = current[: -len(delimiter)].strip()
            if statement:
                statements.append(statement)
            buffer = []

    remaining = "".join(buffer).strip()
    if remaining:
        statements.append(remaining)
    return statements


def validate_statements(statements):
    """Reject destructive statements before opening a database transaction."""
    for number, statement in enumerate(statements, start=1):
        if FORBIDDEN_PATTERN.search(statement):
            raise ValueError(
                f"Statement {number} contains forbidden DROP or DELETE SQL."
            )





def infer_state_from_sql(sql_content):
    """Detect the Indian state code from `student_<state>` table references in SQL."""
    match = STUDENT_TABLE_PATTERN.search(sql_content)
    if match:
        return match.group(1).lower()
    return None


def resolve_mysql_host(state=None):
    """Resolve the target MySQL hostname for a given state across 7 SQL servers.

    Maps 28 states into 7 MySQL servers (`mysql-1` through `mysql-7`), with
    4 state databases hosted per server.
    """
    if state:
        state_code = state.strip().lower().removeprefix("student_")
        if state_code in STATE_SERVER_MAP:
            return STATE_SERVER_MAP[state_code]
        state_slug = state_code.replace("_", "-")
        template = os.getenv("MYSQL_HOST_TEMPLATE", "mysql-{state}")
        return template.format(state=state_slug)

    return os.getenv("MYSQL_HOST", "127.0.0.1")


def resolve_mysql_database(database, state=None):
    """Resolve the database name for a state on its target SQL server."""
    if state:
        state_code = state.strip().lower().removeprefix("student_")
        return f"{database}_{state_code}"
    return database


def database_url(database, state=None):
    """Build a connection URL for the target database and state's SQL server."""
    target_database = resolve_mysql_database(database, state)
    if not target_database or not IDENTIFIER_PATTERN.fullmatch(target_database):
        raise ValueError(
            "database must contain only letters, numbers, and underscores."
        )

    config = configparser.ConfigParser()
    config_path = Path(
        os.getenv("DB_CONFIG_FILE", PROJECT_ROOT / "app" / "database.ini")
    )
    if config_path.exists():
        config.read(config_path)
    section = config["database"] if config.has_section("database") else {}

    def setting(name, default=None):
        return os.getenv(name, section.get(name.lower(), default))

    # If state is provided or inferred, route to that state's assigned SQL server.
    if state:
        host = resolve_mysql_host(state)
    else:
        existing_url = setting("DATABASE_URL")
        if existing_url and target_database == setting("MYSQL_DATABASE"):
            return existing_url
        host = setting("MYSQL_HOST", "127.0.0.1")

    port = setting("MYSQL_PORT", "3306")
    username = setting("MYSQL_USER", "root")
    password = setting("MYSQL_PASSWORD")
    if not username or password is None:
        raise ValueError("MYSQL_USER and MYSQL_PASSWORD must be configured.")

    return (
        "mysql+pymysql://"
        f"{quote_plus(username)}:{quote_plus(password)}@"
        f"{quote_plus(host)}:{quote_plus(port)}/{quote_plus(target_database)}"
    )



def table_for_alter(statement):
    """Return the normalized ALTER TABLE target, or None for other SQL."""
    match = ALTER_TABLE_PATTERN.match(statement)
    return match.group(1).lower() if match else None


def execute_sql_script(database, sql_content, rollback=False, rollback_sql=None, state=None):
    """Execute safe SQL and return timing/status details.

    Routes execution to the designated state's dedicated SQL server. If `state`
    is omitted, attempts to infer the target state from `student_<state>` table
    references within the SQL script.

    ALTER TABLE statements are serialized per table. Since MySQL implicitly
    commits most DDL, an ALTER rollback requires explicit inverse SQL supplied
    as ``rollback_sql``; ordinary DML errors still roll back transactionally.
    """
    started_at = datetime.now(timezone.utc)
    start = time.perf_counter()
    statements = parse_sql_statements(sql_content)
    if not statements:
        raise ValueError("SQL script is empty.")
    validate_statements(statements)

    # Resolve target state from explicit argument or SQL content
    target_state = state or infer_state_from_sql(sql_content)
    target_url = database_url(database, state=target_state)
    target_host = resolve_mysql_host(target_state)

    alter_tables = {table_for_alter(statement) for statement in statements}
    alter_tables.discard(None)
    if rollback and alter_tables and not rollback_sql:
        raise ValueError(
            "rollback_sql is required when rollback=true includes ALTER TABLE."
        )
    if rollback_sql is not None and not isinstance(rollback_sql, str):
        raise ValueError("rollback_sql must be a string when provided.")

    locks = [TABLE_LOCKS[table] for table in sorted(alter_tables)]
    for lock in locks:
        lock.acquire()

    try:
        engine = create_engine(target_url, pool_pre_ping=True)
        with engine.begin() as connection:
            for number, statement in enumerate(statements, start=1):
                logger.info(
                    "Executing statement=%d database=%s host=%s state=%s alter_table=%s",
                    number,
                    database,
                    target_host,
                    target_state,
                    table_for_alter(statement),
                )
                proc_match = CREATE_PROCEDURE_PATTERN.search(statement)
                if proc_match:
                    proc_name = proc_match.group(1)
                    connection.execute(text(f"DROP PROCEDURE IF EXISTS `{proc_name}`"))


                trig_match = CREATE_TRIGGER_PATTERN.search(statement)
                if trig_match:
                    trig_name = trig_match.group(1)
                    connection.execute(text(f"DROP TRIGGER IF EXISTS `{trig_name}`"))

                # Use text() so SQLAlchemy treats the SQL as raw DDL and PyMySQL
                # does not interpret % characters (e.g. in LIKE CONCAT('%',...,'%'))
                # as Python format specifiers.
                connection.execute(text(statement))

            if rollback and rollback_sql:
                rollback_statements = parse_sql_statements(rollback_sql)
                validate_statements(rollback_statements)
                for statement in rollback_statements:
                    connection.execute(text(statement))

                logger.warning(
                    "Rollback SQL executed by request database=%s host=%s state=%s",
                    database,
                    target_host,
                    target_state,
                )

        finished_at = datetime.now(timezone.utc)
        result = {
            "status": "rolled_back" if rollback else "success",
            "database": database,
            "target_state": target_state,
            "target_host": target_host,
            "statement_count": len(statements),
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_ms": round((time.perf_counter() - start) * 1000, 2),
            "queued_tables": sorted(alter_tables),
        }
        logger.info("SQL script completed: %s", result)
        return result
    except (ValueError, SQLAlchemyError):
        finished_at = datetime.now(timezone.utc)
        logger.exception(
            "SQL script failed database=%s host=%s state=%s started_at=%s finished_at=%s duration_ms=%.2f",
            database,
            target_host,
            target_state,
            started_at.isoformat(),
            finished_at.isoformat(),
            (time.perf_counter() - start) * 1000,
        )
        raise
    finally:
        for lock in reversed(locks):
            lock.release()
