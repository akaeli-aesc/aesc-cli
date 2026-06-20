#!/bin/bash
# Reset all benchmark labs to initial state
# Usage: ./reset-labs.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🔄 Resetting AESC benchmark labs..."

# Stop and remove all lab containers
echo "  → Stopping labs..."
docker-compose down -v 2>/dev/null || true

# Clean up any orphaned containers
echo "  → Cleaning orphaned containers..."
docker ps -a --filter "name=ashbench_" -q | xargs -r docker rm -f 2>/dev/null || true

# Rebuild and start fresh
echo "  → Starting fresh labs..."
docker-compose up -d --build

# Wait for health checks
echo "  → Waiting for labs to become healthy..."
sleep 10

# Check status
echo ""
echo "📋 Lab Status:"
docker-compose ps

echo ""
echo "✅ Labs reset complete!"
echo "   Network: ashbench_net"
echo "   Labs available:"
echo "     - diag-console.local (command injection)"
echo "     - invoice-api.local (IDOR)"
echo "     - notes-app.local (XSS)"
echo "     - support-portal.local (SQLi + path traversal)"
echo "     - webhook-hub.local (SSRF)"
echo "     - metadata.local (internal service)"
