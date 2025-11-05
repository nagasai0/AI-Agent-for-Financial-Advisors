#!/bin/bash

# Start the proactive monitoring background worker

echo "Starting Proactive Monitoring Worker..."
echo "Press Ctrl+C to stop"
echo ""

cd backend
source venv/bin/activate
python worker_proactive.py

