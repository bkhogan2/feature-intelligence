#!/usr/bin/env bash
# Local development entry point. Secrets stay in ignored backend/.env.local.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
set -a
if [[ -f backend/.env.local ]]; then
  source backend/.env.local
fi
set +a
export APP_ENV=development
export AUTH_PROVIDER="${AUTH_PROVIDER:-local}"
export DATABASE_URL="${DATABASE_URL:-postgresql://starter_api:starter-local-api-only@127.0.0.1:55439/starter}"
export APP_ALLOWED_ORIGINS="${APP_ALLOWED_ORIGINS:-http://127.0.0.1:5189,http://localhost:5189}"
export COOKIE_SECURE="${COOKIE_SECURE:-false}"
exec backend/.venv/bin/uvicorn app_core.main:create_app --factory --host 127.0.0.1 --port "${PORT:-8019}"
