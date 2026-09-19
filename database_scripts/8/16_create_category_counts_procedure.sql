DELIMITER $$

-- Script 16: Create a procedure that summarizes students by category.
-- Target: any student_<state> table (run after script 08 adds student_category).
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- Procedures have no "IF NOT EXISTS" equivalent in MySQL; run this once per table.
-- No destructive schema-removal or row-removal statements are used.
CREATE PROCEDURE `sp___STATE_TABLE___get_category_counts`()
BEGIN
    SELECT student_category, COUNT(*) AS student_count
    FROM `__STATE_TABLE__`
    GROUP BY student_category;
END$$

DELIMITER ;
