#!/usr/bin/env bash
# Production startup: applies any pending migrations, then launches Gunicorn.
set -euo pipefail

echo "==> Applying database migrations"
flask db upgrade

echo "==> Starting Gunicorn"
exec gunicorn -c gunicorn_config.py run:app
