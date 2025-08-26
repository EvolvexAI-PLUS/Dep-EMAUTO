import imaplib
import smtplib
import email
import json
import os
import socket
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from datetime import datetime
import bcrypt
import secrets
from cryptography.fernet import Fernet

# Encryption key for IMAP passwords (should be from environment variable in production)
IMAP_ENCRYPTION_KEY = os.getenv("IMAP_ENCRYPTION_KEY")
if IMAP_ENCRYPTION_KEY:
    ENCRYPTION_KEY = IMAP_ENCRYPTION_KEY
else:
    # Generate a proper Fernet key for development/testing
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    print(f"⚠️  Using generated encryption key: {ENCRYPTION_KEY}")
    print("⚠️  Set IMAP_ENCRYPTION_KEY environment variable for production!")

def encrypt_password(password: str) -> str:
    """Encrypt password for secure storage"""
    f = Fernet(ENCRYPTION_KEY.encode() if isinstance(ENCRYPTION_KEY, str) else ENCRYPTION_KEY)
    return f.encrypt(password.encode()).decode()

def decrypt_password(encrypted_password: str) -> str:
    """Decrypt password for IMAP authentication"""
    f = Fernet(ENCRYPTION_KEY.encode() if isinstance(ENCRYPTION_KEY, str) else ENCRYPTION_KEY)
    return f.decrypt(encrypted_password.encode()).decode()

class IMAPClient:
    """
    IMAP client for custom email providers (like huzaimah@aljual.ae)
    Handles both IMAP (reading) and SMTP (sending) operations
    """

    def __init__(self, credentials):
        """
        credentials = {
            'email': 'huzaimah@aljual.ae',
            'imap_server': 'mail.aljual.ae',
            'imap_port': 993,
            'smtp_server': 'mail.aljual.ae',
            'smtp_port': 587,
            'password_hash': 'encrypted_password_hash',  # For production
            'password': 'plaintext_password',            # For testing only
            'use_ssl': True
        }
        """
        self.email = credentials['email']
        self.imap_server = credentials.get('imap_server', f'mail.{self.email.split("@")[1]}')
        self.imap_port = credentials.get('imap_port', 993)
        self.smtp_server = credentials.get('smtp_server', f'mail.{self.email.split("@")[1]}')
        self.smtp_port = credentials.get('smtp_port', 587)
        self.use_ssl = credentials.get('use_ssl', True)

        # Handle both testing (plaintext) and production (encrypted) passwords
        if 'password' in credentials:
            # For testing - store plaintext password directly
            self.password_hash = credentials['password']
            self.is_encrypted = False
        elif 'password_hash' in credentials:
            # For production - store encrypted password
            self.password_hash = credentials['password_hash']
            self.is_encrypted = True
        else:
            raise ValueError("Either 'password' (for testing) or 'password_hash' (for production) must be provided")

        # Connection objects
        self.imap_client = None
        self.smtp_client = None

    def decrypt_password(self):
        """Decrypt password from encrypted storage or return plaintext for testing"""
        if self.is_encrypted:
            return decrypt_password(self.password_hash)
        else:
            # For testing - password is already plaintext
            return self.password_hash

    def get_password(self):
        """Get decrypted password for authentication"""
        return self.decrypt_password()

    def connect_imap(self):
        """Establish IMAP connection with enhanced error handling"""
        try:
            if self.imap_client and self.imap_client.state == 'SELECTED':
                return True

            password = self.get_password()

            # Enhanced SSL connection with timeout and better error handling
            if self.use_ssl:
                import ssl
                try:
                    # Create SSL context with better compatibility
                    ssl_context = ssl.create_default_context()
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE  # For self-signed certificates

                    # Try with custom SSL context first
                    self.imap_client = imaplib.IMAP4_SSL(
                        self.imap_server,
                        self.imap_port,
                        ssl_context=ssl_context,
                        timeout=30
                    )
                except Exception as ssl_error:
                    print(f"⚠️  SSL connection failed, trying standard SSL: {ssl_error}")
                    # Fallback to standard SSL
                    self.imap_client = imaplib.IMAP4_SSL(
                        self.imap_server,
                        self.imap_port,
                        timeout=30
                    )
            else:
                self.imap_client = imaplib.IMAP4(self.imap_server, self.imap_port, timeout=30)

            # Test connection with NOOP before login
            try:
                status, data = self.imap_client.noop()
                if status != 'OK':
                    print(f"⚠️  IMAP server response: {data}")
            except Exception as noop_error:
                print(f"⚠️  IMAP NOOP test failed: {noop_error}")

            # Login with better error handling
            status, data = self.imap_client.login(self.email, password)
            if status != 'OK':
                raise Exception(f"IMAP login failed: {data}")

            print(f"✅ IMAP connection successful to {self.imap_server}:{self.imap_port}")
            return True

        except ssl.SSLError as ssl_error:
            print(f"❌ SSL Connection Error: {ssl_error}")
            print("💡 Try disabling SSL or check server certificate")
            return False
        except socket.timeout as timeout_error:
            print(f"❌ Connection Timeout: {timeout_error}")
            print("💡 Check server address, port, and network connectivity")
            return False
        except socket.gaierror as dns_error:
            print(f"❌ DNS Resolution Error: {dns_error}")
            print("💡 Check server hostname and DNS configuration")
            return False
        except Exception as e:
            print(f"❌ IMAP connection failed: {e}")
            print(f"🔍 Server: {self.imap_server}:{self.imap_port}")
            print(f"🔒 SSL: {'Enabled' if self.use_ssl else 'Disabled'}")
            return False

    def connect_smtp(self):
        """Establish SMTP connection with enhanced error handling"""
        try:
            if self.smtp_client:
                return True

            password = self.get_password()

            if self.use_ssl:
                try:
                    # Try SSL connection with timeout
                    self.smtp_client = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, timeout=30)
                except Exception as ssl_error:
                    print(f"⚠️  SMTP SSL failed, trying without SSL: {ssl_error}")
                    # Fallback to non-SSL
                    self.smtp_client = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=30)
                    self.smtp_client.starttls()
            else:
                self.smtp_client = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=30)
                try:
                    self.smtp_client.starttls()
                except Exception as tls_error:
                    print(f"⚠️  STARTTLS failed: {tls_error}")

            # Login
            self.smtp_client.login(self.email, password)
            print(f"✅ SMTP connection successful to {self.smtp_server}:{self.smtp_port}")
            return True

        except smtplib.SMTPAuthenticationError as auth_error:
            print(f"❌ SMTP Authentication Error: {auth_error}")
            print("💡 Check email address and password")
            return False
        except smtplib.SMTPConnectError as connect_error:
            print(f"❌ SMTP Connection Error: {connect_error}")
            print("💡 Check server address and port")
            return False
        except socket.timeout as timeout_error:
            print(f"❌ SMTP Timeout: {timeout_error}")
            print("💡 Check server address and network connectivity")
            return False
        except socket.gaierror as dns_error:
            print(f"❌ SMTP DNS Error: {dns_error}")
            print("💡 Check server hostname")
            return False
        except Exception as e:
            print(f"❌ SMTP connection failed: {e}")
            print(f"🔍 Server: {self.smtp_server}:{self.smtp_port}")
            print(f"🔒 SSL: {'Enabled' if self.use_ssl else 'Disabled'}")
            return False

    def fetch_unread_emails(self, max_count=5):
        """
        Fetch unread emails from IMAP server
        Returns emails in the same format as other clients
        """
        if not self.connect_imap():
            return []

        try:
            # Select inbox
            status, data = self.imap_client.select('INBOX')
            if status != 'OK':
                return []

            # Search for unread emails
            status, data = self.imap_client.search(None, 'UNSEEN')
            if status != 'OK':
                return []

            email_ids = data[0].split()
            emails = []

            # Get the latest emails (reverse order)
            for email_id in email_ids[-max_count:]:
                try:
                    # Fetch email
                    status, data = self.imap_client.fetch(email_id, '(RFC822)')
                    if status != 'OK':
                        continue

                    raw_email = data[0][1]
                    email_message = email.message_from_bytes(raw_email)

                    # Parse email data
                    subject = self._decode_header(email_message.get('Subject', ''))
                    sender = self._decode_header(email_message.get('From', ''))
                    date = email_message.get('Date', '')

                    # Extract body
                    body = self._get_email_body(email_message)

                    # Extract sender email
                    sender_email = self._extract_sender_email(sender)

                    # Generate conversation ID
                    conversation_id = email_id.decode() if isinstance(email_id, bytes) else str(email_id)

                    email_data = {
                        'id': email_id.decode() if isinstance(email_id, bytes) else str(email_id),
                        'threadId': conversation_id,
                        'messageIdHeader': email_message.get('Message-ID', ''),
                        'from': {'emailAddress': {'address': sender_email}},
                        'subject': subject,
                        'body': {'content': body},
                        'conversationId': conversation_id,
                        'snippet': body[:100] if body else '',
                        'timestamp': date
                    }

                    emails.append(email_data)

                    # Mark as read
                    self.imap_client.store(email_id, '+FLAGS', '\\Seen')

                except Exception as e:
                    print(f"❌ Failed to process email {email_id}: {e}")
                    continue

            return emails

        except Exception as e:
            print(f"❌ Failed to fetch emails: {e}")
            return []

    def mark_as_read(self, email_id):
        """Mark email as read"""
        if not self.connect_imap():
            return False

        try:
            self.imap_client.store(email_id, '+FLAGS', '\\Seen')
            return True
        except Exception as e:
            print(f"❌ Failed to mark as read: {e}")
            return False

    def send_email(self, to_email, subject, body, thread_id=None, in_reply_to=None, references=None):
        """Send email via SMTP"""
        if not self.connect_smtp():
            return False

        try:
            # Create message
            message = MIMEMultipart()
            message['From'] = self.email
            message['To'] = to_email
            message['Subject'] = subject

            # Add threading headers if available
            if in_reply_to:
                message['In-Reply-To'] = in_reply_to
            if references:
                message['References'] = references

            # Add body
            message.attach(MIMEText(body, 'plain'))

            # Send email
            self.smtp_client.sendmail(self.email, to_email, message.as_string())

            print(f"✅ Email sent to {to_email} via IMAP/SMTP")
            return True

        except Exception as e:
            print(f"❌ Failed to send email: {e}")
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

    def _decode_header(self, header_text):
        """Decode email headers"""
        if not header_text:
            return ""

        try:
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

    def _get_email_body(self, email_message):
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

    def _extract_sender_email(self, sender_header):
        """Extract email address from sender header"""
        import re
        email_match = re.search(r'<([^>]+)>', sender_header)
        if email_match:
            return email_match.group(1)
        else:
            # Fallback: try to find any email pattern
            email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', sender_header)
            return email_match.group(0) if email_match else sender_header


# Utility functions for password management
def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode(), salt).decode()

def verify_password(password: str, hashed: str) -> bool:
    """Verify password against hash"""
    return bcrypt.checkpw(password.encode(), hashed.encode())

def test_imap_connection(credentials):
    """
    Test IMAP and SMTP connections
    credentials = {
        'email': 'huzaimah@aljual.ae',
        'imap_server': 'mail.aljual.ae',
        'imap_port': 993,
        'smtp_server': 'mail.aljual.ae',
        'smtp_port': 587,
        'password': 'plaintext_password',  # Only for testing
        'use_ssl': True
    }
    """
    client = IMAPClient(credentials)

    # Test IMAP
    imap_success = client.connect_imap()
    print(f"📧 IMAP Connection: {'✅ Success' if imap_success else '❌ Failed'}")

    # Test SMTP
    smtp_success = client.connect_smtp()
    print(f"📤 SMTP Connection: {'✅ Success' if smtp_success else '❌ Failed'}")

    # Clean up
    client.disconnect()

    return imap_success and smtp_success