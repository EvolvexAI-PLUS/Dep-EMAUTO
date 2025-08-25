import os
import requests
from dotenv import load_dotenv

# Load token from env or test secret
load_dotenv("secret.env")

refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")
client_id = os.getenv("GOOGLE_CLIENT_ID")
client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

if not refresh_token:
    raise ValueError("Missing GOOGLE_REFRESH_TOKEN in .env file")

# Google's OAuth token endpoint
url = "https://oauth2.googleapis.com/token"

data = {
    "client_id": client_id,
    "client_secret": client_secret,
    "refresh_token": refresh_token,
    "grant_type": "refresh_token"
}

print("🔄 Refreshing token...")
response = requests.post(url, data=data)

if response.status_code == 200:
    new_token = response.json()
    print("✅ Access token refreshed successfully:")
    print("Access Token:", new_token["access_token"])
    print("Expires In:", new_token.get("expires_in", "?"), "seconds")
else:
    print("❌ Failed to refresh token")
    print("Status:", response.status_code)
    print("Response:", response.text)