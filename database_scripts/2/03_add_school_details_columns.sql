-- Script 03: Add school_name and grade_level columns and backfill dummy values.
-- Target: any student_<state> table.
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- No destructive schema-removal or row-removal statements are used.
-- Uses information_schema + dynamic SQL instead of "ADD COLUMN IF NOT EXISTS"
-- for compatibility with MySQL versions that reject that clause.

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '__STATE_TABLE__' AND COLUMN_NAME = 'school_name'
);
SET @ddl = IF(@col_exists = 0,
    'ALTER TABLE `__STATE_TABLE__` ADD COLUMN school_name VARCHAR(160) NULL AFTER state',
    'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '__STATE_TABLE__' AND COLUMN_NAME = 'grade_level'
);
SET @ddl = IF(@col_exists = 0,
    'ALTER TABLE `__STATE_TABLE__` ADD COLUMN grade_level VARCHAR(20) NULL AFTER school_name',
    'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

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
