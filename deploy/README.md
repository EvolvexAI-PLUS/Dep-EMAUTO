# Railway Deployment Guide

This guide will help you deploy the Email Automation application to Railway.

## Prerequisites

1. A Railway account (https://railway.app)
2. GitHub repository with this code
3. AWS account with DynamoDB access (for database)
4. OAuth applications configured for Google and Outlook

## Step-by-Step Deployment

### 1. Connect to Railway

1. Go to [Railway](https://railway.app)
2. Click "Start a New Project"
3. Choose "Deploy from GitHub repo"
4. Connect your GitHub account and select this repository

### 2. Configure Environment Variables

In your Railway project dashboard:

1. Go to the "Variables" tab
2. Add all the environment variables from `.env.example`:

```
FLASK_SECRET_KEY=your-super-secret-flask-key-here
FLASK_ENV=production
JWT_SECRET=your-super-secret-jwt-key-here
AWS_REGION=ap-south-1
USERS_TABLE=Users
REPLIES_TABLE=EmailReplies
CONVO_TABLE=EmailConversations
USER_STATUS_TABLE=UserStatus
PENDING_TABLE=PendingEmails
REPLY_QUEUE_TABLE=ReplyQueue
EMAIL_QUEUE_TABLE=EmailQueue
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
OUTLOOK_CLIENT_ID=your-outlook-client-id
OUTLOOK_CLIENT_SECRET=your-outlook-client-secret
OUTLOOK_REDIRECT_URI=https://your-app.railway.app/callback/outlook
COOKIE_SECURE=true
ANTHROPIC_API_KEY=your-anthropic-api-key
```

### 3. Configure OAuth Redirect URIs

#### For Google OAuth:
- Go to [Google Cloud Console](https://console.cloud.google.com/)
- Navigate to "APIs & Credentials" > "OAuth 2.0 Client IDs"
- Add your Railway domain to authorized redirect URIs:
  - `https://your-app.railway.app/callback/google`

#### For Outlook OAuth:
- Go to [Azure Portal](https://portal.azure.com/)
- Navigate to "Azure Active Directory" > "App registrations"
- Add your Railway domain to redirect URIs:
  - `https://your-app.railway.app/callback/outlook`

### 4. Set Up AWS Credentials

Railway supports AWS credentials through environment variables or IAM roles. For production, use environment variables:

```
AWS_ACCESS_KEY_ID=your-aws-access-key
AWS_SECRET_ACCESS_KEY=your-aws-secret-key
```

### 5. Deploy

1. Railway will automatically detect the `railway.json` configuration
2. It will build the Docker image using `deploy/Dockerfile`
3. The application will be accessible at `https://your-app.railway.app`

## Database Setup

Before deploying, ensure your DynamoDB tables are created:

```bash
cd database
python schema_setup.py
```

## Post-Deployment

1. **Update OAuth Redirect URIs**: Once deployed, update your OAuth applications with the actual Railway domain
2. **Test Login**: Try logging in with Google/Outlook to ensure OAuth works
3. **Verify Database Connection**: Check that the app can connect to DynamoDB
4. **Test Email Processing**: Send a test email to verify the automation works

## Troubleshooting

### Common Issues:

1. **Port Issues**: Railway assigns a random port - the app handles this automatically
2. **OAuth Redirects**: Make sure to update OAuth apps with the Railway domain
3. **Environment Variables**: Double-check all required environment variables are set
4. **AWS Permissions**: Ensure the AWS user has DynamoDB permissions

### Logs

Check Railway logs for any startup errors:
- Go to your project dashboard
- Click on "Deployments"
- View logs for the latest deployment

## Scaling

Railway automatically scales based on traffic. For production:

1. Monitor performance metrics
2. Set up alerts for errors
3. Consider upgrading to a paid plan for higher limits
4. Set up database backups and monitoring

## Security Notes

- Railway provides SSL/TLS automatically
- Keep sensitive environment variables secure
- Regularly rotate API keys and secrets
- Monitor for unusual activity in logs