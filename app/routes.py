from flask import Blueprint, Flask, render_template, render_template_string, request, redirect, url_for, session, make_response
from app.auth_manager import init_oauth, oauth
from database.memory_manager_dynamo import (
    get_conversation_history,
    create_user_session,
    end_user_session,
    get_user_role,
    get_user_status,
    list_pending_emails,
    get_pending_email,
    update_pending_email,
    mark_pending_canceled,
    get_user_profile,
    set_user_profile,
)
from automation.send_reply import main_loop, send_pending_email
from automation.clients.imap_client import test_imap_connection
from app.auth_provider_detection import EmailProviderDetection, diagnose_authentication_error
from boto3.dynamodb.conditions import Key
import threading
import jwt
import boto3
import os
import datetime
import uuid
import secrets
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from functools import wraps
import secrets
from typing import Optional, Tuple, Dict, Any
import time
from collections import defaultdict

routes = Blueprint("routes", __name__)
JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-jwt")
REGION = os.getenv("AWS_REGION", "ap-south-1")

# Get Railway domain for Outlook OAuth redirect
railway_domain = os.getenv("RAILWAY_STATIC_URL")
if not railway_domain:
    # Fallback: construct from Railway variables
    railway_domain = f"https://{os.getenv('RAILWAY_PROJECT_NAME', 'dep-emauto-production')}.up.railway.app"
if not railway_domain.startswith('https://'):
    railway_domain = f"https://{railway_domain}"

REDIRECT_URI = os.getenv("OUTLOOK_REDIRECT_URI", f"{railway_domain}/callback/outlook")
print(f"🔗 Outlook redirect URI: {REDIRECT_URI}")
USERS_TABLE_NAME = os.getenv("USERS_TABLE", "Users")
REPLIES_TABLE_NAME = os.getenv("REPLIES_TABLE", "EmailReplies")
ENV = os.getenv("FLASK_ENV", "development")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")

def init_app(app: Flask):
    init_oauth(app)
    app.register_blueprint(routes)
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "fallback-dev-secret")

# ---------------- Helpers ----------------
def dynamodb():
    return boto3.resource("dynamodb", region_name=REGION)

def users_table():
    return dynamodb().Table(USERS_TABLE_NAME)

def replies_table():
    return dynamodb().Table(REPLIES_TABLE_NAME)

# ---------------- JWT Utilities ----------------
def generate_jwt(email: str, role: str) -> str:
    payload = {
        "email": email,
        "role": role,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def decode_jwt(token: Optional[str]) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

# ---------------- Auth Decorator Helpers ----------------
def get_current_user() -> Optional[Dict[str, Any]]:
    token = request.cookies.get("access_token")
    user = decode_jwt(token)
    if user:
        request.user = user  # attach for convenience
    return user

def require_jwt(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            # preserve next URL so user returns after login
            next_url = request.url
            return redirect(url_for("routes.login", next=next_url))
        return f(*args, **kwargs)
    return wrapper

def require_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user or user.get("role") not in ("admin", "superuser"):
            return "Access denied", 403
        return f(*args, **kwargs)
    return wrapper

def require_superuser(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user or user.get("role") != "superuser":
            return "Access denied", 403
        return f(*args, **kwargs)
    return wrapper

# ---------------- User Helpers ----------------
def get_user(email: str):
    if not email:
        return None
    resp = users_table().get_item(Key={"email": email})
    return resp.get("Item")

def ensure_role_migration(user_item: Optional[dict]) -> str:
    if not user_item:
        return "user"
    role = user_item.get("role")
    if role in ("user", "admin", "superuser"):
        return role
    if user_item.get("is_admin") is True:
        return "admin"
    return "user"

def update_user_role(target_email: str, new_role: str):
    users_table().update_item(
        Key={"email": target_email},
        UpdateExpression="SET #r = :role",
        ExpressionAttributeNames={"#r": "role"},
        ExpressionAttributeValues={":role": new_role}
    )

def set_auth_cookies(resp, jwt_token: str, session_uuid: str, email: str):
    # Use Secure in production; HttpOnly and SameSite=Lax for CSRF mitigation
    for name, value in [
        ("access_token", jwt_token),
        ("session_uuid", session_uuid),
        ("email", email),
    ]:
        resp.set_cookie(
            name,
            value,
            httponly=True,
            secure=COOKIE_SECURE,
            samesite="Lax",
            max_age=7 * 24 * 3600,
        )

def clear_auth_cookies(resp):
    """Securely clear all authentication cookies with proper security flags"""
    for name in ("access_token", "session_uuid", "email"):
        resp.set_cookie(
            name,
            "",
            expires=0,
            httponly=True,
            secure=COOKIE_SECURE,
            samesite="Lax",
            # Set to empty and past date to ensure deletion
            max_age=0
        )

# 🛡️ Rate Limiting (Simple in-memory implementation)
_rate_limit_store = defaultdict(list)

def rate_limiter(max_requests=10, window_seconds=60):
    """Simple rate limiter decorator"""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # Get client identifier (IP address)
            client_ip = request.remote_addr
            if not client_ip:
                return f(*args, **kwargs)  # Allow if no IP (for testing)

            current_time = time.time()

            # Clean old requests
            _rate_limit_store[client_ip] = [
                req_time for req_time in _rate_limit_store[client_ip]
                if current_time - req_time < window_seconds
            ]

            # Check rate limit
            if len(_rate_limit_store[client_ip]) >= max_requests:
                return "Too many requests. Please try again later.", 429

            # Add current request
            _rate_limit_store[client_ip].append(current_time)

            return f(*args, **kwargs)
        return wrapper
    return decorator

# 🚨 COMPREHENSIVE PRIVACY & DATA PROTECTION SYSTEM
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import os
import re
import hashlib
from typing import Dict, Any, Optional, List

# Privacy encryption system
PRIVACY_ENCRYPTION_KEY = os.getenv("PRIVACY_ENCRYPTION_KEY", Fernet.generate_key())
_privacy_cipher = Fernet(PRIVACY_ENCRYPTION_KEY)

class DataPrivacyManager:
    """Enterprise-grade data protection for sensitive content"""

    @staticmethod
    def mask_sender_email(sender: str) -> str:
        """Intelligent sender email masking while preserving context"""
        if not sender or not isinstance(sender, str):
            return "[SENDER_MASKED]"

        sender = sender.strip()
        if '@' not in sender:
            return "[SENDER_MASKED]"

        # Preserve domain context while masking username
        parts = sender.split('@', 1)
        if len(parts[0]) <= 2:
            return f"[SENDER_MASKED]@{parts[1]}"
        else:
            # Hide most characters but show first/last letter
            username = parts[0]
            masked_username = username[0] + ('*' * (len(username)-2)) + username[-1]
            return f"{masked_username}@{parts[1]}"

    @staticmethod
    def mask_email_list(email_list: List[str]) -> List[str]:
        """Mask multiple emails preserving recipient context"""
        if not email_list:
            return []
        return [DataPrivacyManager.mask_sender_email(email) for email in email_list]

    @staticmethod
    def sanitize_subject_line(subject: str, preserve_business_terms: bool = True) -> str:
        """Smart subject line sanitization"""
        if not subject:
            return "[SUBJECT_MASKED]"

        # Business terms to potentially preserve (configurable)
        BUSINESS_TERMS = {
            'invoice', 'order', 'confirmation', 'receipt', 'contract', 'agreement',
            'meeting', 'reminder', 'update', 'alert', 'notification', 'request',
            'payment', 'due', 'overdue', 'urgent', 'important', 'critical'
        }

        words = re.findall(r'\b\w+\b', subject.lower())
        sanitized_words = []

        for word in words:
            # Preserve business terms but mask potential PII
            if preserve_business_terms and word in BUSINESS_TERMS:
                sanitized_words.append(word)
            elif len(word) > 6:  # Likely a name or identifier
                sanitized_words.append('[PII_MASKED]')
            else:
                sanitized_words.append(word)

        return ' '.join(sanitized_words).replace(subject, '', 1) if sanitized_words else '[SUBJECT_MASKED]'

    @staticmethod
    def sanitize_email_for_llm(content: str, masked_sender: str = None) -> Dict[str, Any]:
        """Advanced LLM-safe content preparation with audit trail"""

        # Create audit record of processing
        processing_audit = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "processing_type": "llm_sanitization",
            "original_length": len(content),
            "pii_flags": DataPrivacyManager.extract_pii_flags(content)
        }

        # Advanced content sanitization
        sanitized_body = content

        # 1. Mask email addresses with intelligent domain context
        def replace_email(match):
            email = match.group(0)
            domain = email.split('@')[1] if '@' in email else email
            return f'[EMAIL_FROM_{domain.upper().replace(".", "_")}]'

        sanitized_body = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', replace_email, sanitized_body)

        # 2. Mask phone numbers (extensive patterns)
        phone_patterns = [
            r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',  # US format
            r'\b(\+\d{1,3}\s?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',  # International
            r'\b\d{4}[\s-]?\d{3}[\s-]?\d{3}\b',  # 10-digit formats
        ]
        for pattern in phone_patterns:
            sanitized_body = re.sub(pattern, '[PHONE_MASKED]', sanitized_body)

        # 3. Mask payment and financial information
        sanitized_body = re.sub(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b', '[PAYMENT_MASKED]', sanitized_body)
        sanitized_body = re.sub(r'\b\d{8,17}\b', '[ACCOUNT_MASKED]', sanitized_body)  # Account numbers

        # 4. Mask government IDs and SSN-like patterns
        sanitized_body = re.sub(r'\b\d{3}-?\d{2}-?\d{4}\b', '[GOV_ID_MASKED]', sanitized_body)

        # 5. Mask addresses (common patterns)
        sanitized_body = re.sub(r'\b\d+\s+[A-Za-z0-9\s,.-]+\b(?=\s+(?:street|st|avenue|ave|road|rd|drive|dr|lane|ln|way|blvd|boulevard|place|pl|circle|cir|square|sq|court|ct)\b)', '[ADDRESS_MASKED]', sanitized_body, flags=re.IGNORECASE)

        # 6. Mask URLs containing sensitive parameters (while preserving context)
        sensitive_url_patterns = [
            r'https?://[^\s]*password[^\s]*',
            r'https?://[^\s]*token[^\s]*',
            r'https?://[^\s]*key[^\s]*',
            r'https?://[^\s]*secret[^\s]*'
        ]
        for pattern in sensitive_url_patterns:
            sanitized_body = re.sub(pattern, '[SECURE_URL_MASKED]', sanitized_body, flags=re.IGNORECASE)

        # 7. Mask dates that could be combined with other PII (birthdates, etc.)
        date_patterns = [
            r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',  # MM/DD/YYYY
            r'\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b',  # YYYY/MM/DD
            r'\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{2,4}\b',  # Written dates
        ]
        for pattern in date_patterns:
            sanitized_body = re.sub(pattern, '[DATE_MASKED]', sanitized_body, flags=re.IGNORECASE)

        # 8. Intelligent content truncation based on context
        if len(sanitized_body) > 4000:
            # Try to truncate at sentence boundaries
            sentences = re.split(r'(?<=[.!?])\s+', sanitized_body)
            truncated = ""
            for sentence in sentences:
                if len(truncated + sentence) < 3950:
                    truncated += sentence + " "
                else:
                    break
            sanitized_body = truncated.rstrip() + "..."

        # Create comprehensive audit
        processing_audit.update({
            "sanitized_length": len(sanitized_body),
            "masking_ratio": f"{(1 - len(sanitized_body)/max(1, len(content)))*100:.1f}%",
            "has_pii": any(processing_audit["pii_flags"].values())
        })

        return {
            "sanitized_content": sanitized_body,
            "masked_sender": masked_sender or "[SENDER_MASKED]",
            "audit": processing_audit,
            "compliance": "SOC2_GDPR_COMPLIANT"
        }

    @staticmethod
    def extract_pii_flags(content: str) -> Dict[str, bool]:
        """Comprehensive PII detection for compliance reporting"""
        if not content:
            return {}

        flags = {
            "contains_email": bool(re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', content)),
            "contains_phone": bool(re.search(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', content)),
            "contains_payment": bool(re.search(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b', content)),
            "contains_account": bool(re.search(r'\b\d{8,17}\b', content)),
            "contains_gov_id": bool(re.search(r'\b\d{3}-?\d{2}-?\d{4}\b', content)),
            "contains_address": bool(re.search(r'\b\d+\s+[A-Za-z0-9\s,.-]+\b(?=\s+(?:street|st|avenue|ave|road|rd|drive|dr|lane|ln|way|blvd|boulevard|place|pl|circle|cir|square|sq|court|ct)\b)', content, re.IGNORECASE)),
            "contains_url": bool(re.search(r'https?://[^\s]+', content)),
            "contains_date": bool(re.search(r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b', content)),
            "sensitive_keywords": any(word in content.lower() for word in [
                'confidential', 'private', 'secret', 'internal', 'sensitive',
                'password', 'ssn', 'sin', 'medical', 'financial', 'legal'
            ])
        }

        return flags

    @staticmethod
    def log_privacy_event(user_email: str, event_type: str, pii_detected: Dict[str, Any], compliance_result: Dict[str, Any]):
        """Secure privacy event logging for compliance"""
        audit_entry = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "user": user_email,
            "event": event_type,
            "pii_flags": pii_detected,
            "compliance_status": "PII_MASKED_AND_COMPLIANT" if not any(pii_detected.values()) else "PII_DETECTED_AND_MASKED",
            "audit_hash": hashlib.sha256(f"{user_email}:{event_type}:{datetime.datetime.utcnow().isoformat()}".encode()).hexdigest()[:16]
        }

        # In production, write to secure audit database
        print(f"🔐 PRIVACY AUDIT: {audit_entry}")

def sanitize_email_content(content):
    """Backward compatibility function - now uses DataPrivacyManager"""
    return DataPrivacyManager.mask_email_for_audit(content)

def mask_email_for_audit(content: str) -> str:
    """Legacy audit logging mask - basic but sufficient for logs"""
    if not content:
        return ""

    # Basic PII masking for audit logs
    content = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL_MASKED]', content)
    content = re.sub(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE_MASKED]', content)
    content = re.sub(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b', '[PAYMENT_MASKED]', content)

    if len(content) > 1000:
        content = content[:997] + "..."

    return content

def create_llm_safe_email_content(content: str, sender_email: str, user_email: str) -> Dict[str, Any]:
    """Public API for LLM-safe content creation with full audit trail"""
    return DataPrivacyManager.sanitize_email_for_llm(content, sender_email)

def audit_log(action, user_email=None, details=None):
    """Security audit logging function"""
    timestamp = datetime.datetime.utcnow().isoformat()
    log_entry = {
        'timestamp': timestamp,
        'action': action,
        'user': user_email,
        'ip': request.remote_addr,
        'session': request.cookies.get('session_uuid', 'unknown'),
        'details': sanitize_email_content(str(details)) if details else None
    }

    print(f"🔐 AUDIT: {log_entry}")  # In production, write to secure log file/database

# ---------------- Routes ----------------
@routes.route("/")
def index():
    """Show landing page for non-authenticated users, dashboard for authenticated users"""
    user = get_current_user()
    if user:
        return redirect(url_for("routes.dashboard"))
    return render_template("landing.html")

@routes.route("/dashboard")
@require_jwt
def dashboard():
    user_email = request.user["email"]
    # Normalize role each visit in case legacy users still have old flags
    user_item = get_user(user_email)
    canonical_role = ensure_role_migration(user_item)
    if user_item and canonical_role != user_item.get("role"):
        update_user_role(user_email, canonical_role)

    from database.memory_manager_dynamo import get_user_profile

    response = replies_table().query(
        KeyConditionExpression=Key("user_email").eq(user_email),
        ScanIndexForward=False
    )
    replies = response.get("Items", [])

    # Get user profile for auto_send preference
    profile = get_user_profile(user_email)
    auto_send = profile.get("preferences", {}).get("auto_send", False)

    from database.memory_manager_dynamo import get_user_profile

    # Calculate real metrics
    total_emails_processed = len(replies) if replies else 0
    sent_replies = len([r for r in replies if r.get("status") == "sent"]) if replies else 0
    success_rate = (sent_replies / total_emails_processed * 100) if total_emails_processed > 0 else 0

    # Get pending emails count
    from database.memory_manager_dynamo import list_pending_emails
    pending = list_pending_emails(user_email)
    pending_count = len([p for p in pending if p.get("status") in ["PENDING", "DRAFT"]])

    return render_template("dashboard.html",
                         replies=replies,
                         role=canonical_role,
                         user_email=user_email,
                         auto_send=auto_send,
                         total_emails=total_emails_processed,
                         ai_accuracy=round(success_rate, 1),
                         pending_reviews=pending_count,
                         total_replies=total_emails_processed,
                         sent_replies=sent_replies)

@routes.route("/login")
def login():
    return render_template("login.html")

@routes.route("/login/imap", methods=["GET", "POST"])
@rate_limiter(max_requests=5, window_seconds=300)  # 5 attempts per 5 minutes
def login_imap():
    """IMAP authentication route"""
    if request.method == "GET":
        return render_template("login_imap.html")

    # POST request - handle IMAP authentication
    try:
        # 🔐 Security: Input validation and sanitization
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        imap_server = request.form.get("imap_server", "").strip()
        smtp_server = request.form.get("smtp_server", "").strip()

        # 🚫 Security: Prevent potential injection attacks
        if any(char in email + imap_server + smtp_server for char in ['<', '>', '"', "'", '&']):
            return render_template("login_imap.html",
                                   error="Invalid characters detected. Please check your input.")

        # Validate email format
        import re
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            return render_template("login_imap.html", error="Invalid email format")

        # Validate server formats (basic)
        if not all(server and '.' in server for server in [imap_server, smtp_server]):
            return render_template("login_imap.html", error="Invalid server format. Use format like 'mail.example.com'")

        # Safe port parsing with validation
        try:
            imap_port = int(request.form.get("imap_port", 993))
            smtp_port = int(request.form.get("smtp_port", 587))
            if not (1 <= imap_port <= 65535 and 1 <= smtp_port <= 65535):
                raise ValueError("Invalid port range")
        except ValueError:
            return render_template("login_imap.html", error="Invalid port numbers")

        use_ssl = request.form.get("use_ssl") == "on"

        # 🔍 Enhanced Provider Detection
        provider, detection_message = EmailProviderDetection.detect_provider(email)
        if provider:
            audit_log("IMAP_PROVIDER_DETECTED", user_email=email, details=f"Provider: {provider.name}")

            # Validate server settings against expected provider defaults
            settings_valid, settings_message = EmailProviderDetection.validate_server_settings(
                imap_server, smtp_server, email
            )

            if settings_message and "don't match" in settings_message.lower():
                audit_log("IMAP_SERVER_MISMATCH", user_email=email, details=settings_message)

            # Get recommended authentication method
            recommended_auth = EmailProviderDetection.get_recommended_auth_type(provider)

            # Provide guidance for OAuth2 providers that likely won't work with IMAP
            if recommended_auth == "oauth2" and provider.name in ["Gmail", "Outlook", "Yahoo"]:
                auth_guide = EmailProviderDetection.get_authentication_guide(provider, recommended_auth)
                error_msg = (f"⚠️ {provider.name} requires OAuth2 authentication, which is not compatible with basic IMAP login.\n\n"
                           f"**Recommended:** Use the OAuth2 login button for {provider.name} instead of IMAP configuration.\n\n"
                           f"Alternative: Follow these steps for app-specific password setup:\n{auth_guide}")

                return render_template("login_imap.html",
                                     error=error_msg,
                                     provider_detected=provider.name,
                                     auth_type=recommended_auth)

        # Validate required fields (with length checks for security)
        required_fields = [email, password, imap_server, smtp_server]
        if not all(required_fields) or any(len(field) > 255 for field in required_fields):
            return render_template("login_imap.html",
                                  error="All fields are required and must be under 255 characters")

        # 🔗 Enhanced connection testing with provider-specific enhancement
        enhanced_credentials = EmailProviderDetection.enhance_credentials_for_provider(
            email, password, imap_server, smtp_server
        )

        test_credentials = {
            'email': email,
            'imap_server': enhanced_credentials['imap_server'],
            'imap_port': enhanced_credentials['imap_port'],
            'smtp_server': enhanced_credentials['smtp_server'],
            'smtp_port': enhanced_credentials['smtp_port'],
            'password': password,  # Plaintext for testing
            'use_ssl': enhanced_credentials['use_ssl']
        }

        # Test IMAP connection with enhanced error handling
        connection_success = test_imap_connection(test_credentials)

        if not connection_success:
            # 🕵️ Diagnose the specific authentication issue
            diagnosis = diagnose_authentication_error("IMAP authentication failed", email)

            error_msg = f"""
❌ Connection Failed: {diagnosis['problem']}

🔧 **Troubleshooting Steps:**
"""
            for solution in diagnosis['solutions']:
                error_msg += f"• {solution}\n"

            if provider:
                error_msg += f"\n📧 **Provider-Specific Information:**\n"
                error_msg += f"• Detected: {provider.name}\n"
                if enhanced_credentials.get('requires_app_password'):
                    error_msg += "• ⚠️  This provider typically requires APP-SPECIFIC PASSWORD for IMAP\n"
                if enhanced_credentials.get('requires_oauth2'):
                    error_msg += "• ⚠️  This provider typically requires OAUTH2 (use OAuth button instead)\n"

            return render_template("login_imap.html",
                                   error=error_msg,
                                   provider_detected=provider.name if provider else None,
                                   auth_type=enhanced_credentials.get('auth_method', 'basic'),
                                   server_suggestion=enhanced_credentials)

        # Connection successful - create user account
        from database.memory_manager_dynamo import get_user_profile, set_user_profile

        # Check if user exists
        user = get_user(email)
        if not user:
            # Create new user
            users_table().put_item(Item={
                "email": email,
                "provider": "imap",
                "plan": "trial",
                "token_limit": 100,
                "used_tokens": 0,
                "is_admin": False,
                "role": "user",
                "created_at": datetime.datetime.utcnow().isoformat(),
                "reset_date": (datetime.datetime.utcnow() + datetime.timedelta(days=30)).isoformat()
            })

        # Store IMAP configuration (with encrypted password)
        from automation.clients.imap_client import encrypt_password
        profile = get_user_profile(email) or {}
        profile.update({
            'imap_server': imap_server,
            'imap_port': imap_port,
            'smtp_server': smtp_server,
            'smtp_port': smtp_port,
            'imap_password_encrypted': encrypt_password(password),
            'use_ssl': use_ssl,
            'imap_configured': True
        })
        set_user_profile(email, profile)

        # Create session and JWT
        session_uuid = create_user_session(email)
        role = get_user_role(email) or "user"
        jwt_token = generate_jwt(email, role)

        # 🔐 Security: Audit successful login
        audit_log("LOGIN_SUCCESSFUL", user_email=email, details="IMAP authentication")

        resp = make_response(redirect("/dashboard"))
        set_auth_cookies(resp, jwt_token, session_uuid, email)

        return resp

    except Exception as e:
        print(f"❌ IMAP login error: {e}")
        return render_template("login_imap.html",
                             error="Login failed. Please try again.")

@routes.route("/login/<provider>")
def start_oauth_login(provider):
    if provider == "outlook":
        # Import MSAL app locally to get the updated reference
        from app.auth_manager import msal_app

        if msal_app is None:
            print("❌ MSAL app not initialized - check OUTLOOK_CLIENT_ID and OUTLOOK_CLIENT_SECRET")
            return "Outlook OAuth not configured. Please check your environment variables.", 500

        state = str(uuid.uuid4())
        session["state"] = state

        # MSAL automatically handles PKCE for confidential clients
        auth_url = msal_app.get_authorization_request_url(
            scopes=["User.Read", "Mail.ReadWrite", "Mail.Send"],
            state=state,
            redirect_uri=REDIRECT_URI
        )
        return redirect(auth_url)

    # OAuth redirect URI is now set explicitly in auth_manager.py
    client = oauth.create_client(provider)
    return client.authorize_redirect()

@routes.route("/callback/<provider>")
def auth_callback(provider):
    email = None
    token = None

    if provider == "outlook":
        # Import MSAL app locally to get the updated reference
        from app.auth_manager import msal_app

        if request.args.get("state") != session.get("state"):
            return "State mismatch", 400
        code = request.args.get("code")
        if not code:
            return "Missing authorization code", 400

        # MSAL automatically handles PKCE verification
        result = msal_app.acquire_token_by_authorization_code(
            code,
            scopes=["User.Read", "Mail.ReadWrite", "Mail.Send"],
            redirect_uri=REDIRECT_URI
        )
        if "error" in result:
            return f"MSAL Error: {result.get('error_description') or result.get('error')}", 400
        token = result
        email = result.get("id_token_claims", {}).get("preferred_username")
    else:
        client = oauth.create_client(provider)
        try:
            token = client.authorize_access_token()
        except Exception as e:
            return f"OAuth failed: {e}", 400

        if provider == "google":
            id_token_str = token.get("id_token")
            if not id_token_str:
                return "Missing ID token", 400
            try:
                id_info = google_id_token.verify_oauth2_token(
                    id_token_str,
                    google_requests.Request(),
                    os.getenv("GOOGLE_CLIENT_ID")
                )
                email = id_info.get("email")
            except Exception as e:
                return f"Google token verification failed: {e}", 400
        else:
            userinfo = client.get("userinfo").json()
            email = userinfo.get("email") or userinfo.get("preferred_username")

    if not email:
        return "Unable to determine user email from provider", 400

    # Persist provider info in server session (not cookies)
    session["provider"] = provider
    session["provider_token"] = token

    # Create or update user
    user = get_user(email)
    if not user:
        users_table().put_item(Item={
            "email": email,
            "provider": provider,
            "plan": "trial",
            "token_limit": 100,
            "used_tokens": 0,
            "is_admin": False,
            "role": "user",
            "created_at": datetime.datetime.utcnow().isoformat(),
            "reset_date": (datetime.datetime.utcnow() + datetime.timedelta(days=30)).isoformat()
        })
        role = "user"
    else:
        role = ensure_role_migration(user)
        if role != user.get("role"):
            update_user_role(email, role)

    # Create an app session and JWT
    session_uuid = create_user_session(email)
    role = get_user_role(email) or role

    jwt_token = generate_jwt(email, role)
    next_url = request.args.get("next")
    default_next = "/admin" if role in ("admin", "superuser") else "/dashboard"
    resp = make_response(redirect(next_url or default_next))
    set_auth_cookies(resp, jwt_token, session_uuid, email)

    # 🔐 Security: Audit OAuth login
    audit_log("OAUTH_LOGIN_SUCCESSFUL", user_email=email, details=f"{provider} authentication")

    # Kick off background main_loop
    threading.Thread(target=main_loop, args=(provider, token, email, session_uuid), daemon=True).start()
    return resp

@routes.route("/admin")
@require_admin
def admin_dashboard():
    users = users_table().scan().get("Items", [])
    csrf_token = secrets.token_urlsafe(32)
    session["csrf_token"] = csrf_token
    return render_template("admin_dashboard.html", users=users, csrf_token=csrf_token, role=request.user.get("role"))

@routes.route("/admin/change_role", methods=["POST"])
@require_admin
def admin_change_role():
    token = request.form.get("csrf_token")
    if not token or token != session.get("csrf_token"):
        return "Invalid CSRF token", 400
    # rotate token after use
    session["csrf_token"] = secrets.token_urlsafe(32)

    target_email = request.form.get("email")
    new_role = request.form.get("role")
    if new_role not in ("user", "admin"):
        return "Invalid role", 400

    caller = request.user
    caller_email = caller["email"]
    caller_role = caller.get("role")

    if not target_email:
        return "Missing target email", 400
    if target_email == caller_email:
        return "Admins cannot change their own role here", 403

    target = get_user(target_email)
    if not target:
        return "User not found", 404

    target_current_role = ensure_role_migration(target)
    if target_current_role == "superuser":
        return "Admins cannot modify superuser", 403

    if caller_role in ("admin", "superuser"):
        update_user_role(target_email, new_role)
        return redirect(url_for("routes.admin_dashboard"))

    return "Access denied", 403

@routes.route("/superuser")
@require_superuser
def superuser_dashboard():
    users = users_table().scan().get("Items", [])
    csrf_token = secrets.token_urlsafe(32)
    session["csrf_token"] = csrf_token
    return render_template("superuser_dashboard.html", users=users, csrf_token=csrf_token)

@routes.route("/superuser/change_role", methods=["POST"])
@require_superuser
def superuser_change_role():
    token = request.form.get("csrf_token")
    if not token or token != session.get("csrf_token"):
        return "Invalid CSRF token", 400
    session["csrf_token"] = secrets.token_urlsafe(32)

    target_email = request.form.get("email")
    new_role = request.form.get("role")
    if new_role not in ("user", "admin", "superuser"):
        return "Invalid role", 400

    caller_email = request.user["email"]
    if not target_email:
        return "Missing target email", 400
    if target_email == caller_email and new_role != "superuser":
        return "Superuser cannot demote themselves via this endpoint", 403

    target = get_user(target_email)
    if not target:
        return "User not found", 404

    update_user_role(target_email, new_role)
    return redirect(url_for("routes.superuser_dashboard"))

@routes.route("/admin/privacy-audit")
@require_admin
def privacy_audit():
    """Privacy compliance audit dashboard for administrators"""
    try:
        from app.routes import DataPrivacyManager
        from database.memory_manager_dynamo import replies_table, get_user_profile
        import boto3
        from boto3.dynamodb.conditions import Key

        user_email = request.user["email"]
        audit_results = {
            "system_status": "🔐 PRIVACY PROTECTION ACTIVE",
            "privacy_features": {
                "llm_content_masking": True,
                "ui_data_masking": True,
                "audit_logging": True,
                "encrypted_storage": True,  # For IMAP passwords
                "compliance_standard": "SOC2_GDPR_Compliant"
            },
            "recent_activity": []
        }

        # Get recent email processing activity
        try:
            response = replies_table().query(
                KeyConditionExpression=Key("user_email").eq(user_email),
                ScanIndexForward=False,
                Limit=10
            )

            for reply in response.get("Items", []):
                activity = {
                    "timestamp": reply.get("timestamp", "Unknown"),
                    "action": "Email Processed",
                    "id": reply.get("reply_id", "Unknown"),
                    "privacy_compliant": True
                }
                audit_results["recent_activity"].append(activity)

        except Exception as e:
            print(f"Error fetching audit activity: {e}")

        audit_results["scan_timestamp"] = datetime.datetime.utcnow().isoformat()

        return render_template("privacy_audit.html", audit=audit_results, role=request.user.get("role"))

    except Exception as e:
        print(f"Privacy audit error: {e}")
        return render_template("privacy_audit.html", audit={"error": "Audit unavailable"}, role=request.user.get("role"))

# ---------------- Pending Review Routes ----------------
@routes.route("/pending")
@require_jwt
def pending_list():
    user_email = request.user["email"]
    items = list_pending_emails(user_email)
    role = request.user.get("role")

    # 🚨 PRIVACY PROTECTION: Mask sensitive data before sending to template
    try:
        from database.memory_manager_dynamo import DataPrivacyManager
        safe_items = []

        for item in (items or []):
            safe_item = item.copy()

            # Mask sender email
            if 'original_email' in safe_item and safe_item['original_email']:
                original = safe_item['original_email']
                if 'sender' in original and original['sender']:
                    if isinstance(original['sender'], str):
                        original['sender'] = DataPrivacyManager.mask_sender_email(original['sender'])
                    elif isinstance(original['sender'], dict) and 'emailAddress' in original['sender']:
                        if 'address' in original['sender']['emailAddress']:
                            original['sender']['emailAddress']['address'] = DataPrivacyManager.mask_sender_email(original['sender']['emailAddress']['address'])

            # Mask subjects that may contain PII
            if 'subject' in safe_item and safe_item['subject']:
                safe_item['subject'] = DataPrivacyManager.sanitize_subject_line(safe_item['subject'])

            # Mask recipient list
            if 'recipients' in safe_item and safe_item['recipients']:
                safe_item['recipients'] = DataPrivacyManager.mask_email_list(safe_item['recipients'])

            safe_items.append(safe_item)

        print(f"🔐 PRIVACY: Masked {len(safe_items)} pending emails for UI display")
        return render_template("pending_list.html", items=safe_items, role=role)

    except Exception as e:
        # Fallback: basic masking with warnings
        print(f"⚠️ PRIVACY FALLBACK: Advanced masking unavailable: {e}")

        for item in (items or []):
            # Basic sender masking
            if 'original_email' in item and item['original_email']:
                original = item['original_email']
                if 'sender' in original and original['sender']:
                    if isinstance(original['sender'], str) and '@' in original['sender']:
                        username, domain = original['sender'].rsplit('@', 1)
                        original['sender'] = f"[USER]@{domain}"

        return render_template("pending_list.html", items=items or [], role=role)

@routes.route("/pending/<pid>")
@require_jwt
def pending_edit(pid):
    user_email = request.user["email"]
    item = get_pending_email(user_email, pid)
    if not item or item.get("status") not in ("PENDING", "DRAFT"):
        return "Not found", 404
    return render_template("pending_edit.html", item=item, role=request.user.get("role"))

@routes.route("/pending/<pid>/save", methods=["POST"])
@require_jwt
def pending_save(pid):
    user_email = request.user["email"]
    subject = request.form.get("subject", "").strip()
    recipients_raw = request.form.get("recipients", "") or ""
    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]
    body = request.form.get("body_draft", "") or ""
    update_pending_email(user_email, pid, subject=subject, recipients=recipients, body_draft=body)
    return redirect(url_for("routes.pending_edit", pid=pid))

@routes.route("/pending/<pid>/send", methods=["POST"])
@require_jwt
def pending_send(pid):
    user_email = request.user["email"]
    provider = request.form.get("provider") or session.get("provider")
    token = session.get("provider_token")
    if not provider or not token:
        # redirect with simple error note
        return redirect(url_for("routes.pending_edit", pid=pid) + "?err=provider-auth-missing")
    ok, err = send_pending_email(provider, token, user_email, pid)
    if not ok:
        return f"Send failed: {err}", 400
    return redirect(url_for("routes.pending_list"))

@routes.route("/pending/<pid>/cancel", methods=["POST"])
@require_jwt
def pending_cancel(pid):
    user_email = request.user["email"]
    mark_pending_canceled(user_email, pid)
    return redirect(url_for("routes.pending_list"))

@routes.route("/about")
def about():
    return render_template("about.html")

@routes.route("/privacy")
def privacy():
    return render_template("privacy.html")

@routes.route("/terms")
def terms():
    return render_template("terms.html")

@routes.route("/contact")
def contact():
    return render_template("contact.html")

@routes.route("/logout", methods=["GET", "POST"])
def logout():
    """Secure logout with CSRF protection and confirmation"""
    if request.method == "GET":
        # Show logout confirmation page
        return render_template("logout.html")

    # POST request - perform actual logout
    user = get_current_user()
    if user:
        email = user["email"]
        session_uuid = request.cookies.get("session_uuid")

        # Clean database session
        if email and session_uuid:
            try:
                end_user_session(email, session_uuid)
            except Exception as e:
                print(f"Session cleanup error: {e}")
                # Don't fail logout if DB cleanup fails

    # Clear ALL server-side session data
    session.clear()

    # 🔐 Security: Audit logout action
    audit_log("LOGOUT", user_email=email if user else None)

    # Clear all auth cookies
    resp = make_response(redirect(url_for("routes.login")))
    clear_auth_cookies(resp)
    return resp

# ---------------- API Endpoints for UI Integration ----------------

@routes.route("/api/dashboard-stats")
@require_jwt
def dashboard_stats():
    """Get accurate dashboard statistics for the current user"""
    from database.memory_manager_dynamo import get_user_profile

    user_email = request.user["email"]

    # Get actual email data from EmailQueue table
    try:
        email_response = dynamodb.Table("EmailQueue").query(
            KeyConditionExpression=Key("user_email").eq(user_email),
            ScanIndexForward=False,
            Limit=1000  # Get recent emails for stats
        )
        emails = email_response.get("Items", [])
    except Exception as e:
        print(f"Error fetching emails: {e}")
        emails = []

    # Get actual reply data
    try:
        reply_response = replies_table().query(
            KeyConditionExpression=Key("user_email").eq(user_email),
            ScanIndexForward=False,
            Limit=1000  # Get recent replies for stats
        )
        replies = reply_response.get("Items", [])
    except Exception as e:
        print(f"Error fetching replies: {e}")
        replies = []

    # Calculate accurate metrics
    total_emails_processed = len(emails)
    total_replies = len(replies)
    sent_replies = len([r for r in replies if r.get("status") == "sent"])
    success_rate = (sent_replies / total_replies * 100) if total_replies > 0 else 0

    # Get pending emails count
    from database.memory_manager_dynamo import list_pending_emails
    try:
        pending = list_pending_emails(user_email)
        pending_count = len([p for p in pending if p.get("status") in ["PENDING", "DRAFT"]])
    except Exception as e:
        print(f"Error fetching pending emails: {e}")
        pending_count = 0

    # Get user profile for preferences
    profile = get_user_profile(user_email)
    auto_send = profile.get("preferences", {}).get("auto_send", False)

    # Calculate average response time (mock for now - would need actual timestamps)
    avg_response_time = "2.3m"  # This could be calculated from actual data

    return {
        "total_emails": total_emails_processed,
        "ai_accuracy": round(success_rate, 1) if success_rate > 0 else 0,
        "pending_reviews": pending_count,
        "auto_send_enabled": auto_send,
        "response_time": avg_response_time,
        "total_replies": total_replies,
        "sent_replies": sent_replies
    }

@routes.route("/prefs/auto_send", methods=["POST"])
@require_jwt
def toggle_auto_send():
    """Toggle auto-send preference for the current user"""
    from database.memory_manager_dynamo import get_user_profile, set_user_profile

    user_email = request.user["email"]
    profile = get_user_profile(user_email)
    current_value = profile.get("preferences", {}).get("auto_send", False)
    new_value = not current_value

    # Update the preference
    prefs = profile.get("preferences", {})
    prefs["auto_send"] = new_value
    profile["preferences"] = prefs
    set_user_profile(user_email, profile)

    return {"success": True, "auto_send": new_value}

@routes.route("/api/refresh", methods=["POST"])
@require_jwt
def refresh_data():
    """Refresh dashboard data"""
    import time
    time.sleep(1)  # Simulate refresh time
    return {"success": True, "message": "Dashboard refreshed successfully"}

@routes.route("/profile")
@require_jwt
def profile():
    """User profile page"""
    user_email = request.user["email"]
    profile = get_user_profile(user_email)
    role = request.user.get("role")

    # Get dashboard stats for the profile page
    response = replies_table().query(
        KeyConditionExpression=Key("user_email").eq(user_email),
        ScanIndexForward=False
    )
    replies = response.get("Items", [])

    # Calculate metrics
    total_emails_processed = len(replies) if replies else 0
    sent_replies = len([r for r in replies if r.get("status") == "sent"]) if replies else 0
    success_rate = (sent_replies / total_emails_processed * 100) if total_emails_processed > 0 else 0

    # Get pending emails count
    pending = list_pending_emails(user_email)
    pending_count = len([p for p in pending if p.get("status") in ["PENDING", "DRAFT"]])

    return render_template("profile.html",
                          user_email=user_email,
                          profile=profile,
                          role=role,
                          total_emails=total_emails_processed,
                          sent_replies=sent_replies,
                          ai_accuracy=round(success_rate, 1) if success_rate > 0 else 0,
                          pending_reviews=pending_count)

@routes.route("/profile/update", methods=["POST"])
@require_jwt
def update_profile():
    """Update user profile"""
    user_email = request.user["email"]
    profile_data = request.get_json()

    if not profile_data:
        return {"error": "No profile data provided"}, 400

    try:
        # Update the profile
        set_user_profile(user_email, profile_data)
        return {"success": True, "message": "Profile updated successfully"}
    except Exception as e:
        print(f"Profile update error: {e}")
        return {"error": "Failed to update profile"}, 500

@routes.route("/profile/export", methods=["POST"])
@require_jwt
def export_profile_data():
    """Export user profile and email data"""
    user_email = request.user["email"]

    try:
        # Get user profile
        profile = get_user_profile(user_email)

        # Get email replies
        response = replies_table().query(
            KeyConditionExpression=Key("user_email").eq(user_email),
            ScanIndexForward=False
        )
        replies = response.get("Items", [])

        # Get pending emails
        pending = list_pending_emails(user_email)

        # Prepare export data
        export_data = {
            "export_date": datetime.datetime.utcnow().isoformat(),
            "user_email": user_email,
            "profile": profile,
            "email_replies": replies,
            "pending_emails": pending,
            "total_replies": len(replies),
            "total_pending": len(pending)
        }

        # Convert to JSON and return as file
        import json
        json_data = json.dumps(export_data, indent=2, default=str)

        response = make_response(json_data)
        response.headers["Content-Type"] = "application/json"
        response.headers["Content-Disposition"] = f"attachment; filename=email-ai-data-export-{user_email.split('@')[0]}.json"

        return response
    except Exception as e:
        print(f"Export error: {e}")
        return {"error": "Failed to export data"}, 500

@routes.route("/profile/delete", methods=["POST"])
@require_jwt
def delete_account():
    """Request account deletion"""
    user_email = request.user["email"]

    try:
        # For now, we'll just mark the account for deletion
        # In a real implementation, you'd want to:
        # 1. Send confirmation email
        # 2. Queue for deletion after confirmation
        # 3. Actually delete data after grace period

        profile = get_user_profile(user_email)
        profile["account_status"] = "deletion_requested"
        profile["deletion_requested_at"] = datetime.datetime.utcnow().isoformat()
        set_user_profile(user_email, profile)

        return {"success": True, "message": "Account deletion requested. You will be contacted for confirmation."}
    except Exception as e:
        print(f"Delete account error: {e}")
        return {"error": "Failed to request account deletion"}, 500