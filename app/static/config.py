import os
from dotenv import load_dotenv

# Load variables from secrets.env
load_dotenv("secret.env")

class Config:
    AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
    REPLIES_TABLE = os.getenv("REPLIES_TABLE", "EmailReplies")
    QUEUE_TABLE = os.getenv("EMAIL_QUEUE_TABLE", "EmailQueue")
    FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "fallback-key")

    # Google OAuth
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

    # Outlook OAuth
    OUTLOOK_CLIENT_ID = os.getenv("OUTLOOK_CLIENT_ID")
    OUTLOOK_CLIENT_SECRET = os.getenv("OUTLOOK_CLIENT_SECRET")

    # Yahoo OAuth
    YAHOO_CLIENT_ID = os.getenv("YAHOO_CLIENT_ID")
    YAHOO_CLIENT_SECRET = os.getenv("YAHOO_CLIENT_SECRET")

    # Claude Model
    BEDROCK_CLAUDE_MODEL = os.getenv("BEDROCK_CLAUDE_MODEL", "anthropic.claude-3-sonnet-20240229-v1:0")