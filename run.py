import os
from flask import Flask
from app.routes import init_app
from dotenv import load_dotenv
load_dotenv("secret.env")

app = Flask(__name__, template_folder="app/templates_web", static_folder="app/static")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "fallback-dev-secret")  # ✅ required for sessions

# 🛡️ Security Configuration
app.config.update(
    # Session security
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production",
    SESSION_COOKIE_SAMESITE="Lax",

    # General security
    PERMANENT_SESSION_LIFETIME=1800,  # 30 minutes

    # Rate limiting preparation
    RATELIMIT_STORAGE_URL="memory://",
)

# 🛡️ Security Headers
@app.after_request
def add_security_headers(response):
    # Prevent MIME type sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'

    # Prevent clickjacking
    response.headers['X-Frame-Options'] = 'DENY'

    # XSS protection
    response.headers['X-XSS-Protection'] = '1; mode=block'

    # HSTS in production
    if os.environ.get("FLASK_ENV") == "production":
        response.headers['Strict-Transport-Security'] = 'max-age=63072000; includeSubDomains'

    # Content Security Policy (basic)
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )

    # Referrer Policy
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'

    return response

# 🚫 Security: Log potential security issues
import logging
security_logger = logging.getLogger('security')
security_logger.setLevel(logging.WARNING)

# Basic rate limiting (can be enhanced with Flask-Limiter)
rate_limit_store = {}

init_app(app)

if __name__ == "__main__":
    # Get port from environment variable (Railway provides this)
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("FLASK_ENV") != "production"

    print("🚀 Running Email Automation Web App...")
    print(f"📍 Port: {port}")
    print(f"🔧 Debug mode: {debug}")

    app.run(host="0.0.0.0", port=port, debug=debug)