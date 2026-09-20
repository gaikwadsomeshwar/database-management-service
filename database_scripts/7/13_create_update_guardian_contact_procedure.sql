DELIMITER $$

-- Script 13: Create a procedure that updates one student's guardian contact.
-- Target: any student_<state> table (run after script 01 adds guardian columns).
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- Procedures have no "IF NOT EXISTS" equivalent in MySQL; run this once per table.
-- No destructive schema-removal or row-removal statements are used.
DROP PROCEDURE IF EXISTS `sp___STATE_TABLE___update_guardian_contact`$$

CREATE PROCEDURE `sp___STATE_TABLE___update_guardian_contact`(
    IN p_student_id BIGINT UNSIGNED,
    IN p_guardian_name VARCHAR(160),
    IN p_guardian_phone VARCHAR(25)
)
BEGIN
    UPDATE `__STATE_TABLE__`
    SET guardian_name = p_guardian_name,
        guardian_phone = p_guardian_phone
    WHERE student_id = p_student_id;
END$$

DELIMITER ;
