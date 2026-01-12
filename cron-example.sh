#!/bin/bash
# Example cron script to trigger check-ins
# 
# Setup instructions:
# 1. Make this script executable: chmod +x cron-example.sh
# 2. Add to crontab: crontab -e
# 3. Add this line to run every hour:
#    0 * * * * /path/to/bsy-chatbot-demo/cron-example.sh >> /var/log/checkin-cron.log 2>&1
#
# Or run every 30 minutes:
#    */30 * * * * /path/to/bsy-chatbot-demo/cron-example.sh >> /var/log/checkin-cron.log 2>&1

# Configuration
SERVER_URL="http://localhost:8000"  # Change to your server URL
API_KEY=""  # Optional: Add your API key if authentication is enabled

# Timestamp
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Triggering check-ins..."

# Trigger check-in endpoint
if [ -z "$API_KEY" ]; then
    # Without API key
    RESPONSE=$(curl -s -X POST "${SERVER_URL}/trigger-checkin" \
        -H "Content-Type: application/json" \
        -w "\nHTTP_CODE:%{http_code}")
else
    # With API key
    RESPONSE=$(curl -s -X POST "${SERVER_URL}/trigger-checkin" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${API_KEY}" \
        -w "\nHTTP_CODE:%{http_code}")
fi

# Parse HTTP status code
HTTP_CODE=$(echo "$RESPONSE" | grep "HTTP_CODE:" | cut -d':' -f2)
BODY=$(echo "$RESPONSE" | sed '/HTTP_CODE:/d')

# Log response
if [ "$HTTP_CODE" = "200" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Success: $BODY"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Error (HTTP $HTTP_CODE): $BODY"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Check-in trigger complete"
echo "----------------------------------------"
