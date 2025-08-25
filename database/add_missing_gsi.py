import boto3
import os
from dotenv import load_dotenv

load_dotenv("secret.env")

region = os.getenv("AWS_REGION", "ap-south-1")
dynamodb = boto3.client("dynamodb", region_name=region)

def add_user_convo_index():
    """Add the missing user_convo_index to EmailConversations table"""
    try:
        response = dynamodb.update_table(
            TableName="EmailConversations",
            AttributeDefinitions=[
                {"AttributeName": "user_email", "AttributeType": "S"},
                {"AttributeName": "timestamp", "AttributeType": "S"},
                {"AttributeName": "convo_id", "AttributeType": "S"}
            ],
            GlobalSecondaryIndexUpdates=[
                {
                    "Create": {
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
                }
            ]
        )
        print("✅ Successfully added user_convo_index to EmailConversations table")
        return True
    except Exception as e:
        print(f"❌ Error adding GSI: {e}")
        return False

def update_table_billing_mode(table_name):
    """Update table to use PROVISIONED billing mode"""
    try:
        dynamodb.update_table(
            TableName=table_name,
            BillingMode="PROVISIONED",
            ProvisionedThroughput={
                "ReadCapacityUnits": 5,
                "WriteCapacityUnits": 5
            }
        )
        print(f"✅ Updated {table_name} to PROVISIONED billing mode")
        return True
    except Exception as e:
        print(f"❌ Error updating {table_name}: {e}")
        return False

def main():
    print("🔧 Fixing DynamoDB context issues...")

    # Add the missing GSI
    print("\n1. Adding user_convo_index to EmailConversations...")
    add_user_convo_index()

    # Update billing modes for better performance
    tables = ["EmailQueue", "EmailReplies", "PendingEmails"]
    print("\n2. Updating billing modes...")
    for table in tables:
        update_table_billing_mode(table)

    print("\n🎉 Context issue fixes applied!")
    print("\nNext steps:")
    print("- Restart your application")
    print("- The user_convo_index warning should disappear")
    print("- Conversation context retrieval will be faster")

if __name__ == "__main__":
    main()