"""Generate and insert synthetic student records into MySQL."""

import argparse
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

INSERT_STUDENT = text(
    """
    INSERT INTO students (
        first_name,
        last_name,
        date_of_birth,
        email,
        phone_number,
        city,
        state,
        country,
        enrollment_date
    ) VALUES (
        :first_name,
        :last_name,
        :date_of_birth,
        :email,
        :phone_number,
        :city,
        :state,
        :country,
        :enrollment_date
    )
    """
)


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


def build_student(fake, index):
    """Create one synthetic student record with a unique email."""
    first_name = fake.first_name()
    last_name = fake.last_name()
    email = f"{first_name}.{last_name}.{index}@example.edu".lower()

    return {
        "first_name": first_name,
        "last_name": last_name,
        "date_of_birth": fake.date_of_birth(
            minimum_age=18,
            maximum_age=36,
        ),
        "email": email,
        "phone_number": fake.numerify(text="+1-###-###-####"),
        "city": fake.city(),
        "state": fake.state(),
        "country": fake.country(),
        "enrollment_date": fake.date_between(
            start_date=date.today() - timedelta(days=11 * 365),
            end_date=date.today(),
        ),
    }


def seed_students(count, batch_size, seed):
    """Replace the students table contents with count synthetic records."""
    if count < 1:
        raise ValueError("Student count must be greater than zero.")

    fake = Faker("en_US")
    fake.seed_instance(seed)
    engine = create_engine(load_database_url())
    wait_for_database(engine)

    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE students"))

            for start in range(0, count, batch_size):
                batch = [
                    build_student(fake, index)
                    for index in range(start + 1, min(start + batch_size, count) + 1)
                ]
                connection.execute(INSERT_STUDENT, batch)
                logger.info("Inserted %d/%d student records", min(start + batch_size, count), count)
    except SQLAlchemyError:
        logger.exception("Failed to seed student records")
        raise

    logger.info("Successfully created %d synthetic student records", count)


def main():
    parser = argparse.ArgumentParser(
        description="Create synthetic student records in the MySQL students table."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=int(os.getenv("STUDENT_COUNT", "100000")),
        help="Number of records to create (default: 100000).",
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
    args = parser.parse_args()

    if args.batch_size < 1:
        parser.error("--batch-size must be greater than zero")

    try:
        seed_students(args.count, args.batch_size, args.seed)
    except (OSError, ValueError, SQLAlchemyError):
        logger.exception("Student data generation failed")
        return 1
    except Exception:
        logger.exception("Unexpected error during student data generation")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
