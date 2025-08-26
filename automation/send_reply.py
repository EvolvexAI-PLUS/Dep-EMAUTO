import boto3
import os
import json
import time
from datetime import datetime
from dotenv import load_dotenv

from automation.clients.gmail_client import GmailClient
from automation.clients.outlook_client import OutlookClient
from automation.clients.yahoo_client import YahooClient
from automation.clients.custom_email_client import CustomEmailClient

from database.memory_manager_dynamo import (
    update_conversation,
    log_sent_reply,
    is_session_active,
    queue_pending_email,
    get_pending_email,
    mark_pending_sent,
)
from automation.generate_reply import generate_replies
from automation.extract_emails import extract_emails

load_dotenv("secret.env")

dynamodb = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "ap-south-1"))
REPLY_QUEUE_TABLE = os.getenv("REPLY_QUEUE_TABLE", "ReplyQueue")
EMAIL_QUEUE_TABLE = os.getenv("EMAIL_QUEUE_TABLE", "EmailQueue")

reply_table = dynamodb.Table(REPLY_QUEUE_TABLE)
email_table = dynamodb.Table(EMAIL_QUEUE_TABLE)

# ---------------- CLIENT FACTORY ----------------
def get_email_client(provider, token, email):
    if provider == "google":
        return GmailClient(token)
    elif provider == "outlook":
        return OutlookClient(token["access_token"], token.get("client_id"))
    elif provider == "yahoo":
        return YahooClient({"access_token": token["access_token"], "email": email})
    elif provider == "custom":
        return CustomEmailClient(token)
    elif provider == "imap":
        # For IMAP, we need to get user credentials from database
        from database.memory_manager_dynamo import get_user_profile
        user_profile = get_user_profile(email) or {}

        if not user_profile.get('imap_server'):
            raise ValueError(f"IMAP configuration not found for {email}")

        # Get IMAP credentials
        credentials = {
            'email': email,
            'imap_server': user_profile.get('imap_server'),
            'imap_port': user_profile.get('imap_port', 993),
            'smtp_server': user_profile.get('smtp_server'),
            'smtp_port': user_profile.get('smtp_port', 587),
            'password_hash': user_profile.get('imap_password_encrypted'),
            'use_ssl': user_profile.get('use_ssl', True)
        }

        from automation.clients.imap_client import IMAPClient
        return IMAPClient(credentials)
    else:
        raise ValueError(f"[ERROR] Unsupported provider: {provider}")

# ---------------- HELPERS ----------------
def extract_sender_email(sender_info):
    # Accepts either string email or {"emailAddress":{"address":"x@y.com"}}
    if isinstance(sender_info, str):
        # If a full "Name <email>" string was stored, try to parse
        if "@" in sender_info:
            import re as _re
            m = _re.search(r'<([^>]+)>', sender_info)
            return (m.group(1) if m else sender_info).strip().strip('"')
        return ""
    elif isinstance(sender_info, dict):
        return sender_info.get("emailAddress", {}).get("address", "")
    return ""

def detect_review_needed(email_record: dict) -> tuple[bool, str]:
    do_not = email_record.get("do_not_auto_reply") is True
    attachments = email_record.get("attachments") or []
    confidential = str(email_record.get("sensitivity", "")).lower() in ("confidential", "high", "restricted")
    if do_not:
        return True, "do_not_auto_reply"
    if attachments:
        return True, "attachment_review"
    if confidential:
        return True, "confidential"
    return False, "normal"

def queue_pending_from_reply(provider, user_email, email_record, subject, reply_text):
    sender_info = email_record.get("sender")
    to_email = extract_sender_email(sender_info)
    recipients = [to_email] if to_email else []
    attachments = email_record.get("attachments") or []
    convo_id = email_record.get("conversationId") or email_record.get("email_id")
    sensitivity = "normal"
    needs_review, reason = detect_review_needed(email_record)
    if needs_review:
        sensitivity = reason

    # Include thread + message-id header for proper threading on approval
    meta = {
        "convo_id": convo_id,
        "email_id": email_record.get("email_id"),
        "original_subject": email_record.get("subject", ""),
        "thread_id": email_record.get("thread_id") or email_record.get("conversationId"),
        "message_id_header": email_record.get("message_id_header"),
        "reason": reason,
    }

    pid = queue_pending_email(
        user_email=user_email,
        provider=provider,
        recipients=recipients,
        subject=subject,
        body_draft=reply_text,
        attachments=attachments,
        sensitivity=sensitivity,
        meta=meta,
    )
    return pid

# ---------------- REPLY PROCESSOR ----------------
def process_replies(provider, token, user_email):
    print(f"[SEND] 🚀 Processing replies for {user_email} via {provider}")
    client = get_email_client(provider, token, user_email)

    try:
        response = reply_table.scan(
            FilterExpression="#status = :ready AND user_email = :email",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":ready": "ready_to_send", ":email": user_email}
        )
    except Exception as e:
        print(f"[ERROR] ❌ Failed to scan ReplyQueue: {e}")
        return

    items = response.get("Items", [])
    print(f"[DEBUG] 📨 Found {len(items)} replies to process for {user_email}")

    for item in items:
        try:
            reply_id = item["reply_id"]
            email_id = item["email_id"]
            reply_text = item["reply_text"]

            email_record = email_table.get_item(
                Key={"user_email": user_email, "email_id": email_id}
            ).get("Item", {})

            if not email_record:
                print(f"[SKIP] ⚠️ No email record found for {email_id}")
                continue

            sender_info = email_record.get("sender")
            to_email = extract_sender_email(sender_info)
            if not to_email:
                print(f"[SKIP] ⚠️ Invalid sender email for {email_id}: {sender_info}")
                continue

            original_subject = email_record.get("subject", "")
            subject = f"Re: {original_subject}" if original_subject else "Re: [No Subject]"
            convo_id = email_record.get("conversationId", email_id)
            original_body = email_record.get("body", "")

            needs_review, reason = detect_review_needed(email_record)
            if needs_review:
                # Queue for inline review instead of sending now
                queue_pending_from_reply(provider, user_email, email_record, subject, reply_text)

                # Mark this reply as queued (not sent)
                reply_table.update_item(
                    Key={"user_email": user_email, "reply_id": reply_id},
                    UpdateExpression="SET #status = :queued, #ts = :ts",
                    ConditionExpression="#status = :ready",
                    ExpressionAttributeNames={"#status": "status", "#ts": "timestamp"},
                    ExpressionAttributeValues={
                        ":queued": "queued_for_review",
                        ":ready": "ready_to_send",
                        ":ts": datetime.utcnow().isoformat()
                    }
                )
                print(f"[QUEUED 📝] Inline review queued for reply_id={reply_id} reason={reason}")
                continue

            # Otherwise send immediately with threading info where available
            thread_id = email_record.get("thread_id") or email_record.get("conversationId")
            in_reply_to = email_record.get("message_id_header")
            references = in_reply_to

            try:
                client.send_email(
                    to_email,
                    subject,
                    reply_text,
                    thread_id=thread_id,
                    in_reply_to=in_reply_to,
                    references=references
                )
            except Exception as send_err:
                print(f"[ERROR] ❌ Failed to send to {to_email}: {send_err}")
                continue

            # Mark reply as sent if it was ready_to_send
            reply_table.update_item(
                Key={"user_email": user_email, "reply_id": reply_id},
                UpdateExpression="SET #status = :sent, #ts = :ts",
                ConditionExpression="#status = :ready",
                ExpressionAttributeNames={"#status": "status", "#ts": "timestamp"},
                ExpressionAttributeValues={
                    ":sent": "sent",
                    ":ready": "ready_to_send",
                    ":ts": datetime.utcnow().isoformat()
                }
            )

            update_conversation(convo_id, "user", original_body, user_email)
            update_conversation(convo_id, "assistant", reply_text, user_email)
            log_sent_reply(convo_id, to_email, subject, reply_text, provider, user_email)

            print(f"[SENT ✅] Email sent to {to_email} for {reply_id}")

        except Exception as e:
            print(f"[ERROR] ❌ Failed on reply_id={item.get('reply_id')}: {e}")

# ---------------- SEND PENDING (after user approval) ----------------
def send_pending_email(provider, token, user_email: str, pending_id: str):
    # Called from routes pending_send endpoint
    item = get_pending_email(user_email, pending_id)
    if not item or item.get("status") != "PENDING":
        return False, "Not found or not pending"

    client = get_email_client(provider or item.get("provider"), token, user_email)

    recipients = item.get("recipients") or []
    if not recipients:
        return False, "Missing recipients"

    subject = item.get("subject") or ""
    body = item.get("body_draft") or ""
    to_email = recipients[0]

    # Threading info from meta
    meta = item.get("meta") or {}
    thread_id = meta.get("thread_id")
    in_reply_to = meta.get("message_id_header")
    references = in_reply_to

    try:
        client.send_email(
            to_email,
            subject,
            body,
            thread_id=thread_id,
            in_reply_to=in_reply_to,
            references=references
        )
    except Exception as send_err:
        return False, f"Send failed: {send_err}"

    convo_id = meta.get("convo_id", pending_id)
    update_conversation(convo_id, "assistant", body, user_email)
    log_sent_reply(convo_id, to_email, subject, body, item.get("provider"), user_email, pending_id=pending_id)
    mark_pending_sent(user_email, pending_id)
    return True, None

# ---------------- CONTINUOUS RUNNER ----------------
def main_loop(provider, token, email, session_uuid):
    print(f"[LOOP] 🔁 Starting loop for {email} with session {session_uuid}")
    if not session_uuid:
        print(f"[LOOP] 🛑 No session UUID for {email}. Exiting loop.")
        return

    while True:
        try:
            if not is_session_active(email, session_uuid):
                print(f"[LOOP] 🛑 Session {session_uuid} for {email} ended or invalid. Exiting loop.")
                break

            extract_emails(provider, token, email)
            generate_replies()
            process_replies(provider, token, email)

        except Exception as e:
            print(f"[LOOP ERROR] 🛑 {e}")

        time.sleep(30)

# ---------------- CLI ENTRY ----------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()

    token = json.loads(args.token)
    # Process replies once (used for testing)
    process_replies(args.provider, token, args.email)