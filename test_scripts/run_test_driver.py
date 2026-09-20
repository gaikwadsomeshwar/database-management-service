"""Driver script to run test_scripts/run_database_scripts_test.py repeatedly (default 1000 runs).

For each run:
- Randomly selects from_folder (1 to 10) and to_folder (from_folder to 10).
- Randomly selects states count (1 to 7).
- Randomly selects iterations count (100 to 1000).
- Executes run_database_scripts_test.py synchronously and waits for completion.
"""

import argparse
import logging
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOGS_DIR / "test_driver.txt", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

TEST_SCRIPT = PROJECT_ROOT / "test_scripts" / "run_database_scripts_test.py"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Driver to run test_scripts/run_database_scripts_test.py repeatedly with randomized parameters."
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1000,
        help="Total number of runs to execute (default: 1000)",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("API_BASE_URL", "http://localhost:5000"),
        help="Base URL of the running API (default: http://localhost:5000)",
    )
    parser.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="Stop driver execution immediately if any run fails",
    )
    return parser.parse_args()


def run_driver():
    args = parse_args()
    total_runs = args.runs
    passed_runs = 0
    failed_runs = 0

    logger.info("Starting test driver for %d runs against %s", total_runs, args.base_url)

    start_time = time.time()

    for run_num in range(1, total_runs + 1):
        from_folder = random.randint(1, 10)
        to_folder = random.randint(from_folder, 10)
        states = random.randint(1, 7)
        iterations = random.randint(100, 1000)

        cmd = [
            sys.executable,
            str(TEST_SCRIPT),
            "--from", str(from_folder),
            "--to", str(to_folder),
            "--states", str(states),
            "--iterations", str(iterations),
            "--base-url", args.base_url,
        ]

        logger.info(
            "=== Run %d/%d: --from %d --to %d --states %d --iterations %d ===",
            run_num, total_runs, from_folder, to_folder, states, iterations
        )

        run_start = time.time()
        result = subprocess.run(cmd)
        elapsed = time.time() - run_start

        if result.returncode == 0:
            passed_runs += 1
            logger.info("Run %d PASSED in %.2fs", run_num, elapsed)
        else:
            failed_runs += 1
            logger.error("Run %d FAILED (exit code %d) in %.2fs", run_num, result.returncode, elapsed)
            if args.stop_on_failure:
                logger.error("Stopping driver due to --stop-on-failure flag.")
                break

    total_elapsed = time.time() - start_time
    logger.info(
        "=== Driver Finished: Total Runs: %d, Passed: %d, Failed: %d (Total time: %.2fs) ===",
        run_num, passed_runs, failed_runs, total_elapsed
    )

    if failed_runs > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_driver()

