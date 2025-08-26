import os
import json
import time
import random
import re
import logging
import requests
from datetime import datetime
from typing import Optional, Dict, Any, List

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Env ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

# Fallback to Claude if Gemini not configured
USE_GEMINI = bool(GEMINI_API_KEY and GEMINI_API_KEY != "your-gemini-api-key")

EMAIL_QUEUE_TABLE = os.getenv("EMAIL_QUEUE_TABLE", "EmailQueue")
REPLY_QUEUE_TABLE = os.getenv("REPLY_QUEUE_TABLE", "ReplyQueue")

MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "5"))
INITIAL_BACKOFF_SECONDS = float(os.getenv("LLM_INITIAL_BACKOFF_SECONDS", "1.0"))
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2000"))

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

# --- Gemini API helpers ---
def _gemini_generate_content(prompt: str, system_prompt: str = "", max_tokens: int = MAX_TOKENS, temperature: float = TEMPERATURE) -> str:
    """Generate content using Gemini API"""
    print(f"[GEMINI] USE_GEMINI: {USE_GEMINI}")
    print(f"[GEMINI] GEMINI_API_KEY: {'Set' if GEMINI_API_KEY else 'Not set'}")

    if not USE_GEMINI:
        print("[GEMINI] Falling back to Claude - Gemini not configured")
        # Fallback to Claude if Gemini not configured
        from .claude_interface import generate_reply_text
        return generate_reply_text(prompt, max_tokens, None)

    print(f"[GEMINI] Using Gemini API with model: {GEMINI_MODEL}")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

    # Combine system prompt with user prompt
    full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt

    payload = {
        "contents": [{
            "parts": [{"text": full_prompt}]
        }],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "topK": 40,
            "topP": 0.95,
        }
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()

            result = response.json()
            print(f"[GEMINI] 📡 Raw API Response: {result}")

            if "candidates" in result and len(result["candidates"]) > 0:
                candidate = result["candidates"][0]
                finish_reason = candidate.get("finishReason", "")

                # Handle MAX_TOKENS case - response was truncated
                if finish_reason == "MAX_TOKENS":
                    print(f"[GEMINI] ⚠️ Response truncated due to MAX_TOKENS limit")
                    # Still try to extract what we can
                    content = candidate.get("content", {})
                    if "parts" in content and len(content["parts"]) > 0:
                        text_response = content["parts"][0].get("text", "").strip()
                        print(f"[GEMINI] 📄 Extracted partial text: {text_response[:200]}...")
                        return text_response

                # Normal case
                content = candidate.get("content", {})
                if "parts" in content and len(content["parts"]) > 0:
                    text_response = content["parts"][0].get("text", "").strip()
                    print(f"[GEMINI] ✅ Extracted text: {text_response[:200]}...")
                    return text_response

            print("[GEMINI] ⚠️ No content found in response")
            return ""

        except requests.exceptions.RequestException as e:
            throttled = response.status_code == 429 if 'response' in locals() else False
            level = logging.WARNING if throttled else logging.ERROR

            if attempt < MAX_RETRIES - 1:
                backoff = (INITIAL_BACKOFF_SECONDS * (2 ** attempt)) + random.uniform(0, 1)
                logging.log(level, f"Gemini API error {attempt+1}/{MAX_RETRIES}: {e}. Retry in {backoff:.2f}s")
                time.sleep(backoff)
            else:
                logging.error(f"Gemini API failed after {MAX_RETRIES} attempts: {e}")
                print(f"[GEMINI] ❌ API Error: {e}")
                print(f"[GEMINI] 📡 Response status: {response.status_code if 'response' in locals() else 'Unknown'}")
                if 'response' in locals():
                    try:
                        error_content = response.json()
                        print(f"[GEMINI] 📄 Error content: {error_content}")
                    except:
                        print(f"[GEMINI] 📄 Raw error: {response.text[:500]}")
                # Fallback to Claude
                from .claude_interface import generate_reply_text
                return generate_reply_text(prompt, max_tokens, None)

    return ""

def _extract_text_from_gemini_response(response_text: str) -> str:
    """Extract text content from Gemini response"""
    # Clean the response text
    cleaned_text = response_text.strip()

    # Handle markdown code blocks
    if cleaned_text.startswith('```json'):
        cleaned_text = cleaned_text[7:]  # Remove ```json
    if cleaned_text.startswith('```'):
        cleaned_text = cleaned_text[3:]  # Remove ```
    if cleaned_text.endswith('```'):
        cleaned_text = cleaned_text[:-3]  # Remove ```

    cleaned_text = cleaned_text.strip()

    try:
        # Try to parse as JSON first (for structured responses)
        result = json.loads(cleaned_text)
        if isinstance(result, dict) and "suggested_reply" in result:
            return result.get("suggested_reply", "")
        return response_text.strip()
    except json.JSONDecodeError:
        print(f"[GEMINI] ❌ JSON parsing failed for: {cleaned_text[:200]}...")
        return response_text.strip()

# --- Prompts ---
SYSTEM_PROMPT = """You are an email assistant. Analyze the incoming email and decide on action.

Choose one action:
- AUTO_REPLY: Draft and send a reply (confident, safe responses only)
- HUMAN_REVIEW: Draft reply but require human approval (uncertain, sensitive, or complex cases)
- IGNORE: No reply needed (spam, irrelevant, or automated messages)

For AUTO_REPLY or HUMAN_REVIEW, draft a brief, professional reply.

Return only valid JSON:
{
  "action": "AUTO_REPLY"|"HUMAN_REVIEW"|"IGNORE",
  "confidence": 0.0-1.0,
  "reason": "brief explanation",
  "suggested_subject": "Re: original or empty",
  "suggested_reply": "draft response or empty",
  "metadata": {
    "needs_clarification": false,
    "topics": [],
    "risk_flags": []
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
    history = email_item.get("history", "")
    persona = email_item.get("persona", "")
    prompt = email_item.get("prompt", "")
    user_email = email_item.get("user_email", "")

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

    # Use the rich prompt if provided, otherwise build a comprehensive one
    if prompt:
        full_user_prompt = prompt
    else:
        # Build comprehensive context like the original system
        context_block = ""
        if user_profile:
            if user_profile.get("bio"): context_block += f"Bio: {user_profile['bio']}\n"
            if user_profile.get("product_context"): context_block += f"Product context: {user_profile['product_context']}\n"
            if user_profile.get("faq"): context_block += f"FAQs: {user_profile['faq']}\n"
            if user_profile.get("policies"): context_block += f"Policies: {user_profile['policies']}\n"
            if user_profile.get("crm_context"): context_block += f"CRM context: {user_profile['crm_context']}\n"

        full_user_prompt = f"""Incoming email:
From: {sender}
Subject: {subject}
Body:
{body}

Thread context (optional):
{snippet or thread or ''}

Conversation history:
{history or 'No previous conversation history available.'}

User context:
{context_block}

Return JSON only per schema. Do not include any prose outside the JSON."""

    # Combine all context for maximum information
    combined_system = SYSTEM_PROMPT
    if user_ctx:
        combined_system += "\n\n" + user_ctx
    if persona:
        combined_system += "\n\n" + persona

    response_text = _gemini_generate_content(full_user_prompt, combined_system)

    try:
        # Clean the response text (remove markdown code blocks)
        cleaned_text = response_text.strip()
        if cleaned_text.startswith('```json'):
            cleaned_text = cleaned_text[7:]  # Remove ```json
        if cleaned_text.startswith('```'):
            cleaned_text = cleaned_text[3:]  # Remove ```
        if cleaned_text.endswith('```'):
            cleaned_text = cleaned_text[:-3]  # Remove ```

        cleaned_text = cleaned_text.strip()
        result = json.loads(cleaned_text)
        print(f"[GEMINI] ✅ Successfully parsed JSON response")
    except Exception as e:
        print(f"[GEMINI] ❌ Failed to parse JSON response: {e}")
        print(f"[GEMINI] 📄 Raw response: {response_text[:500]}...")
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

# Backward-compatible simple generator (if needed elsewhere)
def generate_reply_text(prompt: str, max_tokens: int = 500, model_id: Optional[str] = None) -> Optional[str]:
    """Simple text generation for compatibility"""
    response = _gemini_generate_content(prompt, "", max_tokens, 0.7)
    return response or None

# Test function to verify Gemini integration
def test_gemini_integration():
    """Test Gemini API integration"""
    print("🔍 Testing Gemini Integration...")

    # Test basic content generation
    test_prompt = "Hello, can you respond to this test email?"
    print(f"📝 Test prompt: {test_prompt}")

    try:
        response = _gemini_generate_content(test_prompt)
        print(f"✅ Gemini Response: {response[:200]}...")
        return True
    except Exception as e:
        print(f"❌ Gemini Test Failed: {e}")
        return False

# Legacy functions for compatibility
def triage_email(email_item: Dict[str, Any], user_profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Legacy triage function"""
    triage = classify_and_draft(email_item, user_profile=user_profile)
    action = triage.get("action", "HUMAN_REVIEW")
    return {"action": action}

def triage_new_emails(user_email: str, limit: int = 50) -> None:
    """Legacy batch triage function"""
    import boto3
    from database.memory_manager_dynamo import get_user_profile

    dynamodb = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "ap-south-1"))
    email_table = dynamodb.Table(EMAIL_QUEUE_TABLE)

    resp = email_table.scan(
        FilterExpression="user_email = :ue AND (attribute_not_exists(triage_status) OR triage_status = :pending)",
        ExpressionAttributeValues={":ue": user_email, ":pending": "pending"},
    )
    items = resp.get("Items", [])[:limit]

    for item in items:
        try:
            time.sleep(random.uniform(0, 0.15))  # jitter to reduce burst throttling
            triage = classify_and_draft(item)
            # Update the email with triage results
            email_table.update_item(
                Key={"user_email": item["user_email"], "email_id": item["email_id"]},
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
        except Exception as e:
            logging.error(f"[TRIAGE ERROR] email_id={item.get('email_id')}: {e}", exc_info=True)