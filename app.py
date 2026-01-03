from fastapi import FastAPI, Request, Response, HTTPException, Security
from fastapi.responses import PlainTextResponse
from fastapi.security.api_key import APIKeyHeader
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from supabase import create_client, Client as SupabaseClient
import os
from dotenv import load_dotenv
import logging

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
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

logger = logging.getLogger(__name__)

async def get_api_key(api_key: str = Security(api_key_header)):
    """Validates the API Key from the header"""
    if api_key == MY_API_SECRET:
        return api_key
    raise HTTPException(
        status_code=403,
        detail="Could not validate credentials"
    )

def process_message(user_message: str) -> str:
    """
    Process incoming message and generate response.
    Replace with your own chatbot logic (LLM, rule-based, etc.)
    """
    message_lower = user_message.lower().strip()
    
    # Simple rule-based responses for demo
    responses = {
        "hello": "Hi there! 👋 How can I help you today?",
        "help": "I can help with: orders, returns, billing, and product info. What do you need?",
        "hi": "Hello! 😊 What brings you here?",
        "thanks": "You're welcome! Anything else I can help with?",
    }
    
    # Check for keyword matches
    for keyword, response in responses.items():
        if keyword in message_lower:
            return response
    
    # Default response
    return "Thanks for your message! I'm here to help. You can ask me about orders, returns, or product info."

@app.post("/webhook")
async def whatsapp_webhook(request: Request):
    """
    Webhook endpoint that receives messages from Twilio
    """
    form_data = await request.form()
    
    # Extract incoming message details
    incoming_message = form_data.get("Body", "")
    sender_number = form_data.get("From", "")
    
    logger.info(f"Message from {sender_number}: {incoming_message}")
    
    try:
        # Process the message through your chatbot logic
        reply_text = process_message(incoming_message)
        
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
async def get_tasks_by_user(user_id: str, api_key: str = Security(get_api_key)):
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

# @app.get("/tasks")
# async def get_all_tasks(api_key: str = Depends(get_api_key)):
#     """
#     Get all tasks from Supabase. 
#     Protected by 'X-API-Key' header.
#     """
#     # 1. Setup Supabase Client
#     url: str = os.getenv("SUPABASE_URL")
#     key: str = os.getenv("SUPABASE_KEY")
#     supabase: Client = create_client(url, key)

#     # 2. Setup Security (API Key Header)
#     API_KEY_NAME = "X-API-Key"
#     api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

#     MY_API_SECRET = os.getenv("MY_API_SECRET")

#     async def get_api_key(api_key_header: str = Security(api_key_header)):
#         """Validates the API Key from the header"""
#         if api_key_header == MY_API_SECRET:
#             return api_key_header
#         raise HTTPException(
#             status_code=403,
#             detail="Could not validate credentials"
#         )
#     try:
#         # Select all columns from 'tasks' table
#         response = supabase.table("tasks").select("*").execute()
#         return {"data": response.data}
#     except Exception as e:
#         return {"error": str(e)}

@app.post("/send")
async def send_whatsapp_message(request: Request):
    """
    Optional: Send messages via API
    POST /send with JSON: {"to": "whatsapp:+1234567890", "message": "Hello!"}
    """
    try:
        body = await request.json()
        to_number = body.get("to")
        message_text = body.get("message")
        
        if not to_number or not message_text:
            return {"error": "Missing 'to' or 'message' field"}
        
        message = client.messages.create(
            body=message_text,
            from_=TWILIO_PHONE,
            to=to_number
        )
        
        return {"success": True, "message_sid": message.sid}
    
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return {"error": str(e)}, 500
