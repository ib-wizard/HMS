#!/usr/bin/env bash
# Initializes the database: runs migrations then seeds default data.
# Usage: ./scripts/init_db.sh
set -euo pipefail

echo "==> Loading environment from .env"
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

echo "==> Initializing migrations (only needed once per project)"
if [ ! -d "migrations/versions" ]; then
  flask db init
fi

echo "==> Generating migration"
flask db migrate -m "Initial schema"

echo "==> Applying migrations"
flask db upgrade

echo "==> Seeding database (roles, default admin, departments, demo data)"
flask seed-db

echo "==> Done. Default admin login:"
echo "    Email:    ${DEFAULT_ADMIN_EMAIL:-admin@hospital.com}"
echo "    Password: (see DEFAULT_ADMIN_PASSWORD in your .env file)"
