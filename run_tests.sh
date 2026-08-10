#!/bin/bash
# Quick Test Runner Script

set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

echo "================================"
echo "Unit Test Suite - Docker Run"
echo "================================"
echo ""

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
else
    echo "Error: neither 'docker compose' nor 'docker-compose' is available." >&2
    exit 1
fi

echo "Starting test dependencies..."
"${COMPOSE[@]}" up -d db

echo "Rebuilding web image (ensure dependencies are up to date)..."
"${COMPOSE[@]}" build web

echo ""
echo "Running tests in the web container..."
echo "================================"

"${COMPOSE[@]}" run --rm web python -m pytest -q

echo ""
echo "================================"
echo "Test run complete!"
