#!/bin/bash
# Build and deploy script for the frontend

echo "🔨 Building frontend..."
cd frontend
npm run build

echo "📦 Copying build files to backend..."
rm -rf ../backend/static/*
cp -r dist/* ../backend/static/

echo "✅ Build complete! Files copied to backend/static/"
echo ""
echo "🚀 You can now test these URLs:"
echo "   http://localhost:8000/     - Main landing page"
echo "   http://localhost:8000/main  - Main landing page"
echo "   http://localhost:8000/app   - Dashboard"
echo ""
echo "📁 Static files:"
echo "   http://localhost:8000/assets/index-14da9709.js"
echo "   http://localhost:8000/assets/index-481f4eee.css"
