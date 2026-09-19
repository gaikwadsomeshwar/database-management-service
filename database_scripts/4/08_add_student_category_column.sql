-- Script 08: Add a student_category column and backfill deterministic dummy values.
-- Target: any student_<state> table.
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- No destructive schema-removal or row-removal statements are used.
-- Uses information_schema + dynamic SQL instead of "ADD COLUMN IF NOT EXISTS"
-- for compatibility with MySQL versions that reject that clause.

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '__STATE_TABLE__' AND COLUMN_NAME = 'student_category'
);
SET @ddl = IF(@col_exists = 0,
    'ALTER TABLE `__STATE_TABLE__` ADD COLUMN student_category VARCHAR(20) NULL AFTER state',
    'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

UPDATE `__STATE_TABLE__`
SET student_category = CASE MOD(student_id, 5)
    WHEN 0 THEN 'General'
    WHEN 1 THEN 'OBC'
    WHEN 2 THEN 'SC'
    WHEN 3 THEN 'ST'
    ELSE 'EWS'
END
WHERE student_category IS NULL;
