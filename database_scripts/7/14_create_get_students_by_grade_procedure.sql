-- Script 14: Create a procedure that lists students in one grade level.
-- Target: any student_<state> table (run after script 03 adds grade_level).
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- Procedures have no "IF NOT EXISTS" equivalent in MySQL; run this once per table.
-- No DROP or DELETE statements are used.

DELIMITER $$

CREATE PROCEDURE `sp___STATE_TABLE___get_students_by_grade`(IN p_grade_level VARCHAR(20))
BEGIN
    SELECT student_id, first_name, last_name, school_name, grade_level
    FROM `__STATE_TABLE__`
    WHERE grade_level = p_grade_level;
END$$

DELIMITER ;
