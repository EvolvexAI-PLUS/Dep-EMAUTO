"""
Universal Email Server Discovery and Auto-Configuration System
Handles various email providers including Microsoft 365 custom domains
"""

import dns.resolver
import socket
import ssl
import imaplib
import smtplib
import requests
from typing import Dict, Optional, Tuple, List
import time
import random
from urllib.parse import urlparse


class EmailServerDiscovery:
    """
    Intelligent email server discovery for any email provider
    Handles DNS lookups, MX records, AutoDiscover, and provider detection
    """

    def __init__(self, email: str):
        self.email = email
        self.domain = email.split('@')[1]
        self.discovery_methods = [
            'known_providers',
            'microsoft365_detect',
            'autodiscover',
            'google_workspace_detect',
            'dns_mx_lookup',
            'common_patterns',
            'fallback'
        ]

    def discover_settings(self) -> Optional[Dict]:
        """
        Try multiple discovery methods in order of reliability
        Returns IMAP/SMTP settings or None if discovery fails
        """

        print(f"🔍 Discovering email settings for {self.email}")

        for method in self.discovery_methods:
            try:
                method_func = getattr(self, f'_try_{method}')
                settings = method_func()

                if settings and self.test_settings(settings):
                    print(f"✅ Found working settings using {method}")
                    return settings

            except Exception as e:
                print(f"⚠️ {method} discovery failed: {e}")
                continue

        print("❌ All discovery methods failed")
        return None

    def _try_known_providers(self) -> Optional[Dict]:
        """Check database of known provider configurations"""

        known_configs = {
            'gmail.com': {
                'imap_host': 'imap.gmail.com',
                'imap_port': 993,
                'smtp_host': 'smtp.gmail.com',
                'smtp_port': 587,
                'auth_method': 'oauth2',
                'requires_app_password': True,
                'provider_type': 'google_workspace'
            },
            'googlemail.com': {
                'imap_host': 'imap.gmail.com',
                'imap_port': 993,
                'smtp_host': 'smtp.gmail.com',
                'smtp_port': 587,
                'auth_method': 'oauth2',
                'requires_app_password': True,
                'provider_type': 'google_workspace'
            },
            'outlook.com': {
                'imap_host': 'outlook.office365.com',
                'imap_port': 993,
                'smtp_host': 'smtp-mail.outlook.com',
                'smtp_port': 587,
                'auth_method': 'oauth2',
                'requires_app_password': True,
                'provider_type': 'microsoft365'
            },
            'hotmail.com': {
                'imap_host': 'outlook.office365.com',
                'imap_port': 993,
                'smtp_host': 'smtp-mail.outlook.com',
                'smtp_port': 587,
                'auth_method': 'oauth2',
                'requires_app_password': True,
                'provider_type': 'microsoft365'
            },
            'live.com': {
                'imap_host': 'outlook.office365.com',
                'imap_port': 993,
                'smtp_host': 'smtp-mail.outlook.com',
                'smtp_port': 587,
                'auth_method': 'oauth2',
                'requires_app_password': True,
                'provider_type': 'microsoft365'
            },
            'yahoo.com': {
                'imap_host': 'imap.mail.yahoo.com',
                'imap_port': 993,
                'smtp_host': 'smtp.mail.yahoo.com',
                'smtp_port': 587,
                'auth_method': 'oauth2',
                'requires_app_password': True,
                'provider_type': 'yahoo'
            },
            'aol.com': {
                'imap_host': 'imap.aol.com',
                'imap_port': 993,
                'smtp_host': 'smtp.aol.com',
                'smtp_port': 587,
                'auth_method': 'basic',
                'requires_app_password': True,
                'provider_type': 'aol'
            },
            'zoho.com': {
                'imap_host': 'imap.zoho.com',
                'imap_port': 993,
                'smtp_host': 'smtp.zoho.com',
                'smtp_port': 587,
                'auth_method': 'basic',
                'requires_app_password': True,
                'provider_type': 'zoho'
            }
        }

        config = known_configs.get(self.domain)
        if config:
            print(f"📋 Found known configuration for {self.domain}: {config['provider_type']}")
            return config

        return None

    def _try_microsoft365_detect(self) -> Optional[Dict]:
        """Detect if domain uses Microsoft 365/Exchange Online"""

        if self._is_microsoft365_domain():
            print(f"🔍 Detected Microsoft 365 for {self.domain}")

            return {
                'imap_host': 'outlook.office365.com',
                'imap_port': 993,
                'smtp_host': 'smtp-mail.outlook.com',
                'smtp_port': 587,
                'auth_method': 'oauth2',
                'requires_app_password': True,
                'provider_type': 'microsoft365',
                'custom_domain': self.domain not in ['outlook.com', 'hotmail.com', 'live.com'],
                'hints': {
                    'use_outlook_servers': True,
                    'custom_domain_warning': 'Use outlook.office365.com not mail.yourdomain.com',
                    'admin_required_settings': ['Authenticated SMTP', 'IMAP enabled']
                }
            }

        return None

    def _is_microsoft365_domain(self) -> bool:
        """Check if domain uses Microsoft 365 by analyzing DNS records"""

        try:
            # Check MX records for Microsoft patterns
            mx_records = dns.resolver.resolve(self.domain, 'MX')
            for mx in mx_records:
                mx_host = str(mx.exchange).lower()
                microsoft_indicators = [
                    'protection.outlook.com',
                    'mail.protection.outlook.com',
                    'outlook.com',
                    'mx.microsoft'
                ]

                if any(indicator in mx_host for indicator in microsoft_indicators):
                    return True

            # Check Autodiscover CNAME
            try:
                autodiscover_records = dns.resolver.resolve(
                    f'autodiscover.{self.domain}', 'CNAME'
                )
                for record in autodiscover_records:
                    if 'autodiscover.outlook.com' in str(record).lower():
                        return True
            except:
                pass

            # Check SRV records for Exchange Autodiscover
            try:
                srv_records = dns.resolver.resolve(
                    f'_autodiscover._tcp.{self.domain}', 'SRV'
                )
                for srv in srv_records:
                    if 'outlook.com' in str(srv.target).lower():
                        return True
            except:
                pass

        except Exception as e:
            print(f"DNS lookup failed for {self.domain}: {e}")

        return False

    def _try_autodiscover(self) -> Optional[Dict]:
        """Try Microsoft Autodiscover and Mozilla Autoconfig"""

        # Microsoft Autodiscover URLs
        autodiscover_urls = [
            f'https://autodiscover.{self.domain}/autodiscover/autodiscover.xml',
            f'https://{self.domain}/autodiscover/autodiscover.xml',
            'https://autodiscover-s.outlook.com/autodiscover/autodiscover.xml'
        ]

        # Try each URL
        for url in autodiscover_urls:
            try:
                print(f"🔍 Trying Autodiscover: {url}")

                # For HTTPS requests to custom domains, we might get SSL errors
                # but if it responds, we know it's Exchange
                response = requests.get(url, timeout=10, verify=False)

                if response.status_code == 401 or response.status_code == 403:
                    # Authentication required means it's likely valid Exchange
                    return {
                        'imap_host': 'outlook.office365.com',
                        'imap_port': 993,
                        'smtp_host': 'smtp-mail.outlook.com',
                        'smtp_port': 587,
                        'auth_method': 'oauth2',
                        'requires_app_password': True,
                        'provider_type': 'microsoft365',
                        'discovered_via': 'autodiscover'
                    }

                # Parse response to extract actual server settings
                if 'outlook' in response.text.lower():
                    return {
                        'imap_host': self._extract_server_from_xml(response.text, 'imap'),
                        'imap_port': 993,
                        'smtp_host': self._extract_server_from_xml(response.text, 'smtp'),
                        'smtp_port': 587,
                        'auth_method': 'oauth2',
                        'provider_type': 'microsoft365'
                    }

            except Exception as e:
                print(f"Autodiscover {url} failed: {e}")
                continue

        return None

    def _try_google_workspace_detect(self) -> Optional[Dict]:
        """Detect Google Workspace domains"""

        try:
            # Check MX records for Google
            mx_records = dns.resolver.resolve(self.domain, 'MX')
            for mx in mx_records:
                mx_host = str(mx.exchange).lower()
                if 'google' in mx_host or 'googlemail' in mx_host:
                    return {
                        'imap_host': 'imap.gmail.com',
                        'imap_port': 993,
                        'smtp_host': 'smtp.gmail.com',
                        'smtp_port': 587,
                        'auth_method': 'oauth2',
                        'requires_app_password': True,
                        'provider_type': 'google_workspace'
                    }
        except:
            pass

        return None

    def _try_dns_mx_lookup(self) -> Optional[Dict]:
        """Try DNS MX record analysis for server discovery"""

        try:
            mx_records = dns.resolver.resolve(self.domain, 'MX')

            # Analyze MX records to infer IMAP/SMTP servers
            for mx in mx_records:
                mx_host = str(mx.exchange).lower().rstrip('.')

                # Microsoft 365 patterns
                if 'protection.outlook.com' in mx_host:
                    return {
                        'imap_host': 'outlook.office365.com',
                        'imap_port': 993,
                        'smtp_host': 'smtp-mail.outlook.com',
                        'smtp_port': 587,
                        'auth_method': 'oauth2',
                        'provider_type': 'microsoft365'
                    }

                # Google Workspace patterns
                if 'google' in mx_host or 'googlemail' in mx_host:
                    return {
                        'imap_host': 'imap.gmail.com',
                        'imap_port': 993,
                        'smtp_host': 'smtp.gmail.com',
                        'smtp_port': 587,
                        'auth_method': 'oauth2',
                        'provider_type': 'google_workspace'
                    }

                # Zoho patterns
                if 'zoho' in mx_host:
                    return {
                        'imap_host': 'imap.zoho.com',
                        'imap_port': 993,
                        'smtp_host': 'smtp.zoho.com',
                        'smtp_port': 587,
                        'auth_method': 'basic',
                        'provider_type': 'zoho'
                    }

        except Exception as e:
            print(f"MX lookup failed: {e}")

        return None

    def _try_common_patterns(self) -> Optional[Dict]:
        """Try common server naming patterns"""

        patterns = [
            f'mail.{self.domain}',
            f'imap.{self.domain}',
            f'smtp.{self.domain}',
            f'email.{self.domain}',
            f'mx.{self.domain}',
            f'mx1.{self.domain}'
        ]

        for pattern in patterns:
            # Test IMAP
            if self._test_connection(pattern, 993, 'imap'):
                smtp_server = pattern.replace('imap', 'smtp').replace('mail', 'smtp')

                # If IMAP works, try to find SMTP
                if not self._test_connection(smtp_server, 587, 'smtp'):
                    smtp_server = pattern  # Use same server for both

                return {
                    'imap_host': pattern,
                    'imap_port': 993,
                    'smtp_host': smtp_server,
                    'smtp_port': 587,
                    'auth_method': 'basic',
                    'requires_app_password': True,  # Be safe
                    'provider_type': 'custom',
                    'discovered_via': 'pattern_matching'
                }

        return None

    def _try_fallback(self) -> Dict:
        """Fallback configuration for unknown domains"""

        return {
            'imap_host': f'mail.{self.domain}',
            'imap_port': 993,
            'smtp_host': f'mail.{self.domain}',
            'smtp_port': 587,
            'auth_method': 'basic',
            'requires_app_password': True,
            'provider_type': 'custom',
            'fallback': True,
            'hints': {
                'check_with_provider': True,
                'common_issues': [
                    'IMAP may be disabled',
                    'Port might be different (143, 110)',
                    'SSL/TLS settings may vary'
                ]
            }
        }

    def _test_connection(self, host: str, port: int, service: str) -> bool:
        """Test if a host:port combination accepts connections"""

        try:
            # Basic TCP connection test
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((host, port))
            sock.close()

            if result != 0:
                return False

            # For IMAP, try to establish SSL session
            if service == 'imap':
                try:
                    context = ssl.create_default_context()
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE

                    with socket.create_connection((host, port), timeout=5) as sock:
                        with context.wrap_socket(sock, server_hostname=host) as ssock:
                            # Try to read IMAP greeting
                            ssock.settimeout(3)
                            response = ssock.recv(1024)
                            return b'OK' in response or b'* OK' in response

                except Exception as e:
                    print(f"SSL test failed for {host}:{port}: {e}")
                    return False

            return True

        except Exception as e:
            print(f"Connection test failed for {host}:{port}: {e}")
            return False

    def _extract_server_from_xml(self, xml_content: str, service: str) -> Optional[str]:
        """Extract server settings from Autodiscover XML"""

        import xml.etree.ElementTree as ET

        try:
            root = ET.fromstring(xml_content)

            # Look for protocol settings
            for protocol in root.iter():
                if protocol.tag.endswith('Protocol'):
                    if protocol.findtext('.//{*}Type') == service.upper():
                        server = protocol.findtext('.//{*}Server')
                        if server:
                            return server

        except Exception as e:
            print(f"XML parsing failed: {e}")

        return None

    def test_settings(self, settings: Dict) -> bool:
        """Test if discovered settings work (quick connectivity test)"""

        if not settings or not settings.get('imap_host'):
            return False

        # Perform a quick connection test
        return self._test_connection(
            settings['imap_host'],
            settings.get('imap_port', 993),
            'imap'
        )

    def get_auth_help_url(self, provider_type: str) -> Optional[str]:
        """Get help URL for authentication setup"""

        help_urls = {
            'microsoft365': 'https://account.live.com/security/app-passwords',
            'google_workspace': 'https://myaccount.google.com/apppasswords',
            'yahoo': 'https://help.yahoo.com/kb/SLN15241.html',
            'outlook': 'https://support.microsoft.com/en-us/office/app-passwords-and-two-step-verification-68384be9-5b61-40fd-9d96-2b9d6fb1a5c1',
            'gmail': 'https://support.google.com/accounts/answer/185833'
        }

        return help_urls.get(provider_type.lower())


def get_email_config(email: str) -> Dict:
    """
    Main function to get email configuration for any email address
    Returns complete settings for IMAP/SMTP authentication
    """

    discovery = EmailServerDiscovery(email)
    settings = discovery.discover_settings()

    if settings:
        # Add additional metadata
        settings['email'] = email
        settings['domain'] = email.split('@')[1]
        settings['help_url'] = discovery.get_auth_help_url(settings.get('provider_type', ''))

        # Add security recommendations
        settings['connection_recommendations'] = {
            'use_ssl': True,
            'preferred_auth': settings.get('auth_method', 'basic'),
            'security_notes': [
                "Use SSL/TLS encryption (ports 993/587 with SSL)",
                "Avoid plain authentication on public networks",
                "Consider OAuth2 for commercial providers"
            ]
        }

        return settings

    # Total failure fallback
    return {
        'email': email,
        'domain': email.split('@')[1],
        'discovery_failed': True,
        'fallback_config': {
            'imap_host': f'mail.{email.split("@")[1]}',
            'imap_port': 993,
            'smtp_host': f'mail.{email.split("@")[1]}',
            'smtp_port': 587,
            'auth_method': 'basic',
            'requires_manual_config': True
        },
        'error_message': 'Unable to auto-discover email settings. You may need to configure manually.'
    }


if __name__ == '__main__':
    # Test the discovery system
    test_emails = [
        'user@gmail.com',
        'person@outlook.com',
        'admin@company.com',  # Custom domain (might be Microsoft 365)
        'tareeque@evolvexai.ai'  # Your Microsoft 365 custom domain
    ]

    for email in test_emails:
        print(f"\n{'='*60}")
        print(f"Testing: {email}")
        print(f"{'='*60}")

        config = get_email_config(email)

        if config.get('discovery_failed'):
            print("❌ Discovery failed!")
            print(f"Fallback: {config.get('fallback_config', {})}")
        else:
            print("✅ Discovery successful!")
            print(f"IMAP: {config.get('imap_host')}:{config.get('imap_port')}")
            print(f"SMTP: {config.get('smtp_host')}:{config.get('smtp_port')}")
            print(f"Auth: {config.get('auth_method')}")
            print(f"Provider: {config.get('provider_type')}")

            if config.get('custom_domain'):
                print("🎯 Custom domain detected!")
            if config.get('hints'):
                print(f"Tips: {config.get('hints')}")