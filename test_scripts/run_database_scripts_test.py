"""Randomized database_scripts test harness for distributed per-state SQL servers.

Applies every script in a database_scripts folder range (e.g. 1 to 5) to a
random sample of state tables, in parallel across states, using only the
existing Flask API (POST /api/auth/login, POST /api/sql/execute) which routes
to each state's dedicated MySQL server (e.g. mysql-maharashtra) - no direct
database access. Scripts are applied in order; execution stops at the first
failure for a given state so that later scripts (which may depend on it) are
not attempted.

This is a plain script for local/manual testing only - it is not deployed as
a container, Job, or Pod.

Usage:
    python test_scripts/run_database_scripts_test.py --from 1 --to 5
    python test_scripts/run_database_scripts_test.py --from 1 --to 10 --states 15 --iterations 3

Configuration (environment variables, or the project's root .env):
    API_BASE_URL     Base URL of the running API (default http://localhost:5000)
    API_USERNAME     Login username for POST /api/auth/login (required)
    API_PASSWORD     Login password for POST /api/auth/login (required)
    TEST_DATABASE    Database name passed to /api/sql/execute (default students_db)
"""

import argparse
import concurrent.futures
import logging
import os
import random
import sys
import threading
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_ROOT = PROJECT_ROOT / "database_scripts"
load_dotenv(PROJECT_ROOT / ".env")

sys.path.insert(0, str(PROJECT_ROOT / "app"))
from state_populations import STATE_POPULATIONS  # noqa: E402

LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(threadName)s: %(message)s"

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),
        # Separate log file for this component, alongside console output.
        logging.FileHandler(LOGS_DIR / "test_script.txt", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)
STATE_TABLE_PLACEHOLDER = "__STATE_TABLE__"


def discover_scripts(from_folder, to_folder):
    """Return script file paths for folders [from_folder, to_folder], in order."""
    if from_folder > to_folder:
        raise ValueError("--from must be <= --to")

    scripts = []
    for folder_number in range(from_folder, to_folder + 1):
        folder = SCRIPTS_ROOT / str(folder_number)
        if not folder.is_dir():
            raise ValueError(f"database_scripts folder not found: {folder}")
        scripts.extend(sorted(folder.glob("*.sql")))

    if not scripts:
        raise ValueError(f"No scripts found in folders {from_folder}-{to_folder}")
    return scripts


class ApiClient:
    """Thin wrapper around the existing login and SQL execution endpoints."""

    def __init__(self, base_url, username, password, timeout=30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._username = username
        self._password = password
        self._lock = threading.Lock()
        self._token = self._login()

    def _login(self):
        response = requests.post(
            f"{self.base_url}/api/auth/login",
            json={"username": self._username, "password": self._password},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()["access_token"]

    def execute_sql(self, database, sql, state=None):
        body = {"database": database, "sql": sql}
        if state:
            body["state"] = state

        with self._lock:
            token = self._token
        response = requests.post(
            f"{self.base_url}/api/sql/execute",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=self.timeout,
        )
        if response.status_code == 401:
            # Token likely expired mid-run; re-login once and retry.
            with self._lock:
                self._token = self._login()
                token = self._token
            response = requests.post(
                f"{self.base_url}/api/sql/execute",
                headers={"Authorization": f"Bearer {token}"},
                json=body,
                timeout=self.timeout,
            )
        if response.status_code >= 400:
            raise RuntimeError(
                f"/api/sql/execute failed ({response.status_code}): {response.text}"
            )
        return response.json()


def run_scripts_for_state(client, database, state_code, scripts):
    """Apply every script (in order) to one state's dedicated MySQL server.

    Never raises: failures are logged and recorded so one state's failure
    can't take down other states' threads or later iterations. Stops at the
    first failed script so that later scripts (which may depend on it) are
    not attempted.
    """
    table_name = f"student_{state_code}"
    applied = 0
    errors = []

    for script_path in scripts:
        try:
            sql_content = script_path.read_text(encoding="utf-8-sig").replace(
                STATE_TABLE_PLACEHOLDER, table_name
            )
            logger.info("[%s] Applying %s", state_code, script_path.name)
            client.execute_sql(database, sql_content, state=state_code)
            applied += 1
        except Exception as error:
            logger.exception("[%s] Failed to apply %s", state_code, script_path.name)
            errors.append(f"apply {script_path.name}: {error}")
            break

    return state_code, applied, errors


def run_iteration(client, database, from_folder, to_folder, state_sample_size):
    """Apply all scripts in the folder range to a fresh random state sample.

    Always waits for every state's thread to finish before returning, even if
    some states fail; returns True only if every state completed cleanly.
    """
    scripts = discover_scripts(from_folder, to_folder)
    available_states = list(STATE_POPULATIONS.keys())
    if state_sample_size > len(available_states):
        raise ValueError(
            f"--states {state_sample_size} exceeds the {len(available_states)} available states"
        )
    states = random.sample(available_states, state_sample_size)
    logger.info(
        "Folders %s-%s (%d scripts) against states: %s",
        from_folder,
        to_folder,
        len(scripts),
        ", ".join(states),
    )

    iteration_ok = True
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(states)) as executor:
        futures = {
            executor.submit(
                run_scripts_for_state, client, database, state_code, scripts
            ): state_code
            for state_code in states
        }
        # Iterate every future to completion (as_completed only yields once a
        # future is done), so the next iteration never starts until every
        # state's thread from this one has finished, success or failure.
        for future in concurrent.futures.as_completed(futures):
            state_code = futures[future]
            try:
                state_code, script_count, errors = future.result()
                if errors:
                    iteration_ok = False
                    logger.error(
                        "[%s] Completed %d scripts with %d error(s): %s",
                        state_code, script_count, len(errors), "; ".join(errors),
                    )
                else:
                    logger.info(
                        "[%s] Applied %d scripts successfully",
                        state_code, script_count,
                    )
            except Exception:
                iteration_ok = False
                logger.exception("[%s] Thread raised unexpectedly", state_code)

    return iteration_ok


def parse_args():
    parser = argparse.ArgumentParser(
        description="Apply a database_scripts folder range to random states in parallel.",
    )
    parser.add_argument(
        "--from", dest="from_folder", type=int, required=True,
        help="First database_scripts folder number to run, e.g. 1",
    )
    parser.add_argument(
        "--to", dest="to_folder", type=int, required=True,
        help="Last database_scripts folder number to run, e.g. 5",
    )
    parser.add_argument(
        "--states", type=int, default=10,
        help="Number of random states to test per iteration (default 10)",
    )
    parser.add_argument(
        "--iterations", type=int, default=1,
        help="Number of times to repeat the whole run, re-sampling states each time (default 1)",
    )
    parser.add_argument(
        "--base-url", default=os.getenv("API_BASE_URL", "http://localhost:5000"),
        help="Base URL of the running API (default http://localhost:5000)",
    )
    parser.add_argument(
        "--database",
        default=os.getenv("TEST_DATABASE", os.getenv("MYSQL_DATABASE", "students_db")),
        help="Database name passed to /api/sql/execute (default students_db)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    username = os.getenv("API_USERNAME")
    password = os.getenv("API_PASSWORD")
    if not username or not password:
        logger.error("API_USERNAME and API_PASSWORD must be set (env or .env)")
        return 1

    try:
        client = ApiClient(args.base_url, username, password)
    except requests.RequestException:
        logger.exception("Login failed against %s", args.base_url)
        return 1

    any_failures = False
    for iteration in range(1, args.iterations + 1):
        logger.info("=== Iteration %d/%d ===", iteration, args.iterations)
        try:
            if not run_iteration(
                client, args.database, args.from_folder, args.to_folder, args.states
            ):
                any_failures = True
        except Exception:
            # Keep going: a bad iteration shouldn't stop the remaining ones.
            any_failures = True
            logger.exception("Iteration %d failed", iteration)

    if any_failures:
        logger.error("Completed all %d iteration(s) with failures", args.iterations)
        return 1

    logger.info("All %d iteration(s) completed successfully", args.iterations)
    return 0


if __name__ == "__main__":
    sys.exit(main())
