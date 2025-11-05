#!/bin/bash

# Setup script for Financial Advisor AI Agent
# This script helps you set up environment variables for local development

echo "🚀 Setting up Financial Advisor AI Agent..."

# Create .env file in backend directory
echo "📝 Creating .env file for local development..."

cat > backend/.env << 'EOF'
# Local Development Environment Variables
# Fill in your actual API keys below

# App Configuration
APP_SECRET=dev-secret-key-change-in-production
OAUTH_REDIRECT_BASE=http://localhost:8000

# Google AI API Key (get from https://aistudio.google.com/app/apikey)
GOOGLE_API_KEY=your-google-api-key-here

# Database (for local development)
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/financial_advisor

# Redis (for local development)
REDIS_URL=redis://localhost:6379/0

# Google OAuth Credentials (get from https://console.developers.google.com/)
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
GOOGLE_SCOPES="openid email profile https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/calendar"

# HubSpot OAuth Credentials (get from https://developers.hubspot.com/)
HUBSPOT_CLIENT_ID=your-hubspot-client-id
HUBSPOT_CLIENT_SECRET=your-hubspot-client-secret
HUBSPOT_REDIRECT_URI=http://localhost:8000/auth/hubspot/callback
EOF

echo "✅ Created backend/.env file"
echo ""
echo "📝 Note: Workers will automatically use the backend/.env file"
echo "   since they import from backend/config.py"
echo ""
echo "🔑 Next steps:"
echo "1. Edit backend/.env and fill in your actual API keys:"
echo "   - Google AI API Key: https://aistudio.google.com/app/apikey"
echo "   - Google OAuth: https://console.developers.google.com/"
echo "   - HubSpot OAuth: https://developers.hubspot.com/"
echo ""
echo "2. For local development with Docker:"
echo "   docker-compose up"
echo ""
echo "3. For local development without Docker:"
echo "   # Install dependencies and run locally"
echo "   cd backend && pip install -r requirements.txt"
echo "   python main.py"
echo ""
echo "📚 See README.md for detailed setup instructions"
