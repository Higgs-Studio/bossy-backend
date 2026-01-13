-- ============================================================================
-- Add Multi-Language Support to User Preferences
-- ============================================================================
-- This script adds the boss_language field to support multiple languages
-- Run this in your Supabase SQL Editor after running setup_database.sql
--
-- Supported Languages:
-- - en: English
-- - zh-TW: Traditional Chinese (繁體中文)
-- - zh-CN: Simplified Chinese (简体中文)
-- - yue: Cantonese (廣東話)
-- ============================================================================

-- Add boss_language field to user_preferences table
ALTER TABLE user_preferences 
ADD COLUMN IF NOT EXISTS boss_language TEXT DEFAULT 'en'
CHECK (boss_language IN ('en', 'zh-TW', 'zh-CN', 'yue'));

-- Add comment to explain the field
COMMENT ON COLUMN user_preferences.boss_language IS 
'Language preference for AI boss communication: en (English), zh-TW (Traditional Chinese), zh-CN (Simplified Chinese), yue (Cantonese)';

-- Create index for efficient querying by language
CREATE INDEX IF NOT EXISTS idx_user_preferences_language 
ON user_preferences(boss_language);

-- ============================================================================
-- Helper function to get language name
-- ============================================================================
CREATE OR REPLACE FUNCTION get_language_name(lang_code TEXT)
RETURNS TEXT AS $$
BEGIN
    RETURN CASE lang_code
        WHEN 'en' THEN 'English'
        WHEN 'zh-TW' THEN '繁體中文'
        WHEN 'zh-CN' THEN '简体中文'
        WHEN 'yue' THEN '廣東話'
        ELSE 'English'  -- default
    END;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- ============================================================================
-- Verify the setup
-- ============================================================================

-- Check if column was added successfully
SELECT 
    column_name, 
    data_type, 
    column_default,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'user_preferences' 
    AND column_name = 'boss_language';

-- Check constraint
SELECT 
    constraint_name,
    check_clause
FROM information_schema.check_constraints
WHERE constraint_name LIKE '%boss_language%';

-- View all user language preferences
SELECT 
    user_id, 
    boss_type,
    boss_language,
    get_language_name(boss_language) as language_name
FROM user_preferences
ORDER BY created_at DESC
LIMIT 10;

-- ============================================================================
-- Usage Examples
-- ============================================================================

-- Update a user's language preference
-- UPDATE user_preferences 
-- SET boss_language = 'zh-TW' 
-- WHERE user_id = 'your-user-id';

-- Get users by language
-- SELECT user_id, phone_no, boss_type, boss_language
-- FROM user_preferences
-- WHERE boss_language = 'zh-CN';

-- Count users by language
-- SELECT 
--     boss_language,
--     get_language_name(boss_language) as language_name,
--     COUNT(*) as user_count
-- FROM user_preferences
-- GROUP BY boss_language
-- ORDER BY user_count DESC;
