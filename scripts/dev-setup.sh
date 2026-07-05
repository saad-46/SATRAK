#!/usr/bin/env bash
# =============================================================================
# SATRAK — one-shot local development bootstrap
# =============================================================================
# Installs JS + Python dependencies and seeds env files. Idempotent-ish: safe to
# re-run. Run from the repo root:  ./scripts/dev-setup.sh
# -----------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Seeding environment files"
[ -f .env ] || cp .env.example .env
[ -f apps/api/.env ] || cp apps/api/.env.example apps/api/.env
[ -f apps/web/.env.local ] || cp apps/web/.env.example apps/web/.env.local

echo "==> Installing JS/TS workspace dependencies (pnpm)"
if ! command -v pnpm >/dev/null 2>&1; then
  echo "pnpm not found. Install it: 'npm install -g pnpm' or 'corepack enable'." >&2
  exit 1
fi
pnpm install

echo "==> Setting up Python API virtualenv"
cd apps/api
python -m venv .venv
# shellcheck disable=SC1091
if [ -f .venv/bin/activate ]; then source .venv/bin/activate; else source .venv/Scripts/activate; fi
pip install --upgrade pip
pip install -e ".[dev]"
cd "$ROOT"

echo "==> Done. Next steps:"
echo "    - Start datastores:  make up   (or docker compose ... up -d postgis redis)"
echo "    - Run apps:          make dev"
