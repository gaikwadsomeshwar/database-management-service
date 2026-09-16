# Database Scripts

20 standalone MySQL scripts, two per numbered folder (`1`-`10`), that can be run
against **any** generated `student_<state>` table (e.g. `student_maharashtra`,
`student_uttar_pradesh`).

## Usage

Every script uses the placeholder token `__STATE_TABLE__` wherever the target
table name is needed. Before running a script, replace every occurrence of
`__STATE_TABLE__` with the target table name, then execute it with the CLI
runner or the `/api/sql/execute` endpoint:

```powershell
python app/main.py DatabaseScripts/1/01_add_guardian_contact_columns.sql
```

or via the API (`database` must match the connected schema, e.g. `students_db`):

```json
POST /api/sql/execute
{
  "database": "students_db",
  "sql": "<script contents with __STATE_TABLE__ replaced>"
}
```

## Rules followed by every script

- No `DROP` or `DELETE` statements are used anywhere (enforced by
  [`app/sql_executor.py`](../app/sql_executor.py), which rejects any script
  containing those keywords). Script 15 demonstrates the intended pattern for
  removing a student: flipping an `is_active` flag instead of deleting the row.
- `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` / `ADD INDEX IF NOT EXISTS` and
  `CREATE OR REPLACE VIEW` are used where possible so scripts can be re-run
  safely. `CREATE PROCEDURE` and `CREATE TRIGGER` have no `IF NOT EXISTS`
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
