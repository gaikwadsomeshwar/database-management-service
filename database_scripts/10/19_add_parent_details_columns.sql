-- Script 19: Add parent occupation and email columns and backfill dummy values.
-- Target: any student_<state> table.
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- No destructive schema-removal or row-removal statements are used.
-- Uses information_schema + dynamic SQL instead of "ADD COLUMN IF NOT EXISTS"
-- for compatibility with MySQL versions that reject that clause.

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '__STATE_TABLE__' AND COLUMN_NAME = 'parent_occupation'
);
SET @ddl = IF(@col_exists = 0,
    'ALTER TABLE `__STATE_TABLE__` ADD COLUMN parent_occupation VARCHAR(120) NULL AFTER state',
    'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '__STATE_TABLE__' AND COLUMN_NAME = 'parent_email'
);
SET @ddl = IF(@col_exists = 0,
    'ALTER TABLE `__STATE_TABLE__` ADD COLUMN parent_email VARCHAR(255) NULL AFTER parent_occupation',
    'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

UPDATE `__STATE_TABLE__`
SET
    parent_occupation = CASE MOD(student_id, 6)
        WHEN 0 THEN 'Farmer' WHEN 1 THEN 'Teacher' WHEN 2 THEN 'Engineer'
        WHEN 3 THEN 'Business Owner' WHEN 4 THEN 'Government Employee'
        ELSE 'Homemaker'
    END,
    parent_email = CONCAT('parent.', LOWER(first_name), '.', student_id, '@example.com')
WHERE parent_occupation IS NULL;
