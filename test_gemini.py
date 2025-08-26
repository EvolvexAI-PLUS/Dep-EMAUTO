#!/usr/bin/env python3
"""
Test script to verify Gemini AI integration
"""
import os
import sys

# Add the current directory to the path so we can import the modules
sys.path.append('.')

# Load environment variables
if os.path.exists('secret.env'):
    with open('secret.env', 'r') as f:
        for line in f:
            if '=' in line and not line.strip().startswith('#'):
                key, value = line.strip().split('=', 1)
                os.environ[key] = value

from automation.llm.gemini_interface import test_gemini_integration, classify_and_draft

def test_gemini():
    print("🚀 Starting Gemini Integration Test...")
    print("=" * 50)

    # Test basic integration
    success = test_gemini_integration()

    if not success:
        print("\n❌ Gemini integration test failed!")
        print("🔧 Troubleshooting:")
        print("1. Check if GEMINI_API_KEY is set in secret.env")
        print("2. Verify the API key is valid")
        print("3. Ensure you have internet connection")
        return False

    print("\n✅ Gemini basic integration working!")

    # Test email classification
    print("\n📧 Testing email classification...")
    test_email = {
        "subject": "Meeting tomorrow",
        "body": "Hi, can we schedule a meeting for tomorrow at 2 PM?",
        "sender": "john@example.com",
        "user_email": "test@example.com"
    }

    try:
        result = classify_and_draft(test_email)
        print(f"🤖 AI Classification Result:")
        print(f"   Action: {result.get('action')}")
        print(f"   Confidence: {result.get('confidence')}")
        print(f"   Subject: {result.get('suggested_subject')}")
        print(f"   Reply Preview: {result.get('suggested_reply', '')[:100]}...")

        if result.get('suggested_reply'):
            print("\n✅ Email classification and drafting working!")
            return True
        else:
            print("\n⚠️ Classification worked but no reply generated")
            return False

    except Exception as e:
        print(f"\n❌ Email classification failed: {e}")
        return False

if __name__ == "__main__":
    success = test_gemini()
    print("=" * 50)
    if success:
        print("🎉 Gemini integration is working correctly!")
    else:
        print("🔧 Gemini integration needs fixing")
    sys.exit(0 if success else 1)