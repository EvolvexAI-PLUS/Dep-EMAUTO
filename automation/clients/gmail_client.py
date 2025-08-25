
import requests
import base64
import re


class GmailClient:
    def __init__(self, token):
        # token is a dict with access_token
        self.token = token['access_token']
        self.headers = {'Authorization': f'Bearer {self.token}'}
        self.base_url = 'https://gmail.googleapis.com/gmail/v1/users/me/'

    # -------- Helpers --------
    @staticmethod
    def _get_header(headers, name):
        for h in headers or []:
            if h.get('name', '').lower() == name.lower():
                return h.get('value')
        return None

    @staticmethod
    def _extract_email(addr):
        # Extract just the email from "Name <email@x.com>" or plain email
        if not addr:
            return ''
        m = re.search(r'<([^>]+)>', addr)
        return (m.group(1) if m else addr).strip().strip('"').lower()

    @staticmethod
    def _decode_body(data):
        if not data:
            return ''
        try:
            return base64.urlsafe_b64decode(data.encode('utf-8')).decode('utf-8', errors='ignore')
        except Exception as e:
            print(f"[DECODE ERROR] {e}")
            return ''

    def _get_body(self, payload):
        # Prefer text/plain; fallback to any text/*; search recursively
        def walk(p):
            body = p.get('body', {})
            data = body.get('data')
            mime = (p.get('mimeType') or '').lower()

            if data and (mime == 'text/plain'):
                return self._decode_body(data)

            # If multipart, walk parts
            for part in p.get('parts', []) or []:
                # First try text/plain in child
                if (part.get('mimeType') or '').lower() == 'text/plain' and part.get('body', {}).get('data'):
                    return self._decode_body(part['body']['data'])

            # Fallback: any text/*
            for part in p.get('parts', []) or []:
                pmime = (part.get('mimeType') or '').lower()
                if pmime.startswith('text/') and part.get('body', {}).get('data'):
                    return self._decode_body(part['body']['data'])

            # Recurse deeper if needed
            for part in p.get('parts', []) or []:
                if part.get('parts'):
                    inner = walk(part)
                    if inner:
                        return inner

            # Finally check top-level body if no parts
            if data and mime.startswith('text/'):
                return self._decode_body(data)
            if data and not p.get('parts'):
                return self._decode_body(data)
            return ''

        return walk(payload or {}) or ''

    # -------- API Methods --------
    def fetch_unread_emails(self, query=None, max_count=5):
        print("[GMAIL] Fetching unread emails...")
        q = query or "in:inbox is:unread -from:me"
        res = requests.get(self.base_url + f'messages?q={q}', headers=self.headers)

        if res.status_code != 200:
            print(f"[ERROR] Gmail API failed: {res.status_code} - {res.text}")
            return []

        messages = res.json().get('messages', [])
        total = len(messages)
        print(f"[GMAIL] Gmail returned {total} possibly unread emails.")

        emails = []
        for msg in messages[:max_count]:
            try:
                detail_res = requests.get(self.base_url + f"messages/{msg['id']}", headers=self.headers)
                if detail_res.status_code != 200:
                    print(f"[ERROR] Failed to get message {msg['id']}: {detail_res.status_code} - {detail_res.text}")
                    continue

                msg_detail = detail_res.json()
                payload = msg_detail.get('payload', {}) or {}
                headers = payload.get('headers', []) or []

                # Headers
                reply_to = self._get_header(headers, 'Reply-To')
                from_h = self._get_header(headers, 'From')
                subject = self._get_header(headers, 'Subject') or ''
                message_id_hdr = self._get_header(headers, 'Message-Id') or self._get_header(headers, 'Message-ID')

                sender_raw = reply_to or from_h or ''
                sender_email = self._extract_email(sender_raw)

                body = self._get_body(payload)
                gmail_id = msg_detail.get('id') or msg.get('id')
                thread_id = msg_detail.get('threadId') or msg.get('threadId')

                if not gmail_id or not sender_email:
                    print(f"[HEADERS] id={gmail_id} thread={thread_id} From={from_h} Reply-To={reply_to} Message-Id={message_id_hdr} Subject={subject}")
                    print(f"[SKIP] ⚠️ Missing sender or email ID: {msg.get('id')}")
                    continue

                emails.append({
                    'id': gmail_id,
                    'threadId': thread_id,
                    'messageIdHeader': message_id_hdr or '',
                    'from': {'emailAddress': {'address': sender_email}},
                    'subject': subject,
                    'body': {'content': body},
                    'conversationId': thread_id or gmail_id
                })

            except Exception as e:
                print(f"[ERROR] Failed to process message {msg.get('id')}: {e}")
                continue

        return emails

    def mark_as_read(self, email_id):
        try:
            response = requests.post(
                self.base_url + f"messages/{email_id}/modify",
                headers=self.headers,
                json={"removeLabelIds": ["UNREAD"]}
            )
            if response.status_code == 200:
                print(f"[MARKED ✅] Email {email_id} marked as read.")
            else:
                print(f"[ERROR] Failed to mark email {email_id} as read: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"[ERROR] Exception during mark_as_read: {e}")

    def send_email(self, to_email, subject, body, thread_id=None, in_reply_to=None, references=None):
        """
        Send a new email or a threaded reply via Gmail.
        If thread_id is provided, Gmail will append to that thread.
        Including In-Reply-To and References improves threading in some clients.
        """
        headers_lines = [
            f"To: {to_email}",
            f"Subject: {subject}",
            "Content-Type: text/plain; charset=UTF-8"
        ]
        if in_reply_to:
            headers_lines.append(f"In-Reply-To: {in_reply_to}")
        if references:
            headers_lines.append(f"References: {references}")

        raw_msg = "\r\n".join(headers_lines) + "\r\n\r\n" + body

        payload = {
            "raw": base64.urlsafe_b64encode(raw_msg.encode("utf-8")).decode("utf-8")
        }
        if thread_id:
            payload["threadId"] = thread_id

        url = self.base_url + "messages/send"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            print(f"[SENT ✅] Email sent to {to_email} via Gmail.")
        else:
            print(f"[ERROR] Gmail send failed: {response.status_code} - {response.text}")