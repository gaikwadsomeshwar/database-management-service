import configparser
import logging
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)


def wait_for_database(engine, attempts=30, delay_seconds=2):
    """Wait for MySQL to accept connections during container startup."""
    for attempt in range(1, attempts + 1):
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1")
            return
        except SQLAlchemyError:
            if attempt == attempts:
                raise
            logger.warning(
                "Database is not ready (attempt %d/%d); retrying in %d seconds",
                attempt,
                attempts,
                delay_seconds,
            )
            time.sleep(delay_seconds)


def load_database_config():
    """Load database settings from environment variables or database.ini."""
    config = configparser.ConfigParser()
    config_path = Path(
        os.getenv("DB_CONFIG_FILE", Path(__file__).with_name("database.ini"))
    )

    if config_path.exists():
        config.read(config_path)

    section = config["database"] if config.has_section("database") else {}

    def get_setting(name, default=None):
        return os.getenv(name, section.get(name.lower(), default))

    database_url = get_setting("DATABASE_URL")
    if database_url:
        return database_url

    host = get_setting("MYSQL_HOST", "localhost")
    port = get_setting("MYSQL_PORT", "3306")
    database = get_setting("MYSQL_DATABASE")
    username = get_setting("MYSQL_USER")
    password = get_setting("MYSQL_PASSWORD")

    if not database:
        raise ValueError(
            "MYSQL_DATABASE must be configured."
        )

    if not username or password is None:
        raise ValueError(
            "MYSQL_USER and MYSQL_PASSWORD must be configured."
        )

    return (
        "mysql+pymysql://"
        f"{quote_plus(username)}:{quote_plus(password)}@"
        f"{quote_plus(host)}:{quote_plus(port)}/{quote_plus(database)}"
    )


def parse_sql_statements(sql_content):
    """Split a MySQL script into statements, including DELIMITER blocks."""
    statements = []
    buffer = []
    delimiter = ";"

    for line in sql_content.splitlines(keepends=True):
        delimiter_match = line.strip().split(maxsplit=1)
        if (
            len(delimiter_match) == 2
            and delimiter_match[0].upper() == "DELIMITER"
        ):
            if buffer and "".join(buffer).strip():
                raise ValueError(
                    "DELIMITER cannot appear before the previous statement "
                    "is complete."
                )
            delimiter = delimiter_match[1].strip()
            continue

        buffer.append(line)
        current_statement = "".join(buffer).rstrip()
        if current_statement.endswith(delimiter):
            statement = current_statement[: -len(delimiter)].strip()
            if statement:
                statements.append(statement)
            buffer = []

    remaining = "".join(buffer).strip()
    if remaining:
        statements.append(remaining)

    return statements


def execute_sql_file(sql_file_path):
    sql_file = Path(sql_file_path)

    if not sql_file.exists():
        raise FileNotFoundError(f"SQL file does not exist: {sql_file}")

    if not sql_file.is_file():
        raise ValueError(f"Input path is not a file: {sql_file}")

    try:
        sql_content = sql_file.read_text(encoding="utf-8-sig")
        statements = parse_sql_statements(sql_content)

        if not statements:
            raise ValueError(f"SQL file is empty: {sql_file}")

        connection_string = load_database_config()
        engine = create_engine(connection_string)
        wait_for_database(engine)

        with engine.begin() as connection:
            for statement_number, statement in enumerate(statements, start=1):
                connection.exec_driver_sql(statement)
                logger.info(
                    "Executed statement %d from %s",
                    statement_number,
                    sql_file,
                )

        logger.info("SQL file executed successfully: %s", sql_file)

    except (OSError, ValueError) as error:
        logger.exception("Input or configuration error: %s", error)
        raise
    except SQLAlchemyError:
        logger.exception("Database error while executing: %s", sql_file)
        raise
    except Exception:
        logger.exception("Unexpected error while executing: %s", sql_file)
        raise


def main():
    if len(sys.argv) != 2:
        print("Usage: python main.py <sql_file_path>")
        return 1

    try:
        execute_sql_file(sys.argv[1])
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())