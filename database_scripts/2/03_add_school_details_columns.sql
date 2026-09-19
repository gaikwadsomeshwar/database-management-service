-- Script 03: Add school_name and grade_level columns and backfill dummy values.
-- Target: any student_<state> table.
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- No DROP or DELETE statements are used.

ALTER TABLE `__STATE_TABLE__`
    ADD COLUMN IF NOT EXISTS school_name VARCHAR(160) NULL AFTER state,
    ADD COLUMN IF NOT EXISTS grade_level VARCHAR(20) NULL AFTER school_name;

UPDATE `__STATE_TABLE__`
SET
    school_name = CONCAT('Government School #', LPAD(MOD(student_id, 500) + 1, 3, '0')),
    grade_level = CASE MOD(student_id, 12)
        WHEN 0 THEN 'Grade 1' WHEN 1 THEN 'Grade 2' WHEN 2 THEN 'Grade 3'
        WHEN 3 THEN 'Grade 4' WHEN 4 THEN 'Grade 5' WHEN 5 THEN 'Grade 6'
        WHEN 6 THEN 'Grade 7' WHEN 7 THEN 'Grade 8' WHEN 8 THEN 'Grade 9'
        WHEN 9 THEN 'Grade 10' WHEN 10 THEN 'Grade 11' ELSE 'Grade 12'
    END
WHERE school_name IS NULL;
