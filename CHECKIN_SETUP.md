# Check-in Feature Setup Guide

## Overview

The check-in feature allows the chatbot to proactively reach out to users at regular intervals based on their boss type personality. This helps maintain accountability and keeps users engaged with their goals.

## Check-in Frequencies

The check-in frequency is determined by the user's `boss_type` preference:

| Boss Type | Check-in Interval |
|-----------|------------------|
| drill-sergeant | Every 1 hour |
| execution | Every 2 hours |
| supportive | Every 4 hours |
| mentor | Every 4 hours |

## Database Setup

### 1. Run the Migration Script

First, add the necessary fields to the `user_preferences` table:

```bash
# In your Supabase SQL Editor
# Run the script: add_checkin_field.sql
```

This will add:
- `next_checkin_at` - Timestamp for when the next check-in should be sent
- `last_checkin_at` - Timestamp for when the last check-in was sent
- An index for efficient querying of users due for check-in
- A helper function `get_checkin_interval()` for calculating intervals

### 2. Verify the Setup

```sql
-- Check if columns were added
SELECT column_name, data_type 
FROM information_schema.columns
WHERE table_name = 'user_preferences' 
  AND column_name IN ('next_checkin_at', 'last_checkin_at');

-- View check-in schedule for all users
SELECT user_id, boss_type, next_checkin_at, last_checkin_at
FROM user_preferences
ORDER BY next_checkin_at;
```

## API Endpoint

### POST /trigger-checkin

This endpoint queries all users due for a check-in and sends them a message.

**Response Example:**
```json
{
  "success": true,
  "message": "Check-ins triggered for 5 user(s)",
  "checkins_triggered": 5,
  "current_time": "2026-01-12T10:00:00",
  "results": [
    {
      "user_id": "123e4567-e89b-12d3-a456-426614174000",
      "phone_no": "1234567890",
      "boss_type": "drill-sergeant",
      "next_checkin_at": "2026-01-12T11:00:00",
      "interval_hours": 1
    }
  ]
}
```

## Cron Job Setup

To automate check-ins, you need to set up a cron job that calls the `/trigger-checkin` endpoint regularly.

### Option 1: Server Cron Job (Linux/Mac)

```bash
# Edit crontab
crontab -e

# Add this line to run every hour at minute 0
0 * * * * curl -X POST https://your-server.com/trigger-checkin

# Or run every 30 minutes for more frequent checks
*/30 * * * * curl -X POST https://your-server.com/trigger-checkin
```

**Recommended Schedule:** Run every 30 minutes to 1 hour. The endpoint is smart enough to only send check-ins to users who are actually due.

### Option 2: GitHub Actions (Free Cloud Cron)

Create `.github/workflows/checkin-cron.yml`:

```yaml
name: Trigger Check-ins

on:
  schedule:
    # Run every hour at minute 0
    - cron: '0 * * * *'
  # Allow manual trigger
  workflow_dispatch:

jobs:
  trigger-checkin:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger Check-in Endpoint
        run: |
          curl -X POST https://your-server.com/trigger-checkin
```

### Option 3: Cloud Service (e.g., EasyCron, Cron-job.org)

1. Go to [cron-job.org](https://cron-job.org) or [EasyCron](https://www.easycron.com)
2. Create a free account
3. Add a new cron job:
   - **URL:** `https://your-server.com/trigger-checkin`
   - **Method:** POST
   - **Schedule:** Every hour (or every 30 minutes)
   - **Timezone:** Your server's timezone

### Option 4: Supabase Edge Functions (Recommended for Supabase Users)

Create a Supabase Edge Function that runs on a schedule:

```typescript
// supabase/functions/trigger-checkin/index.ts
import { serve } from 'https://deno.land/std@0.168.0/http/server.ts'

serve(async (req) => {
  try {
    const response = await fetch('https://your-server.com/trigger-checkin', {
      method: 'POST',
    })
    
    const data = await response.json()
    
    return new Response(
      JSON.stringify(data),
      { headers: { 'Content-Type': 'application/json' } }
    )
  } catch (error) {
    return new Response(
      JSON.stringify({ error: error.message }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    )
  }
})
```

Then use Supabase's scheduled functions (cron) feature to trigger it.

## Testing

### Manual Test

```bash
# Test the endpoint manually
curl -X POST http://localhost:8000/trigger-checkin

# Or with authentication if you have it enabled
curl -X POST http://localhost:8000/trigger-checkin \
  -H "X-API-Key: your_api_key"
```

### Check Logs

Monitor your application logs to see check-ins being triggered:

```bash
# If running locally
tail -f logs/app.log

# Or check your cloud provider's logs
```

### Verify Check-ins

```sql
-- Check when users are scheduled for next check-in
SELECT 
  user_id,
  boss_type,
  last_checkin_at,
  next_checkin_at,
  EXTRACT(EPOCH FROM (next_checkin_at - NOW())) / 3600 as hours_until_next
FROM user_preferences
ORDER BY next_checkin_at;
```

## Check-in Messages

The bot generates **AI-powered, context-aware messages** based on:
- User's active goals and their intensity
- Recent tasks (last 7 days) and completion status
- Pending, completed, and missed tasks
- Boss type personality style

**Example AI-Generated Messages:**

**Drill Sergeant:**
> "I see you missed 'Create budget proposal' yesterday. That's not acceptable. Where are we at with the product roadmap? Report in. 💪"

**Execution:**
> "Quick check. You completed 'Research venue options' yesterday - good. But 'Survey team preferences' is still pending. What's the status? 📊"

**Supportive:**
> "Hey! Saw you finished 'Set up development environment' - nice work! 🌟 How's 'Design mockups' coming along?"

**Mentor:**
> "You've been working on 'Improve team communication' - what insights have you gained so far? 🧠 How are you approaching it?"

### Fallback Messages

When AI generation fails or no user context is available, the system uses personality-appropriate fallback messages:

**Drill Sergeant:**
- "Time to report in. What have you accomplished since we last talked? 💪"
- "Check-in time. Give me your status update. Now. ⚡"

**Execution:**
- "Quick check-in. What did you complete today? ✅"
- "Time for a status update. Where are we at? 📊"

**Supportive:**
- "Hey! Just checking in. How are things going? 😊"
- "Time for a friendly check-in. What have you been working on? 🌟"

**Mentor:**
- "Let's reflect on your progress. What did you learn today? 🧠"
- "Check-in time. What challenges did you face and how did you handle them? 💭"

## Troubleshooting

### Check-ins Not Sending

1. **Verify cron job is running:**
   ```bash
   # Check cron logs (Linux)
   grep CRON /var/log/syslog
   ```

2. **Check user data:**
   ```sql
   SELECT user_id, phone_no, next_checkin_at 
   FROM user_preferences 
   WHERE next_checkin_at <= NOW();
   ```

3. **Verify Twilio credentials:**
   - Check `.env` has correct `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`

4. **Check application logs:**
   - Look for errors in check-in processing

### Users Not Receiving Messages

1. **Verify phone numbers:**
   ```sql
   SELECT user_id, phone_no FROM user_preferences;
   ```
   - Phone numbers should be in format: `1234567890` (no + or spaces)

2. **Check WhatsApp connection:**
   - Ensure users have messaged the bot at least once
   - Twilio requires users to opt-in by sending a message first

3. **Test individual user:**
   ```sql
   -- Force immediate check-in for a specific user
   UPDATE user_preferences 
   SET next_checkin_at = NOW() - INTERVAL '1 hour'
   WHERE user_id = 'your-user-id';
   
   -- Then trigger check-in
   ```

### Adjusting Check-in Frequency

To change check-in intervals for all users of a specific boss type:

```sql
-- Update next check-in for all drill-sergeants to 30 minutes from now
UPDATE user_preferences
SET next_checkin_at = NOW() + INTERVAL '30 minutes'
WHERE boss_type = 'drill-sergeant';
```

To manually adjust a single user's next check-in:

```sql
-- Set next check-in to 2 hours from now
UPDATE user_preferences
SET next_checkin_at = NOW() + INTERVAL '2 hours'
WHERE user_id = 'user-id-here';
```

## Monitoring

### View Check-in Statistics

```sql
-- Count users by boss type and their next check-in
SELECT 
  boss_type,
  COUNT(*) as user_count,
  MIN(next_checkin_at) as earliest_checkin,
  MAX(next_checkin_at) as latest_checkin
FROM user_preferences
GROUP BY boss_type;

-- Users due for check-in right now
SELECT 
  COUNT(*) as users_due_now
FROM user_preferences
WHERE next_checkin_at <= NOW();

-- Check-in history (recent)
SELECT 
  user_id,
  boss_type,
  last_checkin_at,
  next_checkin_at
FROM user_preferences
WHERE last_checkin_at IS NOT NULL
ORDER BY last_checkin_at DESC
LIMIT 10;
```

### Logging

The application logs every check-in with:
- User ID
- Boss type
- Next check-in time
- Interval hours

Look for log entries like:
```
Check-in triggered for user abc123 (boss_type: drill-sergeant). Next check-in: 2026-01-12T11:00:00
```

## Best Practices

1. **Run cron more frequently than the shortest interval**
   - Shortest interval: 1 hour (drill-sergeant)
   - Recommended cron: Every 30 minutes
   - This ensures check-ins are sent on time

2. **Monitor for failures**
   - Set up alerts if check-ins fail
   - Log all check-in attempts

3. **Respect quiet hours (optional enhancement)**
   - Consider adding logic to skip check-ins during night hours
   - Example: Skip if current hour is between 10 PM and 7 AM

4. **Rate limiting**
   - The current implementation processes all due users
   - For very large user bases, consider batching

## Optional Enhancements

### Add Quiet Hours

```python
# In the trigger_checkin endpoint, add:
current_hour = current_time.hour
if 22 <= current_hour or current_hour < 7:
    # Skip check-ins during quiet hours (10 PM - 7 AM)
    return {
        "success": True,
        "message": "Quiet hours - check-ins skipped",
        "checkins_triggered": 0
    }
```

### Add User Timezone Support

Update `user_preferences` table:

```sql
ALTER TABLE user_preferences 
ADD COLUMN timezone TEXT DEFAULT 'UTC';
```

Then adjust check-in logic to respect user timezones.

## Security

### Option: Add API Key Authentication

To secure the `/trigger-checkin` endpoint:

```python
# In app.py, add to the endpoint:
from fastapi import Header

@app.post("/trigger-checkin")
async def trigger_checkin(
    background_tasks: BackgroundTasks,
    x_api_key: str = Header(None)
):
    if x_api_key != MY_API_SECRET:
        raise HTTPException(status_code=403, detail="Invalid API key")
    # ... rest of the code
```

Then update your cron job:

```bash
curl -X POST https://your-server.com/trigger-checkin \
  -H "X-API-Key: your_secret_key"
```

---

## Summary

1. Run `add_checkin_field.sql` in Supabase
2. Deploy your updated `app.py`
3. Set up a cron job to call `/trigger-checkin` every 30-60 minutes
4. Monitor logs and check-in statistics
5. Users will receive check-ins based on their boss type automatically

The system is now fully automated and will maintain accountability without manual intervention! 🎯
