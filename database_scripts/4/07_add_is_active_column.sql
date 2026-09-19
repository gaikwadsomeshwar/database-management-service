-- Script 07: Add an is_active flag column and backfill all rows as active.
-- Target: any student_<state> table.
-- Replace every __STATE_TABLE__ with the target table name (e.g. student_maharashtra).
-- No DROP or DELETE statements are used.

ALTER TABLE `__STATE_TABLE__`
    ADD COLUMN IF NOT EXISTS is_active TINYINT(1) NOT NULL DEFAULT 1 AFTER created_at;

UPDATE `__STATE_TABLE__`
SET is_active = 1
WHERE is_active IS NULL;
