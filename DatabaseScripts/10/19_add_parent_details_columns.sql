-- Script 19: Add parent occupation and email columns and backfill dummy values.
-- Target: any student_<state> table.
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- No DROP or DELETE statements are used.

ALTER TABLE `__STATE_TABLE__`
    ADD COLUMN IF NOT EXISTS parent_occupation VARCHAR(120) NULL AFTER state,
    ADD COLUMN IF NOT EXISTS parent_email VARCHAR(255) NULL AFTER parent_occupation;

UPDATE `__STATE_TABLE__`
SET
    parent_occupation = CASE MOD(student_id, 6)
        WHEN 0 THEN 'Farmer' WHEN 1 THEN 'Teacher' WHEN 2 THEN 'Engineer'
        WHEN 3 THEN 'Business Owner' WHEN 4 THEN 'Government Employee'
        ELSE 'Homemaker'
    END,
    parent_email = CONCAT('parent.', LOWER(first_name), '.', student_id, '@example.com')
WHERE parent_occupation IS NULL;
