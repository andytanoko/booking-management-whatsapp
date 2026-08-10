#!/bin/bash
#
# start.sh — Bootstrap and run the Detailing Ops Flask app.
#
# Usage:
#   ./start.sh                  # set up venv, install deps, run the app
#   PORT=8080 ./start.sh        # run on a custom port
#   ./start.sh --skip-install   # skip dependency installation (faster restarts)
#
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

# Resolve the project root (directory of this script) so it works from anywhere.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

VENV_DIR="${VENV_DIR:-.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${PORT:-5000}"
SKIP_INSTALL=0

for arg in "$@"; do
    case "$arg" in
        --skip-install) SKIP_INSTALL=1 ;;
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

# 1. Ensure Python is available.
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "Error: '$PYTHON_BIN' not found. Install Python 3 and retry." >&2
    exit 1
fi

# 2. Create the virtual environment if it does not exist.
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment in '$VENV_DIR'..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# 3. Activate the virtual environment.
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# 4. Install dependencies (unless skipped).
if [ "$SKIP_INSTALL" -eq 0 ]; then
    echo "Installing dependencies from requirements.txt..."
    python -m pip install --upgrade pip >/dev/null
    python -m pip install -r requirements.txt
fi

# 5. Launch the app.
echo "Starting app on http://0.0.0.0:${PORT} ..."
export PORT
export FLASK_APP=wsgi:app
echo "Running database migrations..."
flask db upgrade
echo "Seeding default users/services..."
flask seed-defaults
exec python -m app.app
