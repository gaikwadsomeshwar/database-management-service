-- Script 01: Add guardian contact columns and backfill dummy values.
-- Target: any student_<state> table.
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- No destructive schema-removal or row-removal statements are used.
-- Uses information_schema + dynamic SQL instead of "ADD COLUMN IF NOT EXISTS"
-- for compatibility with MySQL versions that reject that clause.

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '__STATE_TABLE__' AND COLUMN_NAME = 'guardian_name'
);
SET @ddl = IF(@col_exists = 0,
    'ALTER TABLE `__STATE_TABLE__` ADD COLUMN guardian_name VARCHAR(160) NULL AFTER phone_number',
    'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '__STATE_TABLE__' AND COLUMN_NAME = 'guardian_phone'
);
SET @ddl = IF(@col_exists = 0,
    'ALTER TABLE `__STATE_TABLE__` ADD COLUMN guardian_phone VARCHAR(25) NULL AFTER guardian_name',
    'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

UPDATE `__STATE_TABLE__`
SET
    guardian_name = CONCAT('Guardian of ', first_name, ' ', last_name),
    guardian_phone = CONCAT('+91-9', LPAD(MOD(student_id, 900000000), 9, '0'))
WHERE guardian_name IS NULL;
