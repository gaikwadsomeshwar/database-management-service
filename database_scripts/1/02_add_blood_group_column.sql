-- Script 02: Add a blood_group column and backfill deterministic dummy values.
-- Target: any student_<state> table.
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- No DROP or DELETE statements are used.

ALTER TABLE `__STATE_TABLE__`
    ADD COLUMN IF NOT EXISTS blood_group VARCHAR(3) NULL AFTER city;

UPDATE `__STATE_TABLE__`
SET blood_group = CASE MOD(student_id, 8)
    WHEN 0 THEN 'O+'
    WHEN 1 THEN 'A+'
    WHEN 2 THEN 'B+'
    WHEN 3 THEN 'AB+'
    WHEN 4 THEN 'O-'
    WHEN 5 THEN 'A-'
    WHEN 6 THEN 'B-'
    ELSE 'AB-'
END
WHERE blood_group IS NULL;
