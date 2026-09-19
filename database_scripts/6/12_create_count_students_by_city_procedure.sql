-- Script 12: Create a procedure that counts students grouped by city.
-- Target: any student_<state> table.
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- Procedures have no "IF NOT EXISTS" equivalent in MySQL; run this once per table.
-- No DROP or DELETE statements are used.

DELIMITER $$

CREATE PROCEDURE `sp___STATE_TABLE___count_students_by_city`()
BEGIN
    SELECT city, COUNT(*) AS student_count
    FROM `__STATE_TABLE__`
    GROUP BY city
    ORDER BY student_count DESC;
END$$

DELIMITER ;
