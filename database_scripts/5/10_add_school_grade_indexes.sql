-- Script 10: Add lookup indexes for school and postal-code columns.
-- Target: any student_<state> table (run after scripts 03 and 05 add the
-- school_name, grade_level, and postal_code columns).
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- No DROP or DELETE statements are used.

ALTER TABLE `__STATE_TABLE__`
    ADD INDEX IF NOT EXISTS idx_school_grade (school_name, grade_level),
    ADD INDEX IF NOT EXISTS idx_postal_code (postal_code);
