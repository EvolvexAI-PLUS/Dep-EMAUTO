import os
import json
import time
import random
import re
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

import boto3
from dotenv import load_dotenv
from botocore.exceptions import BotoCoreError, ClientError
from botocore.config import Config

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Env ---
load_dotenv("secret.env")
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", AWS_REGION)
BEDROCK_MODEL_ID = os.getenv("BEDROCK_CLAUDE_MODEL", "anthropic.claude-3-sonnet-20240229-v1:0")

EMAIL_QUEUE_TABLE = os.getenv("EMAIL_QUEUE_TABLE", "EmailQueue")
REPLY_QUEUE_TABLE = os.getenv("REPLY_QUEUE_TABLE", "ReplyQueue")

MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "5"))
INITIAL_BACKOFF_SECONDS = float(os.getenv("LLM_INITIAL_BACKOFF_SECONDS", "1.0"))
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "900"))

# --- AWS clients ---
bedrock = boto3.client(
    "bedrock-runtime",
    region_name=BEDROCK_REGION,
    config=Config(retries={"max_attempts": 3, "mode": "standard"})
)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
email_table = dynamodb.Table(EMAIL_QUEUE_TABLE)
reply_table = dynamodb.Table(REPLY_QUEUE_TABLE)

# --- Utils ---
NO_REPLY_REGEX = re.compile(r'(no-?reply|do[\s-]?not[\s-]?reply|donotreply|auto-?reply|mailer-daemon|bounce|bounces?|postmaster|support)', re.IGNORECASE)

def is_invalid_recipient(email_address: str) -> bool:
    if not email_address or not isinstance(email_address, str):
        return True
    return NO_REPLY_REGEX.search(email_address) is not None

def safe_get_sender_string(sender: Any) -> str:
    if isinstance(sender, str):
        return sender
    if isinstance(sender, dict):
        if "emailAddress" in sender:
            return sender["emailAddress"].get("address") or sender["emailAddress"].get("name") or ""
        return sender.get("address") or sender.get("email") or sender.get("name") or ""
    return ""

# --- Bedrock helpers ---
def _bedrock_messages_body(system_prompt: str, user_prompt: str, max_tokens: int = MAX_TOKENS, temperature: float = TEMPERATURE) -> dict:
    return {
        "anthropic_version": "bedrock-2023-05-31",
        "system": system_prompt,
        "messages": [{"role": "user", "content": [{"type": "text", "text": user_prompt}]}],
        "max_tokens": max_tokens,
        "temperature": temperature
    }

def _invoke_bedrock_json(body: dict, model_id: str = BEDROCK_MODEL_ID) -> dict:
    for attempt in range(MAX_RETRIES):
        try:
            resp = bedrock.invoke_model(
                modelId=model_id,
                accept="application/json",
                contentType="application/json",
                body=json.dumps(body).encode("utf-8"),
            )
            return json.loads(resp["body"].read())
        except (BotoCoreError, ClientError) as e:
            throttled = "Throttling" in str(e) or "ThrottlingException" in str(e)
            level = logging.WARNING if throttled else logging.ERROR
            if attempt < MAX_RETRIES - 1:
                backoff = (INITIAL_BACKOFF_SECONDS * (2 ** attempt)) + random.uniform(0, 1)
                logging.log(level, f"Bedrock invoke error {attempt+1}/{MAX_RETRIES}: {e}. Retry in {backoff:.2f}s")
                time.sleep(backoff)
            else:
                logging.error(f"Bedrock failed after {MAX_RETRIES} attempts: {e}")
                raise
        except Exception as e:
            logging.error(f"Unexpected Bedrock error: {e}", exc_info=True)
            raise
    return {}

def _extract_text_from_payload(payload: dict) -> str:
    content = payload.get("content", [])
    out = []
    if isinstance(content, list):
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") == "text":
                out.append(blk.get("text", ""))
    return "".join(out).strip()

# --- Prompts ---
SYSTEM_PROMPT = """You are an email assistant for a busy professional. Your job:
1) Decide whether to:
   - AUTO_REPLY: confidently draft and send a reply aligned with the user's preferences and safety rules.
   - HUMAN_REVIEW: draft a reply but ask for human approval when risk, ambiguity, or policy limits apply.
   - IGNORE: no reply needed (spam/marketing without opt-in, automated notifications, duplicates, irrelevant).
2) If AUTO_REPLY or HUMAN_REVIEW, draft a concise, professional reply (neutral-professional tone, no hallucinations, no legal/price commitments). Ask short clarifying questions only if critical info missing.
3) Safety: avoid spam/phishing, sensitive data, links/attachments. Prefer HUMAN_REVIEW for legal/HR/contracts, sensitive negotiations, upset customers, or uncertainty.
Return strictly valid JSON only:
{
  "action": "AUTO_REPLY" | "HUMAN_REVIEW" | "IGNORE",
  "confidence": 0.0..1.0,
  "reason": "string",
  "suggested_subject": "string or empty",
  "suggested_reply": "string or empty",
  "metadata": {
    "needs_clarification": true|false,
    "topics": ["..."],
    "risk_flags": ["..."]
  }
}"""

def build_user_context(user_profile: Optional[Dict[str, Any]] = None) -> str:
    user_profile = user_profile or {}
    review_rules = user_profile.get("review_rules")
    if not isinstance(review_rules, list):
        review_rules = ["legal", "contracts", "pricing"]
    return (
        f"User preferences:\n"
        f"- Tone: {user_profile.get('tone', 'neutral-professional')}\n"
        f"- Signature: {user_profile.get('signature', '')}\n"
        f"- Business domain: {user_profile.get('domain', 'general')}\n"
        f"- Ignore domains: {', '.join(user_profile.get('ignore_domains', []))}\n"
        f"- Always HUMAN_REVIEW if: {', '.join(review_rules)}\n"
        f"Use these as soft guidelines."
    )

# --- Agentic triage + drafting ---
def classify_and_draft(email_item: Dict[str, Any], user_profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    subject = email_item.get("subject", "")
    body = email_item.get("body", "")
    sender_raw = email_item.get("sender", "")
    sender = safe_get_sender_string(sender_raw)
    snippet = email_item.get("snippet", "")
    thread = email_item.get("thread", "")

    if is_invalid_recipient(sender):
        return {
            "action": "IGNORE",
            "confidence": 0.95,
            "reason": "Automated or no-reply sender",
            "suggested_subject": "",
            "suggested_reply": "",
            "metadata": {"needs_clarification": False, "topics": [], "risk_flags": ["no_reply_sender"]}
        }

    user_ctx = build_user_context(user_profile)
    user_prompt = f"""Incoming email:
From: {sender}
Subject: {subject}
Body:
{body}

Thread context (optional):
{snippet or thread or ''}

Return JSON only per schema. Do not include any prose outside the JSON."""

    body_payload = _bedrock_messages_body(system_prompt=SYSTEM_PROMPT + "\n\n" + user_ctx, user_prompt=user_prompt)
    payload = _invoke_bedrock_json(body_payload)
    text = _extract_text_from_payload(payload)

    try:
        result = json.loads(text)
    except Exception:
        result = {
            "action": "HUMAN_REVIEW",
            "confidence": 0.0,
            "reason": "Failed to parse structured output",
            "suggested_subject": "",
            "suggested_reply": "",
            "metadata": {"needs_clarification": False, "topics": [], "risk_flags": ["parse_error"]}
        }

    # Normalize
    action = str(result.get("action", "HUMAN_REVIEW")).upper()
    result["action"] = action if action in {"AUTO_REPLY", "HUMAN_REVIEW", "IGNORE"} else "HUMAN_REVIEW"
    result["suggested_subject"] = (result.get("suggested_subject") or "")[:500]
    result["suggested_reply"] = (result.get("suggested_reply") or "")[:5000]
    try:
        result["confidence"] = float(result.get("confidence", 0.0))
    except Exception:
        result["confidence"] = 0.0
    if not isinstance(result.get("metadata"), dict):
        result["metadata"] = {"needs_clarification": False, "topics": [], "risk_flags": []}
    return result

def upsert_triage(email_item: Dict[str, Any], triage: Dict[str, Any]) -> None:
    email_table.update_item(
        Key={"user_email": email_item["user_email"], "email_id": email_item["email_id"]},
        UpdateExpression=(
            "SET triage_status = :ts, triage_reason = :tr, "
            "suggested_subject = :ss, suggested_reply = :sr, triage_updated_at = :tsat"
        ),
        ExpressionAttributeValues={
            ":ts": triage.get("action", "").lower(),
            ":tr": triage.get("reason", ""),
            ":ss": triage.get("suggested_subject", ""),
            ":sr": triage.get("suggested_reply", ""),
            ":tsat": datetime.utcnow().isoformat(),
        }
    )

def enqueue_reply(email_item: Dict[str, Any], triage: Dict[str, Any], status: str) -> None:
    reply_id = f"r-{email_item['email_id']}"
    reply_table.put_item(
        Item={
            "user_email": email_item["user_email"],
            "reply_id": reply_id,
            "email_id": email_item["email_id"],
            "status": status,  # draft, needs_review, ready_to_send, sent, ignored
            "timestamp": datetime.utcnow().isoformat(),
            "subject": triage.get("suggested_subject") or f"Re: {email_item.get('subject', '')}",
            "reply_text": triage.get("suggested_reply", ""),
            "triage_reason": triage.get("reason", ""),
            "confidence": float(triage.get("confidence", 0.0)),
            "metadata": triage.get("metadata", {}),
        }
    )

def triage_email(email_item: Dict[str, Any], user_profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    triage = classify_and_draft(email_item, user_profile=user_profile)
    action = triage.get("action", "HUMAN_REVIEW")
    upsert_triage(email_item, triage)

    if action == "IGNORE":
        enqueue_reply(email_item, triage, status="ignored")
        return {"action": "IGNORE"}

    if action == "AUTO_REPLY":
        enqueue_reply(email_item, triage, status="draft")
        return {"action": "AUTO_REPLY"}

    enqueue_reply(email_item, triage, status="needs_review")
    return {"action": "HUMAN_REVIEW"}

def triage_new_emails(user_email: str, limit: int = 50) -> None:
    resp = email_table.scan(
        FilterExpression="user_email = :ue AND (attribute_not_exists(triage_status) OR triage_status = :pending)",
        ExpressionAttributeValues={":ue": user_email, ":pending": "pending"},
    )
    items = resp.get("Items", [])[:limit]
    for item in items:
        try:
            time.sleep(random.uniform(0, 0.15))  # jitter to reduce burst throttling
            triage_email(item)
        except Exception as e:
            logging.error(f"[TRIAGE ERROR] email_id={item.get('email_id')}: {e}", exc_info=True)

# Backward-compatible simple generator (if needed elsewhere)
def generate_reply_text(prompt: str, max_tokens: int = 500, model_id: Optional[str] = None) -> Optional[str]:
    model_id = model_id or BEDROCK_MODEL_ID
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
    }
    try:
        payload = _invoke_bedrock_json(body, model_id=model_id)
        text = _extract_text_from_payload(payload)
        return text or None
    except Exception:
        return None