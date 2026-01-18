from fastapi import FastAPI, Request, Response, HTTPException, Security, BackgroundTasks, Depends
from fastapi.responses import PlainTextResponse
from fastapi.security.api_key import APIKeyHeader
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from supabase import create_client, Client as SupabaseClient
import os
from dotenv import load_dotenv
import logging
import httpx
import json
import random
from typing import Annotated, TypedDict, List, Dict, Any, Optional
from datetime import datetime, date, timedelta
from difflib import SequenceMatcher
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from supabase_checkpointer import SupabaseCheckpointer
from language_prompts import (
    get_system_prompt,
    get_checkin_message,
    get_checkin_ai_prompt,
    get_personality_prompt,
    get_language_name
)

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
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

logger = logging.getLogger(__name__)


async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """Validates the API Key from the header"""
    if not MY_API_SECRET:
        logger.error("MY_API_SECRET not configured in environment variables")
        raise HTTPException(
            status_code=500,
            detail="API key validation not configured"
        )
    if api_key == MY_API_SECRET:
        return api_key
    raise HTTPException(
        status_code=403,
        detail="Invalid API key"
    )


# Initialize LangGraph Supabase AsyncPostgresSaver Checkpointer for persistence
# Note: The checkpointer will be initialized asynchronously when needed
# We'll create a global instance that can be reused
supabase_checkpointer: Optional[SupabaseCheckpointer] = None
SUPABASE_DB_URI = os.getenv("SUPABASE_DB_URI")

if SUPABASE_DB_URI:
    try:
        supabase_checkpointer = SupabaseCheckpointer(SUPABASE_DB_URI)
        logger.info("Supabase checkpointer instance created (will be initialized async)")
    except Exception as e:
        logger.warning(f"Failed to create Supabase checkpointer: {e}. Persistence will be disabled.")
        supabase_checkpointer = None
else:
    logger.warning("SUPABASE_DB_URI not set. LangGraph persistence will be disabled.")

# ============================================================================
# LangGraph Tools for Task Management
# ============================================================================

def calculate_similarity(text1: str, text2: str) -> float:
    """
    Calculate similarity between two texts using SequenceMatcher.
    Returns a value between 0.0 (completely different) and 1.0 (identical).
    """
    return SequenceMatcher(None, text1.lower().strip(), text2.lower().strip()).ratio()


def find_similar_goals(goal_text: str, user_id: str, threshold: float = 0.7) -> List[Dict[str, Any]]:
    """
    Find similar existing goals for a user.
    
    Args:
        goal_text: The goal text to check
        user_id: The user ID
        threshold: Similarity threshold (0.0 to 1.0), default 0.7
        
    Returns:
        List of similar goals with similarity scores
    """
    try:
        # Get all active goals for the user
        goals_result = supabase.table("goals").select("id, title, intensity, status, created_at").eq("user_id", user_id).eq("status", "active").execute()
        existing_goals = goals_result.data if goals_result.data else []
        
        similar_goals = []
        for existing_goal in existing_goals:
            existing_title = existing_goal.get("title", "")
            similarity = calculate_similarity(goal_text, existing_title)
            
            if similarity >= threshold:
                similar_goals.append({
                    "goal": existing_goal,
                    "similarity": similarity,
                    "title": existing_title
                })
        
        # Sort by similarity (highest first)
        similar_goals.sort(key=lambda x: x["similarity"], reverse=True)
        return similar_goals
    except Exception as e:
        logger.error(f"Error finding similar goals: {e}")
        return []


def find_similar_tasks(task_text: str, user_id: str, task_date: str = None, threshold: float = 0.7) -> List[Dict[str, Any]]:
    """
    Find similar existing tasks for a user.
    
    Args:
        task_text: The task text to check
        user_id: The user ID
        task_date: Optional date to filter tasks (YYYY-MM-DD)
        threshold: Similarity threshold (0.0 to 1.0), default 0.7
        
    Returns:
        List of similar tasks with similarity scores
    """
    try:
        # Get all active goals for the user
        goals_result = supabase.table("goals").select("id").eq("user_id", user_id).eq("status", "active").execute()
        goal_ids = [g["id"] for g in (goals_result.data if goals_result.data else [])]
        
        if not goal_ids:
            return []
        
        # Get all tasks for these goals
        tasks_query = supabase.table("daily_tasks").select("id, task_text, task_date, goal_id").in_("goal_id", goal_ids)
        
        if task_date:
            tasks_query = tasks_query.eq("task_date", task_date)
        
        tasks_result = tasks_query.execute()
        existing_tasks = tasks_result.data if tasks_result.data else []
        
        similar_tasks = []
        for existing_task in existing_tasks:
            existing_text = existing_task.get("task_text", "")
            similarity = calculate_similarity(task_text, existing_text)
            
            if similarity >= threshold:
                similar_tasks.append({
                    "task": existing_task,
                    "similarity": similarity,
                    "task_text": existing_text,
                    "task_date": existing_task.get("task_date")
                })
        
        # Sort by similarity (highest first)
        similar_tasks.sort(key=lambda x: x["similarity"], reverse=True)
        return similar_tasks
    except Exception as e:
        logger.error(f"Error finding similar tasks: {e}")
        return []


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
        
        # Check for conflicts with existing active goals
        existing_goals_result = supabase.table("goals").select("id, title, intensity, status").eq("user_id", user_id).eq("status", "active").execute()
        existing_goals = existing_goals_result.data if existing_goals_result.data else []
        
        conflicts = []
        warnings = []
        
        # Check for too many high-intensity goals
        high_intensity_count = sum(1 for g in existing_goals if g.get("intensity") == "high")
        if intensity == "high" and high_intensity_count >= 2:
            warnings.append(f"You already have {high_intensity_count} high-intensity goals active. Adding another high-intensity goal may be overwhelming.")
        elif intensity == "high" and high_intensity_count >= 1:
            warnings.append(f"You have {high_intensity_count} other high-intensity goal(s) active. Make sure you can handle both.")
        
        # Check for date overlaps with existing goals
        start = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
        end = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
        
        for existing_goal in existing_goals:
            existing_start = date.fromisoformat(existing_goal.get("start_date", "")) if existing_goal.get("start_date") else None
            existing_end = date.fromisoformat(existing_goal.get("end_date", "")) if existing_goal.get("end_date") else None
            
            if existing_start and existing_end:
                # Check if date ranges overlap
                if not (end < existing_start or start > existing_end):
                    overlap_msg = f"Date range overlaps with existing goal '{existing_goal.get('title', 'Untitled')}' ({existing_goal.get('intensity', 'medium')} intensity)"
                    if existing_goal.get("intensity") == "high" and intensity == "high":
                        conflicts.append(overlap_msg)
                    else:
                        warnings.append(overlap_msg)
        
        # Check for similar goals before creating
        similar_goals = find_similar_goals(goal, user_id, threshold=0.7)
        
        if similar_goals:
            # Found similar goals - return confirmation request
            similar_list = []
            for sg in similar_goals[:3]:  # Show top 3 most similar
                similar_list.append(f"- '{sg['title']}' ({(sg['similarity']*100):.0f}% similar)")
            
            return json.dumps({
                "success": False,
                "requires_confirmation": True,
                "message": f"I found similar existing goals. Do you want to create a new goal anyway?",
                "similar_goals": [sg["goal"] for sg in similar_goals[:3]],
                "similarity_details": "\n".join(similar_list),
                "new_goal": goal,
                "action": "break_goal_into_tasks",
                "action_params": {
                    "goal": goal,
                    "user_id": user_id,
                    "intensity": intensity,
                    "start_date": start_date,
                    "end_date": end_date,
                    "boss_type": boss_type
                }
            })
        
        # If there are critical conflicts, return warning but allow creation
        conflict_info = {
            "warnings": warnings,
            "conflicts": conflicts,
            "existing_goals_count": len(existing_goals),
            "high_intensity_count": high_intensity_count
        }
        
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
        
        response_data = {
            "success": True,
            "message": f"Created goal '{goal}' with {len(created_tasks)} daily tasks",
            "goal": goal_result.data[0],
            "tasks": created_tasks
        }
        
        # Include conflict information if any
        if warnings or conflicts:
            response_data["conflict_info"] = conflict_info
            if conflicts:
                response_data["message"] += f" (Warning: {len(conflicts)} potential conflicts detected)"
        
        return json.dumps(response_data)
        
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
        
        # Check for conflicts with existing tasks on the same date
        existing_tasks_result = supabase.table("daily_tasks").select("id, task_text, task_date").eq("task_date", task_date).in_("goal_id", [goal_id]).execute()
        existing_tasks = existing_tasks_result.data if existing_tasks_result.data else []
        
        # Also check tasks from other active goals on the same date
        all_active_goals_result = supabase.table("goals").select("id").eq("user_id", user_id).eq("status", "active").execute()
        all_active_goal_ids = [g["id"] for g in (all_active_goals_result.data if all_active_goals_result.data else [])]
        
        all_tasks_on_date_result = supabase.table("daily_tasks").select("id, task_text, goal_id").eq("task_date", task_date).in_("goal_id", all_active_goal_ids).execute()
        all_tasks_on_date = all_tasks_on_date_result.data if all_tasks_on_date_result.data else []
        
        warnings = []
        conflicts = []
        
        # Check if there are too many tasks on the same date
        if len(all_tasks_on_date) >= 5:
            conflicts.append(f"You already have {len(all_tasks_on_date)} tasks scheduled for {task_date}. This may be too many for one day.")
        elif len(all_tasks_on_date) >= 3:
            warnings.append(f"You have {len(all_tasks_on_date)} other tasks scheduled for {task_date}. Make sure you can handle them all.")
        
        # Check for similar tasks using better similarity algorithm
        similar_tasks = find_similar_tasks(task_text, user_id, task_date=task_date, threshold=0.7)
        
        if similar_tasks:
            # Found similar tasks - return confirmation request
            similar_list = []
            for st in similar_tasks[:3]:  # Show top 3 most similar
                task_date_str = st.get("task_date", "unknown date")
                similar_list.append(f"- '{st['task_text']}' on {task_date_str} ({(st['similarity']*100):.0f}% similar)")
            
            return json.dumps({
                "success": False,
                "requires_confirmation": True,
                "message": f"I found similar existing tasks. Do you want to create a new task anyway?",
                "similar_tasks": [st["task"] for st in similar_tasks[:3]],
                "similarity_details": "\n".join(similar_list),
                "new_task": task_text,
                "action": "create_task_in_supabase",
                "action_params": {
                    "task_text": task_text,
                    "user_id": user_id,
                    "goal_id": goal_id,
                    "task_date": task_date
                }
            })
        
        # Check for similar tasks on the same date (legacy check for warnings)
        task_lower = task_text.lower()
        for existing_task in all_tasks_on_date:
            existing_text = existing_task.get("task_text", "").lower()
            # Simple similarity check - if tasks are very similar
            if existing_text and task_lower in existing_text or existing_text in task_lower:
                if len(task_lower) > 10 and len(existing_text) > 10:  # Only flag if both are substantial
                    warnings.append(f"Similar task already exists on {task_date}: '{existing_task.get('task_text', '')}'")
        
        task_data = {
            "goal_id": goal_id,
            "task_date": task_date,
            "task_text": task_text
        }
        
        result = supabase.table("daily_tasks").insert(task_data).execute()
        
        response_data = {
            "success": True,
            "message": f"Task '{task_text}' created successfully",
            "task": result.data[0] if result.data else task_data
        }
        
        # Include conflict information if any
        if warnings or conflicts:
            response_data["conflict_info"] = {
                "warnings": warnings,
                "conflicts": conflicts,
                "tasks_on_date": len(all_tasks_on_date) + 1  # +1 for the new task
            }
            if conflicts:
                response_data["message"] += f" (Warning: {len(conflicts)} potential conflicts detected)"
        
        return json.dumps(response_data)
        
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
def confirm_and_create_goal(goal: str, user_id: str, intensity: str = "medium", start_date: str = None, end_date: str = None, boss_type: str = None) -> str:
    """
    Confirm and create a goal after user approval. This is called when user confirms they want to create a goal despite similar ones existing.
    This bypasses the similarity check and creates the goal directly.
    
    Args:
        goal: The high-level goal or objective to break down
        user_id: The user ID (UUID) who owns this goal
        intensity: Goal intensity - "low", "medium", or "high" (default: "medium")
        start_date: Start date in YYYY-MM-DD format (default: today)
        end_date: End date in YYYY-MM-DD format (default: 30 days from start)
        boss_type: Boss type (optional)
        
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
        
        # Create the goal directly (skip similarity check since user confirmed)
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
        logger.error(f"Error creating confirmed goal: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


@tool
def confirm_and_create_task(task_text: str, user_id: str, goal_id: str = None, task_date: str = None) -> str:
    """
    Confirm and create a task after user approval. This is called when user confirms they want to create a task despite similar ones existing.
    This bypasses the similarity check and creates the task directly.
    
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
        
        # Create the task directly (skip similarity check since user confirmed)
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
        logger.error(f"Error creating confirmed task: {e}")
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


@tool
def delete_goal(goal_id: str, user_id: str, delete_tasks: bool = True) -> str:
    """
    Delete a goal and optionally its associated tasks from Supabase.
    
    Args:
        goal_id: The goal ID (UUID) to delete
        user_id: The user ID (UUID) who owns this goal (for verification)
        delete_tasks: Whether to also delete all tasks associated with this goal (default: True)
        
    Returns:
        A JSON string with the deletion result
    """
    try:
        # First verify the goal belongs to the user
        goal_result = supabase.table("goals").select("id, title, user_id").eq("id", goal_id).eq("user_id", user_id).execute()
        
        if not goal_result.data or len(goal_result.data) == 0:
            return json.dumps({
                "success": False,
                "error": "Goal not found or you don't have permission to delete it"
            })
        
        goal_title = goal_result.data[0].get("title", "Unknown")
        deleted_tasks_count = 0
        
        # Delete associated tasks if requested
        if delete_tasks:
            tasks_result = supabase.table("daily_tasks").select("id").eq("goal_id", goal_id).execute()
            task_ids = [t["id"] for t in (tasks_result.data if tasks_result.data else [])]
            
            if task_ids:
                # Delete all tasks for this goal
                for task_id in task_ids:
                    supabase.table("daily_tasks").delete().eq("id", task_id).execute()
                deleted_tasks_count = len(task_ids)
        
        # Delete the goal
        supabase.table("goals").delete().eq("id", goal_id).execute()
        
        return json.dumps({
            "success": True,
            "message": f"Goal '{goal_title}' deleted successfully",
            "goal_id": goal_id,
            "deleted_tasks_count": deleted_tasks_count
        })
        
    except Exception as e:
        logger.error(f"Error deleting goal: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


@tool
def delete_task(task_id: str, user_id: str) -> str:
    """
    Delete a single task from Supabase.
    
    Args:
        task_id: The task ID (UUID) to delete
        user_id: The user ID (UUID) who owns this task (for verification)
        
    Returns:
        A JSON string with the deletion result
    """
    try:
        # First verify the task belongs to the user by checking through the goal
        # Get the task and its associated goal
        task_result = supabase.table("daily_tasks").select("id, task_text, goal_id").eq("id", task_id).execute()
        
        if not task_result.data or len(task_result.data) == 0:
            return json.dumps({
                "success": False,
                "error": "Task not found"
            })
        
        task_text = task_result.data[0].get("task_text", "Unknown")
        goal_id = task_result.data[0].get("goal_id")
        
        # Verify the goal belongs to the user
        goal_result = supabase.table("goals").select("id, user_id").eq("id", goal_id).eq("user_id", user_id).execute()
        
        if not goal_result.data or len(goal_result.data) == 0:
            return json.dumps({
                "success": False,
                "error": "Task not found or you don't have permission to delete it"
            })
        
        # Delete the task
        supabase.table("daily_tasks").delete().eq("id", task_id).execute()
        
        return json.dumps({
            "success": True,
            "message": f"Task '{task_text}' deleted successfully",
            "task_id": task_id
        })
        
    except Exception as e:
        logger.error(f"Error deleting task: {e}")
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


def create_agent_graph(checkpointer=None):
    """Create and configure the LangGraph agent with tools.
    
    Args:
        checkpointer: Optional AsyncPostgresSaver checkpointer for persistence
    """
    
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
        confirm_and_create_goal,
        confirm_and_create_task,
        get_user_tasks,
        create_check_in,
        create_boss_event,
        get_user_goals,
        delete_goal,
        delete_task
    ]
    llm_with_tools = llm.bind_tools(tools)
    
    # Define the agent node
    def call_model(state: AgentState):
        messages = state["messages"]
        user_id = state.get("user_id", "unknown")
        
        # Get user's boss_type and boss_language preferences
        boss_type = "execution"  # default
        boss_language = "en"  # default
        try:
            pref_result = supabase.table("user_preferences").select("boss_type, boss_language").eq("user_id", user_id).execute()
            if pref_result.data and len(pref_result.data) > 0:
                boss_type = pref_result.data[0].get("boss_type", "execution")
                boss_language = pref_result.data[0].get("boss_language", "en")
        except:
            pass
        
        # Generate complete system prompt using language support module
        system_prompt = get_system_prompt(user_id, boss_type, boss_language)
        
        # Add additional behavioral instructions
        system_prompt += """


---

How You Ask Questions

You only ask questions that unblock execution.

Allowed:

"Did you complete the task? Yes or no."

"What blocked execution?"

"Which option are you committing to?"


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

	⁠"You are repeating the same failure pattern. This is no longer about the task — it's avoidance. Today's action is smaller, but mandatory."




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

Say "I'm here to help you"


You are here to ensure execution, not comfort.


---

Default Closing Line

End most task-setting messages with a clear expectation, e.g.:

"Report back once complete ✅"

"Check-in required today 📋"

"Execution starts now 💪"

"""
        
        # Add system message with generated prompt
        system_msg = SystemMessage(content=system_prompt)
        
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
    
    # Compile with checkpointer if available (enables persistence)
    if checkpointer:
        return workflow.compile(checkpointer=checkpointer)
    else:
        logger.warning("Compiling graph without checkpointer - persistence disabled")
        return workflow.compile()


# Note: Agent graph will be created per-request with the checkpointer
# This allows us to use async checkpointers properly


async def process_message(user_message: str, user_id: str = "default_user", thread_id: str = None) -> str:
    """
    Process incoming message using LangGraph agent with DeepSeek LLM.
    The agent can break down goals into tasks and manage them in Supabase.
    Conversation state is persisted using thread_id for memory across sessions.
    
    Args:
        user_message: The message from the user
        user_id: The user's ID (extracted from phone number or session)
        thread_id: Optional thread ID for conversation persistence. If not provided, uses user_id.
        
    Returns:
        The agent's response as a string
    """
    try:
        # Use user_id as thread_id if not provided (each user has their own conversation thread)
        if thread_id is None:
            thread_id = user_id
        
        # Prepare config with thread_id for persistence
        config = {"configurable": {"thread_id": thread_id}}
        
        # Prepare initial state with new message
        # If checkpointer is enabled, previous messages will be loaded automatically
        initial_state = {
            "messages": [HumanMessage(content=user_message)],
            "user_id": user_id
        }
        
        # Get or create checkpointer connection
        checkpointer_instance = None
        if supabase_checkpointer:
            checkpointer_instance = supabase_checkpointer.checkpointer
            if not checkpointer_instance:
                # Initialize connection if not already done
                await supabase_checkpointer.setup_connection()
                checkpointer_instance = supabase_checkpointer.checkpointer
        
        # Create agent graph with checkpointer
        agent_graph = create_agent_graph(checkpointer=checkpointer_instance)
        
        # Run the agent with config for persistence (async if checkpointer is async)
        if checkpointer_instance:
            # Use ainvoke for async checkpointer
            result = await agent_graph.ainvoke(initial_state, config=config)
        else:
            # Use invoke for sync (no checkpointer)
            result = agent_graph.invoke(initial_state, config=config)
        
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
        logger.error(f"Error in LangGraph agent: {e}", exc_info=True)
        # Fallback to simple response
        return f"I'm having trouble processing that right now. Could you try rephrasing? (Error: {str(e)[:50]})"


def get_checkin_interval_hours(boss_type: str) -> int:
    """
    Get check-in interval in hours based on boss type.
    
    Args:
        boss_type: The boss type (drill-sergeant, execution, supportive, mentor)
        
    Returns:
        Number of hours between check-ins
    """
    intervals = {
        "drill-sergeant": 1,
        "execution": 2,
        "supportive": 4,
        "mentor": 4
    }
    return intervals.get(boss_type, 2)  # default to execution (2 hours)


async def generate_checkin_message_with_context(user_id: str, boss_type: str, last_checkin_at: str = None, boss_language: str = "en") -> str:
    """
    Generate an AI-powered check-in message based on user's tasks and chat history.
    Falls back to default messages if context cannot be retrieved.
    Supports multiple languages based on user preference.
    
    Args:
        user_id: The user ID to fetch context for
        boss_type: The boss type for personality
        last_checkin_at: The last checkin timestamp (ISO format)
        boss_language: The language preference (default: "en")
        
    Returns:
        A personalized check-in message string in the user's preferred language
    """
    try:
        # Check if this is the first ping of the day
        is_first_ping_today = False
        if last_checkin_at:
            try:
                last_checkin_date = datetime.fromisoformat(last_checkin_at.replace('Z', '+00:00')).date()
                today = date.today()
                is_first_ping_today = last_checkin_date < today
            except Exception as e:
                logger.warning(f"Could not parse last_checkin_at: {e}")
                is_first_ping_today = False
        
        # Get user's active goals and recent tasks
        goals_result = supabase.table("goals").select("id, title, intensity, start_date, end_date").eq(
            "user_id", user_id
        ).eq("status", "active").order("created_at", desc=True).limit(3).execute()
        
        goals = goals_result.data if goals_result.data else []
        
        # Get recent tasks (last 7 days)
        today = date.today()
        week_ago = today - timedelta(days=7)
        
        tasks = []
        if goals:
            goal_ids = [g["id"] for g in goals]
            tasks_result = supabase.table("daily_tasks").select(
                "id, task_text, task_date"
            ).in_("goal_id", goal_ids).gte(
                "task_date", week_ago.isoformat()
            ).order("task_date", desc=False).limit(10).execute()
            
            tasks = tasks_result.data if tasks_result.data else []
        
        # Get check-in status for recent tasks
        task_statuses = []
        if tasks:
            task_ids = [t["id"] for t in tasks]
            checkins_result = supabase.table("check_ins").select(
                "task_id, status, checked_at"
            ).in_("task_id", task_ids).order("checked_at", desc=True).limit(10).execute()
            
            checkins = checkins_result.data if checkins_result.data else []
            checkins_by_task = {c["task_id"]: c["status"] for c in checkins}
            
            for task in tasks:
                task_id = task["id"]
                status = checkins_by_task.get(task_id, "pending")
                task_statuses.append({
                    "task": task["task_text"],
                    "date": task["task_date"],
                    "status": status
                })
        
        # If we have context, generate AI message
        if goals or tasks:
            # Build context string
            context_parts = []
            
            if goals:
                goals_text = "\n".join([f"- {g['title']} (intensity: {g['intensity']})" for g in goals])
                context_parts.append(f"Active Goals:\n{goals_text}")
            
            if task_statuses:
                # Separate completed and pending tasks
                completed = [t for t in task_statuses if t["status"] == "done"]
                pending = [t for t in task_statuses if t["status"] == "pending"]
                missed = [t for t in task_statuses if t["status"] == "missed"]
                
                if completed:
                    completed_text = "\n".join([f"- {t['task']} ({t['date']})" for t in completed[:3]])
                    context_parts.append(f"Recently Completed:\n{completed_text}")
                
                if pending:
                    pending_text = "\n".join([f"- {t['task']} ({t['date']})" for t in pending[:3]])
                    context_parts.append(f"Pending Tasks:\n{pending_text}")
                
                if missed:
                    missed_text = "\n".join([f"- {t['task']} ({t['date']})" for t in missed[:2]])
                    context_parts.append(f"Missed Tasks:\n{missed_text}")
            
            context = "\n\n".join(context_parts)
            
            # Get personality prompt in the user's language
            personality = get_personality_prompt(boss_type, boss_language)
            
            # Generate AI message using language-aware prompts
            llm = ChatOpenAI(
                model="deepseek-chat",
                temperature=0.7,
                base_url="https://api.deepseek.com",
                api_key=os.getenv("DEEPSEEK_API_KEY")
            )
            
            # Get language-specific prompt
            prompt = get_checkin_ai_prompt(context, personality, boss_language, is_first_ping_today)

            response = llm.invoke([HumanMessage(content=prompt)])
            ai_message = response.content.strip()
            
            # Validate the message isn't too long (WhatsApp has limits)
            if len(ai_message) > 500:
                ai_message = ai_message[:497] + "..."
            
            return ai_message
        
        # If no context, fall back to default messages
        return generate_checkin_message_fallback(boss_type, boss_language)
        
    except Exception as e:
        logger.error(f"Error generating AI check-in message: {e}")
        # Fall back to default messages on any error
        return generate_checkin_message_fallback(boss_type, boss_language)


def generate_checkin_message_fallback(boss_type: str, boss_language: str = "en") -> str:
    """
    Generate a fallback check-in message based on boss type personality and language.
    Used when AI generation fails or no context is available.
    Supports multiple languages.
    
    Args:
        boss_type: The boss type
        boss_language: The language preference (default: "en")
        
    Returns:
        A check-in message string in the specified language
    """
    return get_checkin_message(boss_type, boss_language)


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


async def process_and_send_message(incoming_message: str, sender_number: str, user_id: str):
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
        
        # Process the message through LangGraph agent (now async)
        reply_text = await process_message(incoming_message, user_id=user_id)
        
        # Send response back via Twilio API
        send_whatsapp_message(sender_number, reply_text)
        
        logger.info(f"Successfully processed and sent response to {sender_number}")
        
    except Exception as e:
        logger.error(f"Error in async message processing: {e}", exc_info=True)
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
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks, api_key: str = Depends(verify_api_key)):
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
def read_root(api_key: str = Depends(verify_api_key)):
    """Health check endpoint"""
    return {"status": "WhatsApp chatbot is running", "endpoint": "/webhook"}

@app.get("/tasks/{user_id}")
async def get_tasks_by_user(user_id: str, api_key: str = Depends(verify_api_key)):
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


@app.post("/trigger-checkin")
async def trigger_checkin(background_tasks: BackgroundTasks, api_key: str = Depends(verify_api_key)):
    """
    Trigger check-ins for all users who are due for a check-in.
    This endpoint should be called by a cron job on a regular schedule (e.g., every hour).
    
    The endpoint will:
    1. Query all users whose next_checkin_at is in the past
    2. Send them a check-in message based on their boss type
    3. Update their next_checkin_at based on their boss type interval
    
    Returns:
        JSON response with the number of check-ins triggered
    """
    try:
        # Get current time
        current_time = datetime.now()
        
        # Query users who are due for check-in
        # next_checkin_at <= current_time
        users_due = supabase.table("user_preferences").select(
            "user_id, phone_no, boss_type, boss_language, next_checkin_at, last_checkin_at"
        ).lte("next_checkin_at", current_time.isoformat()).execute()
        
        if not users_due.data or len(users_due.data) == 0:
            return {
                "success": True,
                "message": "No users due for check-in",
                "checkins_triggered": 0,
                "current_time": current_time.isoformat()
            }
        
        checkins_triggered = 0
        checkin_results = []
        
        for user_pref in users_due.data:
            try:
                user_id = user_pref.get("user_id")
                phone_no = user_pref.get("phone_no")
                boss_type = user_pref.get("boss_type", "execution")
                boss_language = user_pref.get("boss_language", "en")
                last_checkin_at = user_pref.get("last_checkin_at")
                
                if not phone_no:
                    logger.warning(f"User {user_id} has no phone number. Skipping check-in.")
                    continue
                
                # Format phone number for WhatsApp
                whatsapp_number = f"whatsapp:+{phone_no}"
                
                # Generate AI-powered check-in message based on user context and language
                # Falls back to default messages if AI generation fails
                checkin_message = await generate_checkin_message_with_context(user_id, boss_type, last_checkin_at, boss_language)
                
                # Send check-in message in background
                background_tasks.add_task(
                    send_whatsapp_message,
                    whatsapp_number,
                    checkin_message
                )
                
                # Calculate next check-in time based on boss type
                interval_hours = get_checkin_interval_hours(boss_type)
                next_checkin = current_time + timedelta(hours=interval_hours)
                
                # Update user preferences with new next_checkin_at and last_checkin_at
                supabase.table("user_preferences").update({
                    "next_checkin_at": next_checkin.isoformat(),
                    "last_checkin_at": current_time.isoformat()
                }).eq("user_id", user_id).execute()
                
                checkins_triggered += 1
                checkin_results.append({
                    "user_id": user_id,
                    "phone_no": phone_no,
                    "boss_type": boss_type,
                    "next_checkin_at": next_checkin.isoformat(),
                    "interval_hours": interval_hours
                })
                
                logger.info(f"Check-in triggered for user {user_id} (boss_type: {boss_type}). Next check-in: {next_checkin}")
                
            except Exception as user_error:
                logger.error(f"Error processing check-in for user {user_pref.get('user_id')}: {user_error}")
                continue
        
        return {
            "success": True,
            "message": f"Check-ins triggered for {checkins_triggered} user(s)",
            "checkins_triggered": checkins_triggered,
            "current_time": current_time.isoformat(),
            "results": checkin_results
        }
        
    except Exception as e:
        logger.error(f"Error triggering check-ins: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error triggering check-ins: {str(e)}"
        )