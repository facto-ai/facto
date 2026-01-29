#!/bin/bash
# Start Facto infrastructure and services
# Usage: ./scripts/start.sh [--services-only]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=============================================="
echo "Starting Facto Infrastructure"
echo "=============================================="

# Parse arguments
SERVICES_ONLY=false
if [[ "$1" == "--services-only" ]]; then
    SERVICES_ONLY=true
fi

# Function to wait for a service
wait_for_service() {
    local url=$1
    local name=$2
    local timeout=${3:-60}
    local start=$(date +%s)

    echo "Waiting for $name..."
    while true; do
        if curl -s "$url" > /dev/null 2>&1; then
            echo "$name is ready!"
            return 0
        fi

        local now=$(date +%s)
        if (( now - start > timeout )); then
            echo "Timeout waiting for $name"
            return 1
        fi

        sleep 2
    done
}

# Start infrastructure
if [[ "$SERVICES_ONLY" == "false" ]]; then
    echo ""
    echo "Starting Docker containers..."
    docker-compose up -d

    # Wait for NATS
    wait_for_service "http://localhost:8222/healthz" "NATS" 30

    # Wait for ScyllaDB (takes longer)
    echo "Waiting for ScyllaDB (this may take up to 60 seconds)..."
    for i in {1..60}; do
        if docker exec $(docker ps -qf "name=scylla" | head -1) cqlsh -e "SELECT now() FROM system.local" > /dev/null 2>&1; then
            echo "ScyllaDB is ready!"
            break
        fi
        if [ $i -eq 60 ]; then
            echo "Timeout waiting for ScyllaDB"
            exit 1
        fi
        sleep 1
    done

    echo ""
    echo "Infrastructure is ready!"
fi

echo ""
echo "=============================================="
echo "Building Services"
echo "=============================================="

# Build Rust ingestion service
echo ""
echo "Building ingestion service (Rust)..."
cd "$PROJECT_DIR/server/ingestion"
if command -v cargo &> /dev/null; then
    cargo build --release 2>&1 | tail -5
else
    echo "Warning: Rust/Cargo not found. Skipping ingestion service build."
fi

# Build Go processor service
echo ""
echo "Building processor service (Go)..."
cd "$PROJECT_DIR/server/processor"
if command -v go &> /dev/null; then
    go build -o processor . 2>&1 | tail -5
else
    echo "Warning: Go not found. Skipping processor service build."
fi

# Build Go query API
echo ""
echo "Building query API (Go)..."
cd "$PROJECT_DIR/server/api"
if command -v go &> /dev/null; then
    go build -o api . 2>&1 | tail -5
else
    echo "Warning: Go not found. Skipping query API build."
fi

cd "$PROJECT_DIR"

echo ""
echo "=============================================="
echo "Starting Services"
echo "=============================================="
echo ""
echo "To start services manually, run in separate terminals:"
echo ""
echo "  Terminal 1 (Ingestion):"
echo "    cd server/ingestion && RUST_LOG=info ./target/release/facto-ingestion"
echo ""
echo "  Terminal 2 (Processor):"
echo "    cd server/processor && ./processor"
echo ""
echo "  Terminal 3 (Query API):"
echo "    cd server/api && ./api"
echo ""
echo "Or use: ./scripts/start-services.sh"
echo ""
echo "=============================================="
echo "Service Endpoints"
echo "=============================================="
echo ""
echo "  Ingestion API:  http://localhost:8080"
echo "  Processor:      http://localhost:8081/metrics"
echo "  Query API:      http://localhost:8082"
echo "  NATS:           http://localhost:8222"
echo "  Prometheus:     http://localhost:9090"
echo ""
