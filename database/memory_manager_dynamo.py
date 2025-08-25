import boto3
import os
import uuid as uuid_lib
from datetime import datetime, timedelta
from boto3.dynamodb.conditions import Key, Attr
from dotenv import load_dotenv
from botocore.exceptions import ClientError
from typing import Optional, Dict, List
from decimal import Decimal

load_dotenv("secret.env")

region = os.getenv("AWS_REGION", "ap-south-1")
dynamodb = boto3.resource("dynamodb", region_name=region)

CONVOS_TABLE = os.getenv("CONVO_TABLE", "EmailConversations")
REPLIES_TABLE = os.getenv("REPLIES_TABLE", "EmailReplies")
USER_STATUS_TABLE = os.getenv("USER_STATUS_TABLE", "UserStatus")
USERS_TABLE = os.getenv("USERS_TABLE", "Users")
PENDING_TABLE = os.getenv("PENDING_TABLE", "PendingEmails")

convo_table = dynamodb.Table(CONVOS_TABLE)
reply_table = dynamodb.Table(REPLIES_TABLE)
user_status_table = dynamodb.Table(USER_STATUS_TABLE)
users_table = dynamodb.Table(USERS_TABLE)
pending_table = dynamodb.Table(PENDING_TABLE)

SESSION_TIMEOUT_MINUTES = 5

# ---------------- Utils: sanitize floats -> Decimal ----------------

def _to_decimal(val):
    if isinstance(val, float):
        return Decimal(str(val))
    if isinstance(val, dict):
        return {k: _to_decimal(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_to_decimal(v) for v in val]
    return val

# ---------------- Users / Roles ----------------

def get_user_role(email: str) -> str:
    try:
        item = users_table.get_item(Key={"email": email}).get("Item", {}) or {}
    except Exception:
        item = {}
    role = item.get("role")
    if not role and item.get("is_admin") is True:
        role = "admin"
    if role not in ("user", "admin", "superuser"):
        role = "user"
    return role

# ---------------- User Profile and Preferences ----------------

def get_user_profile(email: str) -> dict:
    """
    Returns a merged user profile dict with both top-level and 'profile' subdoc fields.
    Expected fields (optional): name, title, org, timezone, tone, signature,
    preferences { auto_send, brevity, no_emoji, formality, warmth, cta_style },
    bio, product_context, faq, policies, crm_context.
    """
    try:
        item = users_table.get_item(Key={"email": email}).get("Item") or {}
    except Exception:
        item = {}
    profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
    # Merge flat fields into profile as fallback, keeping explicit profile keys preferred
    merged = {**{k: v for k, v in item.items() if k not in ("email", "role", "is_admin", "profile")}, **(profile or {})}
    # Ensure preferences is always a dict
    if "preferences" not in merged or not isinstance(merged["preferences"], dict):
        merged["preferences"] = {}
    return merged

def set_user_profile(email: str, new_profile: dict):
    """
    Upserts the 'profile' subdocument under Users row.
    Only writes to Users.profile to keep schema predictable.
    """
    if not isinstance(new_profile, dict):
        return
    users_table.update_item(
        Key={"email": email},
        UpdateExpression="SET #p = :p",
        ExpressionAttributeNames={"#p": "profile"},
        ExpressionAttributeValues=_to_decimal({":p": new_profile})
    )

def get_user_pref_auto_send(email: str) -> bool:
    prof = get_user_profile(email)
    return bool(prof.get("preferences", {}).get("auto_send", False))

def set_user_pref_auto_send(email: str, value: bool):
    """
    Sets profile.preferences.auto_send = value (true/false).
    If profile/preferences missing, creates them.
    """
    # Fetch current profile to avoid overwriting other fields
    prof = get_user_profile(email)
    prefs = prof.get("preferences", {}) or {}
    prefs["auto_send"] = bool(value)
    prof["preferences"] = prefs
    set_user_profile(email, prof)

# ---------------- Session + Status ----------------

def create_user_session(email: str) -> str:
    session_uuid = str(uuid_lib.uuid4())
    role = get_user_role(email)
    user_status_table.put_item(
        Item=_to_decimal({
            "email": email,
            "uuid": session_uuid,
            "status": "ACTIVE",
            "last_active": datetime.utcnow().isoformat(),
            "role": role,
        })
    )
    return session_uuid

def get_user_status(email: str) -> dict:
    try:
        return users_table.get_item(Key={"email": email}).get("Item") or {}
    except Exception:
        return {}

def update_user_activity(email: str, session_uuid: str):
    user_status_table.update_item(
        Key={"email": email},
        UpdateExpression="SET last_active = :last, #st = :stat",
        ConditionExpression="#uid = :uuid",
        ExpressionAttributeNames={
            "#st": "status",
            "#uid": "uuid",
        },
        ExpressionAttributeValues=_to_decimal({
            ":last": datetime.utcnow().isoformat(),
            ":stat": "ACTIVE",
            ":uuid": session_uuid
        })
    )

def is_session_active(email: str, session_uuid: str) -> bool:
    if not session_uuid:
        return False
    response = user_status_table.get_item(Key={"email": email})
    item = response.get("Item")
    if not item or item.get("uuid") != session_uuid:
        return False

    last_active_str = item.get("last_active")
    if not last_active_str:
        return False
    try:
        last_active = datetime.fromisoformat(last_active_str)
    except Exception:
        return False

    if datetime.utcnow() - last_active > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
        return False
    return item.get("status") == "ACTIVE"

def end_user_session(email: str, session_uuid: str):
    try:
        user_status_table.update_item(
            Key={"email": email},
            UpdateExpression="SET #st = :s",
            ConditionExpression="#uid = :uuid",
            ExpressionAttributeNames={
                "#st": "status",
                "#uid": "uuid",
            },
            ExpressionAttributeValues=_to_decimal({
                ":s": "INACTIVE",
                ":uuid": session_uuid
            })
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return
        raise

# ---------------- Conversations ----------------

def trim_history(history_text: str, max_chars: int = 8000) -> str:
    """
    Optional helper to cap history length to avoid token bloat.
    Keeps the last max_chars characters.
    """
    if not history_text:
        return ""
    if len(history_text) <= max_chars:
        return history_text
    return history_text[-max_chars:]

def update_conversation(convo_id, role, message, user_email):
    item = {
        "user_email": user_email,
        "convo_id": convo_id,
        "timestamp": datetime.utcnow().isoformat(),
        "role": role,
        "message": message
    }
    convo_table.put_item(Item=_to_decimal(item))

def get_conversation_history(convo_id, user_email):
    # Try the GSI first; fall back to a scan if index is missing
    try:
        response = convo_table.query(
            IndexName="user_convo_index",
            KeyConditionExpression=Key("user_email").eq(user_email) & Key("convo_id").eq(convo_id),
            ScanIndexForward=True
        )
        items = response.get("Items", [])
        text = "\n".join(f"{item['role'].capitalize()}: {item['message']}" for item in items)
        return trim_history(text)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code == "ValidationException":
            print(f"[WARN] user_convo_index missing; falling back to scan for {user_email}/{convo_id}")
            try:
                scan_resp = convo_table.scan(
                    FilterExpression=Attr("user_email").eq(user_email) & Attr("convo_id").eq(convo_id)
                )
                items = scan_resp.get("Items", [])
                items.sort(key=lambda x: x.get("timestamp", ""))
                text = "\n".join(f"{item['role'].capitalize()}: {item['message']}" for item in items)
                return trim_history(text)
            except Exception as se:
                print(f"[ERROR] Fallback scan failed: {se}")
                return ""
        else:
            print(f"[ERROR] Failed to fetch convo for {user_email}: {e}")
            return ""
    except Exception as e:
        print(f"[ERROR] Failed to fetch convo for {user_email}: {e}")
        return ""

# ---------------- Sent Reply Logging ----------------

def log_sent_reply(convo_id, recipient, subject, response_text, provider, user_email, pending_id: Optional[str] = None):
    timestamp = datetime.utcnow().isoformat()
    item = {
        "user_email": user_email,
        "timestamp": timestamp,
        "convo_id": convo_id,
        "recipient": recipient,
        "subject": subject,
        "response": response_text,
        "status": "SENT",
        "provider": provider,
        "id": f"{user_email}_{convo_id}_{timestamp}"
    }
    if pending_id:
        item["pending_id"] = pending_id
    reply_table.put_item(Item=_to_decimal(item))

# ---------------- Pending Emails (Inline Review Queue) ----------------

def queue_pending_email(
    user_email: str,
    provider: str,
    recipients: List[str],
    subject: str,
    body_draft: str,
    attachments: Optional[List[dict]] = None,
    sensitivity: str = "normal",
    meta: Optional[Dict] = None
) -> str:
    pid = f"{datetime.utcnow().isoformat()}_{str(uuid_lib.uuid4())}"
    item = {
        "user_email": user_email,
        "id": pid,
        "provider": provider,
        "recipients": recipients or [],
        "subject": subject or "",
        "body_draft": body_draft or "",
        "attachments": attachments or [],
        "sensitivity": sensitivity,  # normal | sensitive | high | attachment_review
        "status": "PENDING",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "meta": meta or {},
    }
    pending_table.put_item(Item=_to_decimal(item))
    return pid

def list_pending_emails(user_email: str, status: Optional[str] = None) -> list:
    """
    Lists pending items for a user. If status provided (e.g., 'PENDING' or 'DRAFT'),
    filters client-side after the query to keep the table simple.
    """
    resp = pending_table.query(
        KeyConditionExpression=Key("user_email").eq(user_email),
        ScanIndexForward=False
    )
    items = resp.get("Items", [])
    if status:
        status_l = status.upper()
        items = [it for it in items if (it.get("status") or "").upper() == status_l]

    # Try to fetch original email content for each pending item
    try:
        email_queue_table = dynamodb.Table("EmailQueue")
        for item in items:
            try:
                # Extract email_id from pending item meta
                email_id = None
                if item.get("meta") and isinstance(item.get("meta"), dict):
                    email_id = item["meta"].get("email_id")

                if email_id:
                    # Try to get the original email from EmailQueue
                    email_resp = email_queue_table.get_item(Key={"user_email": user_email, "email_id": email_id})
                    original_email = email_resp.get("Item")
                    if original_email:
                        # Add original email content to the pending item
                        item["original_email"] = {
                            "sender": original_email.get("sender"),
                            "subject": original_email.get("subject"),
                            "body": original_email.get("body"),
                            "timestamp": original_email.get("timestamp"),
                            "snippet": original_email.get("snippet")
                        }
            except Exception as e:
                print(f"[WARN] Could not fetch original email for {item.get('id', 'unknown')}: {e}")
                # Continue with other items
                continue
    except Exception as e:
        print(f"[WARN] Could not access EmailQueue table: {e}")
        # Continue without original email content

    return items

def get_pending_email(user_email: str, pid: str) -> Optional[dict]:
    resp = pending_table.get_item(Key={"user_email": user_email, "id": pid})
    item = resp.get("Item")
    if not item:
        return None

    # Try to fetch the original email content from EmailQueue table
    try:
        # Extract email_id from pending item meta or use a fallback
        email_id = None
        if item.get("meta") and isinstance(item.get("meta"), dict):
            email_id = item["meta"].get("email_id")

        if email_id:
            # Try to get the original email from EmailQueue
            email_queue_table = dynamodb.Table("EmailQueue")
            email_resp = email_queue_table.get_item(Key={"user_email": user_email, "email_id": email_id})
            original_email = email_resp.get("Item")
            if original_email:
                # Add original email content to the pending item
                item["original_email"] = {
                    "sender": original_email.get("sender"),
                    "subject": original_email.get("subject"),
                    "body": original_email.get("body"),
                    "timestamp": original_email.get("timestamp"),
                    "snippet": original_email.get("snippet")
                }
    except Exception as e:
        print(f"[WARN] Could not fetch original email content: {e}")
        # Continue without original email - it's not critical

    return item

def update_pending_email(
    user_email: str,
    pid: str,
    subject: Optional[str] = None,
    recipients: Optional[List[str]] = None,
    body_draft: Optional[str] = None
):
    expr, names, values = [], {}, {}
    if subject is not None:
        expr.append("#s = :s"); names["#s"] = "subject"; values[":s"] = subject
    if recipients is not None:
        expr.append("#r = :r"); names["#r"] = "recipients"; values[":r"] = recipients
    if body_draft is not None:
        expr.append("#b = :b"); names["#b"] = "body_draft"; values[":b"] = body_draft
    expr.append("#u = :u"); names["#u"] = "updated_at"; values[":u"] = datetime.utcnow().isoformat()
    if not expr:
        return
    pending_table.update_item(
        Key={"user_email": user_email, "id": pid},
        UpdateExpression="SET " + ", ".join(expr),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=_to_decimal(values)
    )

def mark_pending_status(user_email: str, pid: str, status: str):
    pending_table.update_item(
        Key={"user_email": user_email, "id": pid},
        UpdateExpression="SET #st = :s, #u = :u",
        ExpressionAttributeNames={"#st": "status", "#u": "updated_at"},
        ExpressionAttributeValues=_to_decimal({":s": status, ":u": datetime.utcnow().isoformat()})
    )

def mark_pending_sent(user_email: str, pid: str):
    mark_pending_status(user_email, pid, "SENT")

def mark_pending_canceled(user_email: str, pid: str):
    mark_pending_status(user_email, pid, "CANCELED")