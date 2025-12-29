from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
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

logger = logging.getLogger(__name__)

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
