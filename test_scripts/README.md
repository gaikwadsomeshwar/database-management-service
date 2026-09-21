# test_scripts

Plain Python scripts for manually load-testing and debugging the API — not
containers, Jobs, or Pods.

## What it does

`run_database_scripts_test.py`:

1. Groups the 28 Indian state databases across the **7 consolidated MySQL servers** (`mysql-1` through `mysql-7`).
2. Samples 1 random state database per server host (for up to `--states` servers, max 7).
3. Executes the state databases in **parallel** worker threads (`ThreadPoolExecutor`).
4. Within each state database worker thread, applies every SQL script in the requested `database_scripts/<N>` folder range **strictly sequentially, one script at a time**, via `POST /api/sql/execute`. Execution stops on the first failure for a state.
5. Repeats the whole run for `--iterations` times, re-sampling states across servers each time.

## Usage

```powershell
python test_scripts/run_database_scripts_test.py --from 1 --to 5
python test_scripts/run_database_scripts_test.py --from 1 --to 10 --states 7 --iterations 3
```

Requires the API to be reachable (Docker or `kubectl port-forward service/student-api 5000:5000`)
and `API_USERNAME`/`API_PASSWORD` set via the project's `.env` or the environment.
`requests` and `python-dotenv` (already in `requirements.txt`) must be installed
in the Python environment running this script.

| Flag              | Default                 | Meaning                                                           |
| ----------------- | ----------------------- | ----------------------------------------------------------------- |
| `--from` / `--to` | required                | `database_scripts` folder number range, e.g. `1` to `5`           |
| `--states`        | `7`                     | Number of servers/states per iteration (1 to 7, default 7, max 7) |
| `--iterations`    | `1`                     | How many times to repeat the whole run                            |
| `--base-url`      | `http://localhost:5000` | API base URL (or `API_BASE_URL` env var)                          |
| `--database`      | `students_db`           | Database name sent to `/api/sql/execute`                          |

## Automated Test Driver (`run_test_driver.py`)

The automated driver script executes `run_database_scripts_test.py` across two structured testing phases to evaluate API performance, database routing, and pod autoscaling (`hpa-reactive` vs `scaledobject-proactive`).

### Architecture & Testing Phases

1. **Phase 1 (Incremental State Progression)**:
   - Tests system performance as concurrent server load increases.
   - Runs state counts sequentially from `1` up to `7` (default: 10 runs for 1 state, 10 runs for 2 states, ..., 10 runs for 7 states).
   - In each run, randomly selects `from_folder` (1..10), `to_folder` (`from_folder`..10), and `iterations` (`--min-iterations` to `--max-iterations`).

2. **Phase 2 (7-State Combination Load Testing)**:
   - Evaluates sustained load across all 7 SQL servers simultaneously.
   - Executes randomized parameter combinations targeting 7 state databases in parallel.

3. **Maximum Duration Cap (`--max-driver-hours`)**:
   - Enforces a strict runtime limit (default: **10.0 hours**).
   - The driver tracks total elapsed time and automatically stops execution cleanly when the cap is reached, logging final statistics.

---

### Command-Line Arguments

| Flag                 | Default                 | Description                                                              |
| -------------------- | ----------------------- | ------------------------------------------------------------------------ |
| `--runs-per-state`   | `10`                    | Phase 1: Number of test runs for each state count (1 to 7)               |
| `--combinations`     | `100`                   | Phase 2: Number of parameter combinations to execute                     |
| `--phase2-states`    | `7`                     | Phase 2: Number of parallel state databases per run                      |
| `--min-iterations`   | `1`                     | Minimum iteration count passed to `run_database_scripts_test.py` per run |
| `--max-iterations`   | `5`                     | Maximum iteration count passed to `run_database_scripts_test.py` per run |
| `--max-driver-hours` | `10.0`                  | Strict total time cap in hours before the driver gracefully stops        |
| `--skip-phase1`      | `false`                 | Skip Phase 1 (Incremental State Progression)                             |
| `--skip-phase2`      | `false`                 | Skip Phase 2 (Combination Load Testing)                                  |
| `--base-url`         | `http://localhost:5000` | Target API base URL                                                      |
| `--stop-on-failure`  | `false`                 | Immediately abort driver execution if any run fails                      |

---

### Usage Examples

```powershell
# 1. Standard Run (Runs Phase 1 + Phase 2 with 1..5 iterations, finishing in ~1.5 - 2 hours)
python test_scripts/run_test_driver.py

# 2. Quick Smoke Test (~5 - 10 minutes)
python test_scripts/run_test_driver.py --runs-per-state 2 --combinations 5 --min-iterations 1 --max-iterations 2

# 3. Overnight Benchmark with 10-Hour Hard Cap
python test_scripts/run_test_driver.py --runs-per-state 20 --combinations 200 --max-driver-hours 10.0

# 4. Phase 1 Only (Test state progression from 1 to 7 servers)
python test_scripts/run_test_driver.py --skip-phase2 --runs-per-state 15

# 5. Phase 2 Only (Full 7-server concurrent load test)
python test_scripts/run_test_driver.py --skip-phase1 --combinations 150 --phase2-states 7

# 6. Abort on First Failure (Useful for CI/CD or debugging)
python test_scripts/run_test_driver.py --stop-on-failure
```

---

### Logging & Diagnostics

- The driver appends comprehensive logs to `logs/test_driver.txt` including execution times, parameters, and pass/fail status per run.
- Individual script details are logged simultaneously to `logs/test_script.txt`.

## What "rollback" actually reverts

`app/sql_executor.py` rejects any `DROP`/`DELETE` statement, so a schema
change (added column, procedure, view, trigger, index) can never be dropped
through this API — only the **data** a script wrote can be undone. This
script's `ROLLBACK_STATEMENTS` map reverts each script's backfilled columns
back to `NULL` (or their original default, for `NOT NULL` columns); scripts
that only create procedures/views/triggers/indexes have nothing to revert, so
a harmless `SELECT 1` is used instead.

## Known limitation

`CREATE PROCEDURE`/`CREATE TRIGGER` scripts (folders 5-8) have no
`IF NOT EXISTS` equivalent in MySQL. Running the same folder range against the
same state more than once (e.g. across iterations, if `random.sample` repeats
a state) will fail on the second run with an "already exists" error — this is
expected and matches the documented behavior in `database_scripts/README.md`.

## Collecting logs

Both scripts write to `logs/` at the project root (git-ignored except for a
`.gitkeep`), one text file per component:

- `run_database_scripts_test.py` appends its own run log to `logs/test_script.txt`
  (in addition to printing to the console).
- `collect_pod_logs.py` pulls current and (if present) previous/crashed
  container logs for each known component — `student-api`, `forecast-service`,
  `mysql`, `prometheus`, `seed-students` — via `kubectl logs`, writing each to
  its own `logs/<component>.txt`:

  ```powershell
  python test_scripts/collect_pod_logs.py
  python test_scripts/collect_pod_logs.py --namespace default --tail 500
  python test_scripts/collect_pod_logs.py --components student-api mysql
  ```

  Requires `kubectl` on `PATH` and a working cluster context; failures for one
  component (e.g. no matching pods) are written into that component's file
  instead of stopping the others.
