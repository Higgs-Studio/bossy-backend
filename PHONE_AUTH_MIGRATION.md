# Phone Authentication Migration

## Overview
This document describes the migration from anonymous user authentication to phone-based authentication using WhatsApp numbers in Supabase.

## Changes Made

### 1. Function Renamed
- `create_anonymous_user()` → `create_phone_user()`

### 2. Authentication Method Updated
**Before (Anonymous Auth):**
```python
auth_response = supabase.auth.sign_in_anonymously()
```

**After (Phone Auth):**
```python
auth_response = supabase.auth.sign_up({
    "phone": formatted_phone,
    "password": None,
    "options": {
        "data": {
            "phone_no": phone_no,
            "auth_method": "whatsapp"
        }
    }
})
```

### 3. Key Improvements
- Users are now created with their phone number as the primary authentication method
- Phone numbers are stored in Supabase Auth with the `phone` provider
- Metadata includes `auth_method: "whatsapp"` for tracking
- Better handling of existing users (checks if user already exists)
- Maintains backward compatibility with existing user_preferences table structure

## Supabase Configuration Required

### Enable Phone Authentication

1. **Go to Supabase Dashboard**
   - Navigate to: Authentication → Providers

2. **Enable Phone Provider**
   - Click on "Phone" provider
   - Toggle "Enable Phone Sign-up" to ON

3. **Configure Phone Settings (Optional)**
   
   For production, you can configure SMS OTP settings:
   - **SMS Provider**: Choose between Twilio, MessageBird, Vonage, or Textlocal
   - **Phone Number Confirmation**: Enable/disable based on your needs
   
   For WhatsApp integration (current setup):
   - You can disable "Confirm phone" since authentication is handled via WhatsApp interaction
   - Set "Minimum Password Length" to 0 or leave blank (passwordless)

4. **Allow Passwordless Phone Auth**
   - In the Phone provider settings, ensure passwordless authentication is enabled
   - This allows users to sign up with just a phone number

### Database Policies

Ensure your Row Level Security (RLS) policies on `user_preferences` table allow:
```sql
-- Allow users to read their own preferences
CREATE POLICY "Users can read own preferences"
ON user_preferences
FOR SELECT
USING (auth.uid() = user_id);

-- Allow insert for new users (system creates via service role key)
-- Service role bypasses RLS, so this is already handled
```

## Testing

### Test the New Flow

1. **New User Sign Up:**
   - Send a WhatsApp message from a new number
   - System should create a phone-authenticated user
   - Check Supabase Auth dashboard to verify user has phone provider

2. **Existing User:**
   - Send a message from an existing number
   - System should find and use existing user_id

3. **Verify User in Dashboard:**
   - Go to: Authentication → Users
   - New users should show:
     - Phone number in the Phone column
     - Provider: phone
     - User metadata should include `auth_method: "whatsapp"`

## Code Changes Summary

### File: `app.py`

**Lines 3081-3138:** Renamed and updated `create_phone_user()` function
- Uses `sign_up()` with phone provider instead of `sign_in_anonymously()`
- Formats phone number with + prefix for Supabase
- Includes fallback logic to find existing users
- Adds metadata: `auth_method: "whatsapp"`

**Lines 3179-3196:** Updated webhook handler
- Changed function call from `create_anonymous_user()` to `create_phone_user()`
- Updated log messages to reflect "phone user" instead of "anonymous user"

## Migration Notes

### Existing Users
- **Existing anonymous users will continue to work** as they're identified by phone number in `user_preferences`
- New users will use phone authentication
- Over time, as users interact, the system will naturally migrate to phone auth

### Optional: Migrate Existing Anonymous Users
If you want to migrate existing anonymous users to phone auth, you can create a migration script:

```python
# Migration script (run once)
def migrate_anonymous_to_phone():
    # Get all user_preferences with phone numbers
    users = supabase.table("user_preferences").select("*").execute()
    
    for user in users.data:
        phone_no = user['phone_no']
        user_id = user['user_id']
        
        # Check if user exists in auth.users
        # If anonymous, update to phone provider
        # This would require admin API access
        pass
```

## Benefits of Phone Authentication

1. **Proper User Identity**: Users have a real identity tied to their phone number
2. **Better Security**: Can implement OTP verification if needed in future
3. **Compliance**: Aligns with authentication best practices
4. **User Management**: Easier to manage users in Supabase dashboard
5. **Future Features**: Enables SMS notifications, password reset, etc.

## Next Steps

1. ✅ Code updated to use phone authentication
2. ⬜ Enable Phone provider in Supabase Dashboard
3. ⬜ Test with new user registration
4. ⬜ Monitor logs for any authentication errors
5. ⬜ (Optional) Set up SMS OTP for additional security

## Rollback Plan

If you need to rollback to anonymous auth:

1. Rename `create_phone_user()` back to `create_anonymous_user()`
2. Change `sign_up()` back to `sign_in_anonymously()`
3. Remove phone formatting and metadata
4. Redeploy

## Support

If you encounter issues:
- Check Supabase Auth logs in Dashboard
- Verify phone provider is enabled
- Ensure service role key has proper permissions
- Check application logs for authentication errors
