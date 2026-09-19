-- Script 04: Add emergency contact columns and backfill dummy values.
-- Target: any student_<state> table.
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- No DROP or DELETE statements are used.

ALTER TABLE `__STATE_TABLE__`
    ADD COLUMN IF NOT EXISTS emergency_contact_name VARCHAR(160) NULL AFTER enrollment_date,
    ADD COLUMN IF NOT EXISTS emergency_contact_phone VARCHAR(25) NULL AFTER emergency_contact_name;

UPDATE `__STATE_TABLE__`
SET
    emergency_contact_name = CONCAT('Emergency Contact for ', first_name),
    emergency_contact_phone = CONCAT('+91-8', LPAD(MOD(student_id, 900000000), 9, '0'))
WHERE emergency_contact_name IS NULL;
