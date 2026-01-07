"""
Test script for the LangGraph Task Management Agent

This script allows you to test the agent locally without needing Twilio/WhatsApp.
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import after loading env vars
from app import process_message

def main():
    """Interactive test interface for the agent."""
    
    print("=" * 60)
    print("LangGraph Task Management Agent - Test Interface")
    print("=" * 60)
    print("\nThis script lets you test the agent locally.")
    print("\nExample commands:")
    print("  - 'I want to launch a new product'")
    print("  - 'Create a task to review the budget'")
    print("  - 'Show me my tasks'")
    print("  - 'What are my pending tasks?'")
    print("\nType 'quit' or 'exit' to stop.\n")
    
    # Test user ID
    test_user_id = "test_user_123"
    print(f"Using test user ID: {test_user_id}\n")
    
    while True:
        try:
            # Get user input
            user_input = input("\n🧑 You: ").strip()
            
            # Check for exit commands
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("\n👋 Goodbye!")
                break
            
            # Skip empty input
            if not user_input:
                continue
            
            # Process the message
            print("\n🤖 Agent: ", end="", flush=True)
            response = process_message(user_input, user_id=test_user_id)
            print(response)
            
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")
            print("Make sure:")
            print("  1. Ollama is running (ollama serve)")
            print("  2. llama3.2:3b model is installed (ollama pull llama3.2:3b)")
            print("  3. Supabase credentials are set in .env")
            print("  4. Required packages are installed (pip install -r requirements.txt)")


def test_basic_functionality():
    """Run automated tests to verify basic functionality."""
    
    print("\n" + "=" * 60)
    print("Running Automated Tests")
    print("=" * 60)
    
    test_user_id = "automated_test_user"
    
    tests = [
        {
            "name": "Goal Breakdown Test",
            "message": "I want to organize a team building event",
            "expected_keywords": ["task", "created", "event"]
        },
        {
            "name": "Task Retrieval Test",
            "message": "Show me my tasks",
            "expected_keywords": ["task"]
        },
        {
            "name": "Simple Task Creation",
            "message": "Create a task to send monthly report",
            "expected_keywords": ["task", "created", "report"]
        }
    ]
    
    passed = 0
    failed = 0
    
    for i, test in enumerate(tests, 1):
        print(f"\n[Test {i}/{len(tests)}] {test['name']}")
        print(f"Input: {test['message']}")
        
        try:
            response = process_message(test['message'], user_id=test_user_id)
            print(f"Response: {response[:100]}...")
            
            # Check if expected keywords are in response
            response_lower = response.lower()
            found_keywords = [kw for kw in test['expected_keywords'] if kw in response_lower]
            
            if found_keywords:
                print(f"✅ PASSED (found keywords: {', '.join(found_keywords)})")
                passed += 1
            else:
                print(f"⚠️  WARNING: Expected keywords not found")
                print(f"   Expected: {', '.join(test['expected_keywords'])}")
                failed += 1
                
        except Exception as e:
            print(f"❌ FAILED: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("=" * 60)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test the LangGraph Task Management Agent")
    parser.add_argument(
        "--test", 
        action="store_true", 
        help="Run automated tests instead of interactive mode"
    )
    
    args = parser.parse_args()
    
    if args.test:
        test_basic_functionality()
    else:
        main()

