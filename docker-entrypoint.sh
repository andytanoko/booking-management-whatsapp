#!/bin/sh
set -eu

export FLASK_APP=${FLASK_APP:-wsgi:app}

# Apply schema migrations before running app/tests/other commands.
flask db upgrade
flask seed-defaults

exec "$@"
