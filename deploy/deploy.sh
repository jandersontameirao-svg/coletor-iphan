#!/usr/bin/env bash
# Provisionamento do Coletor IPHAN na VPS (Ubuntu + Python 3.12 + PM2 + nginx).
# Idempotente: pode rodar de novo com segurança. NÃO sobe os processos nem mexe
# no nginx/certbot — isso fica nos passos manuais do deploy/DEPLOY.md.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"
echo "==> Projeto em: $APP_DIR"

# 1. Dependências de sistema para OCR/PDF (opcionais; o app degrada sem elas).
echo "==> Instalando dependências de sistema (poppler/tesseract)..."
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y || true
  apt-get install -y --no-install-recommends \
    python3-venv poppler-utils tesseract-ocr tesseract-ocr-por || \
    echo "!! Aviso: falha ao instalar pacotes de OCR (opcional); seguindo."
fi

# 2. Virtualenv + dependências Python (com verificação de hash).
if [ ! -d .venv ]; then
  echo "==> Criando virtualenv (.venv)..."
  python3 -m venv .venv
fi
echo "==> Instalando dependências Python (requirements.lock)..."
.venv/bin/pip install --upgrade pip >/dev/null
.venv/bin/pip install --no-cache-dir --require-hashes -r requirements.lock

# 3. Diretório de dados persistente.
DATA_DIR="${COLLECTOR_DATA:-$APP_DIR/data}"
mkdir -p "$DATA_DIR"
echo "==> Diretório de dados: $DATA_DIR"

# 4. .env a partir do exemplo, se ainda não existir.
if [ ! -f .env ]; then
  cp deploy/env.production.example .env
  echo "==> .env criado a partir de deploy/env.production.example — REVISE antes de subir."
else
  echo "==> .env já existe; mantido."
fi

# 5. Wrappers executáveis.
chmod +x deploy/run-api.sh deploy/run-worker.sh deploy/deploy.sh

echo
echo "==> Provisionamento concluído."
echo "Próximos passos (ver deploy/DEPLOY.md):"
echo "  1) Revisar o .env            -> nano .env"
echo "  2) Criar o administrador     -> COLLECTOR_DATA=\$(grep ^COLLECTOR_DATA .env|cut -d= -f2) .venv/bin/python bootstrap.py"
echo "  3) Subir no PM2              -> pm2 start deploy/run-api.sh --name coletor-api && pm2 start deploy/run-worker.sh --name coletor-worker && pm2 save"
echo "  4) Configurar nginx + HTTPS  -> ver deploy/DEPLOY.md"
