-- Script 09: Add an update-audit table and a trigger that logs student updates.
-- Target: any student_<state> table.
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- Triggers have no "IF NOT EXISTS" equivalent in MySQL; run this once per table.
-- No DROP or DELETE statements are used.

CREATE TABLE IF NOT EXISTS `__STATE_TABLE___audit_log` (
    audit_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    student_id BIGINT UNSIGNED NOT NULL,
    changed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (audit_id),
    KEY idx_audit_student_id (student_id)
) ENGINE=InnoDB;

DELIMITER $$

CREATE TRIGGER `trg___STATE_TABLE___after_update`
AFTER UPDATE ON `__STATE_TABLE__`
FOR EACH ROW
BEGIN
    INSERT INTO `__STATE_TABLE___audit_log` (student_id, changed_at)
    VALUES (NEW.student_id, NOW());
END$$

DELIMITER ;
