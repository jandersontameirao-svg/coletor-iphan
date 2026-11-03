"""API de serviço para a Atena OS (serviço externo em Cloudflare Workers).

Autenticação: token Bearer de CONTA DE SERVIÇO já existente no app
(POST /v1/service-accounts emite o token; identity() valida pelo hash).
Acesso é isolado por processo via ACL (resource_grants). Toda rota autentica
na primeira linha (Depends(identity)) e falha fechado (401 sem token válido).

Leitura e escritas comuns da Atena reutilizam os endpoints /v1/* existentes
(biblioteca, manifesto, categoria, coleta, criar processo). O único recurso
novo aqui é o fluxo de APROVAÇÃO HUMANA para o envio ao SharePoint: ação
irreversível no mundo real NÃO executa direto — a Atena registra um pedido
"pendente" e um revisor humano aprova (ou rejeita). Tudo é auditado.
"""
import time
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
import sharepoint_store as cloud


class SendRequest(BaseModel):
    revision_id: str = Field(min_length=1, max_length=64)
    note: str = Field(default='', max_length=500)


def register(appmod):
    a = appmod
    app = a.app
    with a.db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS atena_sharepoint_requests('
                  'id TEXT PRIMARY KEY,revision_id TEXT,process_id TEXT,category TEXT,status TEXT,'
                  'requested_by TEXT,requested_at REAL,decided_by TEXT,decided_at REAL,note TEXT)')

    def _human_reviewer(user):
        if user.get('kind', 'human') != 'human' or user.get('_delegation'):
            raise HTTPException(403, 'Aprovação exige um revisor humano')

    @app.get('/v1/atena/health')
    def health(user=Depends(a.identity)):
        # Autenticado na primeira linha pelo Depends: sem token válido → 401.
        return {
            'status': 'ok',
            'service': 'coletor-iphan',
            'version': '0.7.0',
            'principal_kind': user.get('kind', 'human'),
            'webhook_configured': a.atena_webhook.configured(),
            'time': time.time(),
        }

    @app.post('/v1/atena/sharepoint-requests', status_code=201)
    def request_send(body: SendRequest, user=Depends(a.identity)):
        with a.db() as c:
            c.execute('BEGIN IMMEDIATE')
            r = a.revision_access(c, body.revision_id, user, 'operate')
            label = c.execute('SELECT category FROM archive_labels WHERE document_id=?', (r['document_id'],)).fetchone()
            if not label:
                raise HTTPException(409, 'Classifique o documento antes de solicitar o envio')
            if c.execute("SELECT 1 FROM atena_sharepoint_requests WHERE revision_id=? AND status='pending'", (body.revision_id,)).fetchone():
                raise HTTPException(409, 'Já existe solicitação pendente para esta revisão')
            req_id = a.uid()
            actor = user.get('_actor_id', user['id'])
            c.execute('INSERT INTO atena_sharepoint_requests VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (req_id, body.revision_id, r['process_id'], label['category'], 'pending',
                       actor, time.time(), None, None, body.note))
            a.event(c, actor, 'atena.sharepoint.requested', req_id)
        return {'id': req_id, 'status': 'pending', 'revision_id': body.revision_id,
                'notice': 'Registrado como pendente; um revisor humano precisa aprovar antes do envio real.'}

    @app.get('/v1/atena/sharepoint-requests')
    def list_requests(status: str = 'pending', user=Depends(a.identity)):
        out = []
        with a.db() as c:
            for row in c.execute('SELECT * FROM atena_sharepoint_requests WHERE status=? ORDER BY requested_at DESC', (status,)):
                try:
                    a.process_access(c, row['process_id'], user, 'read')
                except HTTPException:
                    continue
                out.append(dict(row))
        return out

    @app.post('/v1/atena/sharepoint-requests/{req_id}/approve', status_code=202)
    def approve(req_id: str, user=Depends(a.identity)):
        if a.DEMO_MODE:
            raise HTTPException(403, 'Envio indisponível no modo demonstrativo')
        _human_reviewer(user)
        with a.db() as c:
            c.execute('BEGIN IMMEDIATE')
            req = c.execute('SELECT * FROM atena_sharepoint_requests WHERE id=?', (req_id,)).fetchone()
            if not req:
                raise HTTPException(404)
            if req['status'] != 'pending':
                raise HTTPException(409, 'Solicitação já decidida')
            a.process_access(c, req['process_id'], user, 'operate')
            cloud.queue_revision(c, req['revision_id'], user, req['category'], a.uid)
            c.execute("UPDATE atena_sharepoint_requests SET status='approved',decided_by=?,decided_at=? WHERE id=?",
                      (user['id'], time.time(), req_id))
            a.event(c, user['id'], 'atena.sharepoint.approved', req_id)
        return {'id': req_id, 'status': 'approved', 'notice': 'Envio enfileirado para o SharePoint.'}

    @app.post('/v1/atena/sharepoint-requests/{req_id}/reject')
    def reject(req_id: str, user=Depends(a.identity)):
        _human_reviewer(user)
        with a.db() as c:
            c.execute('BEGIN IMMEDIATE')
            req = c.execute('SELECT * FROM atena_sharepoint_requests WHERE id=?', (req_id,)).fetchone()
            if not req:
                raise HTTPException(404)
            if req['status'] != 'pending':
                raise HTTPException(409, 'Solicitação já decidida')
            a.process_access(c, req['process_id'], user, 'operate')
            c.execute("UPDATE atena_sharepoint_requests SET status='rejected',decided_by=?,decided_at=? WHERE id=?",
                      (user['id'], time.time(), req_id))
            a.event(c, user['id'], 'atena.sharepoint.rejected', req_id)
        return {'id': req_id, 'status': 'rejected'}
