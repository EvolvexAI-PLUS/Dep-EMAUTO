import boto3
import os
import json
import time
from datetime import datetime
from automation.send_reply import get_email_client
from database.memory_manager_dynamo import update_conversation, log_sent_reply
from dotenv import load_dotenv

load_dotenv("secret.env")

dynamodb = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "ap-south-1"))
REPLY_QUEUE_TABLE = os.getenv("REPLY_QUEUE_TABLE", "ReplyQueue")
EMAIL_QUEUE_TABLE = os.getenv("EMAIL_QUEUE_TABLE", "EmailQueue")

reply_table = dynamodb.Table(REPLY_QUEUE_TABLE)
email_table = dynamodb.Table(EMAIL_QUEUE_TABLE)

MAX_RETRIES = 3


def retry_failed_replies(provider, token, user_email):
    print(f"[RETRY] Checking for failed replies for {user_email}...")

    response = reply_table.scan(
        FilterExpression="attribute_exists(#status) AND #status = :failed",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":failed": "failed"}
    )

    failed_items = response.get("Items", [])

    if not failed_items:
        print("[RETRY] No failed replies to retry.")
        return

    client = get_email_client(provider, token, user_email)

    for item in failed_items:
        try:
            reply_id = item["reply_id"]
            email_id = item["email_id"]
            reply_text = item["reply_text"]
            retry_count = item.get("retry_count", 0)

            if retry_count >= MAX_RETRIES:
                print(f"[SKIP] Max retries reached for {reply_id}")
                continue

            email_record = email_table.get_item(Key={"email_id": email_id}).get("Item", {})
            to_email = email_record.get("sender")
            subject = "Re: " + email_record.get("subject", "No Subject")
            convo_id = email_record.get("conversationId", email_id)
            original_body = email_record.get("body", "")

            client.send_email(to_email, subject, reply_text)

            # Mark as sent
            reply_table.update_item(
                Key={"reply_id": reply_id},
                UpdateExpression="SET #status = :sent, retry_count = :count, updated_at = :updated",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":sent": "sent",
                    ":count": retry_count + 1,
                    ":updated": datetime.utcnow().isoformat()
                }
            )

            update_conversation(convo_id, "user", original_body)
            update_conversation(convo_id, "assistant", reply_text)
            log_sent_reply(convo_id, user_email, subject, reply_text, provider)

            print(f"[RETRY] Success: {reply_id} -> {to_email}")

        except Exception as e:
            # Increment retry count
            print(f"[RETRY ERROR] {reply_id} failed again: {e}")
            reply_table.update_item(
                Key={"reply_id": item["reply_id"]},
                UpdateExpression="SET retry_count = if_not_exists(retry_count, :zero) + :inc, updated_at = :updated",
                ExpressionAttributeValues={
                    ":zero": 0,
                    ":inc": 1,
                    ":updated": datetime.utcnow().isoformat()
                }
            )


# Optional: Command-line usage
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()

    token = json.loads(args.token)
    retry_failed_replies(args.provider, token, args.email)