# Task and Goal Status Update Feature

**Date Implemented:** January 19, 2026  
**Feature:** Task status tracking and goal status management with enhanced check-ins  
**Status:** ✅ Complete and ready for deployment

---

## Overview

This update adds comprehensive status tracking for tasks and goals, allowing users to update their progress through natural language interactions with the chatbot. The check-in system has also been enhanced to better categorize expired and incomplete work.

---

## What Was Implemented

### 1. Database Schema Changes

**File:** `add_task_status_field.sql`

Added to `daily_tasks` table:
- `status` field (TEXT) with CHECK constraint for values: 'todo', 'in_progress', 'done'
- Default value: 'todo'
- Indexes:
  - `idx_daily_tasks_status` - for efficient status queries
  - `idx_daily_tasks_goal_status` - composite index for goal_id + status queries
- Migration logic to set status based on existing check-ins

### 2. New Tool Functions

**File:** `app.py`

#### `find_task_by_description(user_id, task_description, task_date)`
- Finds tasks by searching for similar text in task descriptions
- Uses fuzzy matching to identify the correct task when users refer to tasks by description
- Returns top 5 matching tasks sorted by similarity
- Helps the AI identify which task to update when users say things like "I finished the research task"

#### `update_task_status(task_id, user_id, status)`
- Updates the status of a task to: 'todo', 'in_progress', or 'done'
- Validates task ownership through goal verification
- When status is set to 'done', also creates/updates check-in record for backward compatibility
- Returns updated task information including goal context

#### `update_goal_status(goal_id, user_id, status)`
- Updates the status of a goal to: 'active', 'completed', or 'abandoned'
- Validates goal ownership
- Returns updated goal information with task completion statistics
- Shows progress: "X/Y tasks completed"

### 3. Enhanced Check-in Logic

**Function:** `generate_checkin_message_with_context()`

The check-in message generation now separates tasks and goals into more granular categories:

**Goals:**
- Active goals (current)
- Expired goals (end_date < today but still marked active)

**Tasks:**
- Recently Completed (status == "done")
- Planned for Today (status == "pending", date == today, not expired)
- Expired/Incomplete Tasks (date < today, status != "done") ← **NEW**
- Upcoming Tasks (status == "pending", date > today)
- Missed Tasks (status == "missed")

This allows check-in messages to specifically call out:
> "Expired/Incomplete Tasks:
> - Research venue options (from 2026-01-17)
> - Survey team preferences (from 2026-01-16)"

### 4. Updated get_user_tasks Function

Modified to:
- Read status directly from `daily_tasks` table instead of only from `check_ins`
- Default to "todo" if status is not set
- Still include check-in information for backward compatibility
- Return comprehensive task status information

### 5. System Prompt Enhancement

Added new section "Task and Goal Status Management" that teaches the AI:
- When to use the new status update tools
- How to interpret user intent (e.g., "I finished..." → update to "done")
- Examples of natural language patterns to recognize
- Proper workflow: find task → update status

---

## Status Values

### Task Statuses
| Status | Meaning | When to Use |
|--------|---------|-------------|
| `todo` | Planned but not started | Default state, or when user hasn't started |
| `in_progress` | Currently being worked on | User says they're working on it |
| `done` | Completed | User confirms completion |

### Goal Statuses
| Status | Meaning | When to Use |
|--------|---------|-------------|
| `active` | Currently being pursued | Default state for new goals |
| `completed` | Successfully achieved | User completed all objectives |
| `abandoned` | No longer pursuing | User gives up or goal becomes irrelevant |

---

## How Users Interact With This Feature

### Natural Language Examples

**Updating Task Status:**
```
User: "I finished the research task"
AI: Finds task → Updates to "done" → Confirms

User: "I'm working on the design mockups now"
AI: Finds task → Updates to "in_progress" → Acknowledges

User: "I haven't started the budget review yet"
AI: Finds task → Updates to "todo" → Notes it
```

**Updating Goal Status:**
```
User: "I completed my fitness goal"
AI: Finds goal → Updates to "completed" → Celebrates

User: "I want to abandon my side project goal"
AI: Finds goal → Updates to "abandoned" → Confirms

User: "Let's reactivate my learning goal"
AI: Finds goal → Updates to "active" → Acknowledges
```

### Check-in Experience

**Before:**
```
"Quick check. You completed 'Research venue options' yesterday - good. 
But 'Survey team preferences' is still pending. What's the status? 📊"
```

**After (with expired task separation):**
```
"Status check. Good work on 'Research venue options' ✅

Expired/Incomplete:
- Survey team preferences (from 2026-01-16)
- Draft proposal (from 2026-01-15)

Today's Plan:
- Finalize venue booking

What's blocking the expired items? 📊"
```

---

## Benefits

1. **Better Progress Tracking**
   - Users can mark tasks as in-progress to show they're actively working
   - More granular status beyond just "done" or "missed"

2. **Expired Task Visibility**
   - Check-ins now explicitly call out tasks that are overdue
   - Helps users identify bottlenecks and reschedule work

3. **Goal Lifecycle Management**
   - Users can properly complete or abandon goals
   - Prevents clutter from old/irrelevant goals

4. **Natural Interaction**
   - Users can update status using natural language
   - No need to remember task IDs or use complex commands

5. **Backward Compatibility**
   - Still maintains check-in records for reporting
   - Existing functionality continues to work

---

## Database Migration Required

**IMPORTANT:** Before deploying, run the SQL migration:

```bash
# In Supabase SQL Editor, run:
add_task_status_field.sql
```

This will:
1. Add the `status` field to `daily_tasks` table
2. Create necessary indexes
3. Migrate existing tasks based on their check-in status

---

## Testing Checklist

- [ ] Run database migration script
- [ ] Test task status updates via chatbot
  - [ ] "I finished [task]" → status = "done"
  - [ ] "I'm working on [task]" → status = "in_progress"
- [ ] Test goal status updates via chatbot
  - [ ] "I completed [goal]" → status = "completed"
  - [ ] "I want to abandon [goal]" → status = "abandoned"
- [ ] Verify check-ins show expired tasks separately
- [ ] Confirm task search by description works
- [ ] Test `get_user_tasks` API endpoint returns status
- [ ] Verify backward compatibility with check_ins table

---

## API Changes

### New Tools Available to Agent
- `find_task_by_description(user_id, task_description, task_date=None)`
- `update_task_status(task_id, user_id, status)`
- `update_goal_status(goal_id, user_id, status)`

### Updated API Responses

**GET /tasks/{user_id}**
Now includes `status` field in task objects:
```json
{
  "id": "uuid",
  "task_text": "Research venue options",
  "task_date": "2026-01-19",
  "status": "in_progress",
  "goal_id": "uuid",
  ...
}
```

---

## Files Modified

1. **`add_task_status_field.sql`** (NEW)
   - Database migration script

2. **`app.py`**
   - Added `find_task_by_description` tool
   - Added `update_task_status` tool
   - Added `update_goal_status` tool
   - Updated `get_user_tasks` to read status from daily_tasks
   - Enhanced `generate_checkin_message_with_context` to separate expired tasks
   - Bound new tools to LangGraph agent
   - Enhanced system prompt with status management instructions

3. **`STATUS_UPDATE_FEATURE.md`** (NEW)
   - This documentation file

---

## Future Enhancements

Potential improvements for future iterations:

1. **Bulk Status Updates**
   - "Mark all yesterday's tasks as done"
   - "Move all pending tasks to tomorrow"

2. **Status Change History**
   - Track when status changes occurred
   - Show timeline of task progress

3. **Automatic Status Inference**
   - Auto-mark tasks as "missed" if not done by end date
   - Auto-suggest abandoning goals with no recent progress

4. **Status Analytics**
   - Completion rates by goal
   - Average time in "in_progress" state
   - Most frequently abandoned goal types

---

## Support

For issues or questions:
1. Check the implementation in `app.py`
2. Review the migration script in `add_task_status_field.sql`
3. Verify database schema matches expected structure
4. Check logs for any tool execution errors

---

**Implementation Complete!** ✅

The chatbot now supports comprehensive task and goal status tracking with enhanced check-in visibility for expired work.
