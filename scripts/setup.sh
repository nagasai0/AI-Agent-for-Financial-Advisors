#!/bin/bash

# Financial Advisor AI Agent Setup Script

set -e

echo "🚀 Setting up Financial Advisor AI Agent..."

# Check if required tools are installed
command -v python3 >/dev/null 2>&1 || { echo "❌ Python 3 is required but not installed. Aborting." >&2; exit 1; }
command -v node >/dev/null 2>&1 || { echo "❌ Node.js is required but not installed. Aborting." >&2; exit 1; }
command -v psql >/dev/null 2>&1 || { echo "❌ PostgreSQL is required but not installed. Aborting." >&2; exit 1; }
command -v redis-server >/dev/null 2>&1 || { echo "❌ Redis is required but not installed. Aborting." >&2; exit 1; }

echo "✅ All required tools are installed"

# Setup Backend
echo "📦 Setting up backend..."
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd ..

# Setup Frontend
echo "📦 Setting up frontend..."
cd frontend
npm install
cd ..

# Setup Workers
echo "📦 Setting up workers..."
cd workers
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd ..

# Create environment file
echo "⚙️  Creating environment file..."
if [ ! -f backend/.env ]; then
    cp backend/env.example backend/.env
    echo "📝 Please edit backend/.env with your API keys and credentials"
fi

# Database setup
echo "🗄️  Setting up database..."
echo "Please ensure PostgreSQL is running and create the database:"
echo "createdb financial_advisor_agent"
echo "psql financial_advisor_agent < scripts/init.sql"

echo ""
echo "🎉 Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit backend/.env with your API keys"
echo "2. Start PostgreSQL and Redis"
echo "3. Create the database: createdb financial_advisor_agent"
echo "4. Run: psql financial_advisor_agent < scripts/init.sql"
echo "5. Start the services:"
echo "   - Backend: cd backend && source venv/bin/activate && python -m uvicorn main:app --reload"
echo "   - Workers: cd workers && source venv/bin/activate && python worker.py"
echo "   - Frontend: cd frontend && npm run dev"
echo ""
echo "Then visit http://localhost:5173 to get started!"
