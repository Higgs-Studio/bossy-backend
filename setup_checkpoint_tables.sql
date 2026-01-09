-- ============================================================================
-- LangGraph Checkpoint Tables Setup Script
-- ============================================================================
-- This script sets up the necessary tables for LangGraph persistence.
-- 
-- NOTE: The PostgresSaver.setup() method in app.py will automatically create
-- these tables when the application starts. This script is provided for
-- reference and manual setup if needed.
--
-- Run this script in your Supabase SQL Editor:
-- https://app.supabase.com/project/_/sql/new
-- ============================================================================

-- ============================================================================
-- 1. Create checkpoint table
-- ============================================================================
-- This table stores the conversation state checkpoints

CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    checkpoint JSONB NOT NULL,
    parent_checkpoint_id TEXT,
    metadata JSONB,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

-- ============================================================================
-- 2. Create checkpoint_blobs table
-- ============================================================================
-- This table stores binary data associated with checkpoints

CREATE TABLE IF NOT EXISTS checkpoint_blobs (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL,
    version TEXT NOT NULL,
    type TEXT,
    blob BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
);

-- ============================================================================
-- 3. Create indexes for better query performance
-- ============================================================================

-- Index on thread_id for fast conversation lookup
CREATE INDEX IF NOT EXISTS idx_checkpoints_thread_id ON checkpoints(thread_id);

-- Index on parent_checkpoint_id for traversing checkpoint chains
CREATE INDEX IF NOT EXISTS idx_checkpoints_parent ON checkpoints(parent_checkpoint_id);

-- Composite index for common query pattern (thread_id + checkpoint_ns)
CREATE INDEX IF NOT EXISTS idx_checkpoints_thread_ns ON checkpoints(thread_id, checkpoint_ns);

-- Index on checkpoint_blobs thread_id
CREATE INDEX IF NOT EXISTS idx_checkpoint_blobs_thread_id ON checkpoint_blobs(thread_id);

-- ============================================================================
-- 4. Enable Row Level Security (RLS) - Optional but recommended
-- ============================================================================

-- Enable RLS on checkpoint tables
ALTER TABLE checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE checkpoint_blobs ENABLE ROW LEVEL SECURITY;

-- Policy: Allow all operations (adjust based on your auth setup)
-- In production, you may want to restrict access based on user_id
CREATE POLICY "Allow checkpoint access"
    ON checkpoints FOR ALL
    USING (true);

CREATE POLICY "Allow checkpoint_blob access"
    ON checkpoint_blobs FOR ALL
    USING (true);

-- ============================================================================
-- 5. Verify the setup
-- ============================================================================

-- Check if tables were created successfully
SELECT 
    table_name, 
    column_name, 
    data_type, 
    is_nullable
FROM information_schema.columns
WHERE table_name IN ('checkpoints', 'checkpoint_blobs')
ORDER BY table_name, ordinal_position;

-- Check indexes
SELECT 
    indexname, 
    indexdef
FROM pg_indexes
WHERE tablename IN ('checkpoints', 'checkpoint_blobs');

-- ============================================================================
-- 6. Useful queries for monitoring
-- ============================================================================

-- Count checkpoints per thread (conversation)
-- SELECT thread_id, COUNT(*) as checkpoint_count 
-- FROM checkpoints 
-- GROUP BY thread_id 
-- ORDER BY checkpoint_count DESC;

-- Get latest checkpoint for a specific thread
-- SELECT * FROM checkpoints 
-- WHERE thread_id = 'your-user-id' 
-- ORDER BY checkpoint_id DESC 
-- LIMIT 1;

-- Clean up old checkpoints (optional - be careful!)
-- DELETE FROM checkpoints 
-- WHERE thread_id = 'old-thread-id';

-- ============================================================================
-- Setup Complete!
-- ============================================================================

-- Next steps:
-- 1. Ensure SUPABASE_DB_URI is set in your .env file
-- 2. The PostgresSaver.setup() will verify/create these tables on app startup
-- 3. Each user's conversation will be persisted using their user_id as thread_id
-- 4. Conversation history will be automatically loaded when processing new messages
