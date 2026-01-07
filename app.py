from fastapi import FastAPI, Request, Response, HTTPException, Security
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
from typing import Annotated, TypedDict, List, Dict, Any
from datetime import datetime
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
def break_goal_into_tasks(goal: str, user_id: str) -> str:
    """
    Break down a user's goal into multiple actionable tasks.
    
    Args:
        goal: The high-level goal or objective to break down
        user_id: The user ID who owns this goal
        
    Returns:
        A JSON string containing the list of tasks created
    """
    try:
        # Use LLM to break down the goal into tasks
        llm = ChatOpenAI(
            model="deepseek-chat",
            temperature=0.7,
            base_url="https://api.deepseek.com",
            api_key=os.getenv("DEEPSEEK_API_KEY")
        )
        
        prompt = f"""You are a task planning assistant. Break down the following goal into 3-5 specific, actionable tasks.
        
Goal: {goal}

Return ONLY a JSON array of tasks, where each task has:
- title: A clear, concise task title (max 100 chars)
- description: A brief description of what needs to be done
- priority: "high", "medium", or "low"
- estimated_hours: Estimated hours to complete (number)

Example format:
[
  {{"title": "Research options", "description": "Look into available solutions", "priority": "high", "estimated_hours": 2}},
  {{"title": "Create plan", "description": "Draft implementation plan", "priority": "medium", "estimated_hours": 3}}
]

Return ONLY the JSON array, no other text."""

        response = llm.invoke([HumanMessage(content=prompt)])
        tasks_json = response.content.strip()
        
        # Parse and validate JSON
        tasks = json.loads(tasks_json)
        
        # Store tasks in Supabase
        created_tasks = []
        for task in tasks:
            task_data = {
                "user_id": user_id,
                "title": task.get("title", "Untitled Task"),
                "description": task.get("description", ""),
                "priority": task.get("priority", "medium"),
                "estimated_hours": task.get("estimated_hours", 1),
                "status": "pending",
                "goal": goal,
                "created_at": datetime.utcnow().isoformat()
            }
            
            result = supabase.table("tasks").insert(task_data).execute()
            created_tasks.append(result.data[0] if result.data else task_data)
        
        return json.dumps({
            "success": True,
            "message": f"Created {len(created_tasks)} tasks from your goal",
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
def create_task_in_supabase(title: str, description: str, user_id: str, priority: str = "medium") -> str:
    """
    Create a single task in Supabase database.
    
    Args:
        title: The task title
        description: Detailed description of the task
        user_id: The user ID who owns this task
        priority: Task priority (high, medium, or low)
        
    Returns:
        A JSON string with the created task details
    """
    try:
        task_data = {
            "user_id": user_id,
            "title": title,
            "description": description,
            "priority": priority,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat()
        }
        
        result = supabase.table("tasks").insert(task_data).execute()
        
        return json.dumps({
            "success": True,
            "message": f"Task '{title}' created successfully",
            "task": result.data[0] if result.data else task_data
        })
        
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


@tool
def get_user_tasks(user_id: str, status: str = "all") -> str:
    """
    Retrieve tasks for a specific user from Supabase.
    
    Args:
        user_id: The user ID to fetch tasks for
        status: Filter by status (all, pending, in_progress, completed)
        
    Returns:
        A JSON string with the list of tasks
    """
    try:
        query = supabase.table("tasks").select("*").eq("user_id", user_id)
        
        if status != "all":
            query = query.eq("status", status)
        
        result = query.execute()
        
        return json.dumps({
            "success": True,
            "count": len(result.data),
            "tasks": result.data
        })
        
    except Exception as e:
        logger.error(f"Error fetching tasks: {e}")
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
    tools = [break_goal_into_tasks, create_task_in_supabase, get_user_tasks]
    llm_with_tools = llm.bind_tools(tools)
    
    # Define the agent node
    def call_model(state: AgentState):
        messages = state["messages"]
        user_id = state.get("user_id", "unknown")
        
        # Add system message with context
        system_msg = SystemMessage(content=f"""You are a helpful task management assistant. 
You help users break down their goals into actionable tasks and manage them.

Current user ID: {user_id}

When a user mentions a goal or project:
1. Use the break_goal_into_tasks tool to create multiple tasks
2. Confirm the tasks were created and summarize them

When a user wants to create a single task:
1. Use the create_task_in_supabase tool

When a user wants to see their tasks:
1. Use the get_user_tasks tool

Be conversational, helpful, and concise in your responses.""")
        
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

@app.post("/webhook")
async def whatsapp_webhook(request: Request):
    """
    Webhook endpoint that receives messages from Twilio
    """
    form_data = await request.form()
    
    # Extract incoming message details
    incoming_message = form_data.get("Body", "")
    sender_number = form_data.get("From", "")
    
    # Use sender number as user_id (clean it up)
    user_id = sender_number.replace("whatsapp:", "").replace("+", "")
    
    logger.info(f"Message from {sender_number} (user_id: {user_id}): {incoming_message}")
    
    try:
        # Process the message through LangGraph agent
        reply_text = process_message(incoming_message, user_id=user_id)
        
        # Create TwiML response (Twilio's XML format)
        response = MessagingResponse()
        response.message(reply_text)
        
        return PlainTextResponse(str(response), media_type="application/xml")
    
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        response = MessagingResponse()
        response.message("Sorry, something went wrong. Please try again later.")
        return PlainTextResponse(str(response), media_type="application/xml")

@app.get("/")
def read_root():
    """Health check endpoint"""
    return {"status": "WhatsApp chatbot is running", "endpoint": "/webhook"}

@app.get("/tasks/{user_id}")
async def get_tasks_by_user(user_id: str):
    """
    Get all tasks for a specific user from Supabase.
    Protected by 'X-API-Key' header.
    
    Args:
        user_id: The user ID to filter tasks by
        
    Returns:
        JSON response with tasks data or error
    """
    try:
        # Query tasks table filtered by user_id
        response = supabase.table("tasks").select("*").eq("user_id", user_id).execute()
        
        return {
            "success": True,
            "user_id": user_id,
            "count": len(response.data),
            "data": response.data
        }
    except Exception as e:
        logger.error(f"Error fetching tasks for user {user_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching tasks: {str(e)}"
        )
