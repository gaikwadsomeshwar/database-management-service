"""Command-line entry point for safe SQL script execution across per-state SQL servers."""

import argparse
import logging
import os
import sys
from pathlib import Path

from sql_executor import execute_sql_script, infer_state_from_sql
from state_populations import STATE_POPULATIONS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    """Execute one SQL file against a target state's SQL server or all state servers."""
    parser = argparse.ArgumentParser(
        description="Execute a safe SQL script against a state's dedicated SQL server or all state servers."
    )
    parser.add_argument("sql_file", type=Path, help="Path to the SQL file to execute")
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="Target state code (e.g. maharashtra). If omitted, inferred from SQL or executed across all states if --all-states.",
    )
    parser.add_argument(
        "--all-states",
        action="store_true",
        help="Execute the SQL script against every state SQL server (e.g. for common schema scripts).",
    )
    parser.add_argument(
        "--database",
        default=os.getenv("MYSQL_DATABASE", "students_db"),
        help="Target database name (default: students_db).",
    )

    args = parser.parse_args()

    if not args.sql_file.is_file():
        logger.error("SQL file does not exist: %s", args.sql_file)
        return 1

    sql_content = args.sql_file.read_text(encoding="utf-8-sig")

    try:
        if args.all_states:
            logger.info("Executing %s across all %d state SQL servers", args.sql_file.name, len(STATE_POPULATIONS))
            for state_code in STATE_POPULATIONS:
                res = execute_sql_script(
                    database=args.database,
                    sql_content=sql_content,
                    state=state_code,
                )
                logger.info("[%s] Succeeded on %s (%.2f ms)", state_code, res.get("target_host"), res.get("duration_ms", 0))
            return 0

        target_state = args.state or infer_state_from_sql(sql_content)
        result = execute_sql_script(
            database=args.database,
            sql_content=sql_content,
            state=target_state,
        )
        logger.info(
            "CLI SQL execution succeeded: target_host=%s state=%s duration=%.2f ms",
            result.get("target_host"),
            result.get("target_state"),
            result.get("duration_ms", 0),
        )
        return 0
    except Exception:
        logger.exception("CLI SQL execution failed: %s", args.sql_file)
        return 1


if __name__ == "__main__":
    sys.exit(main())
