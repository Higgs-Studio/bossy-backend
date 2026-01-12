-- ============================================================================
-- Add Check-in Feature to User Preferences
-- ============================================================================
-- This script adds the necessary field to support scheduled check-ins
-- Run this in your Supabase SQL Editor after running setup_database.sql

-- Add next_checkin_at field to user_preferences table
-- This stores when the next check-in should be triggered for each user
ALTER TABLE user_preferences 
ADD COLUMN IF NOT EXISTS next_checkin_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();

-- Create index for efficient querying of users due for check-in
-- CREATE INDEX IF NOT EXISTS idx_user_preferences_next_checkin 
-- ON user_preferences(next_checkin_at) 
-- WHERE next_checkin_at <= NOW();

-- Add last_checkin_at to track when the last check-in was sent
ALTER TABLE user_preferences 
ADD COLUMN IF NOT EXISTS last_checkin_at TIMESTAMP WITH TIME ZONE;

-- ============================================================================
-- Helper function to get check-in interval based on boss type
-- ============================================================================
CREATE OR REPLACE FUNCTION get_checkin_interval(boss_type_param TEXT)
RETURNS INTERVAL AS $$
BEGIN
    RETURN CASE boss_type_param
        WHEN 'drill-sergeant' THEN INTERVAL '1 hour'
        WHEN 'execution' THEN INTERVAL '2 hours'
        WHEN 'supportive' THEN INTERVAL '4 hours'
        WHEN 'mentor' THEN INTERVAL '4 hours'
        ELSE INTERVAL '2 hours'  -- default to execution
    END;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- ============================================================================
-- Verify the setup
-- ============================================================================

-- Check if columns were added successfully
SELECT 
    column_name, 
    data_type, 
    is_nullable
FROM information_schema.columns
WHERE table_name = 'user_preferences' 
    AND column_name IN ('next_checkin_at', 'last_checkin_at')
ORDER BY ordinal_position;

-- ============================================================================
-- Initialize next_checkin_at for existing users
-- ============================================================================

-- Update existing users to have their first check-in scheduled based on their boss type
UPDATE user_preferences
SET next_checkin_at = NOW() + get_checkin_interval(boss_type)
WHERE next_checkin_at IS NULL OR next_checkin_at = NOW();

SELECT 
    user_id, 
    boss_type, 
    next_checkin_at,
    last_checkin_at
FROM user_preferences
ORDER BY next_checkin_at;

-- ============================================================================
-- Setup Complete!
-- ============================================================================
