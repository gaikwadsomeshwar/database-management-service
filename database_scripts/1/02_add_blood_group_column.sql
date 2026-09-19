-- Script 02: Add a blood_group column and backfill deterministic dummy values.
-- Target: any student_<state> table.
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- No destructive schema-removal or row-removal statements are used.
-- Uses information_schema + dynamic SQL instead of "ADD COLUMN IF NOT EXISTS"
-- for compatibility with MySQL versions that reject that clause.

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '__STATE_TABLE__' AND COLUMN_NAME = 'blood_group'
);
SET @ddl = IF(@col_exists = 0,
    'ALTER TABLE `__STATE_TABLE__` ADD COLUMN blood_group VARCHAR(3) NULL AFTER city',
    'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

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
