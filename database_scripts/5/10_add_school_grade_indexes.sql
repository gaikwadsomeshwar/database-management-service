-- Script 10: Add lookup indexes for school and postal-code columns.
-- Target: any student_<state> table (run after scripts 03 and 05 add the
-- school_name, grade_level, and postal_code columns).
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- No destructive schema-removal or row-removal statements are used.
-- Uses information_schema + dynamic SQL instead of "ADD INDEX IF NOT EXISTS"
-- for compatibility with MySQL versions that reject that clause.

SET @idx_exists = (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '__STATE_TABLE__' AND INDEX_NAME = 'idx_school_grade'
);
SET @ddl = IF(@idx_exists = 0,
    'ALTER TABLE `__STATE_TABLE__` ADD INDEX idx_school_grade (school_name, grade_level)',
    'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '__STATE_TABLE__' AND INDEX_NAME = 'idx_postal_code'
);
SET @ddl = IF(@idx_exists = 0,
    'ALTER TABLE `__STATE_TABLE__` ADD INDEX idx_postal_code (postal_code)',
    'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
