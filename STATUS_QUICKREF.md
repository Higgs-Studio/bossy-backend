# Quick Reference: Task & Goal Status Updates

## 📋 Task Status Commands

Users can update task status by simply telling the chatbot:

### Mark Task as Done
```
✅ "I finished the research task"
✅ "The design mockups are complete"
✅ "Done with the budget review"
✅ "Completed the presentation"
```

### Mark Task as In Progress
```
🔄 "I'm working on the prototype"
🔄 "Started the code review"
🔄 "Currently doing the market analysis"
```

### Mark Task as Todo (reset)
```
📝 "Haven't started the planning yet"
📝 "Need to do the documentation"
```

---

## 🎯 Goal Status Commands

Users can update goal status by telling the chatbot:

### Mark Goal as Completed
```
🎉 "I completed my fitness goal"
🎉 "Finished my learning goal"
🎉 "Achieved my side project goal"
```

### Mark Goal as Abandoned
```
❌ "I want to abandon my workout goal"
❌ "Giving up on the diet goal"
❌ "Not pursuing the certification anymore"
```

### Reactivate Goal
```
🔄 "Let's reactivate my learning goal"
🔄 "I want to continue my side project"
```

---

## 🔍 How It Works

1. **User mentions a task/goal** in natural language
2. **AI finds the task/goal** using `find_task_by_description()`
3. **AI updates the status** using `update_task_status()` or `update_goal_status()`
4. **AI confirms the update** with task/goal details

---

## 📊 Status Values

### Task Statuses
- `todo` - Not started
- `in_progress` - Currently working on it
- `done` - Completed

### Goal Statuses
- `active` - Currently pursuing
- `completed` - Achieved
- `abandoned` - No longer pursuing

---

## 💡 Check-in Improvements

Check-ins now separate tasks into:

1. **Recently Completed** - Tasks marked as done
2. **Planned for Today** - Tasks scheduled for today
3. **Expired/Incomplete** ⚠️ - Past-due tasks not completed
4. **Upcoming Tasks** - Future scheduled tasks
5. **Missed Tasks** - Explicitly marked as missed

**Example Check-in:**
```
Status check ✅

Recently Completed:
- Research venue options (2026-01-18)

Planned for Today:
- Finalize venue booking

Expired/Incomplete:
- Survey team preferences (from 2026-01-16)
- Draft proposal (from 2026-01-15)

What's blocking the expired items? 📊
```

---

## 🛠️ For Developers

### Tool Functions Added
```python
# Find task by description
find_task_by_description(user_id, task_description, task_date=None)

# Update task status
update_task_status(task_id, user_id, status)  # status: "todo"|"in_progress"|"done"

# Update goal status
update_goal_status(goal_id, user_id, status)  # status: "active"|"completed"|"abandoned"
```

### Database Changes
```sql
-- Added to daily_tasks table
ALTER TABLE daily_tasks ADD COLUMN status TEXT DEFAULT 'todo';
```

---

## 📝 Migration Steps

1. Run SQL migration:
   ```bash
   # In Supabase SQL Editor
   run: add_task_status_field.sql
   ```

2. Restart the application:
   ```bash
   # If using uvicorn
   uvicorn app:app --reload
   ```

3. Test with sample commands:
   - "Show me my tasks"
   - "I finished the first task"
   - "I'm working on the second task"

---

## 🎯 Key Benefits

✅ Natural language status updates  
✅ Better visibility of expired/overdue work  
✅ Proper goal lifecycle management  
✅ More accurate progress tracking  
✅ Backward compatible with existing check-ins  

---

**Ready to Use!** 🚀

Users can now update task and goal statuses simply by talking to the chatbot.
