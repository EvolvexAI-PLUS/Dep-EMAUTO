import boto3
import os
import json
from datetime import datetime
from dotenv import load_dotenv
from automation.clients.gmail_client import GmailClient
from automation.clients.outlook_client import OutlookClient
from automation.clients.yahoo_client import YahooClient
from automation.clients.custom_email_client import CustomEmailClient
from automation.llm.claude_interface import is_invalid_recipient

load_dotenv("secret.env")

dynamodb = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "ap-south-1"))
EMAIL_QUEUE_TABLE = os.getenv("EMAIL_QUEUE_TABLE", "EmailQueue")
email_table = dynamodb.Table(EMAIL_QUEUE_TABLE)

def get_email_client(provider: str, token: dict, email: str):
    try:
        if provider == "google":
            return GmailClient(token)
        elif provider == "outlook":
            return OutlookClient(token["access_token"], token.get("client_id"))
        elif provider == "yahoo":
            return YahooClient({"access_token": token["access_token"], "email": email})
        elif provider == "custom":
            return CustomEmailClient(token)
        else:
            raise ValueError(f"Unsupported provider: {provider}")
    except Exception as e:
        raise RuntimeError(f"[INIT ❌] Failed to initialize client for {provider}: {e}")

def _normalize_sender(provider: str, email_data: dict) -> dict | str:
    """
    Normalize sender into a format compatible with send_reply.extract_sender_email.
    Preferred: {"emailAddress": {"address": "addr@x.com"}}
    """
    if provider == "outlook":
        # Outlook already returns desired structure
        return email_data.get("from", {})  # expect {"emailAddress": {"address": "..."}}
    else:
        # Gmail client now returns {'from': {'emailAddress': {'address': 'x@y.com'}}}
        frm = email_data.get("from")
        if isinstance(frm, dict) and frm.get("emailAddress"):
            return frm
        # Fallback to string if unknown client shape
        raw_sender = frm or ""
        return str(raw_sender)

def extract_emails(provider: str, token: dict, user_email: str):
    print(f"[EXTRACT] 🔍 Starting extraction for {user_email} via '{provider}'")

    try:
        client = get_email_client(provider, token, user_email)
    except Exception as e:
        print(f"[ERROR] ❌ Client initialization failed: {e}")
        return

    try:
        emails = client.fetch_unread_emails()
        print(f"[EXTRACT] 📥 {len(emails)} unread emails fetched")
    except Exception as e:
        print(f"[ERROR] ❌ Failed to fetch unread emails: {type(e).__name__}: {e}")
        return

    for email_data in emails:
        try:
            email_id = email_data.get("id") or email_data.get("email_id")
            subject = (email_data.get("subject") or "No Subject").strip()
            # Body location varies slightly per client
            body = (email_data.get("body", {}) or {}).get("content", "")
            body = (body or "").strip()

            # Normalize sender for all providers
            sender_norm = _normalize_sender(provider, email_data)

            # Extract a plain string address for early skip checks
            if isinstance(sender_norm, dict):
                sender_for_skip = sender_norm.get("emailAddress", {}).get("address", "")
            else:
                sender_for_skip = sender_norm

            if not email_id or not sender_for_skip:
                print(f"[SKIP] ⚠️ Missing sender or email ID: {email_id}")
                continue

            # Optional early skip to reduce LLM load
            if is_invalid_recipient(sender_for_skip):
                print(f"[SKIP] Not queuing system/bot address: {sender_for_skip}")
                email_table.put_item(Item={
                    "user_email": user_email,
                    "email_id": email_id,
                    "sender": sender_norm,
                    "subject": subject[:500],
                    "body": body[:5000],
                    "provider": provider,
                    "status": "skipped",
                    "triage_status": "ignore",
                    "triage_reason": "Automated or no-reply sender",
                    "timestamp": datetime.utcnow().isoformat(),
                    # Keep conversation context fields to avoid downstream issues
                    "conversationId": email_data.get("conversationId") or email_id,
                })
                try:
                    client.mark_as_read(email_id)
                except Exception as e:
                    print(f"[WARN] ⚠️ Could not mark email as read: {email_id} — {e}")
                continue

            # Deduplication Check
            try:
                exists = email_table.get_item(Key={"user_email": user_email, "email_id": email_id}).get("Item")
                if exists:
                    print(f"[SKIP] 🟡 Duplicate email skipped: {email_id}")
                    continue
            except Exception as e:
                print(f"[WARN] 🔄 Deduplication check failed for {email_id}: {e}")

            # Threading metadata (present for Gmail; may be empty for others)
            thread_id = email_data.get("threadId") or email_data.get("thread_id")
            message_id_header = email_data.get("messageIdHeader") or email_data.get("message_id_header")

            item = {
                "user_email": user_email,
                "email_id": email_id,
                "sender": sender_norm,  # dict with emailAddress.address or string
                "subject": subject[:500],
                "body": body[:5000],
                "provider": provider,
                "status": "pending",
                "triage_status": "pending",
                "timestamp": datetime.utcnow().isoformat(),
                "conversationId": email_data.get("conversationId") or thread_id or email_id,
                "snippet": (email_data.get("snippet") or "")[:1000],
                "thread": (email_data.get("thread") or "")[:4000],
            }

            # Persist threading fields explicitly so send paths can use them
            if thread_id:
                item["thread_id"] = thread_id
            if message_id_header:
                item["message_id_header"] = message_id_header

            email_table.put_item(Item=item)
            print(f"[QUEUE ✅] Email queued: {email_id} — {subject[:60]}")

            try:
                client.mark_as_read(email_id)
            except Exception as e:
                print(f"[WARN] ⚠️ Could not mark email as read: {email_id} — {e}")

        except Exception as e:
            print(f"[ERROR] ❌ Failed processing email: {type(e).__name__} — {e}")
            try:
                print(f"[DEBUG] 📄 Raw email: {json.dumps(email_data, indent=2)}")
            except Exception:
                print("[DEBUG] 📄 Raw email could not be serialized")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Extract unread emails from specified provider")
    parser.add_argument("--provider", required=True, help="Email provider: google, outlook, yahoo, custom")
    parser.add_argument("--token", required=True, help="JSON string token or access_token object")
    parser.add_argument("--email", required=True, help="User email address")
    args = parser.parse_args()
    try:
        token = json.loads(args.token)
    except json.JSONDecodeError as e:
        print(f"[ERROR] ❌ Invalid token JSON: {e}")
        exit(1)
    extract_emails(args.provider, token, args.email)
