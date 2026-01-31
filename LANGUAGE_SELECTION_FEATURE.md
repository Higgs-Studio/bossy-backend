# Language Selection Feature Implementation

## Overview
This feature adds automatic language preference selection for new users when they first interact with the WhatsApp bot. Instead of immediately greeting users, the bot now asks them to choose their preferred language before proceeding.

## User Flow

### Step 1: First Message
When a new user sends their first message to the bot, they receive:

```
Welcome! I'm your accountability boss.

Before we start, which language would you prefer?

1. English
2. 繁體中文 (Traditional Chinese)
3. 简体中文 (Simplified Chinese)
4. 廣東話 (Cantonese)

Please reply with the number (1, 2, 3, or 4).
```

### Step 2: Language Selection
The user replies with a number (1-4) to select their language:
- `1` → English (en)
- `2` → Traditional Chinese (zh-TW)
- `3` → Simplified Chinese (zh-CN)
- `4` → Cantonese (zh-HK)

### Step 3: Confirmation & Greeting
Once the user selects a valid language:
1. The `boss_language` field in `user_preferences` is updated
2. The bot sends a personalized greeting in the selected language
3. The conversation continues normally in that language

### Invalid Selection Handling
If the user enters an invalid response (not 1-4), the bot prompts them again:

```
Please choose a valid language option by replying with a number:

1. English
2. 繁體中文 (Traditional Chinese)
3. 简体中文 (Simplified Chinese)
4. 廣東話 (Cantonese)
```

## Technical Implementation

### Files Modified

#### 1. `language_prompts.py`
- Added `LANGUAGE_SELECTION_MESSAGE` constant
- Added `get_language_selection_message()` function
- Added `parse_language_selection()` function to map user input to language codes

#### 2. `app.py`

##### Updated Imports
```python
from language_prompts import (
    # ... existing imports
    get_language_selection_message,
    parse_language_selection
)
```

##### Modified `create_phone_user()` Function (formerly `create_anonymous_user()`)
- Creates anonymous user first using `sign_in_anonymously()`
- Updates the user with phone number using `update_user()`
- Stores `phone_no` in both auth metadata and `user_preferences` table
- Default `boss_language` is set to "en" initially (updated after user selection)
- Avoids password requirements by using anonymous auth + update approach

##### Modified `process_message()` Function
The function now handles three states:

1. **First Message (No History)**
   - Sends language selection message
   - Saves conversation state to checkpointer

2. **Second Message (Language Selection Response)**
   - Checks if user is responding to language selection
   - Validates the input (1-4)
   - Updates `user_preferences.boss_language` in database
   - Sends personalized greeting in selected language

3. **Regular Messages**
   - Processes normally through LangGraph agent
   - Uses stored `boss_language` preference

### Database Changes

The `user_preferences` table now includes:
- `boss_language`: Updated to user's selected language (after Step 2)
- `phone_no`: Stores the WhatsApp phone number (without whatsapp: prefix or +)

### Key Features

1. **Conversation State Management**
   - Uses LangGraph checkpointer to track conversation history
   - Detects if user is in language selection state
   - Ensures language selection happens before normal conversation

2. **Error Handling**
   - Gracefully handles invalid selections
   - Falls back to English if there are errors
   - Logs all state transitions for debugging

3. **Persistence**
   - Language preference is stored in `user_preferences` table
   - All subsequent messages use the selected language
   - Conversation history is maintained across sessions

## Anonymous User Creation

When a phone number is not found:

1. **Create Anonymous Supabase Auth User**
   - Uses Supabase's `sign_in_anonymously()` method
   - No email or password required
   - Creates a truly anonymous user with a UUID
   - Updates user metadata with phone number and `is_anonymous` flag

2. **Create User Preferences Record**
   - Links the anonymous user_id to the WhatsApp phone number
   - Default `boss_type`: "execution"
   - Default `boss_language`: "en" (updated after selection)
   - Default subscription: "free"
   - Stores phone number for lookup

### Where Phone Number is Stored

The phone number is stored in two places:
1. **Supabase Auth User Metadata**: `user.user_metadata.phone_no`
2. **User Preferences Table**: `user_preferences.phone_no` (for quick lookup)

## Testing the Feature

### Test Case 1: New User (English)
1. New user sends: "Hello"
2. Bot responds with language selection
3. User replies: "1"
4. Bot greets in English: "Hey, I'm Clio..."

### Test Case 2: New User (Chinese)
1. New user sends: "你好"
2. Bot responds with language selection
3. User replies: "2"
4. Bot greets in Traditional Chinese: "嘿，我是 Clio..."

### Test Case 3: Invalid Selection
1. New user sends: "Hi"
2. Bot responds with language selection
3. User replies: "5" (invalid)
4. Bot asks again for valid selection

## Benefits

1. **Better User Experience**: Users can choose their preferred language upfront
2. **Multilingual Support**: Seamlessly supports 4 languages
3. **No Manual Configuration**: Language is set through natural conversation
4. **Persistent Preference**: Language choice is saved and used in all future interactions
5. **Clean Onboarding**: First-time users get a clear, guided setup experience

## Future Enhancements

Possible improvements:
- Add more languages
- Allow users to change language later (e.g., "change language" command)
- Auto-detect language from user's first message
- Add language preference to user profile page
