-- Script 20: Create a read-only procedure that searches students by name and city.
-- Target: any student_<state> table.
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- Procedures have no "IF NOT EXISTS" equivalent in MySQL; run this once per table.
-- No DROP or DELETE statements are used.

DELIMITER $$

CREATE PROCEDURE `sp___STATE_TABLE___search_students`(
    IN p_first_name VARCHAR(80),
    IN p_last_name VARCHAR(80),
    IN p_city VARCHAR(100)
)
BEGIN
    SELECT student_id, first_name, last_name, email, city, state
    FROM `__STATE_TABLE__`
    WHERE (p_first_name IS NULL OR first_name LIKE CONCAT('%', p_first_name, '%'))
      AND (p_last_name IS NULL OR last_name LIKE CONCAT('%', p_last_name, '%'))
      AND (p_city IS NULL OR city LIKE CONCAT('%', p_city, '%'));
END$$

DELIMITER ;
