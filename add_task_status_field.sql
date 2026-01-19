-- ============================================================================
-- Add Status Field to Daily Tasks Table
-- ============================================================================
-- This script adds task status tracking directly in the daily_tasks table
-- Run this in your Supabase SQL Editor

-- Add status field to daily_tasks table
-- This allows tracking task status: 'todo', 'in_progress', 'done'
ALTER TABLE daily_tasks 
ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'todo' 
CHECK (status IN ('todo', 'in_progress', 'done'));

-- Create index for efficient status queries
CREATE INDEX IF NOT EXISTS idx_daily_tasks_status 
ON daily_tasks(status);

-- Create composite index for common query patterns (goal_id + status)
CREATE INDEX IF NOT EXISTS idx_daily_tasks_goal_status 
ON daily_tasks(goal_id, status);

-- ============================================================================
-- Update existing tasks to have default status 'todo'
-- ============================================================================
-- For tasks that already have check-ins, set their status based on check-in status
UPDATE daily_tasks dt
SET status = CASE 
    WHEN EXISTS (
        SELECT 1 FROM check_ins ci 
        WHERE ci.task_id = dt.id 
        AND ci.status = 'done'
    ) THEN 'done'
    WHEN EXISTS (
        SELECT 1 FROM check_ins ci 
        WHERE ci.task_id = dt.id 
        AND ci.status = 'missed'
    ) THEN 'todo'
    ELSE 'todo'
END
WHERE status IS NULL;

-- ============================================================================
-- Verify the setup
-- ============================================================================
SELECT 
    column_name, 
    data_type, 
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'daily_tasks' 
    AND column_name = 'status';

-- Check sample data
SELECT 
    id,
    task_text,
    task_date,
    status
FROM daily_tasks
LIMIT 10;

-- ============================================================================
-- Setup Complete!
-- ============================================================================
