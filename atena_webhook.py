"""Webhook de saída para a Atena OS.

Consome a tabela `outbox` (que o event() já alimenta a cada ação) FORA de
qualquer transação de request — o worker chama flush() quando está ocioso — e
entrega cada evento à Atena com assinatura HMAC-SHA256 do CORPO CRU.

Opcional e falha fechado: só opera quando ATENA_WEBHOOK_URL e
ATENA_WEBHOOK_SECRET estão definidos no ambiente. O segredo nunca sai daqui
(não é logado nem devolvido em rota). Ao ser configurado pela primeira vez,
ignora o histórico antigo da outbox (marca um ponto de partida) para não
inundar a Atena com eventos passados.

Assinatura que a Atena verifica:
  header  X-Atena-Signature: sha256=<hex>
  cálculo hex( HMAC_SHA256( ATENA_WEBHOOK_SECRET, corpo_cru_do_POST ) )
"""
import hashlib
import hmac
import json
import os
import time

import httpx

# Eventos enviados por padrão (nomes = ação registrada no event()).
DEFAULT_EVENTS = {
    'process.created',
    'document.revision.created',
    'archive.category.reviewed',
    'collection.completed',
    'sharepoint.transfer.verified',
}
BATCH = 20
MAX_ATTEMPTS = 24
TIMEOUT = 10


def migrate(db):
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS atena_webhook_state(k TEXT PRIMARY KEY,v REAL)')
        c.execute('CREATE TABLE IF NOT EXISTS atena_webhook_delivery('
                  'outbox_id TEXT PRIMARY KEY,status TEXT,attempts INTEGER,'
                  'next_attempt REAL,last_error TEXT,updated REAL)')


def _url():
    return os.getenv('ATENA_WEBHOOK_URL') or ''


def _secret():
    return os.getenv('ATENA_WEBHOOK_SECRET') or ''


def configured():
    return bool(_url() and _secret())


def _allowed_events():
    raw = (os.getenv('ATENA_WEBHOOK_EVENTS') or '').strip()
    if not raw:
        return DEFAULT_EVENTS
    if raw == '*':
        return None  # entrega todos os eventos
    return {part.strip() for part in raw.split(',') if part.strip()}


def _matches(kind, allowed):
    return allowed is None or kind in allowed


def sign(secret, body_bytes):
    return hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()


def _since(db):
    with db() as c:
        row = c.execute("SELECT v FROM atena_webhook_state WHERE k='since'").fetchone()
        if row:
            return row[0]
        now = time.time()
        c.execute("INSERT OR REPLACE INTO atena_webhook_state VALUES('since',?)", (now,))
        return now


def _set(db, outbox_id, status, attempts, next_attempt, err):
    with db() as c:
        c.execute(
            'INSERT INTO atena_webhook_delivery(outbox_id,status,attempts,next_attempt,last_error,updated) '
            'VALUES(?,?,?,?,?,?) ON CONFLICT(outbox_id) DO UPDATE SET '
            'status=excluded.status,attempts=excluded.attempts,next_attempt=excluded.next_attempt,'
            'last_error=excluded.last_error,updated=excluded.updated',
            (outbox_id, status, attempts, next_attempt, err, time.time()),
        )


def _deliver(kind, outbox_id, body):
    signature = sign(_secret(), body)
    headers = {
        'Content-Type': 'application/json',
        'X-Atena-Event': kind,
        'X-Atena-Delivery': outbox_id,
        'X-Atena-Timestamp': str(int(time.time())),
        'X-Atena-Signature': 'sha256=' + signature,
    }
    try:
        resp = httpx.post(_url(), content=body, headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        return False, 'rede: ' + exc.__class__.__name__
    if 200 <= resp.status_code < 300:
        return True, None
    return False, 'http ' + str(resp.status_code)


def flush(appmod):
    """Chamado pelo worker quando ocioso. Retorna True se entregou algo."""
    if not configured():
        return False
    db = appmod.db
    allowed = _allowed_events()
    since = _since(db)
    now = time.time()
    with db() as c:
        rows = c.execute(
            'SELECT o.id,o.kind,o.payload,o.created FROM outbox o '
            'LEFT JOIN atena_webhook_delivery d ON d.outbox_id=o.id '
            'WHERE o.created>=? AND (d.outbox_id IS NULL OR (d.status=\'failed\' AND d.next_attempt<=?)) '
            'ORDER BY o.created LIMIT ?',
            (since, now, BATCH),
        ).fetchall()
    delivered = 0
    for row in rows:
        kind = row['kind']
        if not _matches(kind, allowed):
            _set(db, row['id'], 'skipped', 0, None, None)
            continue
        try:
            payload = json.loads(row['payload'])
        except (TypeError, ValueError):
            payload = {}
        body = json.dumps({
            'delivery_id': row['id'],
            'event': kind,
            'resource_id': payload.get('resource_id'),
            'occurred_at': row['created'],
        }, separators=(',', ':')).encode()
        ok, err = _deliver(kind, row['id'], body)
        if ok:
            _set(db, row['id'], 'delivered', 0, None, None)
            delivered += 1
        else:
            prev = 0
            with db() as c:
                got = c.execute('SELECT attempts FROM atena_webhook_delivery WHERE outbox_id=?', (row['id'],)).fetchone()
                prev = got['attempts'] if got else 0
            attempts = prev + 1
            status = 'dead' if attempts >= MAX_ATTEMPTS else 'failed'
            backoff = min(attempts * 60, 3600)
            _set(db, row['id'], status, attempts, now + backoff, (err or '')[:300])
    return delivered > 0
