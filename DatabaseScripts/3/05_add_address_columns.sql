-- Script 05: Add address_line and postal_code columns and backfill dummy values.
-- Target: any student_<state> table.
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- No DROP or DELETE statements are used.

ALTER TABLE `__STATE_TABLE__`
    ADD COLUMN IF NOT EXISTS address_line VARCHAR(200) NULL AFTER city,
    ADD COLUMN IF NOT EXISTS postal_code VARCHAR(10) NULL AFTER address_line;

UPDATE `__STATE_TABLE__`
SET
    address_line = CONCAT(MOD(student_id, 999) + 1, ' Main Street'),
    postal_code = LPAD(MOD(student_id, 900000) + 100000, 6, '0')
WHERE address_line IS NULL;
