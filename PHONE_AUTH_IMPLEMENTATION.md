# Phone Authentication Implementation

## Overview
This document describes the phone-based authentication implementation using WhatsApp numbers in Supabase. The approach uses anonymous authentication first, then updates the user with their phone number.

## Implementation Approach

### Why Anonymous Auth + Update User?

We use this two-step approach instead of direct phone sign-up because:
1. **No Password Required**: Direct phone sign-up requires a password, even for passwordless flows
2. **No OTP Verification**: Anonymous auth doesn't require SMS OTP verification
3. **Simpler Flow**: WhatsApp interaction itself serves as authentication
4. **Cost Effective**: No SMS costs for OTP verification
5. **Better UX**: Users don't need to receive and enter OTP codes

### How It Works

1. **Check for Existing User**: First check if phone number already exists in `user_preferences`
2. **Create Anonymous User**: Use `sign_in_anonymously()` to create a user without credentials
3. **Update with Phone**: Call `update_user()` to associate the phone number with the user
4. **Store in Database**: Insert user preferences with phone number

## Code Implementation

### Function: `create_phone_user()`

```python
def create_phone_user(phone_no: str) -> Optional[str]:
    """
    Create an anonymous user in Supabase Auth and then update with phone number.
    """
    try:
        # Check if user already exists
        existing_user = supabase.table("user_preferences")\
            .select("user_id")\
            .eq("phone_no", phone_no)\
            .execute()
        
        if existing_user.data and len(existing_user.data) > 0:
            return existing_user.data[0]["user_id"]
        
        # Step 1: Create anonymous user
        auth_response = supabase.auth.sign_in_anonymously()
        user_id = auth_response.user.id
        
        # Step 2: Update with phone number
        formatted_phone = f"+{phone_no}"
        supabase.auth.update_user({
            "phone": formatted_phone,
            "data": {
                "phone_no": phone_no,
                "auth_method": "whatsapp"
            }
        })
        
        # Step 3: Store in user_preferences
        preferences_data = {
            "user_id": user_id,
            "phone_no": phone_no,
            "boss_type": "execution",
            "boss_language": "en",
            "subscription_status": "free",
            "plan_name": "Free"
        }
        supabase.table("user_preferences").insert(preferences_data).execute()
        
        return user_id
    except Exception as e:
        logger.error(f"Error creating phone user: {e}")
        return None
```

## Supabase Configuration

### 1. Enable Anonymous Authentication

1. Go to Supabase Dashboard → Authentication → Providers
2. Find "Anonymous" provider
3. Toggle "Enable anonymous sign-ins" to **ON**

### 2. Optional: Enable Phone Provider

While not required for our implementation, you can optionally enable the Phone provider:

1. Go to Authentication → Providers
2. Click on "Phone" provider
3. Toggle "Enable Phone Sign-up" to ON
4. **Important**: Disable "Confirm phone" (since we're not using OTP)

This allows the phone number to be properly stored in the auth.users table.

## User Flow

1. **User sends WhatsApp message**
   - Webhook receives message with phone number

2. **System checks for existing user**
   - Queries `user_preferences` table by `phone_no`

3. **If user doesn't exist**
   - Create anonymous user in Supabase Auth
   - Update user with phone number
   - Insert record in `user_preferences`

4. **If user exists**
   - Use existing `user_id`
   - Continue with message processing

## Database Structure

### auth.users (Supabase Auth)
- `id`: UUID (user_id)
- `phone`: String (e.g., "+14155551234")
- `user_metadata`: JSON containing:
  - `phone_no`: Clean phone without prefix (e.g., "14155551234")
  - `auth_method`: "whatsapp"

### user_preferences (Custom Table)
- `user_id`: UUID (foreign key to auth.users)
- `phone_no`: String (e.g., "14155551234")
- `boss_type`: String (default: "execution")
- `boss_language`: String (default: "en")
- `subscription_status`: String (default: "free")
- `plan_name`: String (default: "Free")

## Testing

### Test New User Creation

1. Send WhatsApp message from new number: `+14155551234`
2. Check logs for:
   ```
   Created anonymous user with ID: <uuid> for phone: 14155551234
   Updated user <uuid> with phone number: +14155551234
   Created user_preferences record for user_id: <uuid>, phone: 14155551234
   ```

3. Verify in Supabase Dashboard:
   - **Authentication → Users**: Should show anonymous user with phone metadata
   - **Table Editor → user_preferences**: Should show record with phone_no

### Test Existing User

1. Send another message from same number
2. Check logs for:
   ```
   Found existing user with ID: <uuid> for phone: 14155551234
   ```

## Error Handling

The implementation handles several error scenarios:

1. **User Already Exists**: Returns existing user_id without creating duplicate
2. **Update User Fails**: Continues with phone stored in user_preferences table
3. **Database Insert Fails**: Returns None and logs error
4. **Any Exception**: Catches all exceptions, logs error, returns None

## Benefits of This Approach

✅ **No Password Management**: Users don't need passwords  
✅ **No OTP Verification**: Avoids SMS costs and complexity  
✅ **Simple Integration**: Works seamlessly with WhatsApp  
✅ **Cost Effective**: No SMS provider costs  
✅ **Better UX**: No additional steps for users  
✅ **Flexible**: Phone stored in both auth and database  

## Migration from Existing Anonymous Users

If you have existing anonymous users without phone numbers, they will be automatically associated with phone numbers when they send messages, as the system checks `user_preferences` by phone first.

## Security Considerations

1. **Phone Verification**: WhatsApp itself verifies phone numbers
2. **User Identity**: Tracked through WhatsApp interaction
3. **No Public Endpoints**: User creation only happens through webhook
4. **Database Security**: RLS policies should be configured appropriately

## Troubleshooting

### Issue: "Could not update user with phone number"

**Cause**: Phone provider not enabled or phone format incorrect  
**Solution**: 
- Enable Phone provider in Supabase Dashboard
- Ensure phone number has + prefix (e.g., "+14155551234")
- Check that update_user has proper permissions

### Issue: Duplicate users created

**Cause**: Race condition with multiple concurrent messages  
**Solution**: 
- Function checks for existing user first
- Database should have unique constraint on phone_no in user_preferences

### Issue: User not found after creation

**Cause**: Database insert failed but anonymous user was created  
**Solution**: 
- Check database logs
- Verify user_preferences table structure matches expected schema
- Ensure service role key has insert permissions

## Next Steps

1. ✅ Code implemented
2. ⬜ Enable Anonymous provider in Supabase
3. ⬜ (Optional) Enable Phone provider in Supabase
4. ⬜ Test with new WhatsApp number
5. ⬜ Monitor logs for any errors
6. ⬜ Configure RLS policies as needed
