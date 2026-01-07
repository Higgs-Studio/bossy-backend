# Quick Start Guide - LangGraph Task Management Bot

## Prerequisites

1. **Python 3.9+** installed
2. **Ollama** installed and running
3. **Supabase** account with a database set up

## Step-by-Step Setup

### 1. Install Ollama

**Windows:**
```bash
# Download from https://ollama.ai/download
# Run the installer
```

**Verify installation:**
```bash
ollama --version
```

### 2. Pull the Llama3.2 Model

```bash
ollama pull llama3.2:3b
```

This will download the ~2GB model. Wait for it to complete.

### 3. Start Ollama Server

```bash
ollama serve
```

Keep this terminal open. Ollama needs to be running for the bot to work.

### 4. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 5. Set Up Supabase Database

Go to your Supabase project and run this SQL:

```sql
-- Create tasks table
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

-- Add indexes for performance
CREATE INDEX idx_tasks_user_id ON tasks(user_id);
CREATE INDEX idx_tasks_status ON tasks(status);
```

### 6. Configure Environment Variables

Create or update `.env` file:

```env
# Twilio (for WhatsApp)
TWILIO_ACCOUNT_SID=your_account_sid_here
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_NUMBER=your_twilio_number_here

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_key_here

# API Security
MY_API_SECRET=your_secret_key_here
```

### 7. Test the Agent Locally

```bash
python test_agent.py
```

Try these commands:
- "I want to launch a new product"
- "Show me my tasks"
- "Create a task to review the budget"

### 8. Run Automated Tests

```bash
python test_agent.py --test
```

### 9. Start the FastAPI Server

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

The server will be available at: http://localhost:8000

### 10. Test the API Endpoint

```bash
curl http://localhost:8000/tasks/test_user_123
```

## Verify Everything Works

### ✅ Checklist

- [ ] Ollama is running (`ollama list` shows llama3.2:3b)
- [ ] Python dependencies installed
- [ ] Supabase table created
- [ ] Environment variables set
- [ ] Test script works (`python test_agent.py`)
- [ ] FastAPI server starts without errors
- [ ] API endpoint returns data

## Common Issues

### Issue 1: "Connection refused" to Ollama

**Solution:**
```bash
# Make sure Ollama is running
ollama serve
```

### Issue 2: Import errors

**Solution:**
```bash
# Reinstall dependencies
pip install -r requirements.txt --upgrade
```

### Issue 3: Supabase connection errors

**Solution:**
- Check your SUPABASE_URL and SUPABASE_KEY in `.env`
- Verify the table exists in Supabase
- Check if SSL verification is causing issues (already handled in code)

### Issue 4: Model not found

**Solution:**
```bash
# Pull the model again
ollama pull llama3.2:3b

# Verify it's available
ollama list
```

## Usage Examples

### Example 1: Goal Breakdown via WhatsApp

**User sends:** "I want to organize a company retreat"

**Bot responds:**
```
I've broken down your goal into 5 tasks:
1. Research venue options (High priority, 3 hours)
2. Create budget proposal (High priority, 2 hours)
3. Survey team preferences (Medium priority, 1 hour)
4. Book venue and accommodations (High priority, 2 hours)
5. Plan activities and agenda (Medium priority, 4 hours)

All tasks have been saved to your task list!
```

### Example 2: View Tasks

**User sends:** "What are my pending tasks?"

**Bot responds:**
```
You have 5 pending tasks:
1. Research venue options
2. Create budget proposal
3. Survey team preferences
4. Book venue and accommodations
5. Plan activities and agenda

Would you like more details on any of these?
```

### Example 3: API Usage

```bash
# Get all tasks for a user
curl http://localhost:8000/tasks/1234567890

# Response:
{
  "success": true,
  "user_id": "1234567890",
  "count": 5,
  "data": [...]
}
```

## Next Steps

1. **Connect to WhatsApp**: Configure Twilio webhook to point to your server
2. **Deploy**: Deploy to a cloud platform (Render, Railway, AWS, etc.)
3. **Customize**: Modify the system prompts in `app.py` to match your use case
4. **Add Features**: Implement task updates, deletions, and reminders

## Architecture Overview

```
WhatsApp Message
    ↓
Twilio Webhook → FastAPI (/webhook)
    ↓
process_message(message, user_id)
    ↓
LangGraph Agent (Ollama llama3.2:3b)
    ↓
Tools:
  - break_goal_into_tasks
  - create_task_in_supabase
  - get_user_tasks
    ↓
Supabase Database
    ↓
Response back to WhatsApp
```

## Performance Tips

1. **First Request**: The first request may be slow (5-10s) as Ollama loads the model
2. **Subsequent Requests**: Should be faster (2-5s)
3. **Keep Ollama Running**: Don't restart it frequently
4. **Use SSD**: Ollama performs better on SSD storage

## Support

For issues or questions:
1. Check the logs: `uvicorn app:app --log-level debug`
2. Review `LANGGRAPH_SETUP.md` for detailed documentation
3. Test with `test_agent.py` to isolate issues

## Resources

- [Ollama Documentation](https://ollama.ai/docs)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Supabase Documentation](https://supabase.com/docs)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)

---

**Ready to go!** 🚀

Start with: `python test_agent.py`

