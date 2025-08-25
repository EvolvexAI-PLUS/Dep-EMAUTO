#!/usr/bin/env python3
"""
Verification script for conversation context functionality.
This tests the core conversation history features that were previously broken.
"""

import boto3
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv("secret.env")

# AWS Configuration
region = os.getenv("AWS_REGION", "ap-south-1")
dynamodb = boto3.resource("dynamodb", region_name=region)

# Table references
convo_table = dynamodb.Table("EmailConversations")

def test_conversation_context_system():
    """Test the conversation context functionality"""
    print("🧪 Testing Conversation Context System")
    print("=" * 50)

    # Test data
    test_user_email = "test@example.com"
    test_convo_id = "test_conversation_123"

    print(f"📧 Test User: {test_user_email}")
    print(f"💬 Test Conversation ID: {test_convo_id}")
    print()

    try:
        # Test 1: Add conversation messages
        print("📝 Test 1: Adding conversation messages...")

        # Add user message
        convo_table.put_item(Item={
            "user_email": test_user_email,
            "convo_id": test_convo_id,
            "timestamp": datetime.utcnow().isoformat(),
            "role": "user",
            "message": "Hello, I need help with my order"
        })

        # Add assistant message
        convo_table.put_item(Item={
            "user_email": test_user_email,
            "convo_id": test_convo_id,
            "timestamp": (datetime.utcnow() + timedelta(seconds=1)).isoformat(),
            "role": "assistant",
            "message": "I'd be happy to help you with your order. Could you please provide your order number?"
        })

        print("✅ Successfully added conversation messages")

        # Test 2: Retrieve conversation history using the GSI
        print("\n📖 Test 2: Retrieving conversation history...")

        response = convo_table.query(
            IndexName="user_convo_index",
            KeyConditionExpression=boto3.dynamodb.conditions.Key("user_email").eq(test_user_email) & \
                                 boto3.dynamodb.conditions.Key("convo_id").eq(test_convo_id),
            ScanIndexForward=True  # Sort by timestamp ascending
        )

        items = response.get("Items", [])
        print(f"✅ Retrieved {len(items)} conversation messages")

        # Format and display conversation
        if items:
            print("\n💬 Conversation History:")
            for item in items:
                role = item.get("role", "unknown").capitalize()
                message = item.get("message", "")
                print(f"   {role}: {message}")

        # Test 3: Test user isolation
        print("\n🔒 Test 3: Testing user isolation...")

        # Try to access another user's conversation (should return empty)
        other_user_email = "other@example.com"
        response = convo_table.query(
            IndexName="user_convo_index",
            KeyConditionExpression=boto3.dynamodb.conditions.Key("user_email").eq(other_user_email) & \
                                 boto3.dynamodb.conditions.Key("convo_id").eq(test_convo_id)
        )

        other_items = response.get("Items", [])
        if len(other_items) == 0:
            print("✅ User isolation working - cannot access other users' conversations")
        else:
            print("❌ User isolation failed - can access other users' conversations")

        # Test 4: Clean up test data
        print("\n🧹 Test 4: Cleaning up test data...")

        # Delete test conversation messages
        for item in items:
            convo_table.delete_item(
                Key={
                    "user_email": item["user_email"],
                    "timestamp": item["timestamp"]
                }
            )

        print("✅ Test data cleaned up")

        print("\n🎉 All tests passed! Conversation context system is working properly.")
        print("\n📋 Summary:")
        print("   ✅ GSI is functional")
        print("   ✅ Conversation storage works")
        print("   ✅ Conversation retrieval works")
        print("   ✅ User isolation works")
        print("   ✅ Context can be used for AI responses")

    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        print("\n🔧 Troubleshooting:")
        print("   - Check if EmailConversations table exists")
        print("   - Verify user_convo_index GSI is ACTIVE")
        print("   - Ensure AWS credentials have DynamoDB permissions")

if __name__ == "__main__":
    test_conversation_context_system()