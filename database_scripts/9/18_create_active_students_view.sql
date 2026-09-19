-- Script 18: Create a view exposing only active students.
-- Target: any student_<state> table (run after script 07 adds is_active).
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- No DROP or DELETE statements are used; CREATE OR REPLACE keeps this re-runnable.

CREATE OR REPLACE VIEW `vw___STATE_TABLE___active_students` AS
SELECT student_id, first_name, last_name, email, city, state, enrollment_date
FROM `__STATE_TABLE__`
WHERE is_active = 1;
