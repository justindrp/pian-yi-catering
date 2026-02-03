#!/bin/bash
# =============================================================================
# Pian Yi Catering - Frontend Setup Script
# =============================================================================
# This script creates the Next.js frontend application.
# Run this script once to initialize the frontend directory.
#
# Usage:
#   chmod +x setup_frontend.sh
#   ./setup_frontend.sh
# =============================================================================

set -e

echo "🚀 Setting up Pian Yi Catering Frontend..."

# Check if frontend directory already exists
if [ -d "frontend" ]; then
    echo "⚠️  'frontend' directory already exists."
    echo "   Delete it first if you want to reinitialize:"
    echo "   rm -rf frontend && ./setup_frontend.sh"
    exit 1
fi

# Create Next.js app with specified options (non-interactive)
npx create-next-app@latest frontend \
    --typescript \
    --tailwind \
    --eslint \
    --no-src-dir \
    --app \
    --import-alias "@/*" \
    --use-npm

echo ""
echo "✅ Frontend setup complete!"
echo ""
echo "Next steps:"
echo "  1. cd frontend"
echo "  2. Create .env.local with: NEXT_PUBLIC_API_URL=http://localhost:8000"
echo "  3. npm run dev"
echo ""
