"""
Smart IMAP Client with Universal Auto-Discovery
Handles any email provider automatically
"""

import imaplib
import smtplib
import ssl
import socket
from typing import Dict, Optional, Tuple
from .email_server_discovery import get_email_config


class SmartIMAPClient:
    """
    Intelligent IMAP client that auto-discovers server settings
    Works with any email provider including custom domains
    """

    def __init__(self, email: str, password: str = None, auth_token: str = None,
                 force_oauth: bool = False):
        """
        Initialize with email and either password or auth token
        Auto-discovers the correct server settings
        """
        self.email = email
        self.password = password
        self.auth_token = auth_token
        self.force_oauth = force_oauth
        self.domain = email.split('@')[1]

        # Discover server settings
        self.config = self._discover_config()

        # Connection objects
        self.imap_client = None
        self.smtp_client = None

    def _discover_config(self) -> Dict:
        """Auto-discover email server configuration"""

        print(f"🔍 Auto-discovering settings for {self.email}")

        # Get config from discovery service
        config = get_email_config(self.email)

        if config.get('discovery_failed'):
            print(f"⚠️ Discovery failed, using fallback: {config['fallback_config']}")
            return config['fallback_config']

        return config

    def connect_all(self) -> Tuple[bool, str]:
        """Connect both IMAP and SMTP"""

        imap_ok, imap_msg = self.connect_imap()
        smtp_ok, smtp_msg = self.connect_smtp()

        if imap_ok and smtp_ok:
            return True, "All connections successful"

        if not imap_ok and not smtp_ok:
            return False, f"IMAP: {imap_msg} | SMTP: {smtp_msg}"

        if not imap_ok:
            return False, f"IMAP failed: {imap_msg}"

        if not smtp_ok:
            return False, f"SMTP failed: {smtp_msg}"

        return True, "Connections established"

    def connect_imap(self) -> Tuple[bool, str]:
        """Connect to IMAP server with intelligent auth"""

        try:
            if not self.config or not self.config.get('imap_host'):
                return False, "No IMAP configuration available"

            host = self.config['imap_host']
            port = self.config.get('imap_port', 993)

            print(f"📧 Connecting to IMAP: {host}:{port}")

            # Establish SSL connection
            if self.config.get('use_ssl', True):
                context = ssl.create_default_context()
                # For custom domains, be more permissive with SSL
                if self.config.get('provider_type') == 'custom':
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE

                self.imap_client = imaplib.IMAP4_SSL(host, port, ssl_context=context)
            else:
                self.imap_client = imaplib.IMAP4(host, port)

            # Try authentication
            success, auth_msg = self._try_auth('imap')
            if success:
                print(f"✅ IMAP connected successfully")
                return True, "IMAP connected successfully"

            return False, f"Authentication failed: {auth_msg}"

        except ssl.SSLError as e:
            return False, f"SSL error: {e}"
        except socket.timeout:
            return False, f"Connection timeout to {host}:{port}"
        except socket.gaierror:
            return False, f"DNS resolution failed for {host}"
        except Exception as e:
            return False, f"IMAP connection error: {e}"

    def connect_smtp(self) -> Tuple[bool, str]:
        """Connect to SMTP server with intelligent auth"""

        try:
            if not self.config or not self.config.get('smtp_host'):
                return False, "No SMTP configuration available"

            host = self.config['smtp_host']
            port = self.config.get('smtp_port', 587)

            print(f"📤 Connecting to SMTP: {host}:{port}")

            # Try different connection methods
            connected = False

            # Method 1: SSL (port 465)
            if port == 465 or self._test_ssl_connection(host, 465):
                try:
                    self.smtp_client = smtplib.SMTP_SSL(host, 465)
                    connected = True
                    print("🏷️ Connected via SMTP_SSL")
                except Exception as e:
                    print(f"SMTP_SSL failed: {e}")

            # Method 2: STARTTLS (port 587)
            if not connected:
                try:
                    self.smtp_client = smtplib.SMTP(host, port)
                    self.smtp_client.starttls()
                    connected = True
                    print("🏷️ Connected via STARTTLS")
                except Exception as e:
                    print(f"STARTTLS failed: {e}")

            if not connected:
                return False, f"Could not establish SMTP connection to {host}"

            # Try authentication
            success, auth_msg = self._try_auth('smtp')
            if success:
                print(f"✅ SMTP connected successfully")
                return True, "SMTP connected successfully"

            return False, f"Authentication failed: {auth_msg}"

        except Exception as e:
            return False, f"SMTP connection error: {e}"

    def _try_auth(self, service: str) -> Tuple[bool, str]:
        """Try authentication with various methods"""

        if not hasattr(self, f'{service}_client') or getattr(self, f'{service}_client') is None:
            return False, f"No {service} client available"

        client = getattr(self, f'{service}_client')

        # Method 1: Password authentication
        if self.password:
            try:
                if service == 'imap':
                    res = client.login(self.email, self.password)
                    if res[0] == 'OK':
                        return True, "Password auth successful"
                else:  # SMTP
                    client.login(self.email, self.password)
                    return True, "Password auth successful"

            except Exception as e:
                error_msg = str(e).lower()

                # Check for Microsoft 365 specific errors
                if 'login failed' in error_msg or 'authentificationfailed' in error_msg:
                    if 'outlook.office365.com' in self.config.get('imap_host', ''):
                        return False, "Microsoft 365 blocked basic auth - use OAuth2 or App Password"

                print(f"Password auth failed: {e}")
                pass  # Continue to other methods

        # Method 2: OAuth2 (if available)
        if self.auth_token and self.config.get('auth_method') == 'oauth2':
            try:
                # Implement OAuth2 auth here
                # This requires provider-specific OAuth setup
                pass
            except Exception as e:
                print(f"OAuth2 auth failed: {e}")

        # Method 3: App password hint
        if self.config.get('requires_app_password') and not self.auth_token:
            return False, f"This provider requires an App Password. Visit: {self.config.get('help_url', 'provider settings')}"

        return False, "All authentication methods failed"

    def get_inbox_count(self) -> int:
        """Get number of messages in inbox"""

        if not self.imap_client:
            if not self.connect_imap()[0]:
                return 0

        try:
            self.imap_client.select('INBOX')
            status, data = self.imap_client.status('INBOX', '(MESSAGES)')
            if status == 'OK' and data:
                # Parse the status response
                # Format: ['INBOX (MESSAGES 123)']
                msg_match = data[0].decode().split()
                for i, part in enumerate(msg_match):
                    if part == 'MESSAGES':
                        return int(msg_match[i + 1])
            return 0
        except Exception as e:
            print(f"Failed to get inbox count: {e}")
            return 0

    def fetch_recent_emails(self, count: int = 5) -> list:
        """Fetch recent unread emails"""

        if not self.imap_client:
            if not self.connect_imap()[0]:
                return []

        try:
            self.imap_client.select('INBOX')

            # Get unread messages
            status, data = self.imap_client.search(None, 'UNSEEN')
            if status != 'OK':
                return []

            msg_nums = data[0].split()
            recent_msg_nums = msg_nums[-count:] if msg_nums else []

            emails = []
            for msg_num in recent_msg_nums:
                try:
                    status, msg_data = self.imap_client.fetch(msg_num, '(RFC822)')
                    if status != 'OK':
                        continue

                    # Parse email and add to list
                    email_data = self._parse_email(msg_data[0][1])
                    if email_data:
                        emails.append(email_data)

                    # Mark as read
                    self.imap_client.store(msg_num, '+FLAGS', '\\Seen')

                except Exception as e:
                    print(f"Failed to fetch email {msg_num}: {e}")
                    continue

            return emails

        except Exception as e:
            print(f"Failed to fetch emails: {e}")
            return []

    def _parse_email(self, raw_email: bytes) -> Dict:
        """Parse raw email data"""
        try:
            import email
            from email.header import decode_header

            email_message = email.message_from_bytes(raw_email)

            subject = self._decode_header(email_message.get('Subject', ''))
            sender = self._decode_header(email_message.get('From', ''))
            date = email_message.get('Date', '')

            # Extract body
            body = self._get_email_body(email_message)
            sender_email = self._extract_sender_email(sender)

            return {
                'id': email_message.get('Message-ID', ''),
                'subject': subject,
                'sender': sender_email,
                'body': body,
                'date': date,
                'snippet': body[:200] if body else ''
            }

        except Exception as e:
            print(f"Failed to parse email: {e}")
            return None

    def _decode_header(self, header_text: str) -> str:
        """Decode email headers"""
        if not header_text:
            return ""

        try:
            from email.header import decode_header
            decoded_parts = decode_header(header_text)
            decoded_text = ""
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    decoded_text += part.decode(encoding or 'utf-8', errors='ignore')
                else:
                    decoded_text += str(part)
            return decoded_text
        except:
            return str(header_text)

    def _get_email_body(self, email_message) -> str:
        """Extract email body"""
        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_type() == "text/plain":
                    try:
                        return part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    except:
                        return part.get_payload(decode=True).decode('latin-1', errors='ignore')
        else:
            try:
                return email_message.get_payload(decode=True).decode('utf-8', errors='ignore')
            except:
                return email_message.get_payload(decode=True).decode('latin-1', errors='ignore')

        return ""

    def _extract_sender_email(self, sender_header: str) -> str:
        """Extract email address from sender header"""
        import re
        email_match = re.search(r'<([^>]+)>', sender_header)
        if email_match:
            return email_match.group(1)
        else:
            email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', sender_header)
            return email_match.group(0) if email_match else sender_header.strip()

    def _test_ssl_connection(self, host: str, port: int) -> bool:
        """Test if SSL connection is possible"""
        try:
            context = ssl.create_default_context()
            with socket.create_connection((host, port), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname=host) as ssock:
                    return True
        except:
            return False

    def disconnect(self):
        """Clean up connections"""
        try:
            if self.imap_client:
                self.imap_client.logout()
                self.imap_client = None
        except:
            pass

        try:
            if self.smtp_client:
                self.smtp_client.quit()
                self.smtp_client = None
        except:
            pass

    def get_config_summary(self) -> Dict:
        """Get a summary of the discovered configuration"""
        return {
            'email': self.email,
            'domain': self.domain,
            'config': self.config,
            'connected': {
                'imap': self.imap_client is not None,
                'smtp': self.smtp_client is not None
            },
            'autodiscovery_source': self.config.get('discovered_via', 'unknown')
        }


def test_email_auto_discovery(email: str) -> Dict:
    """
    Test auto-discovery for any email address
    Returns connection status and settings
    """

    print(f"🧪 Testing auto-discovery for: {email}")

    # Test without password (just connectivity)
    # In real usage, you'd provide the password/auth token
    client = SmartIMAPClient(email, password=None)

    summary = client.get_config_summary()
    print("📋 Configuration Summary:")
    print(f"   IMAP: {summary['config'].get('imap_host', 'unknown')}:{summary['config'].get('imap_port', '?')}")
    print(f"   SMTP: {summary['config'].get('smtp_host', 'unknown')}:{summary['config'].get('smtp_port', '?')}")
    print(f"   Provider: {summary['config'].get('provider_type', 'unknown')}")
    print(f"   Auth Method: {summary['config'].get('auth_method', 'unknown')}")

    # Test connectivity (will fail auth, but prove we found the right servers)
    connected, msg = client.connect_imap()
    print(f"   Connection Test: {'SUCCESS' if connected else 'FAILED'} - {msg}")

    client.disconnect()
    return summary


if __name__ == '__main__':
    # Test examples
    test_emails = [
        'user@gmail.com',
        'person@outlook.com',
        'admin@company.com',
        'tareeque@evolvexai.ai'
    ]

    for email in test_emails:
        print(f"\n{'='*50}")
        test_email_auto_discovery(email)
        print(f"{'='*50}")