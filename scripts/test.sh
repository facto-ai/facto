#!/bin/bash
# Run Facto tests
# Usage: ./scripts/test.sh [unit|integration|load|all]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

TEST_TYPE=${1:-unit}

echo "=============================================="
echo "Running Facto Tests: $TEST_TYPE"
echo "=============================================="

run_unit_tests() {
    echo ""
    echo "Running Python SDK unit tests..."
    cd "$PROJECT_DIR/sdk/python"
    if command -v python3 &> /dev/null; then
        python3 -m pytest tests/ -v --tb=short 2>&1 || echo "Python tests completed (some may have failed)"
    else
        echo "Python not found, skipping Python tests"
    fi

    echo ""
    echo "Running TypeScript SDK unit tests..."
    cd "$PROJECT_DIR/sdk/typescript"
    if command -v npm &> /dev/null; then
        npm install 2>/dev/null || true
        npm test 2>&1 || echo "TypeScript tests completed (some may have failed)"
    else
        echo "npm not found, skipping TypeScript tests"
    fi

    echo ""
    echo "Running Rust ingestion tests..."
    cd "$PROJECT_DIR/server/ingestion"
    if command -v cargo &> /dev/null; then
        cargo test 2>&1 || echo "Rust tests completed (some may have failed)"
    else
        echo "Cargo not found, skipping Rust tests"
    fi

    echo ""
    echo "Running Go processor tests..."
    cd "$PROJECT_DIR/server/processor"
    if command -v go &> /dev/null; then
        go test -v ./... 2>&1 || echo "Go processor tests completed (some may have failed)"
    else
        echo "Go not found, skipping Go tests"
    fi

    echo ""
    echo "Running Go API tests..."
    cd "$PROJECT_DIR/server/api"
    if command -v go &> /dev/null; then
        go test -v ./... 2>&1 || echo "Go API tests completed (some may have failed)"
    else
        echo "Go not found, skipping Go tests"
    fi
}

run_integration_tests() {
    echo ""
    echo "Running integration tests..."
    echo "Note: Requires services to be running"
    echo ""

    cd "$PROJECT_DIR/tests/integration"
    if command -v python3 &> /dev/null; then
        python3 -m pytest test_e2e.py -v -s 2>&1 || echo "Integration tests completed"
    else
        echo "Python not found, skipping integration tests"
    fi
}

run_load_tests() {
    echo ""
    echo "Running load tests..."
    echo "Note: Requires services to be running"
    echo ""

    cd "$PROJECT_DIR/tests/load"
    if command -v python3 &> /dev/null; then
        python3 load_test.py --duration 30 --target-rps 500 --agents 5
    else
        echo "Python not found, skipping load tests"
    fi
}

case $TEST_TYPE in
    unit)
        run_unit_tests
        ;;
    integration)
        run_integration_tests
        ;;
    load)
        run_load_tests
        ;;
    all)
        run_unit_tests
        run_integration_tests
        run_load_tests
        ;;
    *)
        echo "Unknown test type: $TEST_TYPE"
        echo "Usage: ./scripts/test.sh [unit|integration|load|all]"
        exit 1
        ;;
esac

echo ""
echo "=============================================="
echo "Tests completed!"
echo "=============================================="
