"""Generate and insert synthetic student records into MySQL."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from faker import Faker
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

sys.path.insert(0, str(PROJECT_ROOT / "app"))
from state_populations import (  # type: ignore[import-not-found]
    STATE_POPULATIONS,
    STATE_STUDENT_COUNTS,
    STUDENT_POPULATION_RATIO,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Shared DDL for every generated `student_<state>` table.
STUDENT_COLUMNS = """
    student_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    first_name VARCHAR(80) NOT NULL,
    last_name VARCHAR(80) NOT NULL,
    date_of_birth DATE NOT NULL,
    email VARCHAR(255) NOT NULL,
    phone_number VARCHAR(25) NOT NULL,
    city VARCHAR(100) NOT NULL,
    state VARCHAR(100) NOT NULL,
    enrollment_date DATE NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (student_id),
    UNIQUE KEY uq_email (email),
    KEY idx_last_name (last_name),
    KEY idx_enrollment_date (enrollment_date)
"""


def wait_for_database(engine, attempts=30, delay_seconds=2):
    """Wait for MySQL to accept connections during container startup."""
    for attempt in range(1, attempts + 1):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
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


def load_database_url():
    """Build a MySQL SQLAlchemy URL from environment variables."""
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    host = os.getenv("MYSQL_HOST", "127.0.0.1")
    port = os.getenv("MYSQL_PORT", "3306")
    database = os.getenv("MYSQL_DATABASE")
    username = os.getenv("MYSQL_USER")
    password = os.getenv("MYSQL_PASSWORD")

    if not database:
        raise ValueError("MYSQL_DATABASE must be configured.")
    if not username or password is None:
        raise ValueError("MYSQL_USER and MYSQL_PASSWORD must be configured.")

    return (
        "mysql+pymysql://"
        f"{quote_plus(username)}:{quote_plus(password)}@"
        f"{quote_plus(host)}:{quote_plus(port)}/{quote_plus(database)}"
    )


def build_student(fake):
    """Create one synthetic student record before state-specific enrichment."""
    first_name = fake.first_name()
    last_name = fake.last_name()

    return {
        "first_name": first_name,
        "last_name": last_name,
        "date_of_birth": fake.date_of_birth(
            minimum_age=18,
            maximum_age=36,
        ),
        # The seeding loop adds the table name to make the email globally unique.
        "email": "",
        "phone_number": fake.numerify(text="+1-###-###-####"),
        "city": fake.city(),
        "state": fake.state(),
        "enrollment_date": fake.date_between(
            start_date=date.today() - timedelta(days=11 * 365),
            end_date=date.today(),
        ),
    }


def create_state_table(connection, table_name):
    """Create one isolated student table for an Indian state."""
    connection.exec_driver_sql(f"DROP TABLE IF EXISTS `{table_name}`")
    connection.exec_driver_sql(
        f"CREATE TABLE `{table_name}` ({STUDENT_COLUMNS}) ENGINE=InnoDB"
    )


def seed_state(connection, table_name, state_name, count, batch_size, seed):
    """Create and populate one state's table with deterministic fake data."""
    fake = Faker("en_IN")
    fake.seed_instance(seed)
    insert_student = text(
        f"""
        INSERT INTO `{table_name}` (
            first_name, last_name, date_of_birth, email, phone_number,
            city, state, enrollment_date
        ) VALUES (
            :first_name, :last_name, :date_of_birth, :email, :phone_number,
            :city, :state, :enrollment_date
        )
        """
    )
    create_state_table(connection, table_name)

    for start in range(0, count, batch_size):
        batch = []
        for index in range(start + 1, min(start + batch_size, count) + 1):
            student = build_student(fake)
            student["state"] = state_name
            student["email"] = (
                f"{student['first_name']}.{student['last_name']}."
                f"{table_name}.{index}@example.edu"
            ).lower()
            batch.append(student)
        connection.execute(insert_student, batch)
        logger.info(
            "%s: inserted %d/%d student records",
            state_name,
            min(start + batch_size, count),
            count,
        )


def seed_one_state(engine, table_name, state_name, count, batch_size, seed):
    """Seed one state using an independent connection for thread safety."""
    with engine.begin() as connection:
        seed_state(connection, table_name, state_name, count, batch_size, seed)
    return table_name, count


def seed_students(batch_size, seed, workers):
    """Rebuild all state tables concurrently with bounded worker parallelism."""
    engine = create_engine(
        load_database_url(),
        pool_pre_ping=True,
        pool_size=workers,
        max_overflow=0,
    )
    wait_for_database(engine)

    try:
        # Metadata is written first so workers only perform independent table work.
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM state_metadata"))
            for table_name, (state_name, population) in STATE_POPULATIONS.items():
                count = STATE_STUDENT_COUNTS[table_name]
                connection.execute(
                    text(
                        "INSERT INTO state_metadata "
                        "(state_code, state_name, census_2011_population, "
                        "assumed_student_ratio, allocated_student_count) VALUES "
                        "(:code, :name, :population, :ratio, :count)"
                    ),
                    {
                        "code": table_name,
                        "name": state_name,
                        "population": population,
                        "ratio": STUDENT_POPULATION_RATIO,
                        "count": count,
                    },
                )

        executor = ThreadPoolExecutor(max_workers=workers)
        try:
            jobs = [
                executor.submit(
                    seed_one_state,
                    engine,
                    f"student_{table_name}",
                    state_name,
                    STATE_STUDENT_COUNTS[table_name],
                    batch_size,
                    seed,
                )
                for table_name, (state_name, _) in STATE_POPULATIONS.items()
            ]
            completed = 0
            for future in as_completed(jobs):
                table_name, count = future.result()
                completed += 1
                logger.info(
                    "Completed state table %s (%d records); %d/%d states finished",
                    table_name,
                    count,
                    completed,
                    len(STATE_POPULATIONS),
                )
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
    except SQLAlchemyError:
        logger.exception("Failed to seed student records")
        raise

    logger.info(
        "Successfully created %d records across %d Indian states",
        sum(STATE_STUDENT_COUNTS.values()),
        len(STATE_STUDENT_COUNTS),
    )


def main():
    parser = argparse.ArgumentParser(
        description="Create proportional student tables for India's 28 states."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(os.getenv("STUDENT_BATCH_SIZE", "1000")),
        help="Records inserted per batch (default: 1000).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=int(os.getenv("STUDENT_RANDOM_SEED", "20260914")),
        help="Random seed for reproducible data (default: 20260914).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.getenv("STUDENT_SEED_WORKERS", "4")),
        help="Concurrent state-table workers (default: 4).",
    )
    args = parser.parse_args()

    if args.batch_size < 1:
        parser.error("--batch-size must be greater than zero")
    if args.workers < 1:
        parser.error("--workers must be greater than zero")

    try:
        seed_students(args.batch_size, args.seed, args.workers)
    except (OSError, ValueError, SQLAlchemyError):
        logger.exception("Student data generation failed")
        return 1
    except Exception:
        logger.exception("Unexpected error during student data generation")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
