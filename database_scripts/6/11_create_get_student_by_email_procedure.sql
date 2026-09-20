DELIMITER $$

-- Script 11: Create a procedure that looks up one student by email.
-- Target: any student_<state> table.
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- Procedures have no "IF NOT EXISTS" equivalent in MySQL; run this once per table.
DROP PROCEDURE IF EXISTS `sp___STATE_TABLE___get_student_by_email`$$

CREATE PROCEDURE `sp___STATE_TABLE___get_student_by_email`(IN p_email VARCHAR(255))
BEGIN
    SELECT student_id, first_name, last_name, email, phone_number, city, state
    FROM `__STATE_TABLE__`
    WHERE email = p_email;
END$$

DELIMITER ;
