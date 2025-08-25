import boto3
import os
from dotenv import load_dotenv

load_dotenv("secret.env")

region = os.getenv("AWS_REGION", "ap-south-1")
dynamodb = boto3.client("dynamodb", region_name=region)

def check_table_gsi(table_name):
    """Check if a table has the required GSI"""
    try:
        response = dynamodb.describe_table(TableName=table_name)
        gsis = response.get('Table', {}).get('GlobalSecondaryIndexes', [])
        gsi_names = [gsi['IndexName'] for gsi in gsis]
        return gsi_names
    except Exception as e:
        print(f"Error checking table {table_name}: {e}")
        return []

def add_conversation_gsi():
    """Add the missing user_convo_index to EmailConversations table"""
    try:
        # First check if GSI already exists
        existing_gsis = check_table_gsi("EmailConversations")
        if "user_convo_index" in existing_gsis:
            print("✅ user_convo_index already exists on EmailConversations")
            return

        print("🔧 Adding user_convo_index to EmailConversations table...")

        response = dynamodb.update_table(
            TableName="EmailConversations",
            AttributeDefinitions=[
                {'AttributeName': 'user_email', 'AttributeType': 'S'},
                {'AttributeName': 'timestamp', 'AttributeType': 'S'},
                {'AttributeName': 'convo_id', 'AttributeType': 'S'}
            ],
            GlobalSecondaryIndexUpdates=[
                {
                    'Create': {
                        'IndexName': 'user_convo_index',
                        'KeySchema': [
                            {'AttributeName': 'user_email', 'KeyType': 'HASH'},
                            {'AttributeName': 'convo_id', 'KeyType': 'RANGE'}
                        ],
                        'Projection': {'ProjectionType': 'ALL'}
                    }
                }
            ]
        )
        print("✅ Successfully added user_convo_index to EmailConversations")
        return response
    except Exception as e:
        print(f"❌ Error adding GSI: {e}")
        return None

def check_all_tables():
    """Check all required tables and their GSIs"""
    tables = ["EmailQueue", "ReplyQueue", "EmailConversations", "EmailReplies", "Users", "UserStatus", "PendingEmails"]

    print("🔍 Checking DynamoDB tables and indexes...\n")

    for table in tables:
        try:
            response = dynamodb.describe_table(TableName=table)
            status = response['Table']['TableStatus']
            gsis = check_table_gsi(table)

            print(f"📋 {table}:")
            print(f"   Status: {status}")
            print(f"   GSIs: {', '.join(gsis) if gsis else 'None'}")

            if table == "EmailConversations" and "user_convo_index" not in gsis:
                print("   ⚠️  MISSING: user_convo_index (required for conversation history)")
            print()

        except Exception as e:
            print(f"❌ {table}: Error - {e}\n")

if __name__ == "__main__":
    check_all_tables()
    add_conversation_gsi()
    print("\n🎉 Database check and fix complete!")