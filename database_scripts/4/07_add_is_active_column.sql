-- Script 07: Add an is_active flag column and backfill all rows as active.
-- Target: any student_<state> table.
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- No destructive schema-removal or row-removal statements are used.
-- Uses information_schema + dynamic SQL instead of "ADD COLUMN IF NOT EXISTS"
-- for compatibility with MySQL versions that reject that clause.

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '__STATE_TABLE__' AND COLUMN_NAME = 'is_active'
);
SET @ddl = IF(@col_exists = 0,
    'ALTER TABLE `__STATE_TABLE__` ADD COLUMN is_active TINYINT(1) NOT NULL DEFAULT 1 AFTER created_at',
    'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

UPDATE `__STATE_TABLE__`
SET is_active = 1
WHERE is_active IS NULL;
