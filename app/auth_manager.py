from authlib.integrations.flask_client import OAuth
from flask import Flask
from dotenv import load_dotenv
import os
import msal

load_dotenv("secret.env")

oauth = OAuth()

# MSAL app for Outlook (Microsoft Login)
msal_app = msal.ConfidentialClientApplication(
    client_id=os.getenv("OUTLOOK_CLIENT_ID"),
    client_credential=os.getenv("OUTLOOK_CLIENT_SECRET"),
    authority="https://login.microsoftonline.com/common"
)

def init_oauth(app: Flask):
    oauth.init_app(app)

    # Get Railway domain for OAuth redirects
    railway_domain = os.getenv("RAILWAY_STATIC_URL", "https://dep-emauto-production.up.railway.app")

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