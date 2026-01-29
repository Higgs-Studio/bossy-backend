# Recurring Tasks Enhancement

## Summary

Enhanced the `create_recurring_tasks` function to support flexible recurrence patterns beyond just consecutive daily tasks.

## New Features

### 1. **Daily Tasks (Original Behavior)**
- Creates tasks for every consecutive day in the period
- **Usage**: `recurrence_type="daily"` (default)
- **Example**: "I need to do meditation everyday until next week"

### 2. **Interval-Based Tasks**
- Creates tasks every N days
- **Usage**: `recurrence_type="interval"`, `recurrence_interval=N`
- **Examples**:
  - Every 3 days: `recurrence_interval=3`
  - Every week: `recurrence_interval=7`
- **User Query**: "I need to take vitamins every 3 days until end of month"

### 3. **Biweekly Tasks (NEW)**
- Creates tasks every 2 weeks (14 days)
- **Usage**: `recurrence_type="biweekly"`
- **User Queries**:
  - "I need to do laundry biweekly until summer"
  - "Review project status every 2 weeks until June"

### 4. **Weekly Tasks (Specific Weekdays)**
- Creates tasks only on specified days of the week
- **Usage**: `recurrence_type="weekly"`, `weekdays=[list of day numbers]`
- **Weekday Numbers**: 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 4=Friday, 5=Saturday, 6=Sunday
- **Examples**:
  - Every Saturday: `weekdays=[5]`
  - Every Monday and Friday: `weekdays=[0, 4]`
  - Every Tuesday and Thursday: `weekdays=[1, 3]`
- **User Queries**:
  - "I need to go to the gym every Saturday until end of February"
  - "I need to attend team meeting every Monday and Wednesday until project ends"

### 5. **Monthly Tasks (NEW)**
- Creates tasks on a specific day of each month
- **Usage**: `recurrence_type="monthly"`, `day_of_month=N`
- **Day of Month**: 1-31 (if not specified, uses start_date's day)
- **Smart Handling**: If day doesn't exist in a month (e.g., 31st in February), that month is skipped
- **Examples**:
  - 15th of every month: `day_of_month=15`
  - Last day of month: `day_of_month=31` (skips months with fewer days)
- **User Queries**:
  - "Pay rent on the 1st of every month until end of lease"
  - "Review budget monthly on the 15th until year end"

### 6. **Yearly Tasks (NEW)**
- Creates tasks on the same date every year
- **Usage**: `recurrence_type="yearly"`
- **Uses start_date** as the recurring date each year
- **Leap Year Handling**: Gracefully handles Feb 29th
- **User Queries**:
  - "Renew insurance every year until 2030"
  - "Annual checkup every January 15th for next 5 years"

## Function Signature

```python
@tool
def create_recurring_tasks(
    user_id: str, 
    task_text: str, 
    start_date: str, 
    end_date: str, 
    goal_name: str = None, 
    intensity: str = "medium",
    recurrence_type: str = "daily",      # Enhanced
    recurrence_interval: int = 1,        # For "interval" type
    weekdays: list = None,               # For "weekly" type
    day_of_month: int = None             # NEW - For "monthly" type
) -> str:
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `user_id` | str | - | The user ID (UUID) |
| `task_text` | str | - | The task description to repeat |
| `start_date` | str | - | Start date in YYYY-MM-DD format |
| `end_date` | str | - | End date in YYYY-MM-DD format (inclusive) |
| `goal_name` | str | None | Optional goal name (auto-generated if not provided) |
| `intensity` | str | "medium" | Goal intensity: "low", "medium", or "high" |
| `recurrence_type` | str | "daily" | "daily", "interval", "biweekly", "weekly", "monthly", or "yearly" |
| `recurrence_interval` | int | 1 | For "interval" type, repeat every N days |
| `weekdays` | list | None | For "weekly" type, list of weekday numbers (0-6) |
| `day_of_month` | int | None | For "monthly" type, day of month (1-31). Uses start_date's day if not provided |

## Auto-Generated Goal Names

The function now generates appropriate goal names based on the recurrence pattern:

- **Daily**: "Daily: [task_text]"
- **Interval**: "Every [N] days: [task_text]"
- **Biweekly**: "Biweekly: [task_text]"
- **Weekly (single day)**: "Every [Weekday]: [task_text]"
- **Weekly (multiple days)**: "Every [Day1, Day2]: [task_text]"
- **Monthly**: "Monthly (15th): [task_text]" (uses ordinal: 1st, 2nd, 3rd, etc.)
- **Yearly**: "Yearly: [task_text]"

## Usage Examples in Chatbot

### Example 1: Every 2 Days
**User**: "I need to water my plants every 2 days until end of March"

**Bot calls**:
```python
create_recurring_tasks(
    user_id="user-uuid",
    task_text="water my plants",
    start_date="2026-01-26",
    end_date="2026-03-31",
    recurrence_type="interval",
    recurrence_interval=2
)
```

### Example 2: Biweekly
**User**: "Do laundry biweekly until end of summer"

**Bot calls**:
```python
create_recurring_tasks(
    user_id="user-uuid",
    task_text="do laundry",
    start_date="2026-01-26",
    end_date="2026-08-31",
    recurrence_type="biweekly"
)
```

### Example 3: Every Saturday
**User**: "Remind me to clean the house every Saturday until end of February"

**Bot calls**:
```python
create_recurring_tasks(
    user_id="user-uuid",
    task_text="clean the house",
    start_date="2026-01-26",
    end_date="2026-02-28",
    recurrence_type="weekly",
    weekdays=[5]  # Saturday
)
```

### Example 4: Every Monday and Thursday
**User**: "I need to go to gym every Monday and Thursday until end of next month"

**Bot calls**:
```python
create_recurring_tasks(
    user_id="user-uuid",
    task_text="go to gym",
    start_date="2026-01-26",
    end_date="2026-02-28",
    recurrence_type="weekly",
    weekdays=[0, 3]  # Monday and Thursday
)
```

### Example 5: Monthly on the 15th
**User**: "Pay rent on the 15th every month until end of lease in December 2026"

**Bot calls**:
```python
create_recurring_tasks(
    user_id="user-uuid",
    task_text="pay rent",
    start_date="2026-01-26",
    end_date="2026-12-31",
    recurrence_type="monthly",
    day_of_month=15
)
```

### Example 6: Monthly (using start date's day)
**User**: "Review budget every month until year end"

**Bot calls**:
```python
create_recurring_tasks(
    user_id="user-uuid",
    task_text="review budget",
    start_date="2026-01-26",  # Will use 26th of each month
    end_date="2026-12-31",
    recurrence_type="monthly"
    # day_of_month not specified, so uses start_date's day (26th)
)
```

### Example 7: Yearly
**User**: "Renew car insurance every year until 2030"

**Bot calls**:
```python
create_recurring_tasks(
    user_id="user-uuid",
    task_text="renew car insurance",
    start_date="2026-01-26",  # Will repeat on Jan 26th each year
    end_date="2030-12-31",
    recurrence_type="yearly"
)
```

## Validation

The function includes validation for:
- Valid `recurrence_type` (must be "daily", "interval", "biweekly", "weekly", "monthly", or "yearly")
- `weekdays` is required when using "weekly" type
- `weekdays` values must be integers between 0-6 (Monday to Sunday)
- `recurrence_interval` must be at least 1
- `day_of_month` must be between 1-31 for "monthly" type (uses start_date's day if not provided)

## Special Handling

### Monthly Recurrence
- If the specified day doesn't exist in a month (e.g., February 30th), that month is automatically skipped
- Example: If `day_of_month=31`, tasks will only be created for months with 31 days

### Yearly Recurrence
- Gracefully handles leap year edge cases (e.g., February 29th)
- Uses the exact date from `start_date` as the recurring date each year

## Response Format

The function returns a JSON response with:
- `success`: Boolean indicating success/failure
- `message`: Descriptive message about what was created
- `goal`: The created goal object
- `tasks_created`: Number of tasks created
- `recurrence_pattern`: Human-readable description of the pattern (e.g., "biweekly (every 14 days)", "monthly on the 15th", "yearly on January 26th")
- `sample_tasks`: First 3 tasks as examples

### Example Response
```json
{
  "success": true,
  "message": "Created goal 'Monthly (15th): pay rent' with 12 tasks (monthly on the 15th) from 2026-01-26 to 2026-12-31",
  "goal": { /* goal object */ },
  "tasks_created": 12,
  "recurrence_pattern": "monthly on the 15th",
  "sample_tasks": [ /* first 3 task objects */ ]
}
```

## Backward Compatibility

The enhancement is fully backward compatible. Existing code calling `create_recurring_tasks` without the new parameters will continue to work as before (creating daily tasks).

---

## New Feature: Reschedule Task Occurrence

### Overview

A new function `reschedule_task_occurrence` has been added to handle conflicts in recurring tasks. This allows users to move a specific occurrence of a recurring task to a different date without affecting other occurrences in the series.

### Function Signature

```python
@tool
def reschedule_task_occurrence(
    user_id: str,
    task_description: str,
    original_date: str,
    new_date: str
) -> str:
```

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_id` | str | The user ID (UUID) |
| `task_description` | str | Description or keywords to identify the task |
| `original_date` | str | The original date of the task to reschedule (YYYY-MM-DD) |
| `new_date` | str | The new date to move the task to (YYYY-MM-DD) |

### Use Cases

This function is perfect for handling:
- **Conflicts**: When a recurring task conflicts with another commitment
- **Scheduling changes**: When you need to move one instance without changing the pattern
- **Exceptions**: When you want to keep the recurring series but adjust one occurrence

### Features

1. **Smart Matching**: Uses fuzzy text matching to find the right task
2. **Conflict Detection**: Warns if the same task already exists on the new date
3. **Clarification**: Asks for clarification when multiple matches are found
4. **Preservation**: All other task occurrences remain unchanged
5. **User-Friendly Messages**: Provides helpful feedback with weekday names

### Usage Examples

#### Example 1: Moving a Weekly Gym Session
**User**: "Move my gym session from Monday to Tuesday this week"

**Bot calls**:
```python
reschedule_task_occurrence(
    user_id="user-uuid",
    task_description="gym",
    original_date="2026-01-27",  # Monday
    new_date="2026-01-28"        # Tuesday
)
```

**Response**:
```json
{
  "success": true,
  "message": "Rescheduled 'go to gym' from Monday, January 27 to Tuesday, January 28",
  "task": { /* updated task object */ },
  "goal": "Every Monday: go to gym",
  "original_date": "2026-01-27",
  "new_date": "2026-01-28",
  "note": "Other occurrences of this recurring task remain unchanged."
}
```

#### Example 2: Rescheduling a Monthly Meeting
**User**: "Reschedule the team meeting on Feb 5 to Feb 6"

**Bot calls**:
```python
reschedule_task_occurrence(
    user_id="user-uuid",
    task_description="team meeting",
    original_date="2026-02-05",
    new_date="2026-02-06"
)
```

#### Example 3: Moving a Biweekly Task
**User**: "I can't do laundry on the 26th, move it to the 27th"

**Bot calls**:
```python
reschedule_task_occurrence(
    user_id="user-uuid",
    task_description="laundry",
    original_date="2026-01-26",
    new_date="2026-01-27"
)
```

### Error Handling

The function provides helpful error messages for common scenarios:

#### No Task Found on Original Date
```json
{
  "success": false,
  "error": "No tasks found on 2026-01-27",
  "suggestion": "Please check the date. You can say 'what are my tasks on 2026-01-27' to see what's scheduled."
}
```

#### Task Already Exists on New Date
```json
{
  "success": false,
  "error": "A task with the same description already exists on 2026-01-28",
  "suggestion": "Did you mean to mark the original task on 2026-01-27 as done instead?"
}
```

#### Multiple Matches Found
```json
{
  "success": false,
  "requires_clarification": true,
  "message": "I found multiple tasks on 2026-01-27. Which one do you want to reschedule?",
  "options": [
    {
      "number": 1,
      "task_id": "task-id-1",
      "task_text": "gym session",
      "goal": "Every Monday: gym"
    },
    {
      "number": 2,
      "task_id": "task-id-2",
      "task_text": "gym class",
      "goal": "Weekly fitness"
    }
  ]
}
```

### Chatbot Integration

The function is integrated into the system prompt with usage examples:

**User Queries That Trigger This Function**:
- "Move my gym session from Monday to Tuesday"
- "Reschedule the meeting on Jan 15 to Jan 16"
- "Change my appointment from Feb 3 to Feb 10"
- "I can't do laundry on the 5th, move it to the 6th"

### Important Notes

1. **Single Instance Only**: This function only changes one occurrence, not the entire recurring series
2. **Active Goals Only**: Only searches tasks in active goals
3. **Date Format**: Always use YYYY-MM-DD format for dates
4. **Fuzzy Matching**: Uses similarity matching to find tasks, so exact wording isn't required
5. **Conflict Prevention**: Prevents creating duplicate tasks on the same date

---

## Complete Enhancement Summary

### What's New?

This enhancement provides a comprehensive recurring task management system with:

#### 1. **Six Recurrence Patterns**
| Pattern | Frequency | Use Case |
|---------|-----------|----------|
| Daily | Every day | Daily habits (meditation, journaling) |
| Interval | Every N days | Regular intervals (vitamins every 3 days) |
| **Biweekly** ✨ | Every 14 days | Bi-weekly activities (laundry, reviews) |
| Weekly | Specific weekdays | Weekly schedules (gym Mon/Wed/Fri) |
| **Monthly** ✨ | Specific day each month | Monthly obligations (rent, bills) |
| **Yearly** ✨ | Same date annually | Annual events (insurance, renewals) |

#### 2. **Flexible Rescheduling** ✨
- Move individual task occurrences without affecting the series
- Handle conflicts and scheduling changes gracefully
- Smart conflict detection and prevention

### Key Benefits

✅ **Comprehensive Coverage**: Supports all common recurrence patterns  
✅ **Flexible Management**: Reschedule individual occurrences as needed  
✅ **Smart Matching**: Fuzzy text matching finds tasks without exact wording  
✅ **User-Friendly**: Clear messages with weekday names and helpful suggestions  
✅ **Backward Compatible**: Existing code continues to work unchanged  
✅ **Robust Validation**: Comprehensive error handling and edge case management  
✅ **Conflict Prevention**: Detects and prevents duplicate tasks  

### Real-World Scenarios Supported

1. **"I need to go to the gym every Monday until summer"** ✅
2. **"Pay rent on the 1st of every month"** ✅
3. **"Review project status biweekly"** ✅
4. **"Renew insurance every year"** ✅
5. **"Move Monday's gym session to Tuesday this week"** ✅
6. **"Take vitamins every 3 days"** ✅
7. **"Team meeting every Monday and Wednesday"** ✅

### Implementation Highlights

- **196 lines** of recurring task creation logic with all patterns
- **142 lines** of reschedule logic with smart matching
- Automatic goal naming based on recurrence pattern
- Helper function for ordinal numbers (1st, 2nd, 3rd, etc.)
- Comprehensive system prompt guidance for the AI
- Full integration with existing task management system

This enhancement transforms the chatbot from supporting only consecutive daily tasks to a full-featured recurring task management system that handles virtually any scheduling pattern users might need! 🎉

## Summary of Recurrence Types

| Type | Description | Key Parameters | Example |
|------|-------------|----------------|---------|
| **daily** | Every consecutive day | None | "Do meditation daily" |
| **interval** | Every N days | `recurrence_interval` | "Take vitamins every 3 days" |
| **biweekly** | Every 14 days | None | "Laundry biweekly" |
| **weekly** | Specific weekdays | `weekdays` | "Gym every Monday & Friday" |
| **monthly** | Specific day of month | `day_of_month` (optional) | "Pay rent on the 15th" |
| **yearly** | Same date each year | None | "Renew insurance annually" |

