"""Observações — canal interno de feedback sobre o próprio sistema.

Mini backlog de produto dentro do app: a equipe registra reclamações, bugs,
pedidos de melhoria e características desejadas no momento em que encontram o
problema, sem sair para outra ferramenta. Prints podem ser colados (Ctrl+V) e
vão embutidos como data URL (até 8 por item).

Cruzamento com a Atena: POST /v1/observacoes/organizar transforma uma ideia
solta num item de backlog pronto (titulo, descricao, categoria, area), que o
usuário revê antes de salvar. A IA não inventa requisito: preserva a intenção.
"""
import json
import time

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

import ai_classifier

CATEGORIAS = ('reclamacao', 'melhoria', 'bug', 'caracteristica')
STATUS = ('aberta', 'em_analise', 'resolvida')
MAX_IMAGES = 8
MAX_IMAGE_CHARS = 1_500_000      # ~1.1 MiB por print embutido como data URL

_ORG_SYSTEM = (
    'Você é a Atena organizando feedback interno de produto do Coletor IPHAN. '
    'A partir de uma ideia solta do usuário, produza um item de backlog acionável, '
    'SEM inventar requisito e PRESERVANDO a intenção dele. Responda SOMENTE um objeto JSON '
    'com as chaves: "titulo" (curto e direto), "descricao" (contexto + comportamento esperado + '
    'critério de pronto), "categoria" (uma de: reclamacao, melhoria, bug, caracteristica) e '
    '"area" (área do sistema, ex.: Coleta, Biblioteca, Acompanhamento, SharePoint, Atena, Geral).'
)


class ObsInput(BaseModel):
    titulo: str = Field(min_length=1, max_length=200)
    descricao: str = Field(min_length=1, max_length=5000)
    categoria: str = Field(max_length=20)
    area: str = Field(default='', max_length=80)
    imagens: list[str] = Field(default_factory=list)


class StatusInput(BaseModel):
    status: str = Field(max_length=20)


class OrganizarInput(BaseModel):
    ideia: str = Field(min_length=1, max_length=4000)


def register(appmod):
    a = appmod
    app = a.app
    with a.db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS observacoes('
                  'id TEXT PRIMARY KEY,titulo TEXT,descricao TEXT,categoria TEXT,area TEXT,'
                  'imagens TEXT,status TEXT,criado_por_id TEXT,criado_por_nome TEXT,'
                  'criado REAL,atualizado REAL)')

    def _human(user):
        if user.get('kind', 'human') != 'human' or user.get('_delegation'):
            raise HTTPException(403, 'Observações são para usuários humanos da equipe')

    def _clean_images(imagens):
        out = []
        for img in (imagens or [])[:MAX_IMAGES]:
            if isinstance(img, str) and img.strip() and len(img) <= MAX_IMAGE_CHARS:
                out.append(img.strip())
        return out

    @app.post('/v1/observacoes', status_code=201)
    def create(body: ObsInput, user=Depends(a.identity)):
        _human(user)
        if body.categoria not in CATEGORIAS:
            raise HTTPException(422, 'Categoria inválida')
        oid = a.uid()
        now = time.time()
        with a.db() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('INSERT INTO observacoes VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                      (oid, body.titulo.strip(), body.descricao.strip(), body.categoria,
                       body.area.strip(), json.dumps(_clean_images(body.imagens)), 'aberta',
                       user['id'], user['name'], now, now))
            a.event(c, user.get('_actor_id', user['id']), 'observacao.created', oid)
        return {'id': oid, 'status': 'aberta', 'notice': 'Observação registrada.'}

    @app.get('/v1/observacoes')
    def listar(status: str | None = None, user=Depends(a.identity)):
        _human(user)
        order = "CASE status WHEN 'aberta' THEN 0 WHEN 'em_analise' THEN 1 ELSE 2 END, criado DESC"
        with a.db() as c:
            if status:
                rows = c.execute(f'SELECT * FROM observacoes WHERE status=? ORDER BY {order}', (status,)).fetchall()
            else:
                rows = c.execute(f'SELECT * FROM observacoes ORDER BY {order}').fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d['imagens'] = json.loads(d['imagens'] or '[]')
            except (ValueError, TypeError):
                d['imagens'] = []
            out.append(d)
        return out

    @app.patch('/v1/observacoes/{oid}/status')
    def update_status(oid: str, body: StatusInput, user=Depends(a.identity)):
        _human(user)
        if body.status not in STATUS:
            raise HTTPException(422, 'Status inválido')
        with a.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT 1 FROM observacoes WHERE id=?', (oid,)).fetchone():
                raise HTTPException(404)
            c.execute('UPDATE observacoes SET status=?,atualizado=? WHERE id=?', (body.status, time.time(), oid))
            a.event(c, user.get('_actor_id', user['id']), 'observacao.status.' + body.status, oid)
        return {'id': oid, 'status': body.status}

    @app.delete('/v1/observacoes/{oid}', status_code=204)
    def delete(oid: str, user=Depends(a.identity)):
        _human(user)
        with a.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT criado_por_id FROM observacoes WHERE id=?', (oid,)).fetchone()
            if not row:
                raise HTTPException(404)
            is_admin = user['role'] == 'admin'
            if row['criado_por_id'] != user['id'] and not is_admin:
                raise HTTPException(403, 'Só o autor ou um administrador pode excluir')
            c.execute('DELETE FROM observacoes WHERE id=?', (oid,))
            a.event(c, user.get('_actor_id', user['id']), 'observacao.deleted', oid)

    @app.post('/v1/observacoes/organizar')
    def organizar(body: OrganizarInput, user=Depends(a.identity)):
        """A Atena transforma uma ideia solta num item de backlog pronto — o usuário revê e salva."""
        _human(user)
        if not ai_classifier.available():
            raise HTTPException(503, 'IA indisponível: configure OPENAI_API_KEY')
        import os
        key = os.getenv('OPENAI_API_KEY')
        messages = [{'role': 'system', 'content': _ORG_SYSTEM},
                    {'role': 'user', 'content': 'Ideia solta do usuário:\n' + body.ideia}]
        try:
            raw = ai_classifier._complete(key, ai_classifier._model(), messages)
            parsed = json.loads(ai_classifier._strip_json(raw))
            if not isinstance(parsed, dict):
                raise ValueError
        except ai_classifier.AIError as exc:
            raise HTTPException(502, str(exc))
        except (ValueError, TypeError):
            raise HTTPException(502, 'Resposta da IA ilegível')
        categoria = parsed.get('categoria')
        if categoria not in CATEGORIAS:
            categoria = 'melhoria'
        return {
            'titulo': str(parsed.get('titulo') or '').strip()[:200],
            'descricao': str(parsed.get('descricao') or '').strip()[:5000],
            'categoria': categoria,
            'area': str(parsed.get('area') or '').strip()[:80],
            'notice': 'Rascunho organizado pela Atena; revise antes de salvar.',
        }
