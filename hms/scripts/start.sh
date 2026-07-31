#!/usr/bin/env bash
# Production startup: applies any pending migrations, seeds default data
# (idempotent - safe to run on every boot), then launches Gunicorn.
set -euo pipefail

echo "==> Applying database migrations"
flask db upgrade

echo "==> Seeding default data (roles, admin, departments) - safe to repeat"
flask seed-db

echo "==> Starting Gunicorn"
exec gunicorn -c gunicorn_config.py run:app
