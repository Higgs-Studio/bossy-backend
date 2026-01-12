# WhatsApp Task Management Chatbot

An intelligent WhatsApp chatbot powered by **LangGraph** and **Ollama LLM (llama3.2:3b)** that helps users break down goals into actionable tasks and manage them efficiently.

## 🌟 Features

- 🤖 **AI-Powered Goal Breakdown**: Automatically converts high-level goals into 3-5 actionable tasks
- 📝 **Task Management**: Create, retrieve, and organize tasks via natural conversation
- 💬 **WhatsApp Integration**: Interact with the bot through WhatsApp using Twilio
- 🗄️ **Supabase Storage**: All tasks stored securely in Supabase database
- 🔧 **LangGraph Agent**: Intelligent routing and tool execution
- 🦙 **Local LLM**: Uses Ollama for privacy and control
- ⏰ **Automated Check-ins**: AI-powered contextual check-ins based on boss type (every 1-4 hours)

## 🚀 Quick Start

### Prerequisites

- Python 3.9+
- [Ollama](https://ollama.ai) installed
- Supabase account
- Twilio account (for WhatsApp)

### Installation

1. **Clone the repository**
   ```bash
   cd bsy-chatbot-demo
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Install and start Ollama**
   ```bash
   # Install from https://ollama.ai
   ollama pull llama3.2:3b
   ollama serve
   ```

4. **Set up Supabase database**
   - Go to [Supabase SQL Editor](https://app.supabase.com/project/_/sql/new)
   - Run the script in `setup_database.sql`

5. **Configure environment variables**
   ```bash
   cp env.template .env
   # Edit .env with your credentials
   ```

6. **Test the setup**
   ```bash
   python test_agent.py
   ```

7. **Start the server**
   ```bash
   uvicorn app:app --reload
   ```

## 📖 Documentation

- **[QUICKSTART.md](QUICKSTART.md)** - Step-by-step setup guide
- **[LANGGRAPH_SETUP.md](LANGGRAPH_SETUP.md)** - Detailed technical documentation
- **[IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)** - Complete implementation details
- **[CHECKIN_SETUP.md](CHECKIN_SETUP.md)** - Automated check-in feature setup

## 💡 Usage Examples

### Via WhatsApp

**User:** "I want to organize a team building event"

**Bot:** 
```
I've broken down your goal into 5 tasks:

1. Research venue options (High priority, 3 hours)
2. Create budget proposal (High priority, 2 hours)
3. Survey team preferences (Medium priority, 1 hour)
4. Book venue and accommodations (High priority, 2 hours)
5. Plan activities and agenda (Medium priority, 4 hours)

All tasks have been saved to your task list!
```

**User:** "Show me my pending tasks"

**Bot:**
```
You have 5 pending tasks:
1. Research venue options
2. Create budget proposal
3. Survey team preferences
4. Book venue and accommodations
5. Plan activities and agenda

Would you like more details on any of these?
```

### Via API

```bash
# Get all tasks for a user
curl http://localhost:8000/tasks/1234567890

# Response
{
  "success": true,
  "user_id": "1234567890",
  "count": 5,
  "data": [...]
}
```

### Via Test Script

```bash
# Interactive mode
python test_agent.py

# Automated tests
python test_agent.py --test
```

## 🏗️ Architecture

```
WhatsApp Message
    ↓
Twilio Webhook
    ↓
FastAPI (/webhook)
    ↓
process_message(message, user_id)
    ↓
LangGraph Agent (Ollama llama3.2:3b)
    ├── Agent Node: Decision making
    ├── Tool Node: Execute tools
    │   ├── break_goal_into_tasks
    │   ├── create_task_in_supabase
    │   └── get_user_tasks
    ↓
Supabase Database
    ↓
Response to WhatsApp
```

## 🛠️ Tech Stack

- **Backend**: FastAPI
- **LLM Framework**: LangGraph + LangChain
- **LLM**: Ollama (llama3.2:3b)
- **Database**: Supabase (PostgreSQL)
- **Messaging**: Twilio WhatsApp API
- **HTTP Client**: httpx

## 📊 Database Schema

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
```

## 🔧 Configuration

### Environment Variables

```env
# Twilio
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=your_twilio_number

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_key

# API Security
MY_API_SECRET=your_secret_key
```

See `env.template` for complete configuration options.

## 🧪 Testing

### Local Testing
```bash
# Interactive test
python test_agent.py

# Automated tests
python test_agent.py --test
```

### API Testing
```bash
# Health check
curl http://localhost:8000/

# Get user tasks
curl http://localhost:8000/tasks/test_user_123
```

## 🐛 Troubleshooting

### Ollama Connection Issues
```bash
# Make sure Ollama is running
ollama serve

# Verify model is installed
ollama list
```

### Database Connection Issues
- Check SUPABASE_URL and SUPABASE_KEY in `.env`
- Verify table exists: Run `setup_database.sql`
- Check Supabase dashboard for errors

### Import Errors
```bash
# Reinstall dependencies
pip install -r requirements.txt --upgrade
```

See [QUICKSTART.md](QUICKSTART.md) for more troubleshooting tips.

## 📈 Performance

| Operation | Expected Time |
|-----------|--------------|
| First LLM request | 5-10 seconds |
| Subsequent requests | 2-5 seconds |
| Database queries | <100ms |
| Total response time | 3-7 seconds |

## 🔒 Security

- SSL verification disabled for Supabase (corporate network requirement)
- User identification via WhatsApp phone numbers
- Tasks isolated by user_id
- Optional API key authentication available

## 🚧 Roadmap

### Recently Added
- [x] Automated check-ins based on boss type
- [x] Task update and deletion
- [x] Task status updates via check-ins

### Coming Soon
- [ ] Deadline tracking and reminders
- [ ] Subtasks support
- [ ] Team collaboration features
- [ ] User timezone support for check-ins

### Future Enhancements
- [ ] Multi-language support
- [ ] Voice message processing
- [ ] Analytics dashboard
- [ ] Recurring tasks
- [ ] Task templates
- [ ] Quiet hours for check-ins

## 📝 API Endpoints

### `POST /webhook`
Receives WhatsApp messages from Twilio

### `GET /tasks/{user_id}`
Retrieves all tasks for a specific user

### `POST /trigger-checkin`
Triggers check-ins for all users due for check-in (called by cron job)

### `POST /send`
Sends WhatsApp messages programmatically

### `GET /`
Health check endpoint

## 🤝 Contributing

This is an internal demo project. For questions or suggestions, please contact the development team.

## 📄 License

Internal use only.

## 🙏 Acknowledgments

- [LangGraph](https://langchain-ai.github.io/langgraph/) - Agent framework
- [Ollama](https://ollama.ai) - Local LLM runtime
- [Supabase](https://supabase.com) - Database and backend
- [Twilio](https://twilio.com) - WhatsApp integration
- [FastAPI](https://fastapi.tiangolo.com) - Web framework

## 📞 Support

For issues or questions:
1. Check the documentation in `QUICKSTART.md` and `LANGGRAPH_SETUP.md`
2. Run tests with `python test_agent.py --test`
3. Check application logs
4. Review `IMPLEMENTATION_SUMMARY.md` for technical details

---

**Built with ❤️ using LangGraph and Ollama**

*Last updated: January 3, 2026*

