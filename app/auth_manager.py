from authlib.integrations.flask_client import OAuth
from flask import Flask
from dotenv import load_dotenv
import os
import msal

load_dotenv("secret.env")

oauth = OAuth()

# MSAL app will be created in init_oauth with proper redirect URI
msal_app = None

def init_oauth(app: Flask):
    oauth.init_app(app)

    # Get Railway domain for OAuth redirects
    railway_domain = os.getenv("RAILWAY_STATIC_URL")
    if not railway_domain:
        # Fallback: construct from Railway-provided variables
        railway_domain = f"https://{os.getenv('RAILWAY_PROJECT_NAME', 'dep-emauto-production')}.up.railway.app"
    if not railway_domain.startswith('https://'):
        railway_domain = f"https://{railway_domain}"

    # === Microsoft Outlook (MSAL) ===
    global msal_app
    outlook_client_id = os.getenv("OUTLOOK_CLIENT_ID")
    outlook_client_secret = os.getenv("OUTLOOK_CLIENT_SECRET")

    print(f"🔍 Outlook Client ID: {'✅ Set' if outlook_client_id else '❌ Not set'}")
    print(f"🔍 Outlook Client Secret: {'✅ Set' if outlook_client_secret else '❌ Not set'}")

    if outlook_client_id and outlook_client_secret:
        # Create MSAL app with proper configuration for web app
        msal_app = msal.ConfidentialClientApplication(
            client_id=outlook_client_id,
            client_credential=outlook_client_secret,
            authority="https://login.microsoftonline.com/common",
            # Enable PKCE for cross-origin requests
            client_capabilities=["llt", "xms_cc"],
        )
        print("✅ MSAL app initialized successfully with PKCE support")
    else:
        print("❌ MSAL app not initialized - missing Outlook credentials")
        msal_app = None

    # === Google (Gmail) ===
    oauth.register(
        name='google',
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        redirect_uri=f"{railway_domain}/callback/google",
        client_kwargs={
            'scope': (
                'openid email profile '
                'https://www.googleapis.com/auth/gmail.readonly '
                'https://www.googleapis.com/auth/gmail.modify '
                'https://www.googleapis.com/auth/gmail.send'
            )
        }
    )

    # === Yahoo Mail ===
    if os.getenv("YAHOO_CLIENT_ID") and os.getenv("YAHOO_CLIENT_SECRET"):
        oauth.register(
            name='yahoo',
            client_id=os.getenv("YAHOO_CLIENT_ID"),
            client_secret=os.getenv("YAHOO_CLIENT_SECRET"),
            authorize_url='https://api.login.yahoo.com/oauth2/request_auth',
            access_token_url='https://api.login.yahoo.com/oauth2/get_token',
            redirect_uri=f"{railway_domain}/callback/yahoo",
            client_kwargs={
                'scope': 'mail-w'
            }
        )

    print("✅ OAuth providers registered: Google, Yahoo (Outlook via MSAL)")
    print(f"🔗 OAuth redirect domain: {railway_domain}")
    print(f"🔗 Google redirect URI: {railway_domain}/callback/google")
    print(f"🔗 Outlook redirect URI: {railway_domain}/callback/outlook")