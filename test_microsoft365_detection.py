#!/usr/bin/env python3
"""
Test Microsoft 365 email detection specifically
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.auth_provider_detection import EmailProviderDetection

def test_microsoft365_detection():
    print("🎯 Testing Microsoft 365 Detection")
    print("=" * 40)

    # Test cases for Microsoft 365 emails
    test_emails = [
        "tareeque@evolvexai.ai",
        "user@company.onmicrosoft.com",
        "test@mybusiness.net",
        "admin@customdomain.org",
        "user@personalbusiness.com"
    ]

    print("📧 Testing various email domains:")
    print()

    for email in test_emails:
        provider, message = EmailProviderDetection.detect_provider(email)

        print(f"✉️  {email}")
        print(f"   Provider: {provider.name if provider else 'Unknown'}")
        print(f"   Message: {message}")
        print(f"   Auth Type: {EmailProviderDetection.get_recommended_auth_type(provider) if provider else 'N/A'}")

        if provider and provider.name == "Microsoft 365":
            print(f"   ✅ Microsoft 365 correctly detected!")
            print(f"   IMAP Server: {provider.imap_settings['server']}")
            print(f"   SMTP Server: {provider.smtp_settings['server']}")
        elif provider and provider.name == "Custom Domain":
            print(f"   ℹ️  Detected as Custom Domain - could be Microsoft 365")

        print()

    # Test credential enhancement
    print("🔧 Testing Microsoft 365 Credential Enhancement:")
    print("-" * 40)

    m365_email = "tareeque@evolvexai.ai"
    enhanced = EmailProviderDetection.enhance_credentials_for_provider(m365_email, "password123")

    print(f"📧 Email: {m365_email}")
    print(f"   Provider: {enhanced['provider']}")
    print(f"   IMAP: {enhanced['imap_server']}:{enhanced['imap_port']}")
    print(f"   SMTP: {enhanced['smtp_server']}:{enhanced['smtp_port']}")
    print(f"   OAuth2 Required: {enhanced.get('requires_oauth2', False)}")
    print(f"   App Password Required: {enhanced.get('requires_app_password', False)}")

if __name__ == "__main__":
    test_microsoft365_detection()