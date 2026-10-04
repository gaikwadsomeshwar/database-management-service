"""Automated 340-Run Test Driver Suite.

Executes:
- Part 1: Incremental State Progression (70 runs: 10 runs each for state counts 1 through 7)
- Part 2: 7-Server Parallel Combinations (270 runs targeting 7 state databases across all 7 MySQL servers)
Total: 340 structured test driver runs.

Supports live API execution via test_scripts/database_execution/run_database_scripts_test.py
as well as fast dry-run / mock simulation for validation and benchmarking.

Usage:
    python test_scripts/traffic_generation/run_traffic_suite_340.py --dry-run
    python test_scripts/traffic_generation/run_traffic_suite_340.py --quick-test
    python test_scripts/traffic_generation/run_traffic_suite_340.py --base-url http://localhost:5000
"""

import argparse
import json
import logging
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOGS_DIR / "traffic_suite_340.txt", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

DB_EXEC_SCRIPT = PROJECT_ROOT / "test_scripts" / "database_execution" / "run_database_scripts_test.py"


class TrafficDriver340:
    """Orchestrates the 340-run traffic generation test suite."""

    def __init__(
        self,
        base_url: str = "http://localhost:5000",
        min_iterations: int = 1,
        max_iterations: int = 3,
        dry_run: bool = False,
        stop_on_failure: bool = False,
    ):
        self.base_url = base_url
        self.min_iterations = min_iterations
        self.max_iterations = max_iterations
        self.dry_run = dry_run
        self.stop_on_failure = stop_on_failure
        self.results: List[Dict[str, Any]] = []

    def execute_single_run(
        self,
        run_number: int,
        phase_name: str,
        state_count: int,
        from_folder: int,
        to_folder: int,
        iterations: int,
    ) -> Dict[str, Any]:
        """Execute or simulate a single test run."""
        run_start = time.perf_counter()
        run_label = f"Run #{run_number:03d} [{phase_name}] states={state_count} folders={from_folder}-{to_folder} iters={iterations}"
        logger.info("Executing %s", run_label)

        if self.dry_run:
            # Deterministic simulation of execution timing (5ms - 25ms per simulated script)
            num_scripts = (to_folder - from_folder + 1) * 3
            simulated_latency = 0.002 * num_scripts * state_count * iterations
            time.sleep(min(0.05, simulated_latency))  # keep simulation snappy
            elapsed = time.perf_counter() - run_start
            success = True
            exit_code = 0
            scripts_applied = num_scripts * state_count * iterations
        else:
            cmd = [
                sys.executable,
                str(DB_EXEC_SCRIPT),
                "--from", str(from_folder),
                "--to", str(to_folder),
                "--states", str(state_count),
                "--iterations", str(iterations),
                "--base-url", self.base_url,
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                elapsed = time.perf_counter() - run_start
                exit_code = proc.returncode
                success = (proc.returncode == 0)
                scripts_applied = (to_folder - from_folder + 1) * state_count * iterations if success else 0
            except Exception as e:
                elapsed = time.perf_counter() - run_start
                exit_code = -1
                success = False
                scripts_applied = 0
                logger.error("Run #%d raised exception: %s", run_number, e)

        record = {
            "run_number": run_number,
            "phase": phase_name,
            "state_count": state_count,
            "from_folder": from_folder,
            "to_folder": to_folder,
            "iterations": iterations,
            "duration_seconds": round(elapsed, 4),
            "scripts_applied": scripts_applied,
            "status": "PASSED" if success else "FAILED",
            "exit_code": exit_code,
        }
        self.results.append(record)
        return record

    def run_suite(self, quick_test: bool = False) -> Dict[str, Any]:
        """Run all 340 tests (or quick subset)."""
        suite_start = time.perf_counter()
        passed = 0
        failed = 0
        total_scripts = 0
        global_run = 0

        # Part 1: Progression (70 runs or 7 in quick test)
        p1_runs_per_state = 1 if quick_test else 10
        logger.info("=== Starting Part 1: Incremental Progression (%d runs) ===", p1_runs_per_state * 7)

        for state_count in range(1, 8):
            for _ in range(p1_runs_per_state):
                global_run += 1
                from_f = random.randint(1, 10)
                to_f = random.randint(from_f, 10)
                iters = random.randint(self.min_iterations, self.max_iterations)
                res = self.execute_single_run(global_run, "Progression", state_count, from_f, to_f, iters)
                if res["status"] == "PASSED":
                    passed += 1
                    total_scripts += res["scripts_applied"]
                else:
                    failed += 1
                    if self.stop_on_failure:
                        break
            if failed > 0 and self.stop_on_failure:
                break

        # Part 2: 7-Server Combinations (270 runs or 5 in quick test)
        p2_total_runs = 5 if quick_test else 270
        logger.info("=== Starting Part 2: 7-Server Combinations (%d runs) ===", p2_total_runs)

        if not (failed > 0 and self.stop_on_failure):
            for _ in range(p2_total_runs):
                global_run += 1
                from_f = random.randint(1, 10)
                to_f = random.randint(from_f, 10)
                iters = random.randint(self.min_iterations, self.max_iterations)
                res = self.execute_single_run(global_run, "Parallel-7Servers", 7, from_f, to_f, iters)
                if res["status"] == "PASSED":
                    passed += 1
                    total_scripts += res["scripts_applied"]
                else:
                    failed += 1
                    if self.stop_on_failure:
                        break

        total_duration = time.perf_counter() - suite_start
        summary = {
            "total_runs_executed": global_run,
            "target_runs": 12 if quick_test else 340,
            "passed_runs": passed,
            "failed_runs": failed,
            "pass_rate_pct": round((passed / global_run * 100), 2) if global_run else 0.0,
            "total_scripts_applied": total_scripts,
            "total_duration_seconds": round(total_duration, 2),
            "dry_run": self.dry_run,
            "runs": self.results,
        }

        # Write summary JSON
        summary_path = LOGS_DIR / "traffic_suite_340.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        logger.info(
            "=== Suite Completed: %d/%d Passed (%.1f%%) in %.2fs ===",
            passed, global_run, summary["pass_rate_pct"], total_duration
        )
        return summary


def parse_args():
    parser = argparse.ArgumentParser(
        description="Execute 340-run automated test driver suite (progression and 7-server parallel combinations)."
    )
    parser.add_argument("--base-url", default=os.getenv("API_BASE_URL", "http://localhost:5000"), help="API Base URL")
    parser.add_argument("--min-iterations", type=int, default=1, help="Min iterations per run")
    parser.add_argument("--max-iterations", type=int, default=3, help="Max iterations per run")
    parser.add_argument("--quick-test", action="store_true", help="Execute quick smoke test (12 runs) instead of full 340")
    parser.add_argument("--dry-run", action="store_true", help="Execute simulation of 340 runs without calling network API")
    parser.add_argument("--stop-on-failure", action="store_true", help="Abort suite immediately if any run fails")
    return parser.parse_args()


def main():
    args = parse_args()
    print("=" * 70)
    print("TRAFFIC GENERATION - 340-RUN AUTOMATED TEST DRIVER SUITE")
    print(f"Mode: {'DRY RUN SIMULATION' if args.dry_run else 'LIVE CLUSTER'}")
    print(f"Target: {'12 Runs (Quick Test)' if args.quick_test else '340 Runs (Full Suite)'}")
    print("=" * 70)

    driver = TrafficDriver340(
        base_url=args.base_url,
        min_iterations=args.min_iterations,
        max_iterations=args.max_iterations,
        dry_run=args.dry_run,
        stop_on_failure=args.stop_on_failure,
    )
    summary = driver.run_suite(quick_test=args.quick_test)

    print("-" * 70)
    print(f"Total Runs Executed : {summary['total_runs_executed']}")
    print(f"Passed Runs         : {summary['passed_runs']}")
    print(f"Failed Runs         : {summary['failed_runs']}")
    print(f"Pass Rate           : {summary['pass_rate_pct']}%")
    print(f"Total Duration      : {summary['total_duration_seconds']}s")
    print(f"Detailed Log File   : logs/traffic_suite_340.json")
    print("=" * 70)

    return 0 if summary["failed_runs"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
