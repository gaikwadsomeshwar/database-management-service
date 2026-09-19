-- Script 06: Add a nationality column defaulted to 'Indian' and backfill dummy values.
-- Target: any student_<state> table.
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- No DROP or DELETE statements are used.

ALTER TABLE `__STATE_TABLE__`
    ADD COLUMN IF NOT EXISTS nationality VARCHAR(60) NOT NULL DEFAULT 'Indian' AFTER state;

UPDATE `__STATE_TABLE__`
SET nationality = 'Indian'
WHERE nationality IS NULL OR nationality = '';
