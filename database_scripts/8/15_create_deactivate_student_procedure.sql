DELIMITER $$

-- Script 15: Create a soft-deactivation procedure (the row is never removed).
-- Target: any student_<state> table (run after script 07 adds is_active).
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- Procedures have no "IF NOT EXISTS" equivalent in MySQL; run this once per table.
-- No destructive row-removal statements are used; this flips is_active instead.
CREATE PROCEDURE `sp___STATE_TABLE___deactivate_student`(IN p_student_id BIGINT UNSIGNED)
BEGIN
    UPDATE `__STATE_TABLE__`
    SET is_active = 0
    WHERE student_id = p_student_id;
END$$

DELIMITER ;
