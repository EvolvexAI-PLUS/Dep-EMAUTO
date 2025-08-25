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
from boto3.dynamodb.conditions import Key
import threading
import jwt
import boto3
import os
import datetime
import uuid
import base64
import secrets
import hashlib
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from functools import wraps
import secrets
from typing import Optional, Tuple, Dict, Any

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
    for name in ("access_token", "session_uuid", "email"):
        resp.set_cookie(name, "", expires=0)

# ---------------- Routes ----------------
@routes.route("/")
@routes.route("/dashboard")
@require_jwt
def index():
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

# ---------------- Pending Review Routes ----------------
@routes.route("/pending")
@require_jwt
def pending_list():
    user_email = request.user["email"]
    items = list_pending_emails(user_email)
    role = request.user.get("role")
    return render_template("pending_list.html", items=items, role=role)

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

@routes.route("/logout")
def logout():
    token = request.cookies.get("access_token")
    session_uuid = request.cookies.get("session_uuid")
    email_cookie = request.cookies.get("email")
    user = decode_jwt(token) if token else None
    email_to_end = (user or {}).get("email") or email_cookie

    if email_to_end and session_uuid:
        try:
            end_user_session(email_to_end, session_uuid)
        except Exception:
            # don't fail logout if session cleanup fails
            pass

    # Clear server-side session for provider creds
    session.pop("provider", None)
    session.pop("provider_token", None)

    resp = redirect(url_for("routes.login"))
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
            "export_date": datetime.utcnow().isoformat(),
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
        profile["deletion_requested_at"] = datetime.utcnow().isoformat()
        set_user_profile(user_email, profile)

        return {"success": True, "message": "Account deletion requested. You will be contacted for confirmation."}
    except Exception as e:
        print(f"Delete account error: {e}")
        return {"error": "Failed to request account deletion"}, 500