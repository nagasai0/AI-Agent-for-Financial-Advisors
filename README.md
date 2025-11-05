# AI Agent for Financial Advisors

A fully-featured AI agent that integrates Gmail, Google Calendar, and HubSpot CRM to help financial advisors manage client relationships, schedule meetings, and automate workflows.

## 🌟 Features

### Core Capabilities
- **Intelligent Q&A**: Ask questions about clients and the agent searches Gmail and HubSpot using RAG (pgvector)
- **Tool Calling**: Complex multi-step workflows using Gmail, Calendar, and HubSpot APIs
- **Ongoing Instructions**: Set rules that the agent follows proactively
- **Proactive Agent**: Automatically responds to events from Gmail, Calendar, and HubSpot
- **Task Memory**: Stores tasks that require waiting for responses and resumes them

### Example Interactions

**Questions:**
- "Who mentioned their kid plays baseball?"
- "Why did Greg say he wanted to sell AAPL stock?"
- "What do we know about Sara Smith?"

**Actions:**
- "Schedule an appointment with Sara Smith" → Agent finds contact, emails with available times, waits for response, and books meeting
- "Send an email to john@example.com about Q3 portfolio review"
- "Find me 3 available time slots tomorrow afternoon"

**Ongoing Instructions:**
- "When someone emails me, create a HubSpot contact if they don't exist"
- "When I create a contact in HubSpot, send them a thank you email"
- "Reply 'Thank you' to all new emails"

## 🏗️ Architecture

### Tech Stack
- **Backend**: FastAPI (Python)
- **Frontend**: React + TypeScript + Vite + Tailwind CSS
- **Database**: PostgreSQL with pgvector
- **LLM**: Google Gemini 2.5 Flash
- **Background Jobs**: Redis Queue (RQ)
- **Deployment**: Render / Fly.io ready

### Components
1. **Main API** (`backend/main.py`): FastAPI server with WebSocket support
2. **Agent Runtime** (`backend/agent/runtime.py`): Core agent logic with tool calling
3. **Proactive Worker** (`backend/worker_proactive.py`): Background worker monitoring integrations
4. **RAG System** (`backend/rag/`): Vector search using pgvector
5. **Services** (`backend/services/`): Gmail, Calendar, HubSpot integrations
6. **Frontend** (`frontend/`): React chat interface

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- Node.js 18+
- PostgreSQL with pgvector
- Redis
- Google Cloud Project with OAuth
- HubSpot Developer Account

### Local Development

1. **Clone the repository**
```bash
git clone <your-repo-url>
cd learn-jump
```

2. **Set up PostgreSQL with pgvector**
```bash
# Install PostgreSQL
brew install postgresql@15

# Start PostgreSQL
brew services start postgresql@15

# Create database
createdb financial_advisor_agent

# Install pgvector extension
psql financial_advisor_agent -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

3. **Set up Redis**
```bash
# Install Redis
brew install redis

# Start Redis
brew services start redis
```

4. **Backend Setup**
```bash
cd backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create .env file (see .env.example)
cp env.example .env
# Edit .env with your credentials

# Database will auto-migrate on startup
```

5. **Frontend Setup**
```bash
cd frontend

# Install dependencies
npm install

# Build for production
npm run build

# Copy to backend static files
cp -r dist/* ../backend/static/
```

6. **Start the application**
```bash
# Terminal 1: Start backend
cd backend
source venv/bin/activate
uvicorn main:app --reload --port 8000

# Terminal 2: Start proactive worker
cd backend
source venv/bin/activate
python worker_proactive.py

# Terminal 3 (optional): Frontend dev mode
cd frontend
npm run dev  # Runs on port 5173
```

7. **Access the application**
- Production mode: http://localhost:8000
- Dev mode: http://localhost:5173

## 🔑 OAuth Setup

### Google Cloud Console

1. Go to https://console.cloud.google.com/
2. Create a new project or select existing
3. Enable APIs:
   - Gmail API
   - Google Calendar API
   - Google OAuth2 API
4. Create OAuth 2.0 credentials:
   - Application type: Web application
   - Authorized redirect URIs:
     - `http://localhost:8000/auth/google/callback` (local)
     - `https://your-domain.com/auth/google/callback` (production)
5. Add test users (for testing):
   - Add `webshookeng@gmail.com`
   - Add your own email
6. Note down Client ID and Client Secret

### HubSpot Developer Portal

1. Go to https://developers.hubspot.com/
2. Create a developer account (free)
3. Create an app
4. Set redirect URL:
   - `http://localhost:8000/auth/hubspot/callback` (local)
   - `https://your-domain.com/auth/hubspot/callback` (production)
5. Request scopes:
   - `crm.objects.companies.read`
   - `crm.objects.contacts.read`
   - `crm.objects.contacts.write`
   - `crm.objects.deals.read`
   - `oauth`
6. Note down Client ID and Client Secret

## 📝 Environment Variables

Create `backend/.env`:

```bash
# App
APP_SECRET=your-secret-key-here
APP_URL=http://localhost:8000
OAUTH_REDIRECT_BASE=http://localhost:8000

# Google AI
GOOGLE_API_KEY=your-google-ai-api-key

# Database
DATABASE_URL=postgresql://user@localhost:5432/financial_advisor_agent

# Redis
REDIS_URL=redis://localhost:6379/0

# Google OAuth
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_PROJECT_ID=your-project-id
GOOGLE_SCOPES=openid email profile https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/calendar

# HubSpot OAuth
HUBSPOT_CLIENT_ID=your-client-id
HUBSPOT_CLIENT_SECRET=your-client-secret
HUBSPOT_SCOPES=crm.objects.companies.read crm.objects.contacts.read crm.objects.contacts.write crm.objects.deals.read oauth
```

## 🧪 Testing

### Test OAuth Flow
1. Navigate to http://localhost:8000
2. Click "Connect Gmail & Calendar"
3. Complete Google OAuth flow
4. Click "Connect HubSpot"
5. Complete HubSpot OAuth flow

### Test RAG & Questions
1. Click "Initial Sync" to import Gmail and HubSpot data
2. Wait for sync to complete
3. Ask: "What do we know about [client name]?"
4. Agent should search both Gmail and HubSpot

### Test Tool Calling
1. Ask: "Find me 3 available time slots tomorrow"
2. Ask: "Send an email to test@example.com saying hello"
3. Ask: "Create a HubSpot contact for john@example.com"

### Test Ongoing Instructions
1. Click "Ongoing Instructions"
2. Add: "When I receive an email, reply with 'Thank you'"
3. Send yourself a test email
4. Wait 1-2 minutes (polling interval)
5. Check for automated reply

### Test Proactive Agent
1. Ensure worker is running: `python worker_proactive.py`
2. Create an ongoing instruction
3. Trigger an event (send email, create calendar event, etc.)
4. Check logs to see agent evaluation
5. Verify automated action was taken

## 📦 Deployment

### Deploy to Render

1. **Create Render account**: https://render.com

2. **Create PostgreSQL database**:
   - New → PostgreSQL
   - Name: financial-advisor-db
   - Plan: Free or Starter
   - Note the Internal Database URL

3. **Create Redis instance**:
   - New → Redis
   - Name: financial-advisor-redis
   - Plan: Free
   - Note the Internal Redis URL

4. **Create Web Service**:
   - New → Web Service
   - Connect GitHub repository
   - Name: financial-advisor-agent
   - Environment: Python
   - Build Command: `cd backend && pip install -r requirements.txt && cd ../frontend && npm install && npm run build && cp -r dist/* ../backend/static/`
   - Start Command: `cd backend && gunicorn main:app --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT`
   - Add environment variables from .env
   - Deploy

5. **Create Background Worker**:
   - New → Background Worker
   - Connect same repository
   - Name: proactive-worker
   - Build Command: `cd backend && pip install -r requirements.txt`
   - Start Command: `cd backend && python worker_proactive.py`
   - Use same environment variables
   - Deploy

6. **Update OAuth redirect URIs**:
   - Google Cloud Console: Add `https://your-app.onrender.com/auth/google/callback`
   - HubSpot Developer Portal: Add `https://your-app.onrender.com/auth/hubspot/callback`

### Deploy to Fly.io

```bash
# Install flyctl
curl -L https://fly.io/install.sh | sh

# Login
flyctl auth login

# Launch app (interactive)
flyctl launch

# Set secrets
flyctl secrets set GOOGLE_CLIENT_ID=xxx
flyctl secrets set GOOGLE_CLIENT_SECRET=xxx
flyctl secrets set HUBSPOT_CLIENT_ID=xxx
flyctl secrets set HUBSPOT_CLIENT_SECRET=xxx
# ... set all other secrets

# Deploy
flyctl deploy

# Check status
flyctl status

# View logs
flyctl logs
```

## 🐛 Troubleshooting

### Calendar API 403 Error
**Problem**: `Google Calendar API has not been used in project before or it is disabled`

**Solution**: 
1. Go to https://console.developers.google.com/apis/api/calendar-json.googleapis.com/overview?project=YOUR_PROJECT_ID
2. Click "ENABLE"
3. Wait 2-3 minutes
4. Restart the worker

### OAuth Redirect Mismatch
**Problem**: `redirect_uri_mismatch` error

**Solution**: Add the exact redirect URI to Google Cloud Console and HubSpot Developer Portal

### Database Connection Error
**Problem**: Can't connect to database

**Solution**: Check DATABASE_URL is correct and PostgreSQL is running

### Worker Not Processing Events
**Problem**: Automated actions not triggering

**Solution**: 
1. Check worker is running: `ps aux | grep worker_proactive`
2. Check worker logs for errors
3. Verify ongoing instructions are active

### RAG Returns No Results
**Problem**: "No relevant context found"

**Solution**:
1. Click "Initial Sync" button
2. Wait for sync to complete
3. Check database has docs: `SELECT COUNT(*) FROM docs;`

## 📚 API Documentation

Once running, visit:
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health
- **Debug Endpoints**: 
  - `/debug/webhook-events` - Recent webhook events
  - `/debug/instructions` - Ongoing instructions
  - `/debug/tasks` - Task status
  - `/debug/worker-status` - Worker health

## 🤝 Contributing

This is a take-home assignment project. Contributions should come from the original author only.

## 📄 License

MIT License - See LICENSE file for details

## 👤 Author

Built as a take-home assignment demonstrating:
- Full-stack development (Python, React, TypeScript)
- LLM integration with tool calling
- OAuth integrations (Google, HubSpot)
- RAG with pgvector
- Background job processing
- Proactive AI agents
- Complex workflow automation
- Production deployment

## 🎯 Assignment Completion

All requirements met:
- ✅ Google OAuth with Gmail & Calendar permissions
- ✅ HubSpot OAuth integration
- ✅ ChatGPT-like interface
- ✅ RAG with pgvector for Gmail & HubSpot
- ✅ Question answering from multiple sources
- ✅ Tool calling with memory
- ✅ Complex workflows (scheduling example)
- ✅ Ongoing instructions
- ✅ Proactive agent monitoring all integrations
- ✅ No hard-coded scenarios - uses LLM + tools

