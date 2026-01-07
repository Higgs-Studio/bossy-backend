# LangGraph Task Management Enhancement

## Overview

The chatbot has been enhanced with LangGraph and Ollama LLM (llama3.2:3b) to provide intelligent task management capabilities. Users can now interact with the bot to break down goals into actionable tasks and manage them in Supabase.

## Features

### 1. **Intelligent Goal Breakdown**
- Users can describe a high-level goal
- The AI agent automatically breaks it down into 3-5 actionable tasks
- Tasks are stored in Supabase with proper metadata

### 2. **Task Management Tools**
Three specialized tools are available to the agent:

#### `break_goal_into_tasks`
- Breaks down a goal into multiple tasks using AI
- Automatically creates tasks in Supabase
- Returns structured task information

#### `create_task_in_supabase`
- Creates a single task directly
- Supports title, description, priority, and user_id

#### `get_user_tasks`
- Retrieves tasks for a specific user
- Can filter by status (pending, in_progress, completed, all)

### 3. **LangGraph Agent Architecture**
- Uses StateGraph for conversation flow
- Tool-calling capabilities with Ollama
- Maintains conversation context
- Automatic routing between agent and tools

## Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Install Ollama

Download and install Ollama from: https://ollama.ai

### 3. Pull the Llama3.2 Model

```bash
ollama pull llama3.2:3b
```

### 4. Verify Ollama is Running

```bash
ollama list
```

## Environment Variables

Add to your `.env` file:

```env
# Existing variables
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=your_twilio_number

# Supabase
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key

# API Security
MY_API_SECRET=your_secret_key
```

## Supabase Table Schema

The `tasks` table should have the following structure:

```sql
CREATE TABLE tasks (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    priority TEXT DEFAULT 'medium',
    status TEXT DEFAULT 'pending',
    estimated_hours NUMERIC,
    goal TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Add index for faster queries
CREATE INDEX idx_tasks_user_id ON tasks(user_id);
CREATE INDEX idx_tasks_status ON tasks(status);
```

## Usage Examples

### Example 1: Breaking Down a Goal

**User:** "I want to launch a new marketing campaign"

**Agent Response:**
- Analyzes the goal
- Creates 3-5 specific tasks like:
  - Research target audience
  - Create content calendar
  - Design promotional materials
  - Set up tracking metrics
  - Launch campaign
- Stores all tasks in Supabase
- Confirms creation with summary

### Example 2: Creating a Single Task

**User:** "Create a task to review the monthly budget"

**Agent Response:**
- Uses `create_task_in_supabase` tool
- Creates single task with appropriate details
- Confirms creation

### Example 3: Viewing Tasks

**User:** "Show me my pending tasks"

**Agent Response:**
- Uses `get_user_tasks` tool with status filter
- Returns formatted list of tasks
- Provides count and details

## API Endpoints

### GET `/tasks/{user_id}`
Retrieve all tasks for a specific user.

**Example:**
```bash
curl http://localhost:8000/tasks/1234567890
```

**Response:**
```json
{
  "success": true,
  "user_id": "1234567890",
  "count": 5,
  "data": [
    {
      "id": 1,
      "user_id": "1234567890",
      "title": "Research target audience",
      "description": "Identify demographics and preferences",
      "priority": "high",
      "status": "pending",
      "estimated_hours": 3,
      "goal": "Launch marketing campaign",
      "created_at": "2026-01-03T10:30:00Z"
    }
  ]
}
```

## Architecture

```
User Message (WhatsApp)
    ↓
Twilio Webhook
    ↓
process_message(message, user_id)
    ↓
LangGraph Agent
    ├── Agent Node (LLM Decision Making)
    │   ├── Analyze user intent
    │   └── Decide which tool to use
    ↓
    ├── Tool Node (Execute Tools)
    │   ├── break_goal_into_tasks
    │   ├── create_task_in_supabase
    │   └── get_user_tasks
    ↓
    └── Response Generation
        ↓
    Supabase Database
```

## Key Components

### 1. **AgentState**
```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    user_id: str
```

### 2. **Agent Graph**
- Entry point: agent node
- Conditional routing based on tool calls
- Tool execution and response generation
- Loop back to agent for final response

### 3. **LLM Configuration**
- Model: `llama3.2:3b`
- Temperature: 0.7 (balanced creativity/consistency)
- Tool binding for function calling

## Troubleshooting

### Issue: "Connection refused" when calling Ollama

**Solution:** Make sure Ollama is running:
```bash
ollama serve
```

### Issue: SSL Certificate Errors with Supabase

**Solution:** Already handled - SSL verification is disabled for Supabase requests:
```python
supabase.postgrest.session = httpx.Client(verify=False)
```

### Issue: Tasks not appearing in database

**Solution:** 
1. Check Supabase credentials in `.env`
2. Verify table exists with correct schema
3. Check application logs for errors

## Testing

### Test the Agent Locally

```python
from app import process_message

# Test goal breakdown
response = process_message(
    "I want to build a mobile app", 
    user_id="test_user"
)
print(response)

# Test task retrieval
response = process_message(
    "Show me my tasks", 
    user_id="test_user"
)
print(response)
```

### Test via API

```bash
# Start the server
uvicorn app:app --reload

# Send a test message (requires Twilio setup)
curl -X POST http://localhost:8000/webhook \
  -d "Body=I want to organize a team event" \
  -d "From=whatsapp:+1234567890"
```

## Performance Considerations

1. **LLM Response Time**: Ollama responses typically take 2-5 seconds
2. **Tool Execution**: Supabase queries are fast (<100ms)
3. **Total Response Time**: Expect 3-7 seconds for complex requests

## Future Enhancements

- [ ] Add task update/delete tools
- [ ] Implement task prioritization suggestions
- [ ] Add deadline tracking and reminders
- [ ] Support for task dependencies
- [ ] Multi-language support
- [ ] Voice message processing
- [ ] Task analytics and reporting

## Security Notes

- User IDs are extracted from WhatsApp phone numbers
- SSL verification is disabled for Supabase (corporate network requirement)
- API endpoints can be protected with API key authentication
- Consider implementing rate limiting for production use

## License

This is a demo application for internal use.

