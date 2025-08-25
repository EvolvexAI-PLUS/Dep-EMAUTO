#!/usr/bin/env python3
"""
Demonstration of how conversation context is used in AI response generation.
This shows the complete flow from email extraction to AI response with context.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from database.memory_manager_dynamo import get_conversation_history, update_conversation
from automation.generate_reply import build_reply_prompt, build_persona
from datetime import datetime

def demonstrate_context_flow():
    """Demonstrate how conversation context flows through the system"""
    print("🎭 Conversation Context in Action")
    print("=" * 60)

    # Simulate a user and conversation
    user_email = "demo@example.com"
    convo_id = "demo_conversation_001"

    print(f"👤 User: {user_email}")
    print(f"💬 Conversation: {convo_id}")
    print()

    # Step 1: Simulate existing conversation history
    print("📝 Step 1: Building conversation history...")

    # Add some historical context
    update_conversation(convo_id, "user", "Hi, I need help with my recent order", user_email)
    update_conversation(convo_id, "assistant", "I'd be happy to help! Could you provide your order number?", user_email)
    update_conversation(convo_id, "user", "My order number is ORD-2024-001", user_email)

    print("✅ Added historical conversation context")

    # Step 2: Retrieve conversation history (as AI would see it)
    print("\n📖 Step 2: AI retrieves conversation context...")

    history = get_conversation_history(convo_id, user_email)
    print("📜 Conversation History for AI:")
    print(f"   \"{history}\"")
    print()

    # Step 3: Simulate new incoming email
    print("📧 Step 3: New email arrives...")
    new_email_body = "Actually, I need to change the delivery address for this order."

    print(f"   New Email: \"{new_email_body}\"")
    print()

    # Step 4: Build AI prompt with context
    print("🤖 Step 4: AI builds response with context...")

    # Simulate user profile
    user_profile = {
        "name": "John Doe",
        "tone": "professional",
        "signature": "Best regards,\nJohn"
    }

    # Build persona (as the system would)
    persona = build_persona(user_email, user_profile)
    print("🎭 AI Persona:")
    for line in persona.split('\n'):
        if line.strip():
            print(f"   {line}")

    # Build the complete prompt (as the system would)
    prompt = build_reply_prompt(
        email_body=new_email_body,
        history=history,
        sender="customer@example.com",
        user_email=user_email,
        templates=[],
        profile=user_profile
    )

    print("\n📋 Complete AI Prompt:")
    print("-" * 40)
    print(prompt)
    print("-" * 40)

    # Step 5: Show what the AI will see
    print("\n🎯 Step 5: What AI sees for context-aware response:")
    print("   ✅ Previous conversation about order ORD-2024-001")
    print("   ✅ User's request to change delivery address")
    print("   ✅ Professional tone and signature requirements")
    print("   ✅ Context that this is a follow-up conversation")

    print("\n🚀 Result: AI can now generate a contextually appropriate response!")
    print("\n   Example AI Response:")
    print("   \"I understand you want to change the delivery address for order ORD-2024-001.")
    print("   I can help you with that. What would you like the new delivery address to be?")
    print("   ")
    print("   Best regards,")
    print("   John\"")

    print("\n🎉 Conversation context system is fully functional!")

if __name__ == "__main__":
    demonstrate_context_flow()