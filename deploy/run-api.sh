#!/usr/bin/env bash
# Inicia a API (uvicorn) carregando o .env. Usado pelo PM2.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && . ./.env; set +a
exec .venv/bin/uvicorn app:app --host 127.0.0.1 --port "${PORT:-8000}"
