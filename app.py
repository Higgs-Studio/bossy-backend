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
import secrets
import string
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
    get_language_name,
    get_first_message_greeting,
    get_boss_name,
    get_language_selection_message,
    parse_language_selection
)

load_dotenv()

app = FastAPI()

# Initialize Twilio client
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE = os.getenv("TWILIO_PHONE_NUMBER")

client = Client(ACCOUNT_SID, AUTH_TOKEN)

# Initialize Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)

# API Key security
API_KEY_NAME = "X-API-Key"
MY_API_SECRET = os.getenv("MY_API_SECRET")
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

logger = logging.getLogger(__name__)


# ============================================================================
# Shared Helpers
# ============================================================================

def get_llm(temperature: float = 0.7) -> ChatOpenAI:
    """Create a DeepSeek LLM instance with standard configuration."""
    return ChatOpenAI(
        model="deepseek-chat",
        temperature=temperature,
        base_url="https://api.deepseek.com",
        api_key=os.getenv("DEEPSEEK_API_KEY"),
    )


def get_active_goal_ids(user_id: str) -> List[str]:
    """Return a list of active goal IDs for a user."""
    result = supabase.table("goals").select("id").eq("user_id", user_id).eq("status", "active").execute()
    return [g["id"] for g in (result.data or [])]


def get_user_pref(user_id: str, field: str, default: Any = None) -> Any:
    """Read a single field from user_preferences."""
    try:
        result = supabase.table("user_preferences").select(field).eq("user_id", user_id).execute()
        if result.data and len(result.data) > 0:
            return result.data[0].get(field, default)
    except Exception:
        pass
    return default


def check_and_complete_goal(goal_id: str) -> bool:
    """If all tasks in a goal are done, mark the goal as completed. Returns True if completed."""
    try:
        all_tasks_result = supabase.table("daily_tasks").select("id, status").eq("goal_id", goal_id).execute()
        all_tasks = all_tasks_result.data or []
        if all_tasks and all(t.get("status") == "done" for t in all_tasks):
            supabase.table("goals").update({"status": "completed"}).eq("id", goal_id).execute()
            logger.info(f"Goal {goal_id} marked as completed - all tasks are done")
            return True
    except Exception as e:
        logger.warning(f"Could not check goal completion status: {e}")
    return False


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

def check_free_tier_goal_limit(user_id: str) -> dict:
    """
    Check if a free tier user has reached the maximum goal limit (5 active goals).
    
    Args:
        user_id: The user ID (UUID) to check
        
    Returns:
        A dict with 'allowed' (bool) and optionally 'error' (str) if not allowed
    """
    try:
        # Get subscription_status from user_preferences
        pref_result = supabase.table("user_preferences").select("subscription_status").eq("user_id", user_id).execute()
        
        subscription_status = "free"  # Default to free if not found
        if pref_result.data and len(pref_result.data) > 0:
            subscription_status = pref_result.data[0].get("subscription_status", "free")
        
        # Only check limit for free tier users
        if subscription_status != "free":
            return {"allowed": True}
        
        # Count active goals for the user
        goals_result = supabase.table("goals").select("id").eq("user_id", user_id).eq("status", "active").execute()
        active_goal_count = len(goals_result.data) if goals_result.data else 0
        
        if active_goal_count >= 5:
            return {
                "allowed": False,
                "error": f"You have reached the maximum limit of 5 active goals on the free plan. Please complete or remove an existing goal before creating a new one, or upgrade to a premium plan for unlimited goals."
            }
        
        return {"allowed": True}
    except Exception as e:
        logger.error(f"Error checking free tier goal limit: {e}")
        # Allow goal creation if check fails to avoid blocking users
        return {"allowed": True}


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
    Find similar existing incomplete tasks for a user.
    
    Args:
        task_text: The task text to check
        user_id: The user ID
        task_date: Optional date to filter tasks (YYYY-MM-DD)
        threshold: Similarity threshold (0.0 to 1.0), default 0.7
        
    Returns:
        List of similar tasks with similarity scores
    """
    try:
        goal_ids = get_active_goal_ids(user_id)
        if not goal_ids:
            return []
        
        tasks_query = supabase.table("daily_tasks").select("id, task_text, task_date, goal_id").in_("goal_id", goal_ids).neq("status", "done")
        
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
        end_date: End date in YYYY-MM-DD format (default: 1 days from start)
        boss_type: Boss type - "execution", "supportive", "mentor", or "drill-sergeant" (default: from user_preferences)
        
    Returns:
        A JSON string containing the goal and tasks created
    """
    try:
        # Check free tier goal limit
        limit_check = check_free_tier_goal_limit(user_id)
        if not limit_check["allowed"]:
            return json.dumps({
                "success": False,
                "error": limit_check["error"]
            })
        
        if not boss_type:
            boss_type = get_user_pref(user_id, "boss_type", "execution")
        
        if not start_date:
            start_date = date.today().isoformat()
        if not end_date:
            start = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
            end_date = (start + timedelta(days=1)).isoformat()
        
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
        
        llm = get_llm()
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
        
        tasks = json.loads(tasks_json)
        
        created_tasks = []
        for task in tasks:
            task_data = {
                "goal_id": goal_id,
                "task_date": task.get("task_date", start_date),
                "task_text": task.get("task_text", "Untitled Task"),
                "status": "todo",
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
        if not goal_id:
            goal_result = supabase.table("goals").select("id").eq("user_id", user_id).eq("status", "active").order("created_at", desc=True).limit(1).execute()
            if not goal_result.data or len(goal_result.data) == 0:
                return json.dumps({
                    "success": False,
                    "error": "No active goal found. Please create a goal first."
                })
            goal_id = goal_result.data[0]["id"]
        
        if not task_date:
            task_date = date.today().isoformat()
        
        existing_tasks_result = supabase.table("daily_tasks").select("id, task_text, task_date").eq("task_date", task_date).in_("goal_id", [goal_id]).execute()
        existing_tasks = existing_tasks_result.data if existing_tasks_result.data else []
        
        all_active_goal_ids = get_active_goal_ids(user_id)
        
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
            if existing_text and (task_lower in existing_text or existing_text in task_lower):
                if len(task_lower) > 10 and len(existing_text) > 10:  # Only flag if both are substantial
                    warnings.append(f"Similar task already exists on {task_date}: '{existing_task.get('task_text', '')}'")
        
        task_data = {
            "goal_id": goal_id,
            "task_date": task_date,
            "task_text": task_text,
            "status": "todo",
        }
        
        result = supabase.table("daily_tasks").insert(task_data).execute()
        
        response_data = {
            "success": True,
            "message": f"Task '{task_text}' created successfully",
            "task": result.data[0] if result.data else task_data
        }
        
        if warnings or conflicts:
            response_data["conflict_info"] = {
                "warnings": warnings,
                "conflicts": conflicts,
                "tasks_on_date": len(all_tasks_on_date) + 1
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
        
        # Get check_ins for these tasks to show check-in history
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
            # Status is now stored in daily_tasks table, default to "todo" if not set
            if "status" not in task_with_status or task_with_status["status"] is None:
                task_with_status["status"] = "todo"
            # Include check-in info if available (for backward compatibility)
            if task["id"] in check_ins_by_task:
                task_with_status["check_in"] = check_ins_by_task[task["id"]]
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
        end_date: End date in YYYY-MM-DD format (default: 1 days from start)
        boss_type: Boss type (optional)
        
    Returns:
        A JSON string containing the goal and tasks created
    """
    try:
        # Check free tier goal limit
        limit_check = check_free_tier_goal_limit(user_id)
        if not limit_check["allowed"]:
            return json.dumps({
                "success": False,
                "error": limit_check["error"]
            })
        
        if not boss_type:
            boss_type = get_user_pref(user_id, "boss_type", "execution")
        
        if not start_date:
            start_date = date.today().isoformat()
        if not end_date:
            start = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
            end_date = (start + timedelta(days=1)).isoformat()
        
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
        
        llm = get_llm()
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
        
        tasks = json.loads(tasks_json)
        
        created_tasks = []
        for task in tasks:
            task_data = {
                "goal_id": goal_id,
                "task_date": task.get("task_date", start_date),
                "task_text": task.get("task_text", "Untitled Task"),
                "status": "todo",
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
        if not goal_id:
            goal_result = supabase.table("goals").select("id").eq("user_id", user_id).eq("status", "active").order("created_at", desc=True).limit(1).execute()
            if not goal_result.data or len(goal_result.data) == 0:
                return json.dumps({
                    "success": False,
                    "error": "No active goal found. Please create a goal first."
                })
            goal_id = goal_result.data[0]["id"]
        
        if not task_date:
            task_date = date.today().isoformat()
        
        task_data = {
            "goal_id": goal_id,
            "task_date": task_date,
            "task_text": task_text,
            "status": "todo",
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


@tool
def find_task_by_description(user_id: str, task_description: str, task_date: str = None) -> str:
    """
    Find a task by searching for similar text in the task description. This helps identify the correct task_id
    when a user refers to a task by its description rather than ID.
    
    Args:
        user_id: The user ID (UUID) who owns the task
        task_description: Keywords or description to search for in tasks
        task_date: Optional date in YYYY-MM-DD format to narrow the search
        
    Returns:
        A JSON string with matching tasks
    """
    try:
        # Get all active goals for the user
        goals_result = supabase.table("goals").select("id, title").eq("user_id", user_id).eq("status", "active").execute()
        goal_ids = [g["id"] for g in (goals_result.data if goals_result.data else [])]
        
        if not goal_ids:
            return json.dumps({
                "success": True,
                "count": 0,
                "tasks": [],
                "message": "No active goals found"
            })
        
        # Get tasks for these goals
        tasks_query = supabase.table("daily_tasks").select("id, task_text, task_date, status, goal_id").in_("goal_id", goal_ids)
        if task_date:
            tasks_query = tasks_query.eq("task_date", task_date)
        
        tasks_result = tasks_query.order("task_date", desc=True).limit(20).execute()
        all_tasks = tasks_result.data if tasks_result.data else []
        
        # Find similar tasks using fuzzy matching
        search_lower = task_description.lower().strip()
        matching_tasks = []
        
        for task in all_tasks:
            task_text_lower = task.get("task_text", "").lower()
            # Calculate simple similarity - check if search terms appear in task text
            if search_lower in task_text_lower or task_text_lower in search_lower:
                similarity = calculate_similarity(search_lower, task_text_lower)
                matching_tasks.append({
                    "task": task,
                    "similarity": similarity
                })
        
        # Sort by similarity
        matching_tasks.sort(key=lambda x: x["similarity"], reverse=True)
        
        # Return top 5 matches
        top_matches = matching_tasks[:5]
        
        return json.dumps({
            "success": True,
            "count": len(top_matches),
            "tasks": [m["task"] for m in top_matches],
            "search_term": task_description,
            "message": f"Found {len(top_matches)} matching task(s)"
        })
        
    except Exception as e:
        logger.error(f"Error finding task: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


@tool
def update_task_status(task_id: str, user_id: str, status: str) -> str:
    """
    Update the status of a task. This allows tracking task progress.
    
    Args:
        task_id: The task ID (UUID) to update
        user_id: The user ID (UUID) who owns this task (for verification)
        status: New status - "todo", "in_progress", or "done"
        
    Returns:
        A JSON string with the update result
    """
    try:
        # Validate status
        valid_statuses = ["todo", "in_progress", "done"]
        if status not in valid_statuses:
            return json.dumps({
                "success": False,
                "error": f"Invalid status: {status}. Must be one of: {', '.join(valid_statuses)}"
            })
        
        # First verify the task belongs to the user by checking through the goal
        task_result = supabase.table("daily_tasks").select("id, task_text, task_date, goal_id").eq("id", task_id).execute()
        
        if not task_result.data or len(task_result.data) == 0:
            return json.dumps({
                "success": False,
                "error": "Task not found"
            })
        
        task = task_result.data[0]
        task_text = task.get("task_text", "Unknown")
        task_date = task.get("task_date")
        goal_id = task.get("goal_id")
        
        # Verify the goal belongs to the user
        goal_result = supabase.table("goals").select("id, user_id, title").eq("id", goal_id).eq("user_id", user_id).execute()
        
        if not goal_result.data or len(goal_result.data) == 0:
            return json.dumps({
                "success": False,
                "error": "Task not found or you don't have permission to update it"
            })
        
        goal_title = goal_result.data[0].get("title", "Unknown")
        
        # Update the task status
        update_result = supabase.table("daily_tasks").update({
            "status": status
        }).eq("id", task_id).execute()
        
        if status == "done":
            now_iso = datetime.now().isoformat()
            try:
                existing_checkin = supabase.table("check_ins").select("id").eq("task_id", task_id).execute()
                if existing_checkin.data and len(existing_checkin.data) > 0:
                    supabase.table("check_ins").update({
                        "status": "done",
                        "checked_at": now_iso,
                    }).eq("task_id", task_id).execute()
                else:
                    supabase.table("check_ins").insert({
                        "task_id": task_id,
                        "user_id": user_id,
                        "status": "done",
                        "checked_at": now_iso,
                    }).execute()
            except Exception as checkin_error:
                logger.warning(f"Could not update check-in record: {checkin_error}")
            
            check_and_complete_goal(goal_id)
        
        return json.dumps({
            "success": True,
            "message": f"Task '{task_text}' status updated to '{status}'",
            "task": {
                "id": task_id,
                "task_text": task_text,
                "task_date": task_date,
                "status": status,
                "goal": goal_title
            }
        })
        
    except Exception as e:
        logger.error(f"Error updating task status: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


@tool
def update_goal_status(goal_id: str, user_id: str, status: str) -> str:
    """
    Update the status of a goal. This allows tracking goal progress and marking goals as completed or abandoned.
    
    Args:
        goal_id: The goal ID (UUID) to update
        user_id: The user ID (UUID) who owns this goal (for verification)
        status: New status - "active", "completed", or "abandoned"
        
    Returns:
        A JSON string with the update result
    """
    try:
        # Validate status
        valid_statuses = ["active", "completed", "abandoned"]
        if status not in valid_statuses:
            return json.dumps({
                "success": False,
                "error": f"Invalid status: {status}. Must be one of: {', '.join(valid_statuses)}"
            })
        
        # First verify the goal belongs to the user
        goal_result = supabase.table("goals").select("id, title, user_id, intensity, start_date, end_date").eq("id", goal_id).eq("user_id", user_id).execute()
        
        if not goal_result.data or len(goal_result.data) == 0:
            return json.dumps({
                "success": False,
                "error": "Goal not found or you don't have permission to update it"
            })
        
        goal = goal_result.data[0]
        goal_title = goal.get("title", "Unknown")
        
        # Update the goal status
        update_result = supabase.table("goals").update({
            "status": status
        }).eq("id", goal_id).execute()
        
        # Get count of associated tasks
        tasks_result = supabase.table("daily_tasks").select("id, status").eq("goal_id", goal_id).execute()
        tasks = tasks_result.data if tasks_result.data else []
        total_tasks = len(tasks)
        completed_tasks = len([t for t in tasks if t.get("status") == "done"])
        
        message = f"Goal '{goal_title}' status updated to '{status}'"
        if total_tasks > 0:
            message += f" ({completed_tasks}/{total_tasks} tasks completed)"
        
        return json.dumps({
            "success": True,
            "message": message,
            "goal": {
                "id": goal_id,
                "title": goal_title,
                "status": status,
                "intensity": goal.get("intensity"),
                "start_date": goal.get("start_date"),
                "end_date": goal.get("end_date"),
                "total_tasks": total_tasks,
                "completed_tasks": completed_tasks
            }
        })
        
    except Exception as e:
        logger.error(f"Error updating goal status: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


@tool
def get_incomplete_tasks_prioritized(user_id: str, scope: str = "today") -> str:
    """
    Get incomplete tasks for user, prioritized by deadline proximity, intensity, and task size.
    Use this when user asks "What should I do now?", "What's my plan for today/this week?", etc.
    
    Args:
        user_id: The user ID (UUID)
        scope: "today" for today's focus, "week" for weekly plan, "all" for all incomplete
        
    Returns:
        A JSON string with prioritized incomplete tasks and recommendations
    """
    try:
        today = date.today()
        
        goals_result = supabase.table("goals").select("id, title, intensity, start_date, end_date, status").eq("user_id", user_id).eq("status", "active").execute()
        goals = goals_result.data if goals_result.data else []
        
        if not goals:
            return json.dumps({
                "success": True,
                "message": "No active goals found",
                "incomplete_tasks": [],
                "expired_tasks": [],
                "today_tasks": [],
                "upcoming_tasks": [],
                "recommendation": None
            })
        
        goal_ids = [g["id"] for g in goals]
        goal_map = {g["id"]: g for g in goals}
        
        # Get all tasks that are not done
        tasks_result = supabase.table("daily_tasks").select("id, task_text, task_date, status, goal_id").in_("goal_id", goal_ids).neq("status", "done").execute()
        tasks = tasks_result.data if tasks_result.data else []
        
        # Categorize tasks
        expired_tasks = []  # Past due date, not completed
        today_tasks = []    # Due today
        upcoming_tasks = [] # Future tasks
        
        for task in tasks:
            task_date_str = task.get("task_date")
            if not task_date_str:
                continue
                
            task_date_obj = date.fromisoformat(task_date_str)
            goal = goal_map.get(task.get("goal_id"), {})
            
            # Add goal info to task
            task["goal_title"] = goal.get("title", "Unknown")
            task["goal_intensity"] = goal.get("intensity", "medium")
            task["goal_end_date"] = goal.get("end_date")
            
            # Calculate priority score (higher = more urgent)
            priority_score = 0
            
            # Intensity factor
            intensity_scores = {"high": 30, "medium": 20, "low": 10}
            priority_score += intensity_scores.get(goal.get("intensity", "medium"), 20)
            
            # Deadline proximity factor (closer = higher score)
            days_until = (task_date_obj - today).days
            if days_until < 0:
                priority_score += 50  # Expired tasks get highest priority
            elif days_until == 0:
                priority_score += 40
            elif days_until <= 3:
                priority_score += 30
            elif days_until <= 7:
                priority_score += 20
            else:
                priority_score += 10
            
            task["priority_score"] = priority_score
            task["days_until_due"] = days_until
            
            # Categorize
            if task_date_obj < today:
                expired_tasks.append(task)
            elif task_date_obj == today:
                today_tasks.append(task)
            else:
                upcoming_tasks.append(task)
        
        # Sort by priority score (descending)
        expired_tasks.sort(key=lambda x: x["priority_score"], reverse=True)
        today_tasks.sort(key=lambda x: x["priority_score"], reverse=True)
        upcoming_tasks.sort(key=lambda x: x["priority_score"], reverse=True)
        
        # Build response based on scope
        if scope == "today":
            focus_tasks = expired_tasks + today_tasks
        elif scope == "week":
            week_end = today + timedelta(days=7)
            focus_tasks = expired_tasks + today_tasks + [t for t in upcoming_tasks if date.fromisoformat(t["task_date"]) <= week_end]
        else:
            focus_tasks = expired_tasks + today_tasks + upcoming_tasks
        
        # Generate recommendation (highest priority task)
        recommendation = None
        if focus_tasks:
            top_task = focus_tasks[0]
            recommendation = {
                "task": top_task["task_text"],
                "task_id": top_task["id"],
                "goal": top_task["goal_title"],
                "reason": "Expired task needs immediate attention" if top_task["days_until_due"] < 0 else 
                         "Due today with high priority" if top_task["days_until_due"] == 0 else
                         f"Due in {top_task['days_until_due']} days"
            }
        
        return json.dumps({
            "success": True,
            "scope": scope,
            "today_date": today.isoformat(),
            "expired_tasks": expired_tasks[:5],  # Limit to 5
            "today_tasks": today_tasks[:5],
            "upcoming_tasks": upcoming_tasks[:5] if scope != "today" else [],
            "total_incomplete": len(focus_tasks),
            "recommendation": recommendation
        })
        
    except Exception as e:
        logger.error(f"Error getting prioritized tasks: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


@tool
def create_goal_with_task(user_id: str, task_text: str, task_date: str, goal_name: str = None, intensity: str = "medium") -> str:
    """
    Create a goal AND a task together. Use this for any user request that could be a task or goal.
    The goal name should be a generalized version of the task.
    
    IMPORTANT: Always use this tool instead of separate goal/task creation.
    Never create a goal without a task. Always create the task first conceptually, then generalize for goal.
    
    Args:
        user_id: The user ID (UUID)
        task_text: The specific task description (what exactly needs to be done)
        task_date: The task date in YYYY-MM-DD format
        goal_name: Optional generalized goal name (if not provided, will be derived from task)
        intensity: Goal intensity - "low", "medium", or "high" (default: "medium")
                  Use "high" for: events with people, appointments, time-sensitive items
        
    Returns:
        A JSON string with created goal and task
    """
    try:
        # Check free tier goal limit
        limit_check = check_free_tier_goal_limit(user_id)
        if not limit_check["allowed"]:
            return json.dumps({
                "success": False,
                "error": limit_check["error"]
            })
        
        # Derive goal name from task if not provided
        if not goal_name:
            # Simple generalization - remove date-specific words, make it broader
            goal_name = task_text
        
        start_date = task_date
        end_date = task_date
        
        boss_type = get_user_pref(user_id, "boss_type", "execution")
        
        # Create the goal
        goal_data = {
            "user_id": user_id,
            "title": goal_name,
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
        
        task_data = {
            "goal_id": goal_id,
            "task_date": task_date,
            "task_text": task_text,
            "status": "todo",
        }
        
        task_result = supabase.table("daily_tasks").insert(task_data).execute()
        
        return json.dumps({
            "success": True,
            "message": f"Created goal '{goal_name}' with task '{task_text}' for {task_date}",
            "goal": goal_result.data[0],
            "task": task_result.data[0] if task_result.data else task_data,
            "intensity": intensity
        })
        
    except Exception as e:
        logger.error(f"Error creating goal with task: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


def ordinal(n):
    """Convert number to ordinal string (1st, 2nd, 3rd, etc.)"""
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"


@tool
def create_recurring_tasks(
    user_id: str, 
    task_text: str, 
    start_date: str, 
    end_date: str, 
    goal_name: str = None, 
    intensity: str = "medium",
    recurrence_type: str = "daily",
    recurrence_interval: int = 1,
    weekdays: list = None,
    day_of_month: int = None
) -> str:
    """
    Create a goal with recurring tasks from start_date to end_date with flexible recurrence patterns.
    
    Args:
        user_id: The user ID (UUID)
        task_text: The task description to repeat
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format (inclusive)
        goal_name: Optional goal name (will be generalized from task if not provided)
        intensity: Goal intensity - "low", "medium", or "high"
        recurrence_type: Type of recurrence
            - "daily": Every day (default)
            - "interval": Every N days (use recurrence_interval to specify N)
            - "weekly": Specific days of the week (use weekdays parameter)
            - "biweekly": Every 2 weeks (14 days)
            - "monthly": Specific day of each month (use day_of_month parameter)
            - "yearly": Same date every year
        recurrence_interval: For "interval" type, repeat every N days (default 1)
        weekdays: For "weekly" type, list of weekday numbers (0=Monday, 1=Tuesday, ..., 6=Sunday)
                  Examples: [5] for every Saturday, [0,2] for every Monday and Wednesday
        day_of_month: For "monthly" type, day of month (1-31). If not provided, uses start_date day.
                      If day doesn't exist in a month (e.g., 31st in February), that month is skipped.
    
    Examples:
        - Every day: recurrence_type="daily"
        - Every 3 days: recurrence_type="interval", recurrence_interval=3
        - Every Saturday: recurrence_type="weekly", weekdays=[5]
        - Every Monday and Friday: recurrence_type="weekly", weekdays=[0,4]
        - Biweekly: recurrence_type="biweekly"
        - Monthly on 15th: recurrence_type="monthly", day_of_month=15
        - Yearly: recurrence_type="yearly"
        
    Returns:
        A JSON string with created goal and all tasks
    """
    try:
        limit_check = check_free_tier_goal_limit(user_id)
        if not limit_check["allowed"]:
            return json.dumps({
                "success": False,
                "error": limit_check["error"]
            })
        
        valid_types = ["daily", "interval", "weekly", "biweekly", "monthly", "yearly"]
        if recurrence_type not in valid_types:
            return json.dumps({
                "success": False,
                "error": f"Invalid recurrence_type: {recurrence_type}. Must be one of: {', '.join(valid_types)}"
            })
        
        if recurrence_type == "weekly" and not weekdays:
            return json.dumps({
                "success": False,
                "error": "weekdays parameter is required when recurrence_type is 'weekly'"
            })
        
        if recurrence_type == "weekly" and weekdays:
            if not all(isinstance(d, int) and 0 <= d <= 6 for d in weekdays):
                return json.dumps({
                    "success": False,
                    "error": "weekdays must be a list of integers between 0 (Monday) and 6 (Sunday)"
                })
        
        if recurrence_interval < 1:
            return json.dumps({
                "success": False,
                "error": "recurrence_interval must be at least 1"
            })
        
        # For monthly recurrence, validate day_of_month
        if recurrence_type == "monthly":
            if day_of_month is None:
                # Use start date's day if not specified
                day_of_month = date.fromisoformat(start_date).day
            elif not isinstance(day_of_month, int) or not (1 <= day_of_month <= 31):
                return json.dumps({
                    "success": False,
                    "error": "day_of_month must be an integer between 1 and 31"
                })
        
        # Generate appropriate goal name if not provided
        if not goal_name:
            if recurrence_type == "daily":
                goal_name = f"Daily: {task_text}"
            elif recurrence_type == "interval":
                goal_name = f"Every {recurrence_interval} days: {task_text}"
            elif recurrence_type == "biweekly":
                goal_name = f"Biweekly: {task_text}"
            elif recurrence_type == "monthly":
                if day_of_month is None:
                    day_of_month = date.fromisoformat(start_date).day
                goal_name = f"Monthly ({ordinal(day_of_month)}): {task_text}"
            elif recurrence_type == "yearly":
                goal_name = f"Yearly: {task_text}"
            else:  # weekly
                weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                day_names = [weekday_names[d] for d in sorted(weekdays)]
                if len(day_names) == 1:
                    goal_name = f"Every {day_names[0]}: {task_text}"
                else:
                    goal_name = f"Every {', '.join(day_names)}: {task_text}"
        
        boss_type = get_user_pref(user_id, "boss_type", "execution")
        
        goal_data = {
            "user_id": user_id,
            "title": goal_name,
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
        
        # Create tasks based on recurrence pattern
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        
        created_tasks = []
        current_date = start
        
        def _insert_recurring_task(task_date_iso: str) -> None:
            task_data = {
                "goal_id": goal_id,
                "task_date": task_date_iso,
                "task_text": task_text,
                "status": "todo",
            }
            task_result = supabase.table("daily_tasks").insert(task_data).execute()
            if task_result.data:
                created_tasks.append(task_result.data[0])
        
        if recurrence_type == "daily":
            while current_date <= end:
                _insert_recurring_task(current_date.isoformat())
                current_date += timedelta(days=1)
        
        elif recurrence_type == "interval":
            while current_date <= end:
                _insert_recurring_task(current_date.isoformat())
                current_date += timedelta(days=recurrence_interval)
        
        elif recurrence_type == "biweekly":
            while current_date <= end:
                _insert_recurring_task(current_date.isoformat())
                current_date += timedelta(days=14)
        
        elif recurrence_type == "weekly":
            while current_date <= end:
                if current_date.weekday() in weekdays:
                    _insert_recurring_task(current_date.isoformat())
                current_date += timedelta(days=1)
        
        elif recurrence_type == "monthly":
            if day_of_month is None:
                day_of_month = start.day
            
            if start.day <= day_of_month:
                try:
                    current_date = start.replace(day=day_of_month)
                except ValueError:
                    if start.month == 12:
                        current_date = date(start.year + 1, 1, 1)
                    else:
                        current_date = date(start.year, start.month + 1, 1)
            else:
                if start.month == 12:
                    current_date = date(start.year + 1, 1, 1)
                else:
                    current_date = date(start.year, start.month + 1, 1)
            
            while current_date <= end:
                try:
                    task_date_obj = current_date.replace(day=day_of_month)
                    if task_date_obj <= end:
                        _insert_recurring_task(task_date_obj.isoformat())
                except ValueError:
                    pass
                
                if current_date.month == 12:
                    current_date = date(current_date.year + 1, 1, 1)
                else:
                    current_date = date(current_date.year, current_date.month + 1, 1)
        
        elif recurrence_type == "yearly":
            year = start.year
            month = start.month
            day = start.day
            
            while True:
                try:
                    current_date = date(year, month, day)
                    if current_date > end:
                        break
                    if current_date >= start:
                        _insert_recurring_task(current_date.isoformat())
                except ValueError:
                    pass
                year += 1
        
        # Generate descriptive message
        if recurrence_type == "daily":
            pattern_desc = "daily"
        elif recurrence_type == "interval":
            pattern_desc = f"every {recurrence_interval} days"
        elif recurrence_type == "biweekly":
            pattern_desc = "biweekly (every 14 days)"
        elif recurrence_type == "monthly":
            if day_of_month is None:
                day_of_month = date.fromisoformat(start_date).day
            pattern_desc = f"monthly on the {ordinal(day_of_month)}"
        elif recurrence_type == "yearly":
            start_dt = date.fromisoformat(start_date)
            month_names = ["January", "February", "March", "April", "May", "June", 
                          "July", "August", "September", "October", "November", "December"]
            pattern_desc = f"yearly on {month_names[start_dt.month - 1]} {ordinal(start_dt.day)}"
        else:  # weekly
            weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            day_names = [weekday_names[d] for d in sorted(weekdays)]
            pattern_desc = f"every {', '.join(day_names)}"
        
        return json.dumps({
            "success": True,
            "message": f"Created goal '{goal_name}' with {len(created_tasks)} tasks ({pattern_desc}) from {start_date} to {end_date}",
            "goal": goal_result.data[0],
            "tasks_created": len(created_tasks),
            "recurrence_pattern": pattern_desc,
            "sample_tasks": created_tasks[:3]  # Show first 3 as sample
        })
        
    except Exception as e:
        logger.error(f"Error creating recurring tasks: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


@tool
def mark_task_done_by_description(user_id: str, task_description: str) -> str:
    """
    Find and mark a task as complete based on description matching.
    Use this when user says "I have done [something]" or "I finished [something]".
    Searches incomplete tasks to find the closest match.
    
    Args:
        user_id: The user ID (UUID)
        task_description: Keywords or description of what was completed
        
    Returns:
        A JSON string with the result (task marked done or clarification needed)
    """
    try:
        goals_result = supabase.table("goals").select("id, title").eq("user_id", user_id).eq("status", "active").execute()
        goal_ids = [g["id"] for g in (goals_result.data or [])]
        goal_map = {g["id"]: g["title"] for g in (goals_result.data or [])}
        
        if not goal_ids:
            return json.dumps({
                "success": False,
                "error": "No active goals found",
                "requires_clarification": False
            })
        
        tasks_result = supabase.table("daily_tasks").select("id, task_text, task_date, status, goal_id").in_("goal_id", goal_ids).neq("status", "done").execute()
        tasks = tasks_result.data if tasks_result.data else []
        
        if not tasks:
            return json.dumps({
                "success": False,
                "error": "No incomplete tasks found",
                "requires_clarification": False
            })
        
        search_lower = task_description.lower().strip()
        matches = []
        
        for task in tasks:
            task_text_lower = task.get("task_text", "").lower()
            similarity = calculate_similarity(search_lower, task_text_lower)
            keywords_match = any(word in task_text_lower for word in search_lower.split() if len(word) > 2)
            
            if similarity >= 0.4 or keywords_match:
                matches.append({
                    "task": task,
                    "similarity": similarity,
                    "goal_title": goal_map.get(task.get("goal_id"), "Unknown")
                })
        
        matches.sort(key=lambda x: x["similarity"], reverse=True)
        
        if not matches:
            return json.dumps({
                "success": False,
                "error": f"No matching incomplete tasks found for '{task_description}'",
                "requires_clarification": True,
                "message": "Which task did you complete? I couldn't find a matching incomplete task."
            })
        
        if len(matches) == 1 or (matches[0]["similarity"] > 0.7):
            best_match = matches[0]["task"]
            task_goal_id = best_match.get("goal_id")
            
            supabase.table("daily_tasks").update({"status": "done"}).eq("id", best_match["id"]).execute()
            
            try:
                supabase.table("check_ins").insert({
                    "task_id": best_match["id"],
                    "user_id": user_id,
                    "status": "done",
                    "checked_at": datetime.now().isoformat(),
                }).execute()
            except Exception:
                pass
            
            goal_completed = check_and_complete_goal(task_goal_id)
            
            message = f"Marked '{best_match['task_text']}' as done"
            if goal_completed:
                message += f". Goal '{matches[0]['goal_title']}' is now completed!"
            
            return json.dumps({
                "success": True,
                "message": message,
                "task": best_match,
                "goal": matches[0]["goal_title"],
                "goal_completed": goal_completed
            })
        else:
            # Multiple possible matches - ask for clarification
            options = []
            for i, m in enumerate(matches[:5], 1):
                options.append({
                    "number": i,
                    "task_id": m["task"]["id"],
                    "task_text": m["task"]["task_text"],
                    "task_date": m["task"]["task_date"],
                    "goal": m["goal_title"]
                })
            
            return json.dumps({
                "success": False,
                "requires_clarification": True,
                "message": "I found multiple possible tasks. Which one did you complete?",
                "options": options
            })
        
    except Exception as e:
        logger.error(f"Error marking task done: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


@tool
def reschedule_task_occurrence(
    user_id: str,
    task_description: str,
    original_date: str,
    new_date: str
) -> str:
    """
    Reschedule a specific occurrence of a task in a recurring goal to a different date.
    Use this when user wants to move a single task instance due to a conflict.
    
    Args:
        user_id: The user ID (UUID)
        task_description: Description or keywords to identify the task
        original_date: The original date of the task to reschedule (YYYY-MM-DD format)
        new_date: The new date to move the task to (YYYY-MM-DD format)
        
    Examples:
        - "Move my Monday gym session to Tuesday this week"
        - "Reschedule the team meeting on Jan 15 to Jan 16"
        - "Change my dentist appointment from Feb 3 to Feb 10"
        
    Returns:
        A JSON string with the result of the reschedule operation
    """
    try:
        # Validate dates
        try:
            orig_date_obj = date.fromisoformat(original_date)
            new_date_obj = date.fromisoformat(new_date)
        except ValueError as e:
            return json.dumps({
                "success": False,
                "error": f"Invalid date format: {str(e)}. Use YYYY-MM-DD format."
            })
        
        # Get all active goals for the user
        goals_result = supabase.table("goals").select("id, title").eq("user_id", user_id).eq("status", "active").execute()
        goal_ids = [g["id"] for g in (goals_result.data if goals_result.data else [])]
        goal_map = {g["id"]: g["title"] for g in (goals_result.data if goals_result.data else [])}
        
        if not goal_ids:
            return json.dumps({
                "success": False,
                "error": "No active goals found"
            })
        
        # Find the task on the original date matching the description
        tasks_result = supabase.table("daily_tasks").select("id, task_text, task_date, status, goal_id").in_("goal_id", goal_ids).eq("task_date", original_date).execute()
        tasks = tasks_result.data if tasks_result.data else []
        
        if not tasks:
            return json.dumps({
                "success": False,
                "error": f"No tasks found on {original_date}",
                "suggestion": f"Please check the date. You can say 'what are my tasks on {original_date}' to see what's scheduled."
            })
        
        # Find matching tasks using similarity
        search_lower = task_description.lower().strip()
        matches = []
        
        for task in tasks:
            task_text_lower = task.get("task_text", "").lower()
            similarity = calculate_similarity(search_lower, task_text_lower)
            
            # Also check for keyword matches
            keywords_match = any(word in task_text_lower for word in search_lower.split() if len(word) > 2)
            
            if similarity >= 0.4 or keywords_match:
                matches.append({
                    "task": task,
                    "similarity": similarity,
                    "goal_title": goal_map.get(task.get("goal_id"), "Unknown")
                })
        
        # Sort by similarity
        matches.sort(key=lambda x: x["similarity"], reverse=True)
        
        if not matches:
            return json.dumps({
                "success": False,
                "error": f"No matching tasks found for '{task_description}' on {original_date}",
                "available_tasks": [{"task_text": t["task_text"], "goal": goal_map.get(t["goal_id"], "Unknown")} for t in tasks],
                "suggestion": "Please specify which task you want to reschedule from the list above."
            })
        
        # Check if there's already a task with the same description on the new date
        new_date_tasks = supabase.table("daily_tasks").select("id, task_text, task_date").in_("goal_id", goal_ids).eq("task_date", new_date).execute()
        new_date_tasks_list = new_date_tasks.data if new_date_tasks.data else []
        
        conflict_found = False
        for ndt in new_date_tasks_list:
            if ndt.get("task_text", "").lower() == matches[0]["task"]["task_text"].lower():
                conflict_found = True
                break
        
        if conflict_found:
            return json.dumps({
                "success": False,
                "error": f"A task with the same description already exists on {new_date}",
                "suggestion": f"Did you mean to mark the original task on {original_date} as done instead?"
            })
        
        if len(matches) == 1 or matches[0]["similarity"] > 0.7:
            # Clear match - reschedule it
            best_match = matches[0]["task"]
            
            # Update task date
            update_result = supabase.table("daily_tasks").update({
                "task_date": new_date
            }).eq("id", best_match["id"]).execute()
            
            if not update_result.data:
                return json.dumps({
                    "success": False,
                    "error": "Failed to update task date"
                })
            
            # Format dates nicely for response
            orig_weekday = orig_date_obj.strftime("%A, %B %d")
            new_weekday = new_date_obj.strftime("%A, %B %d")
            
            return json.dumps({
                "success": True,
                "message": f"Rescheduled '{best_match['task_text']}' from {orig_weekday} to {new_weekday}",
                "task": update_result.data[0],
                "goal": matches[0]["goal_title"],
                "original_date": original_date,
                "new_date": new_date,
                "note": "Other occurrences of this recurring task remain unchanged."
            })
        else:
            # Multiple possible matches - ask for clarification
            options = []
            for i, m in enumerate(matches[:5], 1):
                options.append({
                    "number": i,
                    "task_id": m["task"]["id"],
                    "task_text": m["task"]["task_text"],
                    "goal": m["goal_title"]
                })
            
            return json.dumps({
                "success": False,
                "requires_clarification": True,
                "message": f"I found multiple tasks on {original_date}. Which one do you want to reschedule?",
                "options": options
            })
        
    except Exception as e:
        logger.error(f"Error rescheduling task: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


# ============================================================================
# New Tools: Settings, Progress, Date, Snooze, Edit
# ============================================================================

@tool
def get_user_settings(user_id: str) -> str:
    """
    Read the current user settings from Supabase. Use this to check boss_type,
    boss_language, or subscription_status. ALWAYS prefer this over
    remembering values from previous conversation turns.

    Args:
        user_id: The user ID (UUID)

    Returns:
        A JSON string with the user's current settings
    """
    try:
        result = supabase.table("user_preferences").select(
            "boss_type, boss_language, subscription_status"
        ).eq("user_id", user_id).execute()

        if result.data and len(result.data) > 0:
            return json.dumps({"success": True, "settings": result.data[0]})
        return json.dumps({"success": True, "settings": {
            "boss_type": "execution",
            "boss_language": "en",
            "subscription_status": "free",
        }})
    except Exception as e:
        logger.error(f"Error fetching user settings: {e}")
        return json.dumps({"success": False, "error": str(e)})


@tool
def update_user_settings(user_id: str, boss_type: str = None, boss_language: str = None) -> str:
    """
    Update user settings in Supabase. Use this when the user wants to change
    their boss personality or language.

    Args:
        user_id: The user ID (UUID)
        boss_type: New boss type - "execution", "supportive", "mentor", or "drill-sergeant" (optional)
        boss_language: New language - "en", "zh-TW", "zh-CN", or "zh-HK" (optional)

    Returns:
        A JSON string confirming the update
    """
    try:
        update_data = {}
        valid_boss_types = ["execution", "supportive", "mentor", "drill-sergeant"]
        valid_languages = ["en", "zh-TW", "zh-CN", "zh-HK"]

        if boss_type is not None:
            if boss_type not in valid_boss_types:
                return json.dumps({"success": False, "error": f"Invalid boss_type. Must be one of: {', '.join(valid_boss_types)}"})
            update_data["boss_type"] = boss_type

        if boss_language is not None:
            if boss_language not in valid_languages:
                return json.dumps({"success": False, "error": f"Invalid boss_language. Must be one of: {', '.join(valid_languages)}"})
            update_data["boss_language"] = boss_language

        if not update_data:
            return json.dumps({"success": False, "error": "No settings provided to update."})

        supabase.table("user_preferences").update(update_data).eq("user_id", user_id).execute()

        changes = ", ".join(f"{k}={v}" for k, v in update_data.items())
        return json.dumps({"success": True, "message": f"Settings updated: {changes}", "updated": update_data})
    except Exception as e:
        logger.error(f"Error updating user settings: {e}")
        return json.dumps({"success": False, "error": str(e)})


@tool
def get_current_date_info(user_id: str) -> str:
    """
    Get comprehensive date information. Use this tool whenever you need to
    resolve dates or confirm what day it is.

    Args:
        user_id: The user ID (UUID)

    Returns:
        A JSON string with today's date, day of week, and pre-computed key reference dates
    """
    try:
        today = date.today()
        weekday_num = today.weekday()  # 0=Monday .. 6=Sunday
        weekday_name = today.strftime("%A")

        days_until_sunday = 6 - weekday_num
        this_sunday = today + timedelta(days=days_until_sunday)
        this_saturday = today + timedelta(days=(5 - weekday_num) % 7 or 7) if weekday_num > 5 else today + timedelta(days=5 - weekday_num)
        if weekday_num == 5:
            this_saturday = today

        next_monday = today + timedelta(days=(7 - weekday_num) % 7 or 7)
        end_of_next_week_sunday = next_monday + timedelta(days=6)

        days_of_week = {}
        for i in range(7):
            d = today + timedelta(days=i)
            days_of_week[d.strftime("%A")] = d.isoformat()

        return json.dumps({
            "success": True,
            "today": today.isoformat(),
            "today_weekday": weekday_name,
            "tomorrow": (today + timedelta(days=1)).isoformat(),
            "this_saturday": this_saturday.isoformat(),
            "this_sunday": this_sunday.isoformat(),
            "next_monday": next_monday.isoformat(),
            "end_of_next_week": end_of_next_week_sunday.isoformat(),
            "upcoming_days": days_of_week,
        })
    except Exception as e:
        logger.error(f"Error getting date info: {e}")
        return json.dumps({"success": False, "error": str(e)})


@tool
def get_progress_summary(user_id: str) -> str:
    """
    Get a progress summary for the user: active/completed goals, tasks done today/this week,
    completion rate, streak, and overdue count. Use when user asks "How am I doing?" etc.

    Args:
        user_id: The user ID (UUID)

    Returns:
        A JSON string with progress metrics
    """
    try:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())  # Monday

        all_goals = supabase.table("goals").select("id, status").eq("user_id", user_id).execute()
        goals = all_goals.data or []
        active_goals = [g for g in goals if g["status"] == "active"]
        completed_goals = [g for g in goals if g["status"] == "completed"]

        goal_ids = [g["id"] for g in goals]
        all_tasks = []
        if goal_ids:
            all_tasks = (supabase.table("daily_tasks")
                         .select("id, status, task_date, goal_id")
                         .in_("goal_id", goal_ids)
                         .execute()).data or []

        total_tasks = len(all_tasks)
        done_tasks = [t for t in all_tasks if t.get("status") == "done"]
        completion_rate = (len(done_tasks) / total_tasks * 100) if total_tasks > 0 else 0

        tasks_done_today = [t for t in done_tasks if t.get("task_date") == today.isoformat()]
        tasks_done_this_week = [t for t in done_tasks if t.get("task_date") and t["task_date"] >= week_start.isoformat() and t["task_date"] <= today.isoformat()]

        overdue = [t for t in all_tasks if t.get("status") != "done" and t.get("task_date") and t["task_date"] < today.isoformat()]

        # Calculate streak: consecutive days ending today/yesterday with at least one done task
        streak = 0
        check_date = today
        done_dates = set(t.get("task_date") for t in done_tasks if t.get("task_date"))
        while check_date.isoformat() in done_dates:
            streak += 1
            check_date -= timedelta(days=1)
        if streak == 0 and (today - timedelta(days=1)).isoformat() in done_dates:
            check_date = today - timedelta(days=1)
            while check_date.isoformat() in done_dates:
                streak += 1
                check_date -= timedelta(days=1)

        return json.dumps({
            "success": True,
            "today": today.isoformat(),
            "active_goals": len(active_goals),
            "completed_goals": len(completed_goals),
            "total_tasks": total_tasks,
            "tasks_completed": len(done_tasks),
            "completion_rate_pct": round(completion_rate, 1),
            "tasks_done_today": len(tasks_done_today),
            "tasks_done_this_week": len(tasks_done_this_week),
            "overdue_tasks": len(overdue),
            "streak_days": streak,
        })
    except Exception as e:
        logger.error(f"Error getting progress summary: {e}")
        return json.dumps({"success": False, "error": str(e)})


@tool
def update_task_text(user_id: str, task_id: str, new_text: str) -> str:
    """
    Update the description text of an existing task.
    Use when user says "change that task to say X" or "rename task to X".

    Args:
        user_id: The user ID (UUID) for ownership verification
        task_id: The task ID (UUID) to update
        new_text: The new task description text

    Returns:
        A JSON string confirming the update
    """
    try:
        task_result = supabase.table("daily_tasks").select("id, task_text, goal_id").eq("id", task_id).execute()
        if not task_result.data:
            return json.dumps({"success": False, "error": "Task not found"})

        goal_id = task_result.data[0].get("goal_id")
        goal_result = supabase.table("goals").select("id").eq("id", goal_id).eq("user_id", user_id).execute()
        if not goal_result.data:
            return json.dumps({"success": False, "error": "Task not found or permission denied"})

        old_text = task_result.data[0].get("task_text", "")
        supabase.table("daily_tasks").update({"task_text": new_text}).eq("id", task_id).execute()

        return json.dumps({
            "success": True,
            "message": f"Task updated from '{old_text}' to '{new_text}'",
            "task_id": task_id,
        })
    except Exception as e:
        logger.error(f"Error updating task text: {e}")
        return json.dumps({"success": False, "error": str(e)})


@tool
def snooze_task(user_id: str, task_description: str, days: int = 1) -> str:
    """
    Postpone a task by a number of days. Finds the task by description matching
    and moves it forward. Use when user says "push X to tomorrow" or "delay X by 3 days".

    Args:
        user_id: The user ID (UUID)
        task_description: Keywords or description to match the task
        days: Number of days to postpone (default: 1 = tomorrow)

    Returns:
        A JSON string with the result
    """
    try:
        goal_ids = get_active_goal_ids(user_id)
        if not goal_ids:
            return json.dumps({"success": False, "error": "No active goals found"})

        tasks_result = supabase.table("daily_tasks").select(
            "id, task_text, task_date, status, goal_id"
        ).in_("goal_id", goal_ids).neq("status", "done").execute()
        tasks = tasks_result.data or []

        if not tasks:
            return json.dumps({"success": False, "error": "No incomplete tasks found"})

        search_lower = task_description.lower().strip()
        matches = []
        for task in tasks:
            text_lower = task.get("task_text", "").lower()
            similarity = calculate_similarity(search_lower, text_lower)
            keywords_match = any(w in text_lower for w in search_lower.split() if len(w) > 2)
            if similarity >= 0.4 or keywords_match:
                matches.append({"task": task, "similarity": similarity})

        matches.sort(key=lambda x: x["similarity"], reverse=True)

        if not matches:
            return json.dumps({
                "success": False,
                "error": f"No matching task found for '{task_description}'",
            })

        if len(matches) == 1 or matches[0]["similarity"] > 0.7:
            best = matches[0]["task"]
            old_date = best.get("task_date", date.today().isoformat())
            new_date = (date.fromisoformat(old_date) + timedelta(days=days)).isoformat()

            supabase.table("daily_tasks").update({"task_date": new_date}).eq("id", best["id"]).execute()

            return json.dumps({
                "success": True,
                "message": f"Snoozed '{best['task_text']}' from {old_date} to {new_date} ({days} day{'s' if days != 1 else ''})",
                "task_id": best["id"],
                "old_date": old_date,
                "new_date": new_date,
            })
        else:
            options = []
            for i, m in enumerate(matches[:5], 1):
                options.append({
                    "number": i,
                    "task_id": m["task"]["id"],
                    "task_text": m["task"]["task_text"],
                    "task_date": m["task"]["task_date"],
                })
            return json.dumps({
                "success": False,
                "requires_clarification": True,
                "message": "Multiple tasks match. Which one do you want to snooze?",
                "options": options,
            })
    except Exception as e:
        logger.error(f"Error snoozing task: {e}")
        return json.dumps({"success": False, "error": str(e)})


# ============================================================================
# LangGraph State and Agent Setup
# ============================================================================

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    user_id: str


def create_agent_graph(checkpointer=None):
    """Create and configure the LangGraph agent with tools."""
    
    llm = get_llm()
    
    tools = [
        # Primary workflow tools
        get_incomplete_tasks_prioritized,
        create_goal_with_task,
        create_recurring_tasks,
        mark_task_done_by_description,
        reschedule_task_occurrence,
        snooze_task,
        get_progress_summary,
        get_current_date_info,
        get_user_settings,
        update_user_settings,
        update_task_text,
        
        # Supporting tools
        break_goal_into_tasks,
        create_task_in_supabase,
        confirm_and_create_goal,
        confirm_and_create_task,
        get_user_tasks,
        create_check_in,
        create_boss_event,
        get_user_goals,
        delete_goal,
        delete_task,
        find_task_by_description,
        update_task_status,
        update_goal_status,
    ]
    llm_with_tools = llm.bind_tools(tools)
    
    def call_model(state: AgentState):
        messages = state["messages"]
        user_id = state.get("user_id", "unknown")
        
        # ALWAYS read boss_language and subscription_status from Supabase
        boss_type = "execution"
        boss_language = "en"
        subscription_status = "free"
        try:
            pref_result = supabase.table("user_preferences").select(
                "boss_type, boss_language, subscription_status"
            ).eq("user_id", user_id).execute()
            if pref_result.data and len(pref_result.data) > 0:
                row = pref_result.data[0]
                boss_type = row.get("boss_type", "execution")
                boss_language = row.get("boss_language", "en")
                subscription_status = row.get("subscription_status", "free")
        except Exception:
            pass
        
        system_prompt = get_system_prompt(user_id, boss_type, boss_language)
        
        today = date.today()
        today_str = today.isoformat()
        today_weekday = today.strftime("%A")
        
        tomorrow = today + timedelta(days=1)
        days_until_sunday = 6 - today.weekday()
        this_sunday = today + timedelta(days=days_until_sunday)
        next_monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
        next_week_end = next_monday + timedelta(days=6)
        
        # Pre-compute all days of the current week for precise date references
        this_week_days = {}
        for i in range(7):
            d = today + timedelta(days=i)
            this_week_days[d.strftime("%A")] = d.isoformat()
        this_week_str = ", ".join(f"{k}: {v}" for k, v in this_week_days.items())
        
        system_prompt += f"""


---

CURRENT DATE CONTEXT

Today is: {today_str} ({today_weekday})
Tomorrow is: {tomorrow.isoformat()}
This Sunday: {this_sunday.isoformat()}
Next Monday: {next_monday.isoformat()}
End of next week (Sunday): {next_week_end.isoformat()}
Upcoming days this week: {this_week_str}

Subscription: {subscription_status}

---

SETTINGS RULES (CRITICAL)

- boss_language ({boss_language}) and subscription_status ({subscription_status}) are loaded fresh from
  Supabase on every turn. NEVER override or remember these from conversation history.
- If user wants to change language or boss type mid-conversation, use update_user_settings() tool.
- To check current settings, use get_user_settings() tool.

---

CRITICAL HARD RULES (NEVER VIOLATE)

1. NEVER mention completed tasks or goals - focus only on what's incomplete/upcoming
2. When uncertain if something is a task or goal, ALWAYS create BOTH using create_goal_with_task()
3. If an event involves meeting people, set intensity to "high"
4. If the end date of a goal or date of a task is NOT crystal clear, DON'T GUESS -- ASK!
5. NEVER create a goal without a task
6. Always think task first, then generalize for goal name
7. NEVER invent goals/tasks that user did not explicitly mention
8. ONLY create goals/tasks that are EXPLICITLY mentioned by the user
9. NEVER mention or reference time/timing for any task - the system is date-level only
10. NEVER use emojis in any messages or responses

---

DATE INFERENCE RULES

When the user mentions a date, resolve it precisely using the CURRENT DATE CONTEXT above.
If unsure, call get_current_date_info(user_id) to get exact dates.

- "today" / "tonight" / "now" / "this morning" / "this evening" -> {today_str}
- "tomorrow" -> {tomorrow.isoformat()}
- "day after tomorrow" -> {(today + timedelta(days=2)).isoformat()}
- "this [weekday]" -> use the Upcoming days table above; if that weekday has already passed this week, use NEXT week's occurrence
- "next [weekday]" -> the occurrence in the NEXT calendar week (after next Monday {next_monday.isoformat()})
- "this weekend" / "on the weekend" -> {this_sunday.isoformat()}
- "next week" -> the week starting {next_monday.isoformat()}
- "end of next week" -> {next_week_end.isoformat()}
- "in X days" -> {today_str} + X days
- NO DATE MENTIONED -> assume {today_str} (today)
- VAGUE ("soon", "later", "sometime") -> assume {tomorrow.isoformat()} (tomorrow)

---

USER SCENARIO HANDLING

**"What should I do now?" / "What's my plan for today/this week?"**
-> Use get_incomplete_tasks_prioritized(user_id, scope="today" or "week")

**"How am I doing?" / "What's my progress?" / "Show me my stats"**
-> Use get_progress_summary(user_id)

**Aspirational goals ("I want to lose 10kg", "find a good job")**
-> ASK for end date first, then create

**Social/meeting events ("dinner with family tonight", "lunch with friends on Friday")**
-> HIGH intensity, resolve date from context above

**"buy a bag of apples" (no date)**
-> Assume today, create_goal_with_task with medium intensity

**"I have done X" / "Finished X"**
-> Use mark_task_done_by_description(user_id, "X")

**"Done" (no context)**
-> ASK: "What task did you complete?"

**"push X to tomorrow" / "delay X by 3 days"**
-> Use snooze_task(user_id, "X", days=1 or 3)

**"move X from [date] to [date]"**
-> Use reschedule_task_occurrence(user_id, "X", original_date, new_date)

**"change my language to Chinese" / "I want the supportive boss"**
-> Use update_user_settings(user_id, boss_language="zh-TW") or update_user_settings(user_id, boss_type="supportive")

**Recurring tasks ("everyday until next week", "every Saturday", "monthly on 15th")**
-> Use create_recurring_tasks with appropriate recurrence_type and parameters

**"rename my task X to Y" / "change that task"**
-> Find the task, then use update_task_text(user_id, task_id, new_text)

---

INTENSITY GUIDELINES

HIGH: Events with people, time-sensitive deadlines, commitments to others
MEDIUM: Personal tasks with soft deadlines, regular work
LOW: Nice-to-have, flexible timeline

---

TASK/GOAL STATUS MANAGEMENT

Task Statuses: "todo", "in_progress", "done"
Goal Statuses: "active", "completed", "abandoned"

---

QUESTION POLICY

Only ask questions that unblock execution:
- "By when do you want to achieve this?"
- "Which task did you complete?"
- "Which option are you committing to?"

Never: open-ended exploration, preference discovery, emotional validation.

---

ESCALATION LOGIC

Misses 2 times -> Firmer tone
Misses 3+ times -> Confrontational clarity

---

WHATSAPP BEHAVIOUR

- Short, authoritative messages
- One instruction per message when possible
- No lists unless assigning tasks

---

ABSOLUTE RESTRICTIONS

NEVER sound like a friendly assistant. NEVER mention completed tasks/goals.
You are here to ensure execution, not comfort.

---

DEFAULT CLOSING LINE

End task-setting messages with:
- "Report back once complete"
- "Check-in required today"
- "Execution starts now"

"""
        
        # Add system message with generated prompt
        system_msg = SystemMessage(content=system_prompt)
        
        full_messages = [system_msg] + messages
        response = llm_with_tools.invoke(full_messages)
        return {"messages": [response]}
    
    # Define tool node
    tool_node = ToolNode(tools)
    
    # Define routing logic for agent
    def should_continue(state: AgentState):
        messages = state["messages"]
        last_message = messages[-1]
        
        # If there are tool calls, continue to tools
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        # Otherwise, end the conversation
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
        
        # Get or create checkpointer connection
        checkpointer_instance = None
        if supabase_checkpointer:
            try:
                checkpointer_instance = supabase_checkpointer.checkpointer
                if not checkpointer_instance:
                    # Initialize connection if not already done
                    await supabase_checkpointer.setup_connection()
                    checkpointer_instance = supabase_checkpointer.checkpointer
            except Exception as e:
                # Handle case where database tables don't exist or connection fails
                error_msg = str(e).lower()
                if 'relation' in error_msg and 'does not exist' in error_msg:
                    logger.error(f"Database tables not created. Please run database migrations. Error: {e}")
                else:
                    logger.error(f"Failed to setup checkpointer connection: {e}")
                logger.warning("Falling back to non-persistent mode (no conversation history)")
                checkpointer_instance = None
        
        # Check if this is the first ever message by querying the checkpointer
        is_first_message = False
        if checkpointer_instance:
            try:
                # Try to get the state history for this thread
                state_history = [state async for state in checkpointer_instance.alist(config)]
                
                # If there's no history, this is the first message
                if not state_history or len(state_history) == 0:
                    is_first_message = True
                    logger.info(f"First message detected for user {user_id}")
            except Exception as e:
                error_msg = str(e).lower()
                if 'relation' in error_msg and 'does not exist' in error_msg:
                    logger.error(f"Database tables not created. Cannot check message history. Error: {e}")
                    checkpointer_instance = None  # Disable checkpointer for this request
                else:
                    logger.warning(f"Could not check message history: {e}. Assuming not first message.")
                is_first_message = False
        
        # If this is the first message, send language selection
        if is_first_message:
            try:
                # Send language selection message
                language_selection_msg = get_language_selection_message()
                
                logger.info(f"Sending language selection message for new user {user_id}")
                
                # Save the language selection conversation to checkpointer if available
                if checkpointer_instance:
                    try:
                        # Create initial state with the language selection conversation
                        selection_state = {
                            "messages": [
                                HumanMessage(content=user_message),
                                AIMessage(content=language_selection_msg)
                            ],
                            "user_id": user_id
                        }
                        
                        # Create agent graph
                        temp_graph = create_agent_graph(checkpointer=checkpointer_instance)
                        
                        try:
                            await temp_graph.ainvoke(selection_state, config=config)
                            logger.info(f"Language selection conversation saved to checkpointer for user {user_id}")
                        except Exception as invoke_error:
                            error_msg = str(invoke_error).lower()
                            if 'relation' in error_msg and 'does not exist' in error_msg:
                                logger.error(f"Could not save language selection - database tables not created: {invoke_error}")
                            else:
                                logger.warning(f"Could not save language selection to checkpointer: {invoke_error}")
                        
                    except Exception as checkpoint_error:
                        logger.warning(f"Error setting up checkpoint for language selection: {checkpoint_error}")
                
                return language_selection_msg
                
            except Exception as e:
                logger.error(f"Error sending language selection: {e}")
                # Fall through to normal processing if there's an error
        
        # Check if user is responding to language selection
        # (They have 1 message pair in history - the language selection)
        if checkpointer_instance:
            try:
                state_history = [state async for state in checkpointer_instance.alist(config)]
                
                # If there's exactly one checkpoint (language selection sent, waiting for response)
                if state_history and len(state_history) == 1:
                    # Check if the last bot message was the language selection
                    last_state = state_history[0]
                    messages = last_state.values.get("messages", [])
                    
                    if len(messages) >= 2:
                        last_ai_message = None
                        for msg in reversed(messages):
                            if isinstance(msg, AIMessage):
                                last_ai_message = msg
                                break
                        
                        # Check if it contains the language selection text
                        if last_ai_message and "which language would you prefer" in last_ai_message.content.lower():
                            # User is responding to language selection
                            selected_language = parse_language_selection(user_message)
                            
                            if selected_language:
                                # Valid language selection - update user preferences
                                try:
                                    supabase.table("user_preferences").update({
                                        "boss_language": selected_language
                                    }).eq("user_id", user_id).execute()
                                    
                                    logger.info(f"Updated language to {selected_language} for user {user_id}")
                                    
                                    # Get user's boss_type
                                    pref_result = supabase.table("user_preferences").select("boss_type").eq("user_id", user_id).execute()
                                    boss_type = "execution"  # default
                                    if pref_result.data and len(pref_result.data) > 0:
                                        boss_type = pref_result.data[0].get("boss_type", "execution")
                                    
                                    # Get the greeting message in the selected language
                                    greeting = get_first_message_greeting(boss_type, selected_language)
                                    
                                    # Save the greeting to conversation history
                                    if checkpointer_instance:
                                        try:
                                            greeting_state = {
                                                "messages": [
                                                    HumanMessage(content=user_message),
                                                    AIMessage(content=greeting)
                                                ],
                                                "user_id": user_id
                                            }
                                            temp_graph = create_agent_graph(checkpointer=checkpointer_instance)
                                            await temp_graph.ainvoke(greeting_state, config=config)
                                            logger.info(f"Greeting in {selected_language} saved for user {user_id}")
                                        except Exception as e:
                                            logger.warning(f"Could not save greeting to checkpointer: {e}")
                                    
                                    return greeting
                                    
                                except Exception as e:
                                    logger.error(f"Error updating language preference: {e}")
                                    return "Sorry, there was an error saving your language preference. Please try again."
                            else:
                                # Invalid language selection - ask again
                                retry_message = """Please choose a valid language option by replying with a number:

1. English
2. 繁體中文 (Traditional Chinese)
3. 简体中文 (Simplified Chinese)
4. 廣東話 (Cantonese)"""
                                
                                if checkpointer_instance:
                                    try:
                                        retry_state = {
                                            "messages": [
                                                HumanMessage(content=user_message),
                                                AIMessage(content=retry_message)
                                            ],
                                            "user_id": user_id
                                        }
                                        temp_graph = create_agent_graph(checkpointer=checkpointer_instance)
                                        await temp_graph.ainvoke(retry_state, config=config)
                                    except Exception as e:
                                        logger.warning(f"Could not save retry message to checkpointer: {e}")
                                
                                return retry_message
                                
            except Exception as e:
                logger.warning(f"Error checking for language selection state: {e}")
        
        # Prepare initial state with new message
        # If checkpointer is enabled, previous messages will be loaded automatically
        initial_state = {
            "messages": [HumanMessage(content=user_message)],
            "user_id": user_id
        }
        
        # Create agent graph with checkpointer
        agent_graph = create_agent_graph(checkpointer=checkpointer_instance)
        
        # Run the agent with config for persistence (async if checkpointer is async)
        if checkpointer_instance:
            try:
                # Use ainvoke for async checkpointer
                result = await agent_graph.ainvoke(initial_state, config=config)
            except Exception as e:
                error_msg = str(e).lower()
                if 'relation' in error_msg and 'does not exist' in error_msg:
                    logger.error(f"Database tables not created during agent invocation. Error: {e}")
                    logger.warning("Falling back to non-persistent mode for this request")
                    # Recreate graph without checkpointer and retry
                    agent_graph = create_agent_graph(checkpointer=None)
                    result = agent_graph.invoke(initial_state, config=config)
                else:
                    # Re-raise other errors
                    raise
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
    
    FIRST CHECKIN OF THE DAY:
    - Shows expired incomplete tasks (what you left unfinished)
    - Shows today's focus tasks
    - Provides prioritized recommendation (by task size, intensity, deadline proximity)
    - Suggests what to start with
    - NEVER shows tasks beyond today (tomorrow or later)
    
    SUBSEQUENT CHECKINS:
    - Asks for check-in if any tasks are done
    - Shows numbered list for easy reply
    - "Let me know if you have done any of them"
    
    Args:
        user_id: The user ID to fetch context for
        boss_type: The boss type for personality
        last_checkin_at: The last checkin timestamp (ISO format)
        boss_language: The language preference (default: "en")
        
    Returns:
        A personalized check-in message string in the user's preferred language
    """
    try:
        today = date.today()
        
        is_first_ping_today = True
        if last_checkin_at:
            try:
                last_checkin_date = datetime.fromisoformat(last_checkin_at.replace('Z', '+00:00')).date()
                is_first_ping_today = last_checkin_date < today
            except Exception as e:
                logger.warning(f"Could not parse last_checkin_at: {e}")
                is_first_ping_today = True
        
        # Get user's active goals
        goals_result = supabase.table("goals").select("id, title, intensity, start_date, end_date").eq(
            "user_id", user_id
        ).eq("status", "active").execute()
        
        goals = goals_result.data if goals_result.data else []
        
        if not goals:
            return generate_checkin_message_fallback(boss_type, boss_language)
        
        goal_ids = [g["id"] for g in goals]
        goal_map = {g["id"]: g for g in goals}
        
        # Get INCOMPLETE tasks only (never mention completed)
        tasks_result = supabase.table("daily_tasks").select(
            "id, task_text, task_date, status, goal_id"
        ).in_("goal_id", goal_ids).neq("status", "done").order("task_date", desc=False).execute()
        
        tasks = tasks_result.data if tasks_result.data else []
        
        if not tasks:
            # No incomplete tasks - send motivational message
            return generate_motivational_message(boss_type, boss_language)
        
        # Categorize and prioritize tasks
        expired_tasks = []  # Past due, not completed
        today_tasks = []    # Due today
        upcoming_tasks = [] # Future tasks
        
        for task in tasks:
            task_date_str = task.get("task_date")
            if not task_date_str:
                continue
                
            task_date_obj = date.fromisoformat(task_date_str)
            goal = goal_map.get(task.get("goal_id"), {})
            
            # Add goal info
            task["goal_title"] = goal.get("title", "Unknown")
            task["goal_intensity"] = goal.get("intensity", "medium")
            
            # Calculate priority score
            priority_score = 0
            intensity_scores = {"high": 30, "medium": 20, "low": 10}
            priority_score += intensity_scores.get(goal.get("intensity", "medium"), 20)
            
            days_until = (task_date_obj - today).days
            if days_until < 0:
                priority_score += 50
            elif days_until == 0:
                priority_score += 40
            elif days_until <= 3:
                priority_score += 30
            else:
                priority_score += 20
            
            task["priority_score"] = priority_score
            task["days_until_due"] = days_until
            
            if task_date_obj < today:
                expired_tasks.append(task)
            elif task_date_obj == today:
                today_tasks.append(task)
            else:
                upcoming_tasks.append(task)
        
        # Sort by priority
        expired_tasks.sort(key=lambda x: x["priority_score"], reverse=True)
        today_tasks.sort(key=lambda x: x["priority_score"], reverse=True)
        
        # Check if there are no tasks for today or overdue incomplete tasks
        if not expired_tasks and not today_tasks:
            # Send motivational message
            return generate_motivational_message(boss_type, boss_language)
        
        # Get personality prompt
        personality = get_personality_prompt(boss_type, boss_language)
        
        # Build context based on whether first ping or subsequent
        if is_first_ping_today:
            # FIRST PING: Comprehensive overview at task level
            context_parts = []
            
            # Expired/unfinished tasks
            if expired_tasks:
                expired_text = "\n".join([f"- {t['task_text']} (from {t['task_date']}, {t['goal_title']})" for t in expired_tasks[:5]])
                context_parts.append(f"UNFINISHED/EXPIRED TASKS:\n{expired_text}")
            
            # Today's focus
            if today_tasks:
                today_text = "\n".join([f"- {t['task_text']} ({t['goal_title']}, {t['goal_intensity']} intensity)" for t in today_tasks[:5]])
                context_parts.append(f"TODAY'S FOCUS:\n{today_text}")
            
            # Recommendation (highest priority)
            all_focus = expired_tasks + today_tasks
            if all_focus:
                top_task = all_focus[0]
                reason = "expired - needs immediate attention" if top_task["days_until_due"] < 0 else f"high priority today"
                context_parts.append(f"RECOMMENDED START: '{top_task['task_text']}' ({reason})")
            
            context = "\n\n".join(context_parts)
            
            # Generate first-ping message
            prompt = get_checkin_ai_prompt(context, personality, boss_language, is_first_ping=True)
            
        else:
            # SUBSEQUENT PING: Ask progress with numbered list
            all_active_tasks = expired_tasks + today_tasks
            if not all_active_tasks:
                all_active_tasks = upcoming_tasks[:3]
            
            # Create numbered list
            numbered_tasks = []
            for i, task in enumerate(all_active_tasks[:5], 1):
                status_note = "(overdue)" if task.get("days_until_due", 0) < 0 else ""
                numbered_tasks.append(f"{i}. {task['task_text']} {status_note}".strip())
            
            task_list = "\n".join(numbered_tasks)
            
            context = f"""TASKS TO CHECK PROGRESS ON:
{task_list}

INSTRUCTION: Ask for review on these tasks. Present them as a numbered list so user can easily reply with a number. End with "Let me know if you've done any of them." """
            
            prompt = get_checkin_ai_prompt(context, personality, boss_language, is_first_ping=False)
        
        llm = get_llm()
        response = llm.invoke([HumanMessage(content=prompt)])
        ai_message = response.content.strip()
        
        # Validate message length for WhatsApp
        if len(ai_message) > 500:
            ai_message = ai_message[:497] + "..."
        
        return ai_message
        
    except Exception as e:
        logger.error(f"Error generating AI check-in message: {e}")
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


def generate_motivational_message(boss_type: str, boss_language: str = "en") -> str:
    """
    Generate a motivational message when there are no tasks for today or overdue incomplete tasks.
    
    Args:
        boss_type: The boss type
        boss_language: The language preference (default: "en")
        
    Returns:
        A motivational message string in the specified language
    """
    messages = {
        "en": {
            "drill-sergeant": "Outstanding work! You've cleared all your tasks. Stay sharp and ready for what's coming next.",
            "execution": "Great job! You're all caught up. Keep this momentum going.",
            "supportive": "Wonderful! You've completed everything on your list. Take a moment to celebrate your progress.",
            "mentor": "Excellent work! You've handled your responsibilities well. Use this time to reflect on your achievements."
        },
        "zh-TW": {
            "drill-sergeant": "做得好！你已完成所有任務。保持警覺，準備迎接下一個挑戰。",
            "execution": "做得好！你已經全部完成了。繼續保持這個勢頭。",
            "supportive": "太棒了！你已經完成了所有事項。花點時間慶祝你的進步吧。",
            "mentor": "做得很好！你處理得很到位。利用這段時間反思你的成就。"
        },
        "zh-HK": {
            "drill-sergeant": "做得好！你已完成所有任務。保持警覺，準備迎接下一個挑戰。",
            "execution": "做得好！你已經完成晒。繼續保持呢個勢頭。",
            "supportive": "太好啦！你已經完成晒所有嘢。花啲時間慶祝你嘅進步啦。",
            "mentor": "做得好！你處理得好好。利用呢段時間反思你嘅成就。"
        },
        "zh-CN": {
            "drill-sergeant": "做得好！你已完成所有任务。保持警觉，准备迎接下一个挑战。",
            "execution": "干得好！你已经全部完成了。继续保持这个势头。",
            "supportive": "太棒了！你已经完成了所有事项。花点时间庆祝你的进步吧。",
            "mentor": "做得很好！你处理得很到位。利用这段时间反思你的成就。"
        }
    }
    
    # Get language-specific messages, default to English
    lang_messages = messages.get(boss_language, messages["en"])
    
    # Get message for boss type, default to execution
    return lang_messages.get(boss_type, lang_messages["execution"])


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


def generate_secure_password(length: int = 32) -> str:
    """
    Generate a cryptographically secure random password.
    
    Args:
        length: Length of the password (default 32 characters)
        
    Returns:
        A secure random password string
    """
    alphabet = string.ascii_letters + string.digits + string.punctuation
    password = ''.join(secrets.choice(alphabet) for i in range(length))
    return password


def create_phone_user(phone_no: str) -> Optional[str]:
    """
    Create a user in Supabase Auth using phone provider.
    A secure random password is generated for each user (they never need to know it).
    WhatsApp interaction serves as the authentication mechanism.
    
    Args:
        phone_no: The phone number (cleaned, without whatsapp: prefix or +)
        
    Returns:
        The user_id (UUID) if created successfully, None otherwise
    """
    try:
        # Check if user already exists in user_preferences
        existing_user = supabase.table("user_preferences")\
            .select("user_id")\
            .eq("phone_no", phone_no)\
            .execute()
        
        if existing_user.data and len(existing_user.data) > 0:
            user_id = existing_user.data[0]["user_id"]
            logger.info(f"Found existing user with ID: {user_id} for phone: {phone_no}")
            return user_id
        
        # Format phone number for Supabase (needs + prefix)
        formatted_phone = f"+{phone_no}"
        
        # Generate a secure random password (user never needs to know this)
        # Required by Supabase, but WhatsApp handles actual authentication
        secure_password = generate_secure_password()
        
        # Create user with phone provider
        try:
            auth_response = supabase.auth.sign_up({
                "phone": formatted_phone,
                "password": secure_password,
                "options": {
                    "data": {
                        "phone_no": phone_no,
                        "auth_method": "whatsapp"
                    }
                }
            })
            
            if not auth_response.user:
                logger.error(f"Failed to create phone user for phone: {phone_no}")
                return None
                
            user_id = auth_response.user.id
            logger.info(f"Created phone user with ID: {user_id} for phone: {phone_no}")
            
        except Exception as signup_error:
            # If sign_up fails (e.g., user already exists), try to find existing user
            logger.warning(f"Sign up failed: {signup_error}")
            
            # Try to find existing user by phone in user_preferences
            existing_user = supabase.table("user_preferences")\
                .select("user_id")\
                .eq("phone_no", phone_no)\
                .execute()
            
            if existing_user.data and len(existing_user.data) > 0:
                user_id = existing_user.data[0]["user_id"]
                logger.info(f"Found existing user after signup error with ID: {user_id} for phone: {phone_no}")
                return user_id
            else:
                logger.error(f"Could not create or find user for phone: {phone_no}")
                return None
        
        # Insert a record into user_preferences table with phone number
        preferences_data = {
            "user_id": user_id,
            "phone_no": phone_no,
            "boss_type": "execution",
            "boss_language": "en",
            "subscription_status": "free",
            "plan_name": "Free",
        }
        
        pref_result = supabase.table("user_preferences").insert(preferences_data).execute()
        
        if pref_result.data and len(pref_result.data) > 0:
            logger.info(f"Created user_preferences record for user_id: {user_id}, phone: {phone_no}")
            return user_id
        else:
            logger.error(f"Failed to create user_preferences record for user_id: {user_id}")
            return None
            
    except Exception as e:
        logger.error(f"Error creating phone user for phone {phone_no}: {e}")
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
        logger.info(f"User not found for phone number: {phone_no}. Creating phone user...")
        # Create phone user and user_preferences record
        user_id = create_phone_user(phone_no)
        
        if not user_id:
            logger.error(f"Failed to create phone user for phone number: {phone_no}")
            # Send error message asynchronously
            background_tasks.add_task(
                send_whatsapp_message,
                sender_number,
                "Sorry, we encountered an error setting up your account. Please try again later."
            )
            # Return empty TwiML response immediately
            response = MessagingResponse()
            return PlainTextResponse(str(response), media_type="application/xml")
        
        logger.info(f"Successfully created phone user for phone: {phone_no}, user_id: {user_id}")
    
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
        current_time = datetime.utcnow()
        
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