# Deploy — Coletor IPHAN em `coletor.sigpa.com.br`

Ambiente alvo: VPS Hostinger (Ubuntu 24.04), já com **nginx**, **PM2** e **Python 3.12**.
O Coletor roda **nativo** (venv + PM2), com **nginx** fazendo proxy para `127.0.0.1:8000`
e **HTTPS** via Let's Encrypt. Porta `8000` confirmada livre na VPS.

> DNS já configurado: `coletor.sigpa.com.br` → `2.24.109.107` (registro.br).

Todos os comandos abaixo rodam como `root` na VPS.

## 1. Clonar o projeto

```bash
cd /var/www
git clone https://github.com/jandersontameirao-svg/coletor-iphan.git coletor
cd coletor
```

## 2. Provisionar (venv + dependências + .env)

```bash
bash deploy/deploy.sh
```

Isso instala as dependências, cria a `.venv`, o diretório de dados e um `.env`
a partir de `deploy/env.production.example`.

## 3. Revisar o `.env`

```bash
nano .env
```

- `PORT=8000` e `COLLECTOR_DATA=/var/www/coletor/data` já vêm prontos.
- `MICROSOFT_TENANT_ID` / `MICROSOFT_CLIENT_ID` podem ficar vazios no início
  (SharePoint é conectado depois pela interface — ver `docs/SHAREPOINT.md`).

## 4. Criar o administrador (senha definida por você, interativa)

```bash
set -a; . ./.env; set +a
.venv/bin/python bootstrap.py
```

Ele pede a **senha inicial** (mínimo 12 caracteres) sem exibir. Nenhuma senha é gravada em log.

## 5. Subir no PM2

```bash
pm2 start deploy/run-api.sh    --name coletor-api
pm2 start deploy/run-worker.sh --name coletor-worker
pm2 save
```

Verificar:

```bash
pm2 status
curl -s http://127.0.0.1:8000/_app/health
```

## 6. nginx (proxy do subdomínio)

```bash
cp deploy/nginx-coletor.conf /etc/nginx/sites-available/coletor.sigpa.com.br
ln -s /etc/nginx/sites-available/coletor.sigpa.com.br /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

## 7. HTTPS (Let's Encrypt)

Se o certbot ainda não estiver instalado:

```bash
apt-get install -y certbot python3-certbot-nginx
```

Emitir o certificado (ajusta o nginx para 443 e redireciona 80→443):

```bash
certbot --nginx -d coletor.sigpa.com.br --redirect -m SEU_EMAIL --agree-tos --no-eff-email
```

Pronto: **https://coletor.sigpa.com.br**

## Operação

- Logs:        `pm2 logs coletor-api` / `pm2 logs coletor-worker`
- Reiniciar:   `pm2 restart coletor-api coletor-worker`
- Atualizar:   `cd /var/www/coletor && git pull && bash deploy/deploy.sh && pm2 restart coletor-api coletor-worker`
- Backup:      parar os processos e usar `backup.py` (ver README). Guardar `token.key` separado.

> Não apagar `/var/www/coletor/data`: contém catálogo, rastreabilidade e arquivos pendentes.
