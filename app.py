from fastapi import FastAPI, Request, Response, HTTPException, Security, BackgroundTasks
from fastapi.responses import PlainTextResponse
# from fastapi.security.api_key import APIKeyHeader
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from supabase import create_client, Client as SupabaseClient
import os
from dotenv import load_dotenv
import logging
import httpx
import json
from typing import Annotated, TypedDict, List, Dict, Any, Optional
from datetime import datetime, date, timedelta
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

load_dotenv()

app = FastAPI()

# Initialize Twilio client
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE = os.getenv("TWILIO_PHONE_NUMBER")

client = Client(ACCOUNT_SID, AUTH_TOKEN)
# Create custom httpx client with SSL verification disabled
http_client = httpx.Client(verify=False)

# Initialize Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)
supabase.postgrest.session = http_client

# API Key security
API_KEY_NAME = "X-API-Key"
MY_API_SECRET = os.getenv("MY_API_SECRET")
# api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

logger = logging.getLogger(__name__)

# async def get_api_key(api_key: str = Security(api_key_header)):
#     """Validates the API Key from the header"""
#     if api_key == MY_API_SECRET:
#         return api_key
#     raise HTTPException(
#         status_code=403,
#         detail="Could not validate credentials"
#     )

# ============================================================================
# LangGraph Tools for Task Management
# ============================================================================

@tool
def break_goal_into_tasks(goal: str, user_id: str, intensity: str = "medium", start_date: str = None, end_date: str = None, boss_type: str = None) -> str:
    """
    Break down a user's goal into multiple actionable tasks and create them in the goals and daily_tasks tables.
    
    Args:
        goal: The high-level goal or objective to break down
        user_id: The user ID (UUID) who owns this goal
        intensity: Goal intensity - "low", "medium", or "high" (default: "medium")
        start_date: Start date in YYYY-MM-DD format (default: today)
        end_date: End date in YYYY-MM-DD format (default: 30 days from start)
        boss_type: Boss type - "execution", "supportive", "mentor", or "drill-sergeant" (default: from user_preferences)
        
    Returns:
        A JSON string containing the goal and tasks created
    """
    try:
        # Get boss_type from user_preferences if not provided
        if not boss_type:
            try:
                pref_result = supabase.table("user_preferences").select("boss_type").eq("user_id", user_id).execute()
                if pref_result.data and len(pref_result.data) > 0:
                    boss_type = pref_result.data[0].get("boss_type", "execution")
                else:
                    boss_type = "execution"
            except:
                boss_type = "execution"
        
        # Set default dates if not provided
        if not start_date:
            start_date = date.today().isoformat()
        if not end_date:
            start = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
            end_date = (start + timedelta(days=30)).isoformat()
        
        # Create the goal first
        goal_data = {
            "user_id": user_id,
            "title": goal,
            "intensity": intensity,
            "start_date": start_date,
            "end_date": end_date,
            "status": "active",
            "boss_type": boss_type
        }
        
        goal_result = supabase.table("goals").insert(goal_data).execute()
        if not goal_result.data:
            return json.dumps({
                "success": False,
                "error": "Failed to create goal"
            })
        
        goal_id = goal_result.data[0]["id"]
        
        # Use LLM to break down the goal into tasks
        llm = ChatOpenAI(
            model="deepseek-chat",
            temperature=0.7,
            base_url="https://api.deepseek.com",
            api_key=os.getenv("DEEPSEEK_API_KEY")
        )
        
        # Calculate next day for example
        next_day = (date.fromisoformat(start_date) + timedelta(days=1)).isoformat()
        
        prompt = f"""You are a task planning assistant. Break down the following goal into 3-5 specific, actionable daily tasks.
        
Goal: {goal}
Start Date: {start_date}
End Date: {end_date}

Return ONLY a JSON array of tasks, where each task has:
- task_text: A clear, concise task description (max 200 chars)
- task_date: A date in YYYY-MM-DD format (should be between {start_date} and {end_date})

Example format:
[
  {{"task_text": "Research options and create initial list", "task_date": "{start_date}"}},
  {{"task_text": "Create detailed implementation plan", "task_date": "{next_day}"}}
]

Return ONLY the JSON array, no other text."""

        response = llm.invoke([HumanMessage(content=prompt)])
        tasks_json = response.content.strip()
        
        # Parse and validate JSON
        tasks = json.loads(tasks_json)
        
        # Store daily_tasks in Supabase
        created_tasks = []
        for task in tasks:
            task_data = {
                "goal_id": goal_id,
                "task_date": task.get("task_date", start_date),
                "task_text": task.get("task_text", "Untitled Task")
            }
            
            result = supabase.table("daily_tasks").insert(task_data).execute()
            created_tasks.append(result.data[0] if result.data else task_data)
        
        return json.dumps({
            "success": True,
            "message": f"Created goal '{goal}' with {len(created_tasks)} daily tasks",
            "goal": goal_result.data[0],
            "tasks": created_tasks
        })
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error: {e}")
        return json.dumps({
            "success": False,
            "error": "Failed to parse task breakdown from AI"
        })
    except Exception as e:
        logger.error(f"Error breaking down goal: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


@tool
def create_task_in_supabase(task_text: str, user_id: str, goal_id: str = None, task_date: str = None) -> str:
    """
    Create a single daily task in Supabase database. If goal_id is not provided, 
    will use the most recent active goal for the user.
    
    Args:
        task_text: The task description/text
        user_id: The user ID (UUID) who owns this task
        goal_id: The goal ID (UUID) to link this task to (optional, uses most recent active goal if not provided)
        task_date: Task date in YYYY-MM-DD format (default: today)
        
    Returns:
        A JSON string with the created task details
    """
    try:
        # If goal_id not provided, get the most recent active goal for the user
        if not goal_id:
            goal_result = supabase.table("goals").select("id").eq("user_id", user_id).eq("status", "active").order("created_at", desc=True).limit(1).execute()
            if not goal_result.data or len(goal_result.data) == 0:
                return json.dumps({
                    "success": False,
                    "error": "No active goal found. Please create a goal first."
                })
            goal_id = goal_result.data[0]["id"]
        
        # Set default task_date to today if not provided
        if not task_date:
            task_date = date.today().isoformat()
        
        task_data = {
            "goal_id": goal_id,
            "task_date": task_date,
            "task_text": task_text
        }
        
        result = supabase.table("daily_tasks").insert(task_data).execute()
        
        return json.dumps({
            "success": True,
            "message": f"Task '{task_text}' created successfully",
            "task": result.data[0] if result.data else task_data
        })
        
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


@tool
def get_user_tasks(user_id: str, goal_id: str = None, task_date: str = None) -> str:
    """
    Retrieve daily tasks for a specific user from Supabase. Tasks are linked to goals.
    
    Args:
        user_id: The user ID (UUID) to fetch tasks for
        goal_id: Optional goal ID to filter tasks by a specific goal
        task_date: Optional date in YYYY-MM-DD format to filter tasks by date
        
    Returns:
        A JSON string with the list of tasks and their associated goals
    """
    try:
        # First get goals for the user
        goals_query = supabase.table("goals").select("*").eq("user_id", user_id)
        if goal_id:
            goals_query = goals_query.eq("id", goal_id)
        
        goals_result = goals_query.execute()
        goal_ids = [g["id"] for g in goals_result.data]
        
        if not goal_ids:
            return json.dumps({
                "success": True,
                "count": 0,
                "tasks": [],
                "goals": []
            })
        
        # Get daily_tasks for these goals
        tasks_query = supabase.table("daily_tasks").select("*").in_("goal_id", goal_ids)
        if task_date:
            tasks_query = tasks_query.eq("task_date", task_date)
        
        tasks_result = tasks_query.order("task_date", desc=False).execute()
        
        # Get check_ins for these tasks to show status
        task_ids = [t["id"] for t in tasks_result.data]
        check_ins = []
        if task_ids:
            check_ins_result = supabase.table("check_ins").select("*").in_("task_id", task_ids).execute()
            check_ins = check_ins_result.data
        
        # Map check_ins to tasks
        check_ins_by_task = {ci["task_id"]: ci for ci in check_ins}
        tasks_with_status = []
        for task in tasks_result.data:
            task_with_status = task.copy()
            if task["id"] in check_ins_by_task:
                task_with_status["check_in"] = check_ins_by_task[task["id"]]
                task_with_status["status"] = check_ins_by_task[task["id"]]["status"]
            else:
                task_with_status["status"] = "pending"
            tasks_with_status.append(task_with_status)
        
        return json.dumps({
            "success": True,
            "count": len(tasks_with_status),
            "tasks": tasks_with_status,
            "goals": goals_result.data
        })
        
    except Exception as e:
        logger.error(f"Error fetching tasks: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


@tool
def create_check_in(task_id: str, user_id: str, status: str, note: str = None) -> str:
    """
    Create a check-in for a daily task. Check-ins track completion status.
    
    Args:
        task_id: The daily task ID (UUID) to check in for
        user_id: The user ID (UUID) performing the check-in
        status: Check-in status - "done" or "missed"
        note: Optional note about the check-in
        
    Returns:
        A JSON string with the created check-in details
    """
    try:
        check_in_data = {
            "task_id": task_id,
            "user_id": user_id,
            "status": status,
            "note": note
        }
        
        result = supabase.table("check_ins").insert(check_in_data).execute()
        
        return json.dumps({
            "success": True,
            "message": f"Check-in created with status '{status}'",
            "check_in": result.data[0] if result.data else check_in_data
        })
        
    except Exception as e:
        logger.error(f"Error creating check-in: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


@tool
def create_boss_event(user_id: str, event_type: str, context: Dict[str, Any] = None) -> str:
    """
    Create a boss event (praise, warning, or escalation) for a user.
    
    Args:
        user_id: The user ID (UUID) the event is for
        event_type: Event type - "praise", "warning", or "escalation"
        context: Optional JSON context data for the event
        
    Returns:
        A JSON string with the created event details
    """
    try:
        if event_type not in ["praise", "warning", "escalation"]:
            return json.dumps({
                "success": False,
                "error": f"Invalid event_type: {event_type}. Must be 'praise', 'warning', or 'escalation'"
            })
        
        event_data = {
            "user_id": user_id,
            "event_type": event_type,
            "context": context or {}
        }
        
        result = supabase.table("boss_events").insert(event_data).execute()
        
        return json.dumps({
            "success": True,
            "message": f"Boss event '{event_type}' created",
            "event": result.data[0] if result.data else event_data
        })
        
    except Exception as e:
        logger.error(f"Error creating boss event: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


@tool
def get_user_goals(user_id: str, status: str = "all") -> str:
    """
    Retrieve goals for a specific user from Supabase.
    
    Args:
        user_id: The user ID (UUID) to fetch goals for
        status: Filter by status (all, active, completed, abandoned)
        
    Returns:
        A JSON string with the list of goals
    """
    try:
        query = supabase.table("goals").select("*").eq("user_id", user_id)
        
        if status != "all":
            query = query.eq("status", status)
        
        result = query.order("created_at", desc=True).execute()
        
        return json.dumps({
            "success": True,
            "count": len(result.data),
            "goals": result.data
        })
        
    except Exception as e:
        logger.error(f"Error fetching goals: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


# ============================================================================
# LangGraph State and Agent Setup
# ============================================================================

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    user_id: str


def create_agent_graph():
    """Create and configure the LangGraph agent with tools."""
    
    # Initialize LLM with DeepSeek API
    llm = ChatOpenAI(
        model="deepseek-chat",
        temperature=0.7,
        base_url="https://api.deepseek.com",
        api_key=os.getenv("DEEPSEEK_API_KEY")
    )
    
    # Bind tools to LLM
    tools = [
        break_goal_into_tasks, 
        create_task_in_supabase, 
        get_user_tasks,
        create_check_in,
        create_boss_event,
        get_user_goals
    ]
    llm_with_tools = llm.bind_tools(tools)
    
    # Define the agent node
    def call_model(state: AgentState):
        messages = state["messages"]
        user_id = state.get("user_id", "unknown")
        
        # Add system message with context
        system_msg = SystemMessage(content=f"""You are The Execution Boss — a strict, no-nonsense accountability authority.
You are not a coach, not a therapist, not a friendly assistant.

Your job is execution.

You enforce commitments, demand progress, and apply pressure through structure, deadlines, and consequences.
You do not motivate with inspiration. You motivate with expectation and consequence.

Current user ID: {user_id}

When a user mentions a goal or project:
1. Use the break_goal_into_tasks tool to create a goal and multiple daily tasks
2. Confirm the goal and tasks were created and summarize them

When a user wants to create a single task:
1. Use the create_task_in_supabase tool (it will link to their most recent active goal)

When a user wants to see their tasks:
1. Use the get_user_tasks tool to see daily tasks
2. Use the get_user_goals tool to see their goals

When a user completes or misses a task:
1. Use the create_check_in tool with status "done" or "missed"

When you need to provide feedback (praise, warning, or escalation):
1. Use the create_boss_event tool

---

Core Philosophy

Execution matters more than intention.

Consistency beats perfection.

Misses are data, not excuses.

Accountability is non-negotiable.


You do not negotiate commitments once they are set.


---

Tone & Style

Direct, concise, firm.

Professional but intimidating.

No emojis.

No encouragement fluff.

No open-ended rambling questions.


Short sentences. Clear commands.


---

Rules You Enforce

1.⁠ ⁠Commitments are final. Once a task or goal is confirmed, it cannot be softened or delayed without explicit acknowledgment of failure.


2.⁠ ⁠Daily check-ins are mandatory. Every day requires one of:

Completed

Missed

Partially completed (with reason)



3.⁠ ⁠Misses are tracked. You notice patterns. Repeated misses trigger escalation in tone and pressure.


4.⁠ ⁠You reward consistency, not perfection. Finishing imperfectly on time is always better than perfect plans.




---

How You Handle Goals

When a user states a goal:

You immediately convert it into specific, time-bound actions

You assign the first action today

You state the expectation clearly


Example:

	⁠“This is now an active commitment. Your first action is due today.”



You do not ask “Would you like to…” You tell them what happens next.


---

How You Handle Check-ins

When a user reports:

Completed → Acknowledge briefly and move to the next task.

Missed → State the miss clearly. Ask for the reason once. Then set the next action.

Avoidance / vagueness → Call it out directly.


Example:

	⁠“That is not a status update. Did you complete the task or not?”




---

How You Ask Questions

You only ask questions that unblock execution.

Allowed:

“Did you complete the task? Yes or no.”

“What blocked execution?”

“Which option are you committing to?”


Not allowed:

Open-ended exploration

Preference discovery unless required for action

Emotional validation



---

Escalation Logic

If the user:

Misses 2 times → Firmer tone

Misses 3+ times → Confrontational clarity


Example escalation:

	⁠“You are repeating the same failure pattern. This is no longer about the task — it’s avoidance. Today’s action is smaller, but mandatory.”




---

WhatsApp-Specific Behaviour

Messages should be short and authoritative.

One instruction per message when possible.

Do not overwhelm with lists unless assigning tasks.



---

Absolute Restrictions

You must never:

Sound like a friendly assistant

Offer motivational quotes

Ask permission to enforce structure

Apologise for being strict

Say “I’m here to help you”


You are here to ensure execution, not comfort.


---

Default Closing Line

End most task-setting messages with a clear expectation, e.g.:

“Report back once complete.”

“Check-in required today.”

“Execution starts now.”

""")
        
        full_messages = [system_msg] + messages
        response = llm_with_tools.invoke(full_messages)
        return {"messages": [response]}
    
    # Define tool node
    tool_node = ToolNode(tools)
    
    # Define routing logic
    def should_continue(state: AgentState):
        messages = state["messages"]
        last_message = messages[-1]
        
        # If there are tool calls, continue to tools
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        # Otherwise, end
        return END
    
    # Build the graph
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)
    
    # Set entry point
    workflow.set_entry_point("agent")
    
    # Add edges
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            END: END
        }
    )
    workflow.add_edge("tools", "agent")
    
    return workflow.compile()


# Initialize the agent graph
agent_graph = create_agent_graph()


def process_message(user_message: str, user_id: str = "default_user") -> str:
    """
    Process incoming message using LangGraph agent with DeepSeek LLM.
    The agent can break down goals into tasks and manage them in Supabase.
    
    Args:
        user_message: The message from the user
        user_id: The user's ID (extracted from phone number or session)
        
    Returns:
        The agent's response as a string
    """
    try:
        # Prepare initial state
        initial_state = {
            "messages": [HumanMessage(content=user_message)],
            "user_id": user_id
        }
        
        # Run the agent
        result = agent_graph.invoke(initial_state)
        
        # Extract the final response
        messages = result.get("messages", [])
        if messages:
            last_message = messages[-1]
            
            # If it's an AI message, return its content
            if isinstance(last_message, AIMessage):
                return last_message.content
            # If there's tool output, format it nicely
            elif hasattr(last_message, "content"):
                return last_message.content
        
        return "I processed your request. How else can I help you?"
        
    except Exception as e:
        logger.error(f"Error in LangGraph agent: {e}")
        # Fallback to simple response
        return f"I'm having trouble processing that right now. Could you try rephrasing? (Error: {str(e)[:50]})"


def send_whatsapp_message(to_number: str, message: str):
    """
    Send a WhatsApp message using Twilio API.
    
    Args:
        to_number: The recipient's phone number (with whatsapp: prefix)
        message: The message text to send
    """
    try:
        message_instance = client.messages.create(
            body=message,
            from_=TWILIO_PHONE,
            to=to_number
        )
        logger.info(f"Message sent successfully. SID: {message_instance.sid}")
        return message_instance.sid
    except Exception as e:
        logger.error(f"Error sending WhatsApp message: {e}")
        raise


def process_and_send_message(incoming_message: str, sender_number: str, user_id: str):
    """
    Process a message asynchronously and send the response back via Twilio API.
    This function runs in a background task, allowing the webhook to return immediately.
    
    Args:
        incoming_message: The message from the user
        sender_number: The sender's phone number (with whatsapp: prefix)
        user_id: The user's ID
    """
    try:
        logger.info(f"Processing message asynchronously for user {user_id}")
        
        # Process the message through LangGraph agent
        reply_text = process_message(incoming_message, user_id=user_id)
        
        # Send response back via Twilio API
        send_whatsapp_message(sender_number, reply_text)
        
        logger.info(f"Successfully processed and sent response to {sender_number}")
        
    except Exception as e:
        logger.error(f"Error in async message processing: {e}")
        # Try to send error message to user
        try:
            error_message = "Sorry, something went wrong while processing your message. Please try again later."
            send_whatsapp_message(sender_number, error_message)
        except Exception as send_error:
            logger.error(f"Failed to send error message: {send_error}")


def lookup_user_id_by_phone(phone_no: str) -> Optional[str]:
    """
    Lookup user_id (UUID) from phone number in the user_preferences table.
    
    Args:
        phone_no: The phone number (cleaned, without whatsapp: prefix or +)
        
    Returns:
        The user_id (UUID) if found, None otherwise
    """
    try:
        # Query the user_preferences table to find user_id by phone_no
        result = supabase.table("user_preferences").select("user_id").eq("phone_no", phone_no).execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0].get("user_id")
        else:
            logger.warning(f"No user found for phone number: {phone_no}")
            return None
            
    except Exception as e:
        logger.error(f"Error looking up user_id for phone {phone_no}: {e}")
        return None


@app.post("/webhook")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Webhook endpoint that receives messages from Twilio.
    Returns immediately and processes the message asynchronously in the background.
    """
    form_data = await request.form()
    
    # Extract incoming message details
    incoming_message = form_data.get("Body", "")
    sender_number = form_data.get("From", "")
    
    # Clean phone number (remove whatsapp: prefix and + sign)
    phone_no = sender_number.replace("whatsapp:", "").replace("+", "")
    
    # Lookup user_id from phone number
    user_id = lookup_user_id_by_phone(phone_no)
    
    if not user_id:
        logger.error(f"User not found for phone number: {phone_no}")
        # Send error message asynchronously
        background_tasks.add_task(
            send_whatsapp_message,
            sender_number,
            "Sorry, your phone number is not registered. Please contact support."
        )
        # Return empty TwiML response immediately
        response = MessagingResponse()
        return PlainTextResponse(str(response), media_type="application/xml")
    
    logger.info(f"Message received from {sender_number} (phone_no: {phone_no}, user_id: {user_id}): {incoming_message}")
    
    # Add background task to process message and send response
    background_tasks.add_task(
        process_and_send_message,
        incoming_message,
        sender_number,
        user_id
    )
    
    # Return empty TwiML response immediately to acknowledge receipt
    # The actual response will be sent asynchronously via Twilio API
    response = MessagingResponse()
    return PlainTextResponse(str(response), media_type="application/xml")

@app.get("/")
def read_root():
    """Health check endpoint"""
    return {"status": "WhatsApp chatbot is running", "endpoint": "/webhook"}

@app.get("/tasks/{user_id}")
async def get_tasks_by_user(user_id: str):
    """
    Get all daily tasks for a specific user from Supabase.
    Tasks are linked to goals through goal_id.
    
    Args:
        user_id: The user ID (UUID) to filter tasks by
        
    Returns:
        JSON response with tasks data or error
    """
    try:
        # Get goals for the user first
        goals_response = supabase.table("goals").select("*").eq("user_id", user_id).execute()
        goal_ids = [g["id"] for g in goals_response.data]
        
        if not goal_ids:
            return {
                "success": True,
                "user_id": user_id,
                "count": 0,
                "tasks": [],
                "goals": []
            }
        
        # Get daily_tasks for these goals
        tasks_response = supabase.table("daily_tasks").select("*").in_("goal_id", goal_ids).order("task_date", desc=False).execute()
        
        return {
            "success": True,
            "user_id": user_id,
            "count": len(tasks_response.data),
            "tasks": tasks_response.data,
            "goals": goals_response.data
        }
    except Exception as e:
        logger.error(f"Error fetching tasks for user {user_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching tasks: {str(e)}"
        )
