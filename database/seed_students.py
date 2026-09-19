"""Generate and insert synthetic student records across distributed per-state MySQL servers."""

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
from sql_executor import resolve_mysql_host  # type: ignore[import-not-found]

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

STATE_METADATA_DDL = """
CREATE TABLE IF NOT EXISTS state_metadata (
    state_code VARCHAR(64) NOT NULL,
    state_name VARCHAR(100) NOT NULL,
    census_2011_population BIGINT UNSIGNED NOT NULL,
    assumed_student_ratio DECIMAL(4, 3) NOT NULL,
    allocated_student_count INT UNSIGNED NOT NULL,
    PRIMARY KEY (state_code),
    UNIQUE KEY uq_state_metadata_name (state_name)
) ENGINE=InnoDB;
"""


def wait_for_database(engine, state_name, attempts=30, delay_seconds=2):
    """Wait for MySQL server of a given state to accept connections."""
    for attempt in range(1, attempts + 1):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except SQLAlchemyError:
            if attempt == attempts:
                raise
            logger.warning(
                "[%s] Database is not ready (attempt %d/%d); retrying in %d seconds",
                state_name,
                attempt,
                attempts,
                delay_seconds,
            )
            time.sleep(delay_seconds)


def load_database_url_for_state(state_code):
    """Build a MySQL SQLAlchemy URL targeting that state's dedicated SQL server."""
    host = resolve_mysql_host(state_code)
    port = os.getenv("MYSQL_PORT", "3306")
    database = os.getenv("MYSQL_DATABASE", "students_db")
    username = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD")

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
    """Create one isolated student table on that state's dedicated SQL server."""
    connection.exec_driver_sql(
        f"CREATE TABLE IF NOT EXISTS `{table_name}` ({STUDENT_COLUMNS}) ENGINE=InnoDB"
    )


def seed_state(connection, table_name, state_name, count, batch_size, seed):
    """Converge one state table to its target count.

    Missing rows are appended. If the table is over the target, rows with the
    highest student IDs are removed first, treating the end as the newest rows.
    """
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
    existing_count = connection.execute(
        text(f"SELECT COUNT(*) FROM `{table_name}`")
    ).scalar_one()
    excess_count = max(0, existing_count - count)

    if excess_count:
        connection.exec_driver_sql(
            f"DELETE FROM `{table_name}` "
            f"ORDER BY student_id DESC LIMIT {excess_count}"
        )
        existing_count -= excess_count
        logger.info(
            "%s: removed %d excess records from the end; now %d/%d",
            state_name,
            excess_count,
            existing_count,
            count,
        )

    missing_count = max(0, count - existing_count)

    if missing_count == 0:
        logger.info(
            "%s: has required %d/%d records; no insert required",
            state_name,
            existing_count,
            count,
        )
        return {"deleted": excess_count, "inserted": 0}

    fake = Faker("en_IN")
    fake.seed_instance(seed)

    for start in range(0, missing_count, batch_size):
        batch = []
        for index in range(
            existing_count + start + 1,
            existing_count + min(start + batch_size, missing_count) + 1,
        ):
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
            existing_count + min(start + batch_size, missing_count),
            count,
        )
    return {"deleted": excess_count, "inserted": missing_count}


def seed_one_state(
    table_name,
    state_name,
    population,
    count,
    batch_size,
    seed,
):
    """Run metadata, DDL, reconciliation, and inserts for one state's dedicated SQL server.

    Connects directly to that state's MySQL server (e.g. mysql-maharashtra),
    ensuring independent buffer pools, redo logs, and connection pools.
    """
    state_code = table_name.removeprefix("student_")
    db_url = load_database_url_for_state(state_code)
    engine = create_engine(db_url, pool_pre_ping=True)
    wait_for_database(engine, state_name)

    with engine.begin() as connection:
        connection.exec_driver_sql(STATE_METADATA_DDL)
        connection.execute(
            text(
                "INSERT INTO state_metadata "
                "(state_code, state_name, census_2011_population, "
                "assumed_student_ratio, allocated_student_count) VALUES "
                "(:code, :name, :population, :ratio, :count) "
                "ON DUPLICATE KEY UPDATE "
                "state_name = VALUES(state_name), "
                "census_2011_population = VALUES(census_2011_population), "
                "assumed_student_ratio = VALUES(assumed_student_ratio), "
                "allocated_student_count = VALUES(allocated_student_count)"
            ),
            {
                "code": state_code,
                "name": state_name,
                "population": population,
                "ratio": STUDENT_POPULATION_RATIO,
                "count": count,
            },
        )
        changes = seed_state(
            connection,
            table_name,
            state_name,
            count,
            batch_size,
            seed,
        )
    engine.dispose()
    return table_name, count, changes


def seed_students(batch_size, seed, workers, target_state=None, state_batch_size=5):
    """Add missing records across state SQL servers in batches of states."""
    if target_state:
        state_key = target_state.strip().lower().removeprefix("student_")
        if state_key not in STATE_POPULATIONS:
            raise ValueError(f"Unknown state code: {target_state}")
        items = [(state_key, STATE_POPULATIONS[state_key])]
    else:
        items = list(STATE_POPULATIONS.items())

    # Chunk the 28 states into batches of size state_batch_size (e.g. 5 states per batch)
    state_chunks = [
        items[i : i + state_batch_size]
        for i in range(0, len(items), state_batch_size)
    ]

    total_states = len(items)
    logger.info(
        "Starting student seeding for %d state SQL server(s) in %d state batch(es) of up to %d state(s) each (workers=%d)",
        total_states,
        len(state_chunks),
        state_batch_size,
        workers,
    )

    completed_total = 0
    try:
        for chunk_index, chunk in enumerate(state_chunks, start=1):
            chunk_workers = min(workers, len(chunk))
            logger.info(
                "--- Processing State Batch %d/%d (%d state(s)) ---",
                chunk_index,
                len(state_chunks),
                len(chunk),
            )
            with ThreadPoolExecutor(max_workers=chunk_workers) as executor:
                futures = {
                    executor.submit(
                        seed_one_state,
                        f"student_{table_name}",
                        state_name,
                        population,
                        STATE_STUDENT_COUNTS[table_name],
                        batch_size,
                        seed,
                    ): table_name
                    for table_name, (state_name, population) in chunk
                }
                for future in as_completed(futures):
                    table_name, count, changes = future.result()
                    completed_total += 1
                    logger.info(
                        "Completed state server student_%s (%d records); %d/%d total finished",
                        table_name,
                        count,
                        completed_total,
                        total_states,
                    )
                    logger.info(
                        "student_%s changes: inserted=%d deleted=%d",
                        table_name,
                        changes["inserted"],
                        changes["deleted"],
                    )
    except SQLAlchemyError:
        logger.exception("Failed to seed student records")
        raise

    total_records = sum(STATE_STUDENT_COUNTS[t] for t, _ in items)
    logger.info(
        "Successfully reconciled %d records across %d state SQL server(s)",
        total_records,
        total_states,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Seed student records into distributed per-state MySQL servers (one SQL server per state)."
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
        default=int(os.getenv("STUDENT_SEED_WORKERS", "5")),
        help="Concurrent state-table workers (default: 5).",
    )
    parser.add_argument(
        "--state-batch-size",
        type=int,
        default=int(os.getenv("STUDENT_STATE_BATCH_SIZE", "5")),
        help="Number of state SQL servers to seed per batch (default: 5).",
    )
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="Seed an individual state SQL server only (e.g. maharashtra). Omit to seed all 28 states.",
    )
    args = parser.parse_args()

    if args.batch_size < 1:
        parser.error("--batch-size must be greater than zero")
    if args.workers < 1:
        parser.error("--workers must be greater than zero")
    if args.state_batch_size < 1:
        parser.error("--state-batch-size must be greater than zero")

    try:
        seed_students(
            args.batch_size,
            args.seed,
            args.workers,
            target_state=args.state,
            state_batch_size=args.state_batch_size,
        )
    except (OSError, ValueError, SQLAlchemyError):
        logger.exception("Student data generation failed")
        return 1
    except Exception:
        logger.exception("Unexpected error during student data generation")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
