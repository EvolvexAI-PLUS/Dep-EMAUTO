#!/usr/bin/env python3
"""
Test script to verify all required dependencies are available
Run this before deploying to ensure no import errors
"""

def test_imports():
    """Test all imports used in the application"""
    print("🧪 Testing imports...")

    try:
        # Standard library imports
        import os, json, time, re, logging, threading, uuid, datetime, random, secrets, functools
        import imaplib, smtplib, email, base64
        from email.message import EmailMessage
        from datetime import datetime, timedelta
        from typing import Optional, Dict, Any, List
        from decimal import Decimal
        print("✅ Standard library imports: OK")
    except ImportError as e:
        print(f"❌ Standard library import failed: {e}")
        return False

    try:
        # Third-party imports
        import flask
        from flask import Blueprint, Flask, render_template, request, redirect, url_for, session, make_response
        print("✅ Flask imports: OK")
    except ImportError as e:
        print(f"❌ Flask import failed: {e}")
        return False

    try:
        import requests
        print("✅ requests import: OK")
    except ImportError as e:
        print(f"❌ requests import failed: {e}")
        return False

    try:
        import boto3
        from boto3.dynamodb.conditions import Key, Attr
        from botocore.exceptions import BotoCoreError, ClientError
        from botocore.config import Config
        print("✅ boto3 and botocore imports: OK")
    except ImportError as e:
        print(f"❌ boto3/botocore import failed: {e}")
        return False

    try:
        import jwt
        print("✅ jwt import: OK")
    except ImportError as e:
        print(f"❌ jwt import failed: {e}")
        return False

    try:
        from authlib.integrations.flask_client import OAuth
        import msal
        print("✅ authlib and msal imports: OK")
    except ImportError as e:
        print(f"❌ authlib/msal import failed: {e}")
        return False

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token
        print("✅ google-auth imports: OK")
    except ImportError as e:
        print(f"❌ google-auth import failed: {e}")
        return False

    try:
        from dotenv import load_dotenv
        print("✅ python-dotenv import: OK")
    except ImportError as e:
        print(f"❌ python-dotenv import failed: {e}")
        return False

    print("🎉 All imports successful!")
    return True

def test_app_initialization():
    """Test that the Flask app can be initialized"""
    print("\n🧪 Testing Flask app initialization...")

    try:
        from app.routes import init_app
        from flask import Flask

        app = Flask(__name__)
        app.secret_key = "test-secret"

        # This will test all the imports in the routes module
        init_app(app)
        print("✅ Flask app initialization: OK")
        return True
    except Exception as e:
        print(f"❌ Flask app initialization failed: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Starting dependency verification...\n")

    success = True
    success &= test_imports()
    success &= test_app_initialization()

    if success:
        print("\n🎉 All tests passed! Ready for deployment.")
        exit(0)
    else:
        print("\n❌ Some tests failed. Please check dependencies.")
        exit(1)