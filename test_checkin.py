#!/usr/bin/env python3
"""
Test script for the check-in feature.

This script helps you test the check-in functionality by:
1. Manually triggering check-ins
2. Setting up test users with different boss types
3. Viewing current check-in schedule
"""

import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client, Client
import httpx
import argparse

# Load environment variables
load_dotenv()

# Configuration
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8000")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Initialize Supabase client
http_client = httpx.Client(verify=False)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
supabase.postgrest.session = http_client


def trigger_checkin():
    """Manually trigger check-ins for all due users"""
    print(f"\n🔔 Triggering check-ins at {datetime.now().isoformat()}")
    print("=" * 60)
    
    try:
        response = requests.post(f"{SERVER_URL}/trigger-checkin")
        response.raise_for_status()
        data = response.json()
        
        print(f"✅ Success!")
        print(f"   Message: {data.get('message')}")
        print(f"   Check-ins triggered: {data.get('checkins_triggered')}")
        print(f"   Current time: {data.get('current_time')}")
        
        if data.get('results'):
            print("\n📊 Check-in Details:")
            for result in data['results']:
                print(f"   - User: {result['user_id']}")
                print(f"     Boss Type: {result['boss_type']}")
                print(f"     Next Check-in: {result['next_checkin_at']}")
                print(f"     Interval: {result['interval_hours']} hours")
                print()
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Error: {e}")


def view_schedule():
    """View the current check-in schedule for all users"""
    print("\n📅 Check-in Schedule")
    print("=" * 80)
    
    try:
        result = supabase.table("user_preferences").select(
            "user_id, phone_no, boss_type, next_checkin_at, last_checkin_at"
        ).order("next_checkin_at").execute()
        
        if not result.data:
            print("No users found in database.")
            return
        
        now = datetime.now()
        
        for user in result.data:
            user_id = user['user_id'][:8] + "..."  # Truncate for display
            phone = user.get('phone_no', 'N/A')
            boss_type = user.get('boss_type', 'N/A')
            next_checkin = user.get('next_checkin_at')
            last_checkin = user.get('last_checkin_at')
            
            # Calculate time until next check-in
            if next_checkin:
                next_dt = datetime.fromisoformat(next_checkin.replace('Z', '+00:00'))
                time_until = next_dt - now.replace(tzinfo=next_dt.tzinfo)
                hours_until = time_until.total_seconds() / 3600
                
                status = "🔴 DUE NOW" if hours_until <= 0 else f"🟢 in {hours_until:.1f}h"
            else:
                status = "⚪ Not scheduled"
            
            print(f"\nUser: {user_id} | Phone: {phone}")
            print(f"  Boss Type: {boss_type}")
            print(f"  Status: {status}")
            print(f"  Next Check-in: {next_checkin or 'N/A'}")
            print(f"  Last Check-in: {last_checkin or 'Never'}")
        
        print(f"\n{'=' * 80}")
        print(f"Total users: {len(result.data)}")
        
        # Count users due now
        due_now = sum(1 for u in result.data 
                     if u.get('next_checkin_at') 
                     and datetime.fromisoformat(u['next_checkin_at'].replace('Z', '+00:00')) <= now.replace(tzinfo=datetime.fromisoformat(u['next_checkin_at'].replace('Z', '+00:00')).tzinfo))
        print(f"Users due for check-in now: {due_now}")
        
    except Exception as e:
        print(f"❌ Error: {e}")


def force_checkin(user_id: str):
    """Force immediate check-in for a specific user"""
    print(f"\n⚡ Forcing immediate check-in for user: {user_id}")
    print("=" * 60)
    
    try:
        # Set next_checkin_at to past time
        past_time = (datetime.now() - timedelta(hours=1)).isoformat()
        
        supabase.table("user_preferences").update({
            "next_checkin_at": past_time
        }).eq("user_id", user_id).execute()
        
        print(f"✅ User {user_id} set to check-in immediately")
        print(f"   Now trigger check-in with: python test_checkin.py --trigger")
        
    except Exception as e:
        print(f"❌ Error: {e}")


def set_boss_type(user_id: str, boss_type: str):
    """Update boss type for a user"""
    valid_types = ["drill-sergeant", "execution", "supportive", "mentor"]
    
    if boss_type not in valid_types:
        print(f"❌ Invalid boss type. Must be one of: {', '.join(valid_types)}")
        return
    
    print(f"\n🔧 Updating boss type for user: {user_id}")
    print("=" * 60)
    
    try:
        # Get current interval
        intervals = {
            "drill-sergeant": 1,
            "execution": 2,
            "supportive": 4,
            "mentor": 4
        }
        interval_hours = intervals[boss_type]
        
        # Update boss type and reset next check-in
        next_checkin = (datetime.now() + timedelta(hours=interval_hours)).isoformat()
        
        supabase.table("user_preferences").update({
            "boss_type": boss_type,
            "next_checkin_at": next_checkin
        }).eq("user_id", user_id).execute()
        
        print(f"✅ Boss type updated to: {boss_type}")
        print(f"   Check-in interval: {interval_hours} hours")
        print(f"   Next check-in: {next_checkin}")
        
    except Exception as e:
        print(f"❌ Error: {e}")


def stats():
    """Show check-in statistics"""
    print("\n📊 Check-in Statistics")
    print("=" * 60)
    
    try:
        result = supabase.table("user_preferences").select(
            "boss_type, next_checkin_at, last_checkin_at"
        ).execute()
        
        if not result.data:
            print("No users found.")
            return
        
        # Count by boss type
        boss_counts = {}
        for user in result.data:
            boss_type = user.get('boss_type', 'unknown')
            boss_counts[boss_type] = boss_counts.get(boss_type, 0) + 1
        
        print("\nUsers by Boss Type:")
        for boss_type, count in sorted(boss_counts.items()):
            print(f"  {boss_type}: {count} users")
        
        # Check-in activity
        total_users = len(result.data)
        users_with_checkins = sum(1 for u in result.data if u.get('last_checkin_at'))
        
        print(f"\nCheck-in Activity:")
        print(f"  Total users: {total_users}")
        print(f"  Users who received check-ins: {users_with_checkins}")
        print(f"  Users never checked in: {total_users - users_with_checkins}")
        
    except Exception as e:
        print(f"❌ Error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Test the check-in feature")
    parser.add_argument("--trigger", action="store_true", 
                       help="Trigger check-ins for all due users")
    parser.add_argument("--schedule", action="store_true",
                       help="View check-in schedule")
    parser.add_argument("--force", metavar="USER_ID",
                       help="Force immediate check-in for a user")
    parser.add_argument("--set-boss-type", nargs=2, metavar=("USER_ID", "BOSS_TYPE"),
                       help="Set boss type for a user (drill-sergeant, execution, supportive, mentor)")
    parser.add_argument("--stats", action="store_true",
                       help="Show check-in statistics")
    
    args = parser.parse_args()
    
    if args.trigger:
        trigger_checkin()
    elif args.schedule:
        view_schedule()
    elif args.force:
        force_checkin(args.force)
    elif args.set_boss_type:
        set_boss_type(args.set_boss_type[0], args.set_boss_type[1])
    elif args.stats:
        stats()
    else:
        # Default: show schedule
        print("🤖 Check-in Feature Test Script")
        print("\nAvailable commands:")
        print("  --trigger              Trigger check-ins now")
        print("  --schedule             View check-in schedule")
        print("  --force USER_ID        Force check-in for a user")
        print("  --set-boss-type USER_ID TYPE  Set boss type")
        print("  --stats                Show statistics")
        print("\nShowing current schedule...\n")
        view_schedule()


if __name__ == "__main__":
    main()
