#!/usr/bin/env bash
#
# start-docker.sh — Build and start the full Docker Compose stack:
# Postgres (db), the Flask app via gunicorn (web), and the WhatsApp
# bridge (wa-bridge).
#
# Usage:
#   ./start-docker.sh              # build + run in the foreground
#   ./start-docker.sh -d           # build + run detached
#   ./start-docker.sh --no-build   # skip rebuilding images
#
set -euo pipefail

# Resolve the project root (directory of this script) so it works from anywhere.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

DETACH=0
BUILD=1

for arg in "$@"; do
    case "$arg" in
        -d|--detach) DETACH=1 ;;
        --no-build) BUILD=0 ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "Unknown option: $arg" >&2
            exit 1
            ;;
    esac
done

# 1. Ensure Docker is available.
if ! command -v docker >/dev/null 2>&1; then
    echo "Error: 'docker' not found. Install Docker and retry." >&2
    exit 1
fi

# 2. Pick whichever compose CLI is available (plugin vs standalone binary).
if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
else
    echo "Error: neither 'docker compose' nor 'docker-compose' is available." >&2
    exit 1
fi

# 3. Ensure a .env file exists (Postgres credentials, SECRET_KEY, etc.).
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        echo "No .env found — copying .env.example to .env."
        cp .env.example .env
    else
        echo "Error: no .env or .env.example found. Create .env first." >&2
        exit 1
    fi
fi

# 4. Build images (unless skipped) and start the stack.
ARGS=(up)
[ "$BUILD" -eq 1 ] && ARGS+=(--build)
[ "$DETACH" -eq 1 ] && ARGS+=(-d)

# Needed on machines behind a corporate TLS-intercepting proxy (e.g. Netskope),
# where Chromium in wa-bridge otherwise fails QR generation with ERR_CERT_AUTHORITY_INVALID.
export WA_BRIDGE_IGNORE_CERT_ERRORS=true

echo "Starting stack: db, web, wa-bridge ..."
"${COMPOSE[@]}" "${ARGS[@]}"

if [ "$DETACH" -eq 1 ]; then
    echo
    echo "App:       http://localhost:8080"
    echo "WA bridge: http://localhost:8080/wa-bridge/qr  (scan to pair WhatsApp)"
    echo "Logs:      ${COMPOSE[*]} logs -f"
fi
