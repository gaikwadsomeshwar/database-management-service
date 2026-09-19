-- Script 04: Add emergency contact columns and backfill dummy values.
-- Target: any student_<state> table.
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- No destructive schema-removal or row-removal statements are used.
-- Uses information_schema + dynamic SQL instead of "ADD COLUMN IF NOT EXISTS"
-- for compatibility with MySQL versions that reject that clause.

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '__STATE_TABLE__' AND COLUMN_NAME = 'emergency_contact_name'
);
SET @ddl = IF(@col_exists = 0,
    'ALTER TABLE `__STATE_TABLE__` ADD COLUMN emergency_contact_name VARCHAR(160) NULL AFTER enrollment_date',
    'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '__STATE_TABLE__' AND COLUMN_NAME = 'emergency_contact_phone'
);
SET @ddl = IF(@col_exists = 0,
    'ALTER TABLE `__STATE_TABLE__` ADD COLUMN emergency_contact_phone VARCHAR(25) NULL AFTER emergency_contact_name',
    'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

UPDATE `__STATE_TABLE__`
SET
    emergency_contact_name = CONCAT('Emergency Contact for ', first_name),
    emergency_contact_phone = CONCAT('+91-8', LPAD(MOD(student_id, 900000000), 9, '0'))
WHERE emergency_contact_name IS NULL;
