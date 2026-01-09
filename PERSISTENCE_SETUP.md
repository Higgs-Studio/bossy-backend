# LangGraph Persistence Setup Guide

## Overview

This application now includes conversation persistence for LangGraph, allowing the chatbot to maintain conversation history across sessions. Each user's conversation is stored in Supabase using the **REST API** (not direct PostgreSQL connections), making it compatible with serverless deployments like Vercel.

## How It Works

1. **Thread-based Persistence**: Each user's conversation is stored using a unique `thread_id` (defaults to `user_id`)
2. **Automatic State Loading**: When a user sends a message, the previous conversation history is automatically loaded from the database
3. **Checkpoint System**: LangGraph uses a checkpoint system to save conversation state after each interaction
4. **REST API Based**: Uses Supabase REST API instead of direct PostgreSQL connections, making it compatible with Vercel and other serverless platforms

## Setup Instructions

### 1. Install Dependencies

The required packages are already in `requirements.txt`. Install them with:
```bash
pip install -r requirements.txt
```

**Note**: We use a custom `SupabaseRESTCheckpointer` that uses Supabase REST API, so no direct PostgreSQL connection libraries are needed.

### 2. Configure Supabase REST API

Add your Supabase REST API credentials to your `.env` file:

```bash
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your_supabase_anon_key_here
```

**How to get your credentials:**
1. Go to your Supabase project dashboard
2. Navigate to **Settings** → **API**
3. Copy the **Project URL** (this is your `SUPABASE_URL`)
4. Copy the **anon/public** key (this is your `SUPABASE_KEY`)

**Important**: These are the same credentials used for other Supabase operations in the app. No separate database connection string is needed!

### 3. Database Tables Setup

The checkpoint tables need to be created manually in Supabase. Run the SQL script:

```bash
# Run in Supabase SQL Editor
setup_checkpoint_tables.sql
```

The script creates two main tables:
- `checkpoints`: Stores conversation state checkpoints
- `checkpoint_blobs`: Stores binary data associated with checkpoints

**To run the script:**
1. Go to your Supabase project dashboard
2. Navigate to **SQL Editor**
3. Create a new query
4. Copy and paste the contents of `setup_checkpoint_tables.sql`
5. Run the query

### 4. Verify Setup

When you start the application, check the logs for:
```
LangGraph Supabase REST checkpointer initialized successfully
```

If you see a warning instead, check:
- `SUPABASE_URL` and `SUPABASE_KEY` are set correctly in `.env`
- The checkpoint tables exist in your Supabase database
- Your Supabase API key has the necessary permissions

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

1. **Check Environment Variables**: Ensure `SUPABASE_URL` and `SUPABASE_KEY` are set in `.env`
2. **Check Logs**: Look for initialization messages in application logs
3. **Verify Tables**: Ensure `checkpoints` and `checkpoint_blobs` tables exist in Supabase
4. **Test REST API**: Try querying the tables via Supabase dashboard to verify access

### Connection Errors

If you see connection errors:
- Verify `SUPABASE_URL` and `SUPABASE_KEY` are correct
- Check that your Supabase API key has proper permissions
- Ensure Row Level Security (RLS) policies allow access (see setup_checkpoint_tables.sql)
- Verify the tables exist and have the correct schema

### Vercel Deployment

This implementation is **fully compatible with Vercel** because:
- ✅ Uses Supabase REST API (no direct PostgreSQL connections)
- ✅ No connection pooling issues
- ✅ Works in serverless environments
- ✅ No persistent connections required

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
SupabaseRESTCheckpointer loads previous checkpoints via REST API
    ↓
Agent processes with full conversation history
    ↓
SupabaseRESTCheckpointer saves new checkpoint via REST API
    ↓
Response returned to user
```

**Key Difference**: Uses Supabase REST API instead of direct PostgreSQL connections, making it compatible with serverless platforms.

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
