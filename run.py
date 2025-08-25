import os
from flask import Flask
from app.routes import init_app
from dotenv import load_dotenv
load_dotenv("secret.env")

app = Flask(__name__, template_folder="app/templates_web", static_folder="app/static")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "fallback-dev-secret")  # ✅ required for sessions

init_app(app)

if __name__ == "__main__":
    # Get port from environment variable (Railway provides this)
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("FLASK_ENV") != "production"

    print("🚀 Running Email Automation Web App...")
    print(f"📍 Port: {port}")
    print(f"🔧 Debug mode: {debug}")

    app.run(host="0.0.0.0", port=port, debug=debug)