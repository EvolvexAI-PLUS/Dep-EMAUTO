import boto3
import os
from dotenv import load_dotenv

load_dotenv("secret.env")

region = os.getenv("AWS_REGION", "ap-south-1")
dynamodb = boto3.client("dynamodb", region_name=region)

def verify_table_gsi(table_name):
    """Verify table has the correct GSI and configuration"""
    try:
        response = dynamodb.describe_table(TableName=table_name)
        table = response['Table']

        print(f"\n📊 {table_name} Status:")
        print(f"   Status: {table.get('TableStatus', 'Unknown')}")

        # Check GSI
        if 'GlobalSecondaryIndexes' in table:
            for gsi in table['GlobalSecondaryIndexes']:
                print(f"   GSI: {gsi['IndexName']} - Status: {gsi.get('IndexStatus', 'Unknown')}")
        else:
            print("   No GSIs found")

        # Check billing mode
        billing_mode = table.get('BillingModeSummary', {}).get('BillingMode', 'Unknown')
        print(f"   Billing Mode: {billing_mode}")

        return True
    except Exception as e:
        print(f"❌ Error checking {table_name}: {e}")
        return False

def test_conversation_query():
    """Test the conversation query that was failing"""
    try:
        # This is the query that was causing the warning
        from database.memory_manager_dynamo import get_conversation_history

        # Test with a dummy conversation ID
        result = get_conversation_history("test_convo_id", "test@example.com")
        print("✅ Conversation query test completed")
        return True
    except Exception as e:
        print(f"❌ Conversation query test failed: {e}")
        return False

def main():
    print("🔍 Verifying DynamoDB Context Issue Fixes")
    print("=" * 50)

    # Check main tables
    tables = ["EmailConversations", "EmailQueue", "EmailReplies", "PendingEmails"]

    for table in tables:
        verify_table_gsi(table)

    print("\n" + "=" * 50)
    print("🧪 Testing conversation retrieval...")

    test_conversation_query()

    print("\n" + "=" * 50)
    print("📋 Recommendations:")
    print("1. If GSI status shows 'CREATING', wait a few minutes for it to become 'ACTIVE'")
    print("2. If warnings persist, the GSI might be in a different state")
    print("3. Restart your application after GSI becomes active")
    print("4. Monitor CloudWatch for any DynamoDB errors")

if __name__ == "__main__":
    main()