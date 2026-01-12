# Check-in Feature - Quick Reference

## TL;DR

1. Run database migration: `add_checkin_field.sql` in Supabase
2. Deploy updated `app.py`
3. Set up cron job to call `/trigger-checkin` every 30-60 minutes
4. Done! Users get automatic check-ins based on their boss type

## Check-in Frequencies

| Boss Type | Interval |
|-----------|----------|
| drill-sergeant | 1 hour |
| execution | 2 hours |
| supportive | 4 hours |
| mentor | 4 hours |

## Quick Setup

### 1. Database Setup (30 seconds)

```sql
-- In Supabase SQL Editor, run:
-- File: add_checkin_field.sql
```

### 2. Test Locally (1 minute)

```bash
# Start your server
uvicorn app:app --reload

# In another terminal, test the endpoint
curl -X POST http://localhost:8000/trigger-checkin

# Or use the test script
python test_checkin.py --trigger
```

### 3. Set Up Cron Job (2 minutes)

**Option A: Linux/Mac Cron**
```bash
crontab -e
# Add this line:
0 * * * * curl -X POST https://your-server.com/trigger-checkin
```

**Option B: Use the provided script**
```bash
chmod +x cron-example.sh
# Edit cron-example.sh with your server URL
crontab -e
# Add this line:
*/30 * * * * /path/to/bsy-chatbot-demo/cron-example.sh >> /var/log/checkin.log 2>&1
```

**Option C: Cloud Cron Service**
- Go to [cron-job.org](https://cron-job.org)
- Add new job: POST `https://your-server.com/trigger-checkin`
- Schedule: Every hour

## Testing Commands

```bash
# View check-in schedule
python test_checkin.py --schedule

# Trigger check-ins manually
python test_checkin.py --trigger

# Force check-in for a specific user
python test_checkin.py --force USER_ID

# Change boss type (and update interval)
python test_checkin.py --set-boss-type USER_ID drill-sergeant

# View statistics
python test_checkin.py --stats
```

## SQL Quick Reference

```sql
-- View all users and their next check-in
SELECT user_id, boss_type, next_checkin_at, last_checkin_at
FROM user_preferences
ORDER BY next_checkin_at;

-- See who's due for check-in right now
SELECT user_id, boss_type, next_checkin_at
FROM user_preferences
WHERE next_checkin_at <= NOW();

-- Force immediate check-in for a user
UPDATE user_preferences
SET next_checkin_at = NOW() - INTERVAL '1 hour'
WHERE user_id = 'your-user-id';

-- Change boss type for a user
UPDATE user_preferences
SET boss_type = 'drill-sergeant',
    next_checkin_at = NOW() + INTERVAL '1 hour'
WHERE user_id = 'your-user-id';

-- Pause check-ins for a user (set far future date)
UPDATE user_preferences
SET next_checkin_at = NOW() + INTERVAL '100 years'
WHERE user_id = 'your-user-id';

-- Resume check-ins for a user
UPDATE user_preferences
SET next_checkin_at = NOW()
WHERE user_id = 'your-user-id';
```

## API Response Format

```json
{
  "success": true,
  "message": "Check-ins triggered for 3 user(s)",
  "checkins_triggered": 3,
  "current_time": "2026-01-12T10:00:00",
  "results": [
    {
      "user_id": "uuid-here",
      "phone_no": "1234567890",
      "boss_type": "drill-sergeant",
      "next_checkin_at": "2026-01-12T11:00:00",
      "interval_hours": 1
    }
  ]
}
```

## Example Check-in Messages

### AI-Generated (Contextual)

**Drill Sergeant:**
> "I see you missed 'Create budget proposal' yesterday. That's not acceptable. Where are we at with the product roadmap? Report in. 💪"

**Execution:**
> "Quick check. You completed 'Research venue options' yesterday - good. But 'Survey team preferences' is still pending. What's the status? 📊"

**Supportive:**
> "Hey! Saw you finished 'Set up development environment' - nice work! 🌟 How's 'Design mockups' coming along?"

**Mentor:**
> "You've been working on 'Improve team communication' - what insights have you gained so far? 🧠"

### Fallback (Default - when no context available)

**Drill Sergeant:**
> "Time to report in. What have you accomplished since we last talked? 💪"

**Execution:**
> "Quick check-in. What did you complete today? ✅"

**Supportive:**
> "Hey! Just checking in. How are things going? 😊"

**Mentor:**
> "Let's reflect on your progress. What did you learn today? 🧠"

## Troubleshooting

**Problem:** No check-ins being sent
```bash
# 1. Check if cron is running
ps aux | grep cron

# 2. Check users due for check-in
python test_checkin.py --schedule

# 3. Manually trigger
python test_checkin.py --trigger

# 4. Check logs
tail -f logs/app.log  # or your log location
```

**Problem:** User not receiving messages
```sql
-- 1. Verify user data
SELECT * FROM user_preferences WHERE user_id = 'user-id';

-- 2. Check next_checkin_at is in the past
SELECT user_id, next_checkin_at, NOW()
FROM user_preferences
WHERE user_id = 'user-id';

-- 3. Force immediate check-in
UPDATE user_preferences
SET next_checkin_at = NOW() - INTERVAL '1 hour'
WHERE user_id = 'user-id';
```

**Problem:** Wrong check-in frequency
```sql
-- Update boss type and reset schedule
UPDATE user_preferences
SET boss_type = 'execution',  -- or drill-sergeant, supportive, mentor
    next_checkin_at = NOW() + INTERVAL '2 hours'  -- adjust based on type
WHERE user_id = 'user-id';
```

## Files Created

- `add_checkin_field.sql` - Database migration
- `CHECKIN_SETUP.md` - Detailed setup guide
- `CHECKIN_QUICKREF.md` - This quick reference
- `test_checkin.py` - Testing and management script
- `cron-example.sh` - Example cron script
- Updated `app.py` - Added check-in endpoint and helpers
- Updated `README.md` - Added check-in feature info

## Architecture

```
Cron Job (every 30-60 min)
    ↓
POST /trigger-checkin
    ↓
Query users where next_checkin_at <= NOW()
    ↓
For each user:
  - Generate boss-type specific message
  - Send WhatsApp message (background task)
  - Calculate next check-in time
  - Update user_preferences table
    ↓
Return results
```

## Next Steps

1. **Test locally first**: Run `python test_checkin.py --trigger`
2. **Monitor for a day**: Watch logs to ensure check-ins work
3. **Set up production cron**: Use one of the cron options
4. **Optional**: Add API key authentication to `/trigger-checkin`
5. **Optional**: Add quiet hours (skip 10 PM - 7 AM)
6. **Optional**: Add user timezone support

## Support

- **Full Guide**: `CHECKIN_SETUP.md`
- **Test Script**: `python test_checkin.py --help`
- **Issues**: Check application logs

---

**Quick Start Time**: ~5 minutes  
**Boss Types Supported**: 4  
**Zero Manual Intervention**: After setup, fully automated! ✨
