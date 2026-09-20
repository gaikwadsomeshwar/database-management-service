"""Driver script to run test_scripts/run_database_scripts_test.py in two phases.

Phase 1: Incremental State Testing
- Runs the test script for state count = 1 (100 times).
- Runs for state count = 2 (100 times).
- Continues sequentially up to state count = 7 (100 times).
- Each run randomly selects from_folder (1..10), to_folder (from_folder..10), and iterations (100..1000).

Phase 2: 7-State Combination Testing
- Executes 10,000 randomized parameter combinations targeting 7 states.
- Each run randomly selects from_folder (1..10), to_folder (from_folder..10), iterations (100..1000), and states (default 7).
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
        description="Driver to run test_scripts/run_database_scripts_test.py across state progression and 10,000 parameter combinations."
    )
    parser.add_argument(
        "--runs-per-state",
        type=int,
        default=100,
        help="Phase 1: Number of runs for each state count 1 to 7 (default: 100)",
    )
    parser.add_argument(
        "--combinations",
        type=int,
        default=10000,
        help="Phase 2: Number of parameter combinations to run (default: 10000)",
    )
    parser.add_argument(
        "--phase2-states",
        type=int,
        default=7,
        help="Phase 2: State database count per iteration (default: 7)",
    )
    parser.add_argument(
        "--skip-phase1",
        action="store_true",
        help="Skip Phase 1 (Incremental State Testing)",
    )
    parser.add_argument(
        "--skip-phase2",
        action="store_true",
        help="Skip Phase 2 (7-State Combination Load Testing)",
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


def execute_run(cmd, run_label, base_url, stop_on_failure):
    logger.info("=== Executing %s ===", run_label)
    run_start = time.time()
    result = subprocess.run(cmd)
    elapsed = time.time() - run_start

    if result.returncode == 0:
        logger.info("%s PASSED in %.2fs", run_label, elapsed)
        return True
    else:
        logger.error("%s FAILED (exit code %d) in %.2fs", run_label, result.returncode, elapsed)
        if stop_on_failure:
            logger.error("Stopping driver due to --stop-on-failure flag.")
        return False


def run_driver():
    args = parse_args()
    passed_runs = 0
    failed_runs = 0
    global_run_num = 0

    start_time = time.time()

    # -------------------------------------------------------------------------
    # Phase 1: Incremental State Testing (States 1 to 7, 100 runs each)
    # -------------------------------------------------------------------------
    if not args.skip_phase1:
        logger.info(
            "Starting Phase 1: Testing State Counts 1 to 7 (%d runs per state)",
            args.runs_per_state,
        )

        for state_count in range(1, 8):
            logger.info("--- Phase 1: Testing State Count %d/7 ---", state_count)
            for run_idx in range(1, args.runs_per_state + 1):
                global_run_num += 1
                from_folder = random.randint(1, 10)
                to_folder = random.randint(from_folder, 10)
                iterations = random.randint(100, 1000)

                cmd = [
                    sys.executable,
                    str(TEST_SCRIPT),
                    "--from", str(from_folder),
                    "--to", str(to_folder),
                    "--states", str(state_count),
                    "--iterations", str(iterations),
                    "--base-url", args.base_url,
                ]

                run_label = f"Phase 1 (States {state_count}) Run {run_idx}/{args.runs_per_state} (Global #{global_run_num}): --from {from_folder} --to {to_folder} --iterations {iterations}"
                success = execute_run(cmd, run_label, args.base_url, args.stop_on_failure)

                if success:
                    passed_runs += 1
                else:
                    failed_runs += 1
                    if args.stop_on_failure:
                        break
            if failed_runs > 0 and args.stop_on_failure:
                break

    # -------------------------------------------------------------------------
    # Phase 2: 7-State Combination Testing (10,000 combinations)
    # -------------------------------------------------------------------------
    if not args.skip_phase2 and not (failed_runs > 0 and args.stop_on_failure):
        logger.info(
            "Starting Phase 2: Testing %d Combinations for %d random states",
            args.combinations,
            args.phase2_states,
        )

        for combo_idx in range(1, args.combinations + 1):
            global_run_num += 1
            from_folder = random.randint(1, 10)
            to_folder = random.randint(from_folder, 10)
            iterations = random.randint(100, 1000)

            cmd = [
                sys.executable,
                str(TEST_SCRIPT),
                "--from", str(from_folder),
                "--to", str(to_folder),
                "--states", str(args.phase2_states),
                "--iterations", str(iterations),
                "--base-url", args.base_url,
            ]

            run_label = f"Phase 2 Combo {combo_idx}/{args.combinations} (Global #{global_run_num}): --from {from_folder} --to {to_folder} --states {args.phase2_states} --iterations {iterations}"
            success = execute_run(cmd, run_label, args.base_url, args.stop_on_failure)

            if success:
                passed_runs += 1
            else:
                failed_runs += 1
                if args.stop_on_failure:
                    break

    total_elapsed = time.time() - start_time
    logger.info(
        "=== Driver Finished: Total Executed Runs: %d, Passed: %d, Failed: %d (Total time: %.2fs) ===",
        global_run_num, passed_runs, failed_runs, total_elapsed
    )

    if failed_runs > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_driver()
