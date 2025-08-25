import imaplib
import smtplib
import email
from email.message import EmailMessage

class CustomEmailClient:
    def __init__(self, config):
        self.email = config['email']
        self.password = config['password']
        self.imap_server = config['imap_server']
        self.smtp_server = config['smtp_server']

    def fetch_unread_emails(self):
        mail = imaplib.IMAP4_SSL(self.imap_server)
        mail.login(self.email, self.password)
        mail.select("inbox")
        status, messages = mail.search(None, 'UNSEEN')
        emails = []

        for num in messages[0].split():
            status, data = mail.fetch(num, '(RFC822)')
            msg = email.message_from_bytes(data[0][1])
            body = msg.get_payload(decode=True).decode(errors='ignore')
            emails.append({
                'from': {'emailAddress': {'address': msg['From']}},
                'subject': msg['Subject'],
                'body': {'content': body},
                'conversationId': msg['Message-ID'],
                'id': num.decode()
            })
        return emails

    def send_email(self, to_email, subject, body):
        msg = EmailMessage()
        msg["From"] = self.email
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP_SSL(self.smtp_server, 465) as server:
            server.login(self.email, self.password)
            server.send_message(msg)

    def mark_email_read(self, msg_id):
        pass