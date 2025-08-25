import os
import json
import boto3
from datetime import datetime
from dotenv import load_dotenv
from decimal import Decimal

from automation.llm.claude_interface import (
    is_invalid_recipient,
    classify_and_draft,
)
from database.memory_manager_dynamo import (
    get_conversation_history,
    queue_pending_email,
    get_user_profile,  # make sure this exists (see notes below)
)

load_dotenv("secret.env")

dynamodb = boto3.resource('dynamodb', region_name=os.getenv("AWS_REGION", "ap-south-1"))
EMAIL_QUEUE_TABLE = os.getenv("EMAIL_QUEUE_TABLE", "EmailQueue")
REPLY_QUEUE_TABLE = os.getenv("REPLY_QUEUE_TABLE", "ReplyQueue")
email_table = dynamodb.Table(EMAIL_QUEUE_TABLE)
reply_table = dynamodb.Table(REPLY_QUEUE_TABLE)

# If you want AUTO_REPLY drafts to appear in Pending for approval, set True
MIRROR_DRAFTS_TO_PENDING = True

# ---------- Utils ----------
def _to_decimal(val):
    if isinstance(val, float):
        return Decimal(str(val))
    if isinstance(val, dict):
        return {k: _to_decimal(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_to_decimal(v) for v in val]
    return val

def _extract_sender_email(sender_raw) -> str:
    if isinstance(sender_raw, dict):
        return sender_raw.get("emailAddress", {}).get("address", "") or sender_raw.get("email", "")
    return str(sender_raw or "")

def load_templates() -> list:
    path = "automation/templates/reply_templates.json"
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception:
        return []

# ---------- Persona & Prompt with Profile Context ----------
def _format_profile_persona(user_email: str, profile: dict) -> str:
    name = profile.get("name") or user_email.split('@')[0].replace('.', ' ').title()
    org = profile.get("org") or os.getenv("ORG_NAME", "")
    title = profile.get("title") or ""
    tz = profile.get("timezone") or ""
    tone = profile.get("tone") or os.getenv("DEFAULT_TONE", "polite, concise, professional")
    # signature in profile overrides env; fallback to a basic signoff with name
    signoff = profile.get("signature") or os.getenv("DEFAULT_SIGNOFF", f"Best regards,\n{name}")
    prefs = profile.get("preferences", {}) or {}

    pref_lines = []
    if prefs.get("brevity") is True: pref_lines.append("Write succinctly.")
    if prefs.get("no_emoji") is True: pref_lines.append("Avoid emojis.")
    if prefs.get("formality"): pref_lines.append("Use a formal tone.")
    if prefs.get("warmth"): pref_lines.append("Be warm and friendly.")
    if prefs.get("cta_style"): pref_lines.append(f"Call-to-action style: {prefs.get('cta_style')}.")

    who = f"You are replying as {name}"
    if title: who += f", {title}"
    if org: who += f" at {org}"
    who += f" <{user_email}>.\n"

    tz_line = f"User timezone: {tz}\n" if tz else ""
    pref_text = (" ".join(pref_lines)).strip()

    guardrails = (
        "Safety and policy:\n"
        "- Do not fabricate facts, prices, or commitments.\n"
        "- Never share sensitive information or passwords.\n"
        "- If the request is unclear, ask 1 concise clarifying question.\n"
        "- Keep it brief, specific, and actionable.\n"
        "- Maintain the existing thread subject and context.\n"
    )

    return (
        f"{who}"
        f"{tz_line}"
        f"Tone: {tone}.\n"
        f"{guardrails}"
        f"{('Preferences: ' + pref_text + '\\n') if pref_text else ''}"
        f"Always sign off exactly as:\n{signoff}\n"
    )

def _build_context_block(profile: dict) -> str:
    lines = []
    if profile.get("bio"): lines.append(f"Bio: {profile['bio']}")
    if profile.get("product_context"): lines.append(f"Product context: {profile['product_context']}")
    if profile.get("faq"): lines.append(f"FAQs: {profile['faq']}")
    if profile.get("policies"): lines.append(f"Policies: {profile['policies']}")
    if profile.get("crm_context"): lines.append(f"CRM context: {profile['crm_context']}")
    if not lines: return ""
    return "Reference context:\n" + "\n".join(lines) + "\n"

def build_persona(user_email: str, profile: dict) -> str:
    return _format_profile_persona(user_email, profile)

def build_reply_prompt(email_body: str, history: str, sender: str, user_email: str, templates: list, profile: dict) -> str:
    persona = build_persona(user_email, profile)
    context_block = _build_context_block(profile)
    instructions = (
        "Task:\n"
        "1) If this email does NOT require a reply, respond with exactly [NO_REPLY_NEEDED].\n"
        "2) If a reply IS needed, produce only the email body text to send (no preamble, no quotes).\n"
    )
    template_hint = ""
    for temp in templates:
        if temp.get("keyword", "").lower() in (email_body or "").lower():
            template_hint = f"Use this structure if it fits:\n{temp.get('template','')}\n"
            break

    context = f"Conversation so far:\n{history}\n\n" if history else ""
    return (
        f"{persona}\n"
        f"{context_block}"
        f"{instructions}\n"
        f"{template_hint}"
        f"{context}"
        f"Sender: {sender}\n"
        f"Incoming Email:\n{email_body}\n"
    )

# ---------- Main ----------
def generate_replies(max_per_run: int = 5):
    templates = load_templates()
    print("[GEN] Scanning for pending emails...")

    try:
        response = email_table.scan(
            FilterExpression="attribute_not_exists(#status) OR #status = :pending",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":pending": "pending"}
        )
        items = response.get("Items", [])
    except Exception as e:
        print(f"[ERROR] Email table scan failed: {e}")
        return

    print(f"[GEN] Found {len(items)} pending emails")
    items = items[:max_per_run]

    for item in items:
        try:
            if not all(k in item for k in ["email_id", "user_email", "body", "sender"]):
                print(f"[SKIP] Missing fields in email item: {json.dumps(item)}")
                continue

            email_id = item["email_id"]
            user_email = item["user_email"]
            body = item["body"]
            sender_raw = item["sender"]
            convo_id = item.get("conversationId", email_id)
            provider = item.get("provider", "google")

            sender_email = _extract_sender_email(sender_raw)
            if is_invalid_recipient(sender_email):
                print(f"[SKIP] Not replying to system/bot address: {sender_email}")
                email_table.update_item(
                    Key={"user_email": user_email, "email_id": email_id},
                    UpdateExpression="SET #status = :skipped",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={":skipped": "skipped"}
                )
                continue

            # Pull personalized profile
            profile = get_user_profile(user_email) or {}

            # Conversation context
            history = get_conversation_history(convo_id, user_email)

            # Build richer prompt and pass context to triage/draft
            persona_text = build_persona(user_email, profile)
            prompt_text = build_reply_prompt(body, history, sender_email, user_email, templates, profile)

            triage = classify_and_draft({
                "subject": item.get("subject", ""),
                "body": body,
                "sender": sender_email,
                "snippet": item.get("snippet", ""),
                "thread": item.get("thread", ""),
                "user_email": user_email,
                "email_id": email_id,
                "history": history,
                "persona": persona_text,
                "prompt": prompt_text,
                "profile": profile,
            })

            action = triage.get("action", "HUMAN_REVIEW")
            reason = triage.get("reason", "")
            reply_text = (triage.get("suggested_reply") or "").strip()
            subject = triage.get("suggested_subject") or f"Re: {item.get('subject','')}"

            if action == "IGNORE":
                # Audit and mark skipped
                reply_table.put_item(Item=_to_decimal({
                    "reply_id": f"r-{email_id}",
                    "user_email": user_email,
                    "email_id": email_id,
                    "status": "ignored",
                    "timestamp": datetime.utcnow().isoformat(),
                    "triage_reason": reason
                }))
                email_table.update_item(
                    Key={"user_email": user_email, "email_id": email_id},
                    UpdateExpression="SET #status = :skipped, triage_status = :ts, triage_reason = :tr",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues=_to_decimal({
                        ":skipped": "skipped",
                        ":ts": "ignore",
                        ":tr": reason
                    })
                )
                print(f"[SKIP] Ignored by triage for {email_id}: {reason}")
                continue

            # If model couldn’t produce a draft, force human review
            if not reply_text:
                action = "HUMAN_REVIEW"

            # Per-user auto-send toggle
            prefs = profile.get("preferences", {}) or {}
            auto_send = bool(prefs.get("auto_send", False))

            if action == "AUTO_REPLY":
                status = "ready_to_send" if auto_send else "draft"
            else:
                status = "needs_review"

            # Store reply into ReplyQueue
            reply_item = {
                "reply_id": f"r-{email_id}",
                "user_email": user_email,
                "email_id": email_id,
                "reply_text": reply_text,
                "subject": subject,
                "status": status,  # ready_to_send | draft | needs_review
                "timestamp": datetime.utcnow().isoformat(),
                "triage_reason": reason,
                "confidence": float(triage.get("confidence", 0.0)),
                "metadata": triage.get("metadata", {}),
                "history_used": bool(history),
                "provider": provider,
            }
            reply_table.put_item(Item=_to_decimal(reply_item))

            # Mirror to PendingEmails:
            # - Always mirror needs_review
            # - Optionally mirror AUTO_REPLY drafts when auto-send is off
            should_mirror = (status == "needs_review") or (status == "draft" and MIRROR_DRAFTS_TO_PENDING)
            if should_mirror:
                meta = {
                    "convo_id": item.get("conversationId") or item.get("thread_id") or email_id,
                    "email_id": email_id,
                    "original_subject": item.get("subject", ""),
                    "provider": provider,
                }
                if "thread_id" in item:
                    meta["thread_id"] = item["thread_id"]
                if "message_id_header" in item:
                    meta["message_id_header"] = item["message_id_header"]

                recipients = [sender_email] if sender_email else []
                queue_pending_email(
                    user_email=user_email,
                    provider=provider,
                    recipients=recipients,
                    subject=subject,
                    body_draft=reply_text or "",
                    attachments=item.get("attachments") or [],
                    sensitivity="normal",
                    meta=meta
                )

            # Update EmailQueue row
            email_table.update_item(
                Key={"user_email": user_email, "email_id": email_id},
                UpdateExpression="SET #status = :processed, triage_status = :ts, triage_reason = :tr, suggested_subject = :ss, suggested_reply = :sr",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues=_to_decimal({
                    ":processed": "processed",
                    ":ts": action.lower(),
                    ":tr": reason,
                    ":ss": subject[:500],
                    ":sr": reply_text[:5000],
                })
            )

            print(f"[REPLY ✅] {status} created for {email_id} ({action})")

        except Exception as e:
            print(f"[ERROR ❌] Failed on email {item.get('email_id')}: {e}")

# ---------------- Entrypoint ----------------
if __name__ == "__main__":
    generate_replies()