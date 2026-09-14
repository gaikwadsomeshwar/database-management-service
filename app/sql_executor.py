"""Safe, logged MySQL script execution shared by the CLI and API."""

import configparser
import logging
import os
import re
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
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
FORBIDDEN_PATTERN = re.compile(r"\b(DROP|DELETE)\b", re.IGNORECASE)
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


def database_url(database):
    """Build a connection URL for the database named by the request."""
    if not database or not IDENTIFIER_PATTERN.fullmatch(database):
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

    existing_url = setting("DATABASE_URL")
    if existing_url and database == setting("MYSQL_DATABASE"):
        return existing_url

    host = setting("MYSQL_HOST", "localhost")
    port = setting("MYSQL_PORT", "3306")
    username = setting("MYSQL_USER")
    password = setting("MYSQL_PASSWORD")
    if not username or password is None:
        raise ValueError("MYSQL_USER and MYSQL_PASSWORD must be configured.")

    return (
        "mysql+pymysql://"
        f"{quote_plus(username)}:{quote_plus(password)}@"
        f"{quote_plus(host)}:{quote_plus(port)}/{quote_plus(database)}"
    )


def table_for_alter(statement):
    """Return the normalized ALTER TABLE target, or None for other SQL."""
    match = ALTER_TABLE_PATTERN.match(statement)
    return match.group(1).lower() if match else None


def execute_sql_script(database, sql_content, rollback=False, rollback_sql=None):
    """Execute safe SQL and return timing/status details.

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
        engine = create_engine(database_url(database), pool_pre_ping=True)
        with engine.begin() as connection:
            for number, statement in enumerate(statements, start=1):
                logger.info(
                    "Executing statement=%d database=%s alter_table=%s",
                    number,
                    database,
                    table_for_alter(statement),
                )
                connection.exec_driver_sql(statement)

            if rollback and rollback_sql:
                rollback_statements = parse_sql_statements(rollback_sql)
                validate_statements(rollback_statements)
                for statement in rollback_statements:
                    connection.exec_driver_sql(statement)
                logger.warning(
                    "Rollback SQL executed by request database=%s", database
                )

        finished_at = datetime.now(timezone.utc)
        result = {
            "status": "rolled_back" if rollback else "success",
            "database": database,
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
            "SQL script failed database=%s started_at=%s finished_at=%s duration_ms=%.2f",
            database,
            started_at.isoformat(),
            finished_at.isoformat(),
            (time.perf_counter() - start) * 1000,
        )
        raise
    finally:
        for lock in reversed(locks):
            lock.release()
