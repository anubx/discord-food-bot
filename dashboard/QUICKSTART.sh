#!/bin/bash

# FoodTracker Dashboard - Quick Start Script
# Run this to set up the project locally

echo "=========================================="
echo "FoodTracker Dashboard - Quick Start Setup"
echo "=========================================="
echo ""

# Check if node is installed
if ! command -v node &> /dev/null; then
    echo "❌ Node.js not found. Please install Node.js 18+ first."
    exit 1
fi

echo "✅ Node.js version: $(node --version)"
echo ""

# Install dependencies
echo "📦 Installing dependencies..."
npm install
echo "✅ Dependencies installed"
echo ""

# Copy .env.local template
if [ ! -f .env.local ]; then
    echo "📝 Creating .env.local from template..."
    cp .env.local.example .env.local
    echo "✅ .env.local created (UPDATE WITH YOUR CREDENTIALS)"
    echo ""
    echo "Next steps:"
    echo "1. Edit .env.local with your credentials:"
    echo "   - DISCORD_CLIENT_ID (from Discord Developer Portal)"
    echo "   - DISCORD_CLIENT_SECRET (from Discord Developer Portal)"
    echo "   - NEXTAUTH_SECRET (run: openssl rand -base64 32)"
    echo "   - DATABASE_URL (PostgreSQL connection string)"
    echo "   - GEMINI_API_KEY (from Google AI Studio)"
    echo ""
else
    echo "✅ .env.local already exists (skipped)"
    echo ""
fi

# Generate NextAuth secret if needed
if grep -q "NEXTAUTH_SECRET=$" .env.local; then
    echo "🔐 Generating NextAuth secret..."
    SECRET=$(openssl rand -base64 32)
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/NEXTAUTH_SECRET=.*/NEXTAUTH_SECRET=$SECRET/" .env.local
    else
        sed -i "s/NEXTAUTH_SECRET=.*/NEXTAUTH_SECRET=$SECRET/" .env.local
    fi
    echo "✅ NextAuth secret generated and saved"
    echo ""
fi

echo "=========================================="
echo "Setup Complete! ✅"
echo "=========================================="
echo ""
echo "To start the development server:"
echo "  npm run dev"
echo ""
echo "Then visit: http://localhost:3000"
echo ""
echo "Dashboard will redirect to /login for Discord OAuth"
echo ""
echo "For production:"
echo "  npm run build"
echo "  npm start"
echo ""
