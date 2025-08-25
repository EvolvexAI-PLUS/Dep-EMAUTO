import requests
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class OutlookClient:
    BASE_URL = "https://graph.microsoft.com/v1.0/me"
    TIMEOUT = 10
    RETRIES = 2

    def __init__(self, access_token: str, client_id: Optional[str] = None):
        if not access_token:
            raise ValueError("Access token is required for OutlookClient.")
        self.token = access_token
        self.client_id = client_id

    def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: Optional[Dict[str, str]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        url = f"{self.BASE_URL}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Prefer": 'outlook.body-content-type="text"',
            "Content-Type": "application/json"
        }

        for attempt in range(1, self.RETRIES + 1):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=data,
                    timeout=self.TIMEOUT
                )
                response.raise_for_status()
                if response.status_code == 202:
                    return {"status": "Accepted"}
                return response.json()

            except requests.exceptions.HTTPError as e:
                logger.error(f"[OutlookClient] HTTP Error on attempt {attempt}: {e.response.status_code} - {e.response.text}")
                if e.response.status_code in [401, 403]:
                    break  # Token-related or forbidden, don't retry

            except requests.exceptions.RequestException as e:
                logger.warning(f"[OutlookClient] Request Error on attempt {attempt}: {str(e)}")

        logger.error(f"[OutlookClient] Failed after {self.RETRIES} attempts: {method} {url}")
        return None

    def fetch_unread_emails(self, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        Fetch unread emails from the inbox, sorted by most recent.
        """
        logger.info("[OutlookClient] 📬 Fetching unread Outlook emails...")
        params = {
            "$filter": "isRead eq false",
            "$orderby": "receivedDateTime desc",
            "$top": str(max_results)
        }

        result = self._make_request("mailFolders/inbox/messages", method="GET", params=params)
        messages = result.get("value", []) if result else []
        logger.info(f"[OutlookClient] 🔎 Retrieved {len(messages)} unread messages.")
        return messages

    def mark_as_read(self, message_id: str) -> None:
        """
        Mark a specific email message as read.
        """
        if not message_id:
            logger.warning("[OutlookClient] ❗ Email ID is required to mark as read.")
            return

        endpoint = f"messages/{message_id}"
        data = {"isRead": True}
        success = self._make_request(endpoint, method="PATCH", data=data)

        if success:
            logger.info(f"[OutlookClient] ✅ Marked email {message_id} as read.")
        else:
            logger.warning(f"[OutlookClient] ⚠️ Failed to mark email {message_id} as read.")

    def send_email(self, recipient: str, subject: str, body: str) -> bool:
        """
        Send an email using Microsoft Graph API.
        """
        logger.info(f"[OutlookClient] ✉️ Sending email to {recipient} with subject '{subject}'")
        endpoint = "sendMail"
        email_msg = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "Text",
                    "content": body
                },
                "toRecipients": [
                    {"emailAddress": {"address": recipient}}
                ]
            },
            "saveToSentItems": True
        }

        result = self._make_request(endpoint, method="POST", data=email_msg)

        if result and result.get("status") == "Accepted":
            logger.info(f"[OutlookClient] ✅ Email sent to {recipient}")
            return True
        else:
            logger.error(f"[OutlookClient] ❌ Failed to send email to {recipient}")
            return False