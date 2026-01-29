#!/bin/bash
# Stop Facto infrastructure
# Usage: ./scripts/stop.sh [--keep-data]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=============================================="
echo "Stopping Facto Infrastructure"
echo "=============================================="

# Parse arguments
KEEP_DATA=false
if [[ "$1" == "--keep-data" ]]; then
    KEEP_DATA=true
fi

# Kill any running services
echo "Stopping services..."
pkill -f "facto-ingestion" 2>/dev/null || true
pkill -f "processor" 2>/dev/null || true
pkill -f "./api" 2>/dev/null || true

# Stop Docker containers
echo "Stopping Docker containers..."
docker-compose down

if [[ "$KEEP_DATA" == "false" ]]; then
    echo "Removing volumes..."
    docker-compose down -v
    echo "Data volumes removed."
else
    echo "Data volumes preserved."
fi

echo ""
echo "Facto infrastructure stopped."
