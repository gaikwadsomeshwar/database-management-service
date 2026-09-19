# test_scripts

Plain Python scripts for manually load-testing and debugging the API — not
containers, Jobs, or Pods.

## What it does

`run_database_scripts_test.py`:

1. Picks a random sample of state tables (default 10 of the 28 in
   `app/state_populations.py`).
2. For each state, **in parallel**, applies every script in the requested
   `database_scripts/<N>` folder range, **in order**, via `POST /api/sql/execute`.
3. Once a state's scripts are all applied, rolls each one back (in reverse
   order) via the same endpoint's `rollback`/`rollback_sql` fields.
4. Repeats the whole thing for `--iterations` runs, re-sampling states each time.

## Usage

```powershell
python test_scripts/run_database_scripts_test.py --from 1 --to 5
python test_scripts/run_database_scripts_test.py --from 1 --to 10 --states 15 --iterations 3
```

Requires the API to be reachable (Docker or `kubectl port-forward service/student-api 5000:5000`)
and `API_USERNAME`/`API_PASSWORD` set via the project's `.env` or the environment.
`requests` and `python-dotenv` (already in `requirements.txt`) must be installed
in the Python environment running this script.

| Flag              | Default                 | Meaning                                                 |
| ----------------- | ----------------------- | ------------------------------------------------------- |
| `--from` / `--to` | required                | `database_scripts` folder number range, e.g. `1` to `5` |
| `--states`        | 10                      | Number of random states per iteration                   |
| `--iterations`    | 1                       | How many times to repeat the whole run                  |
| `--base-url`      | `http://localhost:5000` | API base URL (or `API_BASE_URL` env var)                |
| `--database`      | `students_db`           | Database name sent to `/api/sql/execute`                |

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
