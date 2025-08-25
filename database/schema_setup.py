import boto3
import os
from dotenv import load_dotenv

load_dotenv("secret.env")

region = os.getenv("AWS_REGION", "ap-south-1")
dynamodb = boto3.client("dynamodb", region_name=region)

def create_email_queue():
    dynamodb.create_table(
        TableName="EmailQueue",
        KeySchema=[
            {"AttributeName": "user_email", "KeyType": "HASH"},
            {"AttributeName": "email_id", "KeyType": "RANGE"}
        ],
        AttributeDefinitions=[
            {"AttributeName": "user_email", "AttributeType": "S"},
            {"AttributeName": "email_id", "AttributeType": "S"}
        ],
        BillingMode="PROVISIONED",
        ProvisionedThroughput={
            "ReadCapacityUnits": 5,
            "WriteCapacityUnits": 5
        }
    )
    print("✅ Created table: EmailQueue")

def create_reply_queue():
    dynamodb.create_table(
        TableName="ReplyQueue",
        KeySchema=[
            {"AttributeName": "user_email", "KeyType": "HASH"},
            {"AttributeName": "reply_id", "KeyType": "RANGE"}
        ],
        AttributeDefinitions=[
            {"AttributeName": "user_email", "AttributeType": "S"},
            {"AttributeName": "reply_id", "AttributeType": "S"}
        ],
        BillingMode="PAY_PER_REQUEST"
    )
    print("✅ Created table: ReplyQueue")

def create_email_conversations():
    dynamodb.create_table(
        TableName="EmailConversations",
        KeySchema=[
            {"AttributeName": "user_email", "KeyType": "HASH"},
            {"AttributeName": "timestamp", "KeyType": "RANGE"}
        ],
        AttributeDefinitions=[
            {"AttributeName": "user_email", "AttributeType": "S"},
            {"AttributeName": "timestamp", "AttributeType": "S"},
            {"AttributeName": "convo_id", "AttributeType": "S"}
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "user_convo_index",
                "KeySchema": [
                    {"AttributeName": "user_email", "KeyType": "HASH"},
                    {"AttributeName": "convo_id", "KeyType": "RANGE"}
                ],
                "Projection": {"ProjectionType": "ALL"},
                "ProvisionedThroughput": {
                    "ReadCapacityUnits": 5,
                    "WriteCapacityUnits": 5
                }
            }
        ],
        BillingMode="PROVISIONED",
        ProvisionedThroughput={
            "ReadCapacityUnits": 5,
            "WriteCapacityUnits": 5
        }
    )
    print("✅ Created table: EmailConversations with GSI")

def create_email_replies():
    dynamodb.create_table(
        TableName="EmailReplies",
        KeySchema=[
            {"AttributeName": "user_email", "KeyType": "HASH"},
            {"AttributeName": "id", "KeyType": "RANGE"}
        ],
        AttributeDefinitions=[
            {"AttributeName": "user_email", "AttributeType": "S"},
            {"AttributeName": "id", "AttributeType": "S"}
        ],
        BillingMode="PROVISIONED",
        ProvisionedThroughput={
            "ReadCapacityUnits": 5,
            "WriteCapacityUnits": 5
        }
    )
    print("✅ Created table: EmailReplies")

def create_users_table():
    dynamodb.create_table(
        TableName="Users",
        KeySchema=[
            {"AttributeName": "email", "KeyType": "HASH"}
        ],
        AttributeDefinitions=[
            {"AttributeName": "email", "AttributeType": "S"}
        ],
        BillingMode="PAY_PER_REQUEST"
    )
    print("✅ Created table: Users")

def create_user_status():
    dynamodb.create_table(
        TableName="UserStatus",
        KeySchema=[
            {"AttributeName": "email", "KeyType": "HASH"}
        ],
        AttributeDefinitions=[
            {"AttributeName": "email", "AttributeType": "S"}
        ],
        BillingMode="PAY_PER_REQUEST"
    )
    print("✅ Created table: UserStatus")

def create_pending_emails():
    dynamodb.create_table(
        TableName="PendingEmails",
        KeySchema=[
            {"AttributeName": "user_email", "KeyType": "HASH"},
            {"AttributeName": "id", "KeyType": "RANGE"}
        ],
        AttributeDefinitions=[
            {"AttributeName": "user_email", "AttributeType": "S"},
            {"AttributeName": "id", "AttributeType": "S"}
        ],
        BillingMode="PAY_PER_REQUEST"
    )
    print("✅ Created table: PendingEmails")

def main():
    create_email_queue()
    create_reply_queue()
    create_email_conversations()
    create_email_replies()
    create_users_table()
    create_user_status()
    create_pending_emails()

if __name__ == "__main__":
    main()