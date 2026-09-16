-- Script 17: Create a view summarizing student and guardian contact details.
-- Target: any student_<state> table (run after script 01 adds guardian columns).
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- No DROP or DELETE statements are used; CREATE OR REPLACE keeps this re-runnable.

CREATE OR REPLACE VIEW `vw___STATE_TABLE___contact_summary` AS
SELECT
    student_id,
    CONCAT(first_name, ' ', last_name) AS full_name,
    email,
    phone_number,
    guardian_name,
    guardian_phone
FROM `__STATE_TABLE__`;
