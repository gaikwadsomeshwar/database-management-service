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
