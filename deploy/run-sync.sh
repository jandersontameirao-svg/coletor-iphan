#!/usr/bin/env bash
# Inicia o processo de pos-processamento (SharePoint + classificacao) carregando o .env. Usado pelo PM2.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && . ./.env; set +a
exec .venv/bin/python sync_worker.py
