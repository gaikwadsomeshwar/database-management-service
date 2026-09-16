-- Script 08: Add a student_category column and backfill deterministic dummy values.
-- Target: any student_<state> table.
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- No DROP or DELETE statements are used.

ALTER TABLE `__STATE_TABLE__`
    ADD COLUMN IF NOT EXISTS student_category VARCHAR(20) NULL AFTER state;

UPDATE `__STATE_TABLE__`
SET student_category = CASE MOD(student_id, 5)
    WHEN 0 THEN 'General'
    WHEN 1 THEN 'OBC'
    WHEN 2 THEN 'SC'
    WHEN 3 THEN 'ST'
    ELSE 'EWS'
END
WHERE student_category IS NULL;
