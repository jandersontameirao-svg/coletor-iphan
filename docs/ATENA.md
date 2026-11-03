# Integração Atena OS ↔ Coletor IPHAN

Guia para o time da Atena (serviço externo em Cloudflare Workers) consumir a
API de serviço do Coletor. Base de produção: `https://coletor.sigpa.com.br`.

## Autenticação (token de serviço)

O acesso é por **conta de serviço** com token Bearer. Um administrador do
Coletor cria a conta e entrega o token **uma única vez**:

```
POST /v1/service-accounts            # body: {"name":"atena"}  (admin)
→ {"id":"...","access_token":"<TOKEN>","expires_in":2592000, ...}
```

A Atena envia em **toda** requisição:

```
Authorization: Bearer <TOKEN>
```

- Sem token válido → **401** (todas as rotas autenticam na primeira linha).
- O token é guardado no servidor apenas como **hash**; valor em claro só existe
  no cofre da Atena. Revogação: `POST /v1/service-accounts/{id}/revoke`.
- **Acesso é por processo (ACL).** O token só enxerga processos cujos grants
  foram concedidos à conta `atena`:
  `POST /v1/processes/{pid}/permissions` com
  `{"subject_type":"user","subject_id":"<id da conta atena>","role":"read|operate|review|admin"}`.
  O poder do token = a soma desses grants (não é acesso total por padrão).

Teste de conectividade:

```
GET /v1/atena/health      → 200 {"status":"ok",...} com token; 401 sem token
```

## Leitura

Reutiliza o contrato já existente (todos exigem Bearer + ACL de leitura):

| Endpoint | Para quê |
|---|---|
| `GET /v1/processes` | processos autorizados |
| `GET /v1/bridge/library?process_id=&category=&format=&text=&limit=&offset=` | catálogo de originais (nome, SHA-256, categoria, status SharePoint) |
| `GET /v1/bridge/manifest/{process_id}` | revisões, hashes, ocorrências e referências remotas |
| `GET /v1/document-revisions/{revision_id}/download` | original autorizado do cache |
| `GET /v1/market/processes/{process_id}` | inteligência de mercado (empresas/responsáveis) |

## Escrita

Reutiliza endpoints existentes (Bearer + ACL; tudo auditado):

| Ação | Endpoint | ACL |
|---|---|---|
| Aplicar categoria de documento | `PATCH /v1/bridge/documents/{document_id}/category` — body `{"category":"RAIPA"}` | review |
| Enfileirar coleta de links | `POST /v1/collection-jobs` (header `Idempotency-Key`) | operate |
| Criar processo | `POST /v1/processes` — body `{"number":"...","title":"..."}` | operate/admin |
| Validar/rejeitar fato de mercado | `PATCH /v1/market/facts/{id}` | review |

### Envio ao SharePoint = aprovação humana (ação irreversível)

A Atena **não** dispara o upload direto. Ela registra um pedido **pendente**; um
revisor **humano** do Coletor aprova (ou rejeita):

```
POST /v1/atena/sharepoint-requests          # Atena. body: {"revision_id":"...","note":""}
→ 201 {"id":"...","status":"pending", ...}

GET  /v1/atena/sharepoint-requests?status=pending     # revisor humano lista
POST /v1/atena/sharepoint-requests/{id}/approve       # revisor humano → enfileira envio
POST /v1/atena/sharepoint-requests/{id}/reject        # revisor humano
```

O documento precisa estar **classificado** antes do pedido. A aprovação exige
conta **humana** com ACL `operate` no processo.

## Webhook de saída (PUSH) — opcional

Quando `ATENA_WEBHOOK_URL` e `ATENA_WEBHOOK_SECRET` estão configurados no
Coletor, ele faz `POST` ao endpoint da Atena a cada evento relevante. Corpo
JSON compacto:

```json
{"delivery_id":"...","event":"archive.category.reviewed","resource_id":"...","occurred_at":1730600000.0}
```

Eventos padrão: `process.created`, `document.revision.created`,
`archive.category.reviewed`, `collection.completed`,
`sharepoint.transfer.verified`. (Configurável por `ATENA_WEBHOOK_EVENTS`;
`*` = todos.) O corpo traz apenas a **notificação**; detalhes a Atena busca
pela API de leitura (menos dado sensível em trânsito).

### Verificação da assinatura (OBRIGATÓRIA na Atena)

Cada POST traz os headers:

```
X-Atena-Event:     <nome do evento>
X-Atena-Delivery:  <id único da entrega>
X-Atena-Timestamp: <unix seconds>
X-Atena-Signature: sha256=<hex>
```

A assinatura é o **HMAC-SHA256 do CORPO CRU** (bytes exatos recebidos),
em **hexadecimal**, com a chave `ATENA_WEBHOOK_SECRET`. Verifique assim
(exemplo em Cloudflare Workers / Web Crypto):

```js
async function verify(rawBody, header, secret) {
  const expected = header.replace(/^sha256=/, '');
  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(rawBody));
  const hex = [...new Uint8Array(sig)].map(b => b.toString(16).padStart(2, '0')).join('');
  // comparação em tempo constante no seu lado
  return hex.length === expected.length &&
         crypto.subtle.timingSafeEqual
           ? crypto.subtle.timingSafeEqual(enc(hex), enc(expected))
           : hex === expected;
}
```

Assine sobre o **corpo exato** (não re-serialize o JSON antes de verificar).
Entregas falhas são retentadas com backoff; use `X-Atena-Delivery` para
idempotência.
