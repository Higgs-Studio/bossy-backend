-- ============================================================================
-- Supabase Database Setup Script
-- ============================================================================
-- Run this script in your Supabase SQL Editor to set up the tasks table
-- https://app.supabase.com/project/_/sql/new

-- ============================================================================
-- 1. Create the tasks table
-- ============================================================================

CREATE TABLE IF NOT EXISTS tasks (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    priority TEXT DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high')),
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed', 'cancelled')),
    estimated_hours NUMERIC,
    goal TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- 2. Create indexes for better query performance
-- ============================================================================

-- Index on user_id for fast user-specific queries
CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id);

-- Index on status for filtering by task status
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

-- Composite index for common query pattern (user_id + status)
CREATE INDEX IF NOT EXISTS idx_tasks_user_status ON tasks(user_id, status);

-- Index on created_at for sorting by date
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC);

-- ============================================================================
-- 3. Create updated_at trigger
-- ============================================================================

-- Function to automatically update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger to call the function before any update
DROP TRIGGER IF EXISTS update_tasks_updated_at ON tasks;
CREATE TRIGGER update_tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- 4. Enable Row Level Security (RLS) - Optional but recommended
-- ============================================================================

-- Enable RLS on the tasks table
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;

-- Policy: Users can view their own tasks
CREATE POLICY "Users can view own tasks"
    ON tasks FOR SELECT
    USING (true);  -- Adjust this based on your auth setup

-- Policy: Users can insert their own tasks
CREATE POLICY "Users can insert own tasks"
    ON tasks FOR INSERT
    WITH CHECK (true);  -- Adjust this based on your auth setup

-- Policy: Users can update their own tasks
CREATE POLICY "Users can update own tasks"
    ON tasks FOR UPDATE
    USING (true);  -- Adjust this based on your auth setup

-- Policy: Users can delete their own tasks
CREATE POLICY "Users can delete own tasks"
    ON tasks FOR DELETE
    USING (true);  -- Adjust this based on your auth setup

-- ============================================================================
-- 5. Insert sample data for testing (optional)
-- ============================================================================

-- Uncomment the following lines to insert sample data

-- INSERT INTO tasks (user_id, title, description, priority, status, estimated_hours, goal)
-- VALUES 
--     ('test_user_123', 'Research market trends', 'Analyze current market conditions and competitors', 'high', 'pending', 3, 'Launch new product'),
--     ('test_user_123', 'Create product roadmap', 'Define features and timeline for product launch', 'high', 'pending', 5, 'Launch new product'),
--     ('test_user_123', 'Design mockups', 'Create UI/UX designs for the product', 'medium', 'in_progress', 8, 'Launch new product'),
--     ('test_user_123', 'Set up development environment', 'Configure tools and frameworks', 'medium', 'completed', 2, 'Launch new product'),
--     ('test_user_456', 'Plan team meeting', 'Schedule and prepare agenda for team sync', 'low', 'pending', 1, 'Improve team communication');

-- ============================================================================
-- 6. Verify the setup
-- ============================================================================

-- Check if table was created successfully
SELECT 
    table_name, 
    column_name, 
    data_type, 
    is_nullable
FROM information_schema.columns
WHERE table_name = 'tasks'
ORDER BY ordinal_position;

-- Check indexes
SELECT 
    indexname, 
    indexdef
FROM pg_indexes
WHERE tablename = 'tasks';

-- Count rows (should be 0 or 5 if you inserted sample data)
SELECT COUNT(*) as total_tasks FROM tasks;

-- ============================================================================
-- 7. Useful queries for testing
-- ============================================================================

-- Get all tasks for a specific user
-- SELECT * FROM tasks WHERE user_id = 'test_user_123';

-- Get pending tasks for a user
-- SELECT * FROM tasks WHERE user_id = 'test_user_123' AND status = 'pending';

-- Get high priority tasks
-- SELECT * FROM tasks WHERE priority = 'high' ORDER BY created_at DESC;

-- Get tasks by goal
-- SELECT * FROM tasks WHERE goal LIKE '%product%';

-- Update task status
-- UPDATE tasks SET status = 'completed' WHERE id = 1;

-- Delete a task
-- DELETE FROM tasks WHERE id = 1;

-- ============================================================================
-- Setup Complete!
-- ============================================================================

-- Next steps:
-- 1. Copy your SUPABASE_URL and SUPABASE_KEY to .env file
-- 2. Test the connection with: python test_agent.py
-- 3. Start the FastAPI server: uvicorn app:app --reload

-- For more information, see:
-- - QUICKSTART.md
-- - LANGGRAPH_SETUP.md
-- - IMPLEMENTATION_SUMMARY.md

