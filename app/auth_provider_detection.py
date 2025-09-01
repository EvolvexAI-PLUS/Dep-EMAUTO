"""
Enhanced Email Provider Detection and Authentication Handler
Supports OAuth2, App Passwords, and Basic Auth based on provider requirements
"""

import re
from typing import Dict, Optional, Tuple, List


class EmailProvider:
    """Represents an email service provider with its authentication requirements"""

    def __init__(self, name: str, domains: List[str], authentication_types: List[str],
                 imap_settings: Dict, smtp_settings: Dict, oauth_scopes: List[str] = None,
                 domain_patterns: List[str] = None):
        self.name = name
        self.domains = domains
        self.domain_patterns = domain_patterns or []  # Regex patterns for dynamic domain matching
        self.authentication_types = authentication_types  # ['oauth2', 'app_password', 'basic']
        self.imap_settings = imap_settings
        self.smtp_settings = smtp_settings
        self.oauth_scopes = oauth_scopes or []


# Provider configurations
PROVIDERS = [
    EmailProvider(
        name="Gmail",
        domains=["gmail.com", "googlemail.com"],
        authentication_types=["oauth2", "app_password"],
        imap_settings={
            "server": "imap.gmail.com",
            "port": 993,
            "use_ssl": True
        },
        smtp_settings={
            "server": "smtp.gmail.com",
            "port": 587,
            "use_ssl": True
        },
        oauth_scopes=[
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.send"
        ]
    ),

    EmailProvider(
        name="Microsoft 365",
        domains=[],  # Dynamic detection
        domain_patterns=[".*\.onmicrosoft\.com$", ".*"],  # Matches any domain potentially using M365
        authentication_types=["oauth2", "app_password"],
        imap_settings={
            "server": "outlook.office365.com",
            "port": 993,
            "use_ssl": True
        },
        smtp_settings={
            "server": "smtp-mail.outlook.com",
            "port": 587,
            "use_ssl": True
        },
        oauth_scopes=[
            "User.Read",
            "Mail.ReadWrite",
            "Mail.Send"
        ]
    ),

    EmailProvider(
        name="Outlook",
        domains=["outlook.com", "hotmail.com", "live.com", "msn.com"],
        authentication_types=["oauth2", "app_password"],
        imap_settings={
            "server": "outlook.office365.com",
            "port": 993,
            "use_ssl": True
        },
        smtp_settings={
            "server": "smtp-mail.outlook.com",
            "port": 587,
            "use_ssl": True
        },
        oauth_scopes=[
            "User.Read",
            "Mail.ReadWrite",
            "Mail.Send"
        ]
    ),

    EmailProvider(
        name="Yahoo",
        domains=["yahoo.com", "yahoo.co.uk", "ymail.com"],
        authentication_types=["oauth2", "app_password"],
        imap_settings={
            "server": "imap.mail.yahoo.com",
            "port": 993,
            "use_ssl": True
        },
        smtp_settings={
            "server": "smtp.mail.yahoo.com",
            "port": 587,
            "use_ssl": True
        },
        oauth_scopes=["mail-w"]
    ),

    EmailProvider(
        name="AOL",
        domains=["aol.com"],
        authentication_types=["app_password"],
        imap_settings={
            "server": "imap.aol.com",
            "port": 993,
            "use_ssl": True
        },
        smtp_settings={
            "server": "smtp.aol.com",
            "port": 587,
            "use_ssl": True
        }
    ),

    EmailProvider(
        name="Custom Domain",
        domains=[],  # Special case for custom domains
        authentication_types=["basic", "app_password"],
        imap_settings={
            "server": None,  # Auto-detected as mail.domain.com
            "port": 993,
            "use_ssl": True
        },
        smtp_settings={
            "server": None,  # Auto-detected as mail.domain.com
            "port": 587,
            "use_ssl": True
        }
    )
]


class EmailProviderDetection:
    """Detects email provider and suggests optimal authentication method"""

    @staticmethod
    def detect_provider(email: str) -> Tuple[Optional[EmailProvider], str]:
        """Detect email provider based on email domain"""
        if not email or '@' not in email:
            return None, "Invalid email format"

        domain = email.split('@')[1].lower()

        # Check specific providers first
        for provider in PROVIDERS:
            if domain in provider.domains:
                return provider, "Provider detected"

        # Check domain patterns for dynamic providers (like Microsoft 365)
        import re
        for provider in PROVIDERS:
            if provider.domain_patterns:
                for pattern in provider.domain_patterns:
                    if re.match(pattern, domain):
                        # For Microsoft 365, we want to be more confident
                        if provider.name == "Microsoft 365":
                            # Microsoft 365 might use custom domains, so check for common patterns
                            # or just assume it's M365 for any non-Gmail domain
                            if not domain.endswith(('gmail.com', 'yahoo.com', 'hotmail.com', 'live.com')):
                                return provider, "Microsoft 365/Exchange Online detected"
                        else:
                            return provider, f"Provider pattern matched: {pattern}"

        # Enhanced detection: Try to identify Microsoft 365 by domain
        # If it's not a common personal email and not in our list, it might be M365
        if not any(domain.endswith(personal) for personal in ['gmail.com', 'yahoo.com', 'hotmail.com', 'live.com', 'aol.com']):
            # For Microsoft 365 detection, provide M365 settings
            m365_provider = next(p for p in PROVIDERS if p.name == "Microsoft 365")
            return m365_provider, "Likely Microsoft 365/Exchange Online domain"

        # Custom domain fallback
        custom_provider = next(p for p in PROVIDERS if p.name == "Custom Domain")
        custom_provider.imap_settings["server"] = f"mail.{domain}"
        custom_provider.smtp_settings["server"] = f"mail.{domain}"

        return custom_provider, "Custom domain configuration"

    @staticmethod
    def get_recommended_auth_type(provider: EmailProvider) -> str:
        """Get recommended authentication type for provider"""
        if "oauth2" in provider.authentication_types:
            return "oauth2"
        elif "app_password" in provider.authentication_types:
            return "app_password"
        else:
            return "basic"

    @staticmethod
    def get_authentication_guide(provider: EmailProvider, auth_type: str) -> str:
        """Get specific instructions for authentication setup"""

        guides = {
            "gmail_oauth2": """
🔐 Gmail OAuth2 Setup:
1. Go to Google Cloud Console
2. Enable Gmail API and create OAuth2 credentials
3. Add your redirect URIs
4. Configure scopes: mail.readonly, mail.modify, mail.send
5. Use the OAuth2 flow for authentication
            """,

            "gmail_app_password": """
🔑 Gmail App Password Setup:
1. Enable 2-Factor Authentication on your Google account
2. Go to Google Account Settings > Security > App passwords
3. Generate an app password for "Email Automation"
4. Use this 16-character password instead of your regular password
5. Keep your app password secure - it has full email access
            """,

            "outlook_oauth2": """
🔐 Outlook OAuth2 Setup:
1. Register your app in Azure AD
2. Add delegated permissions: Mail.ReadWrite, Mail.Send
3. Configure redirect URIs
4. Use Microsoft Authentication Library (MSAL)
5. The system already supports this - just use the OAuth button
            """,

            "outlook_app_password": """
🔑 Outlook App Password Setup:
1. Go to your Microsoft account security settings
2. Enable two-step verification if not already
3. Generate an app password under "Security" > "App passwords"
4. Use this password instead of your regular password
5. Label it clearly for email automation use
            """,

            "yahoo_oauth2": """
🔐 Yahoo OAuth2 Setup:
1. Register your app in Yahoo Developer Console
2. Enable Mail API with read/write permissions
3. Configure OAuth2 redirect URIs
4. Use the Yahoo OAuth2 flow
5. Support for Yahoo OAuth2 is available
            """,

            "yahoo_app_password": """
🔑 Yahoo App Password Setup:
1. Go to your Yahoo Account Security settings
2. Enable two-step verification
3. Generate an app password for third-party apps
4. Use this app password instead of your regular password
5. This provides secure access to your Yahoo Mail
            """
        }

        provider_name = provider.name.lower()
        auth_key = f"{provider_name}_{auth_type}"

        return guides.get(auth_key, f"""
📧 {provider.name} Authentication Setup:
- IMAP Server: {provider.imap_settings['server']}:{provider.imap_settings['port']}
- SMTP Server: {provider.smtp_settings['server']}:{provider.smtp_settings['port']}
- Use SSL: {'Yes' if provider.imap_settings['use_ssl'] else 'No'}
- Check your provider's documentation for specific setup instructions
- For custom domains, contact your email administrator for IMAP/SMTP settings
        """).strip()

    @staticmethod
    def validate_server_settings(imap_server: str, smtp_server: str, email: str) -> Tuple[bool, str]:
        """Validate IMAP/SMTP server settings against expected values"""
        provider, _ = EmailProviderDetection.detect_provider(email)

        if not provider:
            return True, "Unable to validate - provider not detected"

        # For custom domains, any settings are potentially valid
        if provider.name == "Custom Domain":
            return True, "Custom domain settings accepted"

        # Check if provided servers match expected
        expected_imap = provider.imap_settings['server']
        expected_smtp = provider.smtp_settings['server']

        if imap_server != expected_imap or smtp_server != expected_smtp:
            warning = (f"Server settings don't match {provider.name} defaults. "
                      f"Expected IMAP: {expected_imap}, SMTP: {expected_smtp}. "
                      "This might work if you've customized your settings, but common issues result from incorrect servers.")

            # Allow override but warn user
            return True, warning

        return True, "Server settings match provider defaults"

    @staticmethod
    def enhance_credentials_for_provider(email: str, password: str,
                                       imap_server: str = None, smtp_server: str = None,
                                       provider_override: str = None) -> Dict:
        """Enhance IMAP credentials with provider-specific optimizations"""

        provider, message = EmailProviderDetection.detect_provider(email)

        # Allow manual provider override
        if provider_override and provider_override.lower() in [p.name.lower() for p in PROVIDERS]:
            provider = next(p for p in PROVIDERS if p.name.lower() == provider_override.lower())

        if not provider:
            # Fallback for unknown providers
            domain = email.split('@')[1] if '@' in email else email
            return {
                'email': email,
                'password': password,
                'imap_server': imap_server or f'mail.{domain}',
                'imap_port': 993,
                'smtp_server': smtp_server or f'mail.{domain}',
                'smtp_port': 587,
                'use_ssl': True,
                'provider': 'Unknown/Custom',
                'auth_method': 'basic'
            }

        return {
            'email': email,
            'password': password,
            'imap_server': imap_server or provider.imap_settings['server'],
            'imap_port': provider.imap_settings['port'],
            'smtp_server': smtp_server or provider.smtp_settings['server'],
            'smtp_port': provider.smtp_settings['port'],
            'use_ssl': provider.imap_settings.get('use_ssl', True),
            'provider': provider.name,
            'auth_method': EmailProviderDetection.get_recommended_auth_type(provider),
            'requires_oauth2': 'oauth2' in provider.authentication_types,
            'requires_app_password': 'app_password' in provider.authentication_types,
            'oauth_scopes': provider.oauth_scopes
        }


def diagnose_authentication_error(error_message: str, email: str) -> Dict:
    """Diagnose common authentication errors and provide specific solutions"""

    provider, _ = EmailProviderDetection.detect_provider(email)
    provider_name = provider.name if provider else "Unknown"
    domain = email.split('@')[1] if '@' in email else "unknown"

    diagnoses = {
        'authentication_failed': {
            'problem': "Authentication credentials incorrect or not accepted",
            'solutions': [
                "Verify email and password/app-password are correct",
                "For Gmail/Outlook/Yahoo: Use app-specific password instead of regular password",
                "Enable 2FA on your account to generate app passwords",
                "Check if your provider requires special permissions or app registration"
            ]
        },

        'microsoft_365_auth': {
            'problem': "Microsoft 365 authentication failed - OAuth2 recommended",
            'solutions': [
                "🎯 RECOMMENDED: Use the 'Sign in with Microsoft' OAuth2 button instead of IMAP",
                "Microsoft 365 prefers OAuth2 authentication for security",
                "IMAP with Microsoft 365 can be complex and may require special app password setup",
                "If you must use IMAP:",
                "   • Enable IMAP access in Microsoft 365 admin center",
                "   • Create an 'App Password' in your Microsoft account settings"
            ]
        },

        'imap_disabled': {
            'problem': "IMAP/SMTP access is disabled on your account",
            'solutions': [
                f"Enable IMAP access in your {provider_name} account settings",
                f"For Gmail: Go to Settings > Forwarding and POP/IMAP > Enable IMAP",
                f"For Outlook: Ensure POP/IMAP is enabled in account settings",
                f"For Yahoo: Check Account Security settings for IMAP access",
                f"For Microsoft 365: Enable IMAP in the Microsoft 365 admin center"
            ]
        },

        'less_secure_apps_blocked': {
            'problem': "Your email provider blocks 'less secure apps'",
            'solutions': [
                "Use app-specific password (recommended)",
                "Consider using OAuth2 authentication instead",
                f"Check {provider_name} security settings for third-party access"
            ]
        },

        'connection_refused': {
            'problem': "Email servers are refusing connection",
            'solutions': [
                f"Verify IMAP/SMTP server settings for {provider_name}",
                "Check if your firewall/antivirus is blocking mail connections",
                "Try toggling SSL/TLS settings (enable/disable)",
                "Contact your email provider if servers are down"
            ]
        },

        'certificate_error': {
            'problem': "SSL/TLS certificate verification failed",
            'solutions': [
                "Try disabling SSL verification temporarily (not recommended for production)",
                "Check if server certificate is valid",
                "For Microsoft 365: Ensure you're using 'outlook.office365.com' as IMAP server",
                f"For {provider_name}: Verify you're using the correct server name"
            ]
        },

        'server_not_verified': {
            'problem': "Server cannot be verified or connected",
            'solutions': [
                f"For Microsoft 365: Ensure you're using outlook.office365.com (not your custom domain)",
                f"For {provider_name}: Verify the exact server names and ports",
                "Check if your domain has proper MX records pointing to the email provider",
                "Try using OAuth2 authentication instead - it's more reliable",
                "If connecting from restricted network, check firewall/proxy settings"
            ]
        },

        'dns_resolution': {
            'problem': "DNS resolution failed - mail server not found",
            'solutions': [
                "For Microsoft 365: IMAP should be 'outlook.office365.com', SMTP 'smtp-mail.outlook.com'",
                "For custom domains: Ensure your mail server (mail.yourdomain.com) exists and is accessible",
                "Check if your domain's DNS records are properly configured",
                "Contact your email hosting provider for correct server addresses"
            ]
        }
    }

    # Analyze error message and return most likely diagnosis
    error_lower = error_message.lower()

    # Special handling for Microsoft 365 errors
    if provider and provider.name == "Microsoft 365":
        if any(keyword in error_lower for keyword in ['auth', 'login', 'password']):
            return diagnoses['microsoft_365_auth']
        elif any(keyword in error_lower for keyword in ['verif', 'cannot be verified', 'certificate']):
            return diagnoses['server_not_verified']
        elif any(keyword in error_lower for keyword in ['connect', 'refused']):
            return diagnoses['connection_refused']

    # Standard error pattern matching
    if any(keyword in error_lower for keyword in ['auth', 'login', 'password', 'credentials']):
        return diagnoses['authentication_failed']
    elif any(keyword in error_lower for keyword in ['imap', 'disabled', 'not enabled']):
        return diagnoses['imap_disabled']
    elif any(keyword in error_lower for keyword in ['less secure', 'security', 'blocked']):
        return diagnoses['less_secure_apps_blocked']
    elif any(keyword in error_lower for keyword in ['connection', 'refused', 'connect']):
        return diagnoses['connection_refused']
    elif any(keyword in error_lower for keyword in ['certificate', 'ssl', 'tls']):
        return diagnoses['certificate_error']
    elif any(keyword in error_lower for keyword in ['verif', 'cannot be verified']):
        return diagnoses['server_not_verified']
    elif any(keyword in error_lower for keyword in ['name or service not known', 'dns', 'resolution']):
        return diagnoses['dns_resolution']
    else:
        # Default diagnosis with provider-specific suggestions
        base_solutions = [
            "Verify all email settings are correct",
            "Try using app-specific password instead of regular password",
            "Contact your email provider's support"
        ]

        if provider and provider.name == "Microsoft 365":
            base_solutions.insert(0, "🎯 RECOMMENDED: Use 'Sign in with Microsoft' OAuth2 button instead of IMAP")
            base_solutions.append("Microsoft 365 works best with OAuth2 authentication")

        return {
            'problem': "Unknown authentication error",
            'solutions': base_solutions
        }