# Database Scripts

20 standalone MySQL scripts, two per numbered folder (`1`-`10`), that can be run
against **any** generated `student_<state>` table (e.g. `student_maharashtra`,
`student_uttar_pradesh`).

## Usage

Every script uses the placeholder token `__STATE_TABLE__` wherever the target
table name is needed. Before running a script, replace every occurrence of
`__STATE_TABLE__` with the target table name (e.g. `student_maharashtra`), then
execute it with the CLI runner or the `/api/sql/execute` endpoint:

CLI runner (targeting a specific state's SQL server, or all state servers):

```powershell
# Target a specific state SQL server (e.g. mysql-maharashtra)
python app/main.py database_scripts/1/01_add_guardian_contact_columns.sql --state maharashtra

# Or apply across all 28 state SQL servers
python app/main.py database_scripts/1/01_add_guardian_contact_columns.sql --all-states
```

API execution (auto-routed to that state's dedicated SQL server):

```json
POST /api/sql/execute
{
  "database": "students_db",
  "state": "maharashtra",
  "sql": "<script contents with __STATE_TABLE__ replaced with student_maharashtra>"
}
```

If `state` is omitted in the JSON body, the service automatically detects the target state from the `student_<state>` table name and routes to the appropriate state SQL server.

## Rules followed by every script

- No `DROP` or `DELETE` statements are used anywhere (enforced by
  [`app/sql_executor.py`](../app/sql_executor.py), which rejects any script
  containing those keywords, including inside `--` comments). Script 15
  demonstrates the intended pattern for removing a student: flipping an
  `is_active` flag instead of removing the row.
- Column/index additions check `information_schema` and run the `ALTER TABLE`
  via `PREPARE`/`EXECUTE`/`DEALLOCATE PREPARE` instead of
  `ADD COLUMN IF NOT EXISTS` / `ADD INDEX IF NOT EXISTS`, since that clause
  isn't supported by every MySQL version and previously caused a syntax error.
  `CREATE OR REPLACE VIEW` is used where possible so those scripts can be
  re-run safely. `CREATE PROCEDURE` and `CREATE TRIGGER` have no `IF NOT EXISTS`
  equivalent in MySQL, so those scripts are intended to run once per table.

## Folder index

| Folder | Scripts | Purpose                                                   |
| ------ | ------- | --------------------------------------------------------- |
| 1      | 01, 02  | Guardian contact columns; blood group column              |
| 2      | 03, 04  | School name/grade columns; emergency contact columns      |
| 3      | 05, 06  | Address/postal code columns; nationality column           |
| 4      | 07, 08  | Active-flag column; student category column               |
| 5      | 09, 10  | Audit log table + update trigger; lookup indexes          |
| 6      | 11, 12  | Procedure: get student by email; count students by city   |
| 7      | 13, 14  | Procedure: update guardian contact; get students by grade |
| 8      | 15, 16  | Procedure: soft-deactivate student; category counts       |
| 9      | 17, 18  | Views: contact summary; active students                   |
| 10     | 19, 20  | Parent detail columns; search-students procedure          |

Some later scripts assume columns added by earlier ones (noted in each file's
header comment) — run folders in order for a fully populated table.
