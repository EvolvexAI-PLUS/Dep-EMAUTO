# automation/__init__.py
# Load environment automatically when importing this package
from dotenv import load_dotenv
load_dotenv("secret.env")


# automation/clients/__init__.py
# Expose all supported clients for easier import
from automation.clients.gmail_client import GmailClient
from automation.clients.outlook_client import OutlookClient
from automation.clients.yahoo_client import YahooClient
from automation.clients.custom_email_client import CustomEmailClient


# automation/llm/__init__.py
# Shortcut for generate_reply
from automation.llm.claude_interface import generate_reply_text

# database/__init__.py
# Shortcut for memory operations
from database.memory_manager_dynamo import (
    update_conversation,
    get_conversation_history,
    log_sent_reply
)
