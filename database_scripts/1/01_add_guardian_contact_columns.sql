-- Script 01: Add guardian contact columns and backfill dummy values.
-- Target: any student_<state> table.
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- No DROP or DELETE statements are used.

ALTER TABLE `__STATE_TABLE__`
    ADD COLUMN IF NOT EXISTS guardian_name VARCHAR(160) NULL AFTER phone_number,
    ADD COLUMN IF NOT EXISTS guardian_phone VARCHAR(25) NULL AFTER guardian_name;

UPDATE `__STATE_TABLE__`
SET
    guardian_name = CONCAT('Guardian of ', first_name, ' ', last_name),
    guardian_phone = CONCAT('+91-9', LPAD(MOD(student_id, 900000000), 9, '0'))
WHERE guardian_name IS NULL;
