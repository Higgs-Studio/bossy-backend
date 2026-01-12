# Migration Guide: Adding Check-in Feature to Existing Deployment

If you already have the chatbot running in production, follow this guide to add the check-in feature.

## Pre-Migration Checklist

- [ ] Backup your Supabase database
- [ ] Note your current app version
- [ ] Verify you have admin access to Supabase
- [ ] Verify you can deploy to your production server
- [ ] Have access to set up cron jobs

## Migration Steps

### Step 1: Database Migration (2 minutes)

1. **Backup your database** (important!)
   ```sql
   -- In Supabase SQL Editor
   -- This is just for safety, RLS policies will remain intact
   ```

2. **Run the migration script**
   - Open Supabase SQL Editor
   - Copy and paste contents of `add_checkin_field.sql`
   - Click "Run"
   - Verify success (should see "Success. No rows returned")

3. **Verify the migration**
   ```sql
   -- Check new columns exist
   SELECT column_name, data_type 
   FROM information_schema.columns
   WHERE table_name = 'user_preferences' 
     AND column_name IN ('next_checkin_at', 'last_checkin_at');
   
   -- Should return 2 rows
   ```

4. **Initialize existing users**
   ```sql
   -- Set initial check-in times for existing users
   UPDATE user_preferences
   SET next_checkin_at = NOW() + get_checkin_interval(boss_type)
   WHERE next_checkin_at IS NULL;
   
   -- Verify
   SELECT user_id, boss_type, next_checkin_at 
   FROM user_preferences 
   LIMIT 5;
   ```

### Step 2: Update Application Code (1 minute)

1. **Pull the latest code**
   ```bash
   git pull origin main
   # Or copy the updated app.py file
   ```

2. **Verify changes**
   ```bash
   # Check for new functions
   grep -n "get_checkin_interval_hours" app.py
   grep -n "generate_checkin_message" app.py
   grep -n "trigger-checkin" app.py
   ```

3. **No new dependencies needed!**
   - All required packages already in requirements.txt
   - No need to reinstall dependencies

### Step 3: Test Locally (3 minutes)

1. **Start the server locally**
   ```bash
   # If using virtual environment
   source venv/bin/activate  # or venv\Scripts\activate on Windows
   
   uvicorn app:app --reload
   ```

2. **Test the new endpoint**
   ```bash
   # In another terminal
   curl -X POST http://localhost:8000/trigger-checkin
   
   # Should see JSON response with success: true
   ```

3. **Test with test script**
   ```bash
   # View schedule
   python test_checkin.py --schedule
   
   # Should show all users and their next check-in times
   ```

### Step 4: Deploy to Production (5 minutes)

1. **Deploy updated code**
   ```bash
   # Example for common deployment methods:
   
   # If using systemd service
   sudo systemctl restart your-app-service
   
   # If using Docker
   docker-compose down
   docker-compose up -d --build
   
   # If using PM2
   pm2 restart app
   
   # If using manual process
   # Stop the current process and start again
   pkill -f "uvicorn app:app"
   nohup uvicorn app:app --host 0.0.0.0 --port 8000 &
   ```

2. **Verify deployment**
   ```bash
   # Test the endpoint on production
   curl -X POST https://your-production-server.com/trigger-checkin
   
   # Should return JSON with success: true
   ```

### Step 5: Set Up Cron Job (2 minutes)

1. **Choose your cron method** (see CHECKIN_SETUP.md for all options)

2. **Option A: Server Cron (Recommended)**
   ```bash
   # SSH to your server
   ssh user@your-server.com
   
   # Edit crontab
   crontab -e
   
   # Add this line (runs every hour)
   0 * * * * curl -X POST https://your-server.com/trigger-checkin
   
   # Or every 30 minutes
   */30 * * * * curl -X POST https://your-server.com/trigger-checkin
   
   # Save and exit
   ```

3. **Option B: Use the provided script**
   ```bash
   # Copy cron-example.sh to your server
   scp cron-example.sh user@your-server:/path/to/app/
   
   # SSH to server
   ssh user@your-server.com
   
   # Make executable
   chmod +x /path/to/app/cron-example.sh
   
   # Edit with your server URL
   nano /path/to/app/cron-example.sh
   
   # Add to crontab
   crontab -e
   # Add:
   */30 * * * * /path/to/app/cron-example.sh >> /var/log/checkin.log 2>&1
   ```

4. **Verify cron is running**
   ```bash
   # Check cron service
   sudo systemctl status cron  # or crond on some systems
   
   # Test the script manually
   /path/to/app/cron-example.sh
   
   # Check logs
   tail -f /var/log/checkin.log
   ```

### Step 6: Monitor Initial Check-ins (10 minutes)

1. **Watch the logs**
   ```bash
   # On your server
   tail -f /var/log/your-app.log  # adjust path as needed
   
   # Or if using systemd
   journalctl -u your-app-service -f
   ```

2. **Force a test check-in**
   ```bash
   # Set a test user to check-in immediately
   python test_checkin.py --force YOUR_TEST_USER_ID
   
   # Trigger check-in
   curl -X POST https://your-server.com/trigger-checkin
   
   # Check if message was received
   ```

3. **Verify database updates**
   ```sql
   -- In Supabase SQL Editor
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

## Post-Migration Verification

### Checklist

- [ ] Database migration completed successfully
- [ ] New columns visible in user_preferences table
- [ ] Application restarted with new code
- [ ] `/trigger-checkin` endpoint responding (200 OK)
- [ ] Cron job set up and running
- [ ] Test check-in message received
- [ ] Logs show successful check-in processing
- [ ] `last_checkin_at` updating in database
- [ ] `next_checkin_at` being calculated correctly

### Success Criteria

✅ **Database:**
```sql
-- Should return data
SELECT * FROM user_preferences 
WHERE next_checkin_at IS NOT NULL 
LIMIT 1;
```

✅ **API:**
```bash
# Should return 200 with JSON
curl -i -X POST https://your-server.com/trigger-checkin
```

✅ **Cron:**
```bash
# Should show your cron job
crontab -l | grep trigger-checkin
```

✅ **Messages:**
- At least one test user received a check-in message

## Rollback Plan

If something goes wrong, here's how to rollback:

### 1. Stop Check-ins Immediately

```bash
# Remove cron job
crontab -e
# Comment out or delete the trigger-checkin line

# Or pause all check-ins in database
UPDATE user_preferences
SET next_checkin_at = NOW() + INTERVAL '100 years';
```

### 2. Rollback Application Code

```bash
# Restore previous version
git checkout previous-commit-hash

# Restart service
sudo systemctl restart your-app-service
```

### 3. Rollback Database (if needed)

```sql
-- Remove new columns (optional - they won't cause issues if left)
ALTER TABLE user_preferences 
DROP COLUMN IF EXISTS next_checkin_at,
DROP COLUMN IF EXISTS last_checkin_at;

-- Remove index
DROP INDEX IF EXISTS idx_user_preferences_next_checkin;

-- Remove function
DROP FUNCTION IF EXISTS get_checkin_interval(TEXT);
```

**Note:** The new columns are optional and won't break existing functionality if left in place.

## Common Migration Issues

### Issue: Migration script fails

**Error:** "column already exists"

**Solution:** The migration has already been run. Check if columns exist:
```sql
SELECT * FROM user_preferences LIMIT 1;
```

### Issue: Application won't start after update

**Error:** Import errors or syntax errors

**Solution:**
1. Check Python version: `python --version` (need 3.9+)
2. Verify no syntax errors: `python -m py_compile app.py`
3. Check logs for specific error

### Issue: Cron job not triggering

**Solution:**
1. Verify cron service: `sudo systemctl status cron`
2. Check cron logs: `grep CRON /var/log/syslog`
3. Test URL manually: `curl -X POST https://your-server.com/trigger-checkin`
4. Verify server is accessible from cron host

### Issue: Check-ins sending but users not receiving

**Solution:**
1. Check Twilio logs in Twilio dashboard
2. Verify phone numbers are correct format (no + or spaces)
3. Check users have opted in (sent at least one message to bot)
4. Verify Twilio credentials in environment variables

## Timeline

**Total Migration Time:** ~15-20 minutes

- Database migration: 2 minutes
- Code update: 1 minute  
- Local testing: 3 minutes
- Production deployment: 5 minutes
- Cron setup: 2 minutes
- Monitoring: 10 minutes

## Need Help?

1. **Check logs:**
   - Application logs for errors
   - Cron logs for execution
   - Supabase logs for database issues

2. **Use test script:**
   ```bash
   python test_checkin.py --schedule  # View all check-in times
   python test_checkin.py --stats     # View statistics
   ```

3. **Review documentation:**
   - `CHECKIN_SETUP.md` - Full setup guide
   - `CHECKIN_QUICKREF.md` - Quick commands
   - `CHECKIN_IMPLEMENTATION.md` - Technical details

4. **Test with one user first:**
   ```bash
   # Force check-in for one user
   python test_checkin.py --force USER_ID
   
   # Trigger
   curl -X POST https://your-server.com/trigger-checkin
   ```

## Post-Migration

After successful migration:

1. **Monitor for 24 hours**
   - Watch logs for errors
   - Verify check-ins are being sent
   - Check user feedback

2. **Adjust if needed**
   - Modify cron frequency if needed
   - Adjust boss types for specific users
   - Fine-tune quiet hours (future enhancement)

3. **Document your setup**
   - Note your cron schedule
   - Document any customizations
   - Share with team

---

**Migration Status:** ✅ Safe and tested

**Risk Level:** Low (backwards compatible, can be disabled anytime)

**Downtime Required:** None (can be done with zero downtime)

**Rollback Time:** <5 minutes if needed

---

*Last updated: January 12, 2026*
