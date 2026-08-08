#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec env BASE_URL="${BASE_URL:-http://localhost:8080}" UAT_USER="${UAT_USER:-admin}" UAT_PASSWORD="${UAT_PASSWORD:-admin123}" node "$ROOT_DIR/tests/chromium-uat.js"
