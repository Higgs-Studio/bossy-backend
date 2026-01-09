# LangGraph Persistence Setup Guide

## Overview

This application now includes conversation persistence for LangGraph, allowing the chatbot to maintain conversation history across sessions. Each user's conversation is stored in a PostgreSQL database (Supabase) and automatically loaded when they send a new message.

## How It Works

1. **Thread-based Persistence**: Each user's conversation is stored using a unique `thread_id` (defaults to `user_id`)
2. **Automatic State Loading**: When a user sends a message, the previous conversation history is automatically loaded from the database
3. **Checkpoint System**: LangGraph uses a checkpoint system to save conversation state after each interaction

## Setup Instructions

### 1. Install Dependencies

The required packages have been added to `requirements.txt`:
- `langgraph-checkpoint-postgres==2.0.5`
- `psycopg2-binary==2.9.10`

Install them with:
```bash
pip install -r requirements.txt
```

### 2. Configure Supabase Database Connection

Add your Supabase PostgreSQL connection string to your `.env` file:

```bash
SUPABASE_DB_URI=postgresql://postgres:[YOUR-PASSWORD]@db.[YOUR-PROJECT-REF].supabase.co:5432/postgres
```

**How to get your connection string:**
1. Go to your Supabase project dashboard
2. Navigate to **Settings** → **Database**
3. Find the **Connection string** section
4. Copy the **URI** format connection string
5. Replace `[YOUR-PASSWORD]` with your database password
6. Replace `[YOUR-PROJECT-REF]` with your project reference ID

### 3. Database Tables Setup

The checkpoint tables are automatically created when the application starts via `PostgresSaver.setup()`. However, you can also manually create them using the SQL script:

```bash
# Run in Supabase SQL Editor
setup_checkpoint_tables.sql
```

The script creates two main tables:
- `checkpoints`: Stores conversation state checkpoints
- `checkpoint_blobs`: Stores binary data associated with checkpoints

### 4. Verify Setup

When you start the application, check the logs for:
```
LangGraph Postgres checkpointer initialized successfully
```

If you see a warning instead, check:
- `SUPABASE_DB_URI` is set correctly in `.env`
- Database credentials are valid
- Network connectivity to Supabase database

## Usage

### Automatic Persistence

Once configured, persistence works automatically:

1. **First Message**: User sends a message → Conversation starts fresh
2. **Subsequent Messages**: User sends another message → Previous conversation history is loaded automatically
3. **Context Retention**: The agent remembers the entire conversation history

### Thread ID Management

By default, each `user_id` gets its own conversation thread. The `process_message()` function uses `user_id` as the `thread_id`:

```python
# In app.py
def process_message(user_message: str, user_id: str = "default_user", thread_id: str = None):
    # Uses user_id as thread_id if not provided
    if thread_id is None:
        thread_id = user_id
```

### Custom Thread IDs

If you need multiple conversation threads per user (e.g., different topics), you can pass a custom `thread_id`:

```python
# Example: Different thread for different goals
thread_id = f"{user_id}-goal-{goal_id}"
process_message(message, user_id, thread_id=thread_id)
```

## Monitoring

### Check Conversation History

Query the checkpoints table in Supabase SQL Editor:

```sql
-- Get all conversations for a user
SELECT thread_id, checkpoint_id, checkpoint->'channel_values'->'messages' as messages
FROM checkpoints
WHERE thread_id = 'your-user-id'
ORDER BY checkpoint_id DESC;
```

### Count Conversations

```sql
-- Count checkpoints per user (thread)
SELECT thread_id, COUNT(*) as message_count
FROM checkpoints
GROUP BY thread_id
ORDER BY message_count DESC;
```

### Clean Up Old Conversations

```sql
-- Delete all checkpoints for a specific user
DELETE FROM checkpoints WHERE thread_id = 'old-user-id';

-- Delete all checkpoints older than 30 days (example)
DELETE FROM checkpoints 
WHERE checkpoint->>'created_at' < NOW() - INTERVAL '30 days';
```

## Troubleshooting

### Persistence Not Working

1. **Check Environment Variable**: Ensure `SUPABASE_DB_URI` is set in `.env`
2. **Check Logs**: Look for initialization messages in application logs
3. **Verify Database Connection**: Test the connection string manually
4. **Check Tables**: Verify `checkpoints` and `checkpoint_blobs` tables exist

### Connection Errors

If you see connection errors:
- Verify the connection string format
- Check that your Supabase database is accessible
- Ensure your IP is whitelisted (if using connection pooling restrictions)

### Memory Issues

If conversations become too long:
- Consider implementing conversation pruning
- Set a maximum conversation length
- Periodically archive old conversations

## Architecture

```
User Message
    ↓
process_message(user_message, user_id)
    ↓
agent_graph.invoke(initial_state, config={"configurable": {"thread_id": user_id}})
    ↓
PostgresSaver loads previous checkpoints for thread_id
    ↓
Agent processes with full conversation history
    ↓
PostgresSaver saves new checkpoint
    ↓
Response returned to user
```

## Benefits

1. **Context Awareness**: The agent remembers previous conversations
2. **Multi-turn Conversations**: Users can reference earlier messages
3. **Personalization**: Each user has their own conversation history
4. **Scalability**: PostgreSQL handles large volumes of conversations efficiently

## Security Considerations

1. **Row Level Security**: The checkpoint tables have RLS enabled (adjust policies as needed)
2. **Data Privacy**: Conversation data is stored in your Supabase database
3. **Access Control**: Ensure proper authentication/authorization for database access
4. **Data Retention**: Consider implementing data retention policies for compliance

## Next Steps

- Monitor conversation storage usage
- Implement conversation archiving if needed
- Consider adding conversation search capabilities
- Set up alerts for storage limits
