"""Command-line entry point for safe SQL script execution."""

import logging
import os
import sys
from pathlib import Path

from sql_executor import execute_sql_script


logger = logging.getLogger(__name__)


def main():
    """Execute one SQL file; the database is selected by ``MYSQL_DATABASE``."""
    if len(sys.argv) != 2:
        print("Usage: python main.py <sql_file_path>")
        return 1

    sql_file = Path(sys.argv[1])
    try:
        if not sql_file.is_file():
            raise FileNotFoundError(f"SQL file does not exist: {sql_file}")
        result = execute_sql_script(
            database=os.getenv("MYSQL_DATABASE", ""),
            sql_content=sql_file.read_text(encoding="utf-8-sig"),
        )
        logger.info("CLI SQL execution succeeded: %s", result)
        return 0
    except Exception:
        logger.exception("CLI SQL execution failed: %s", sql_file)
        return 1


if __name__ == "__main__":
    sys.exit(main())
