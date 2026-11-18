"""Andamento processual (Seção 6 do escopo): relaciona exigência do IPHAN ao
documento apresentado e à manifestação que o analisou.

Regra de ouro: "apresentação não equivale a aprovação". Uma tramitação só pode
ficar 'aprovado' se tiver o DOCUMENTO DE MANIFESTAÇÃO vinculado (a evidência que
sustenta). Sem isso, permanece pendente de conferência.

A IA SUGERE as exigências a partir do texto dos documentos (TRE/ofício etc.);
o humano confirma, vincula os documentos reais e define a situação.
"""
import json
import os
import time
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

import ai_classifier

SITUATIONS = ('solicitado', 'apresentado', 'em_complementacao', 'aprovado', 'pendente')
STUDY_TYPES = ('PAPIPA', 'RAPIPA', 'PAIPA', 'RAIPA', 'PGPA', 'RAIPI', 'FCA', 'TRE', 'educacao_patrimonial', 'outro')
SUGGEST_LIMIT = 15

_SUGGEST_SYSTEM = (
    'Você lê trechos de documentos de um processo de arqueologia do IPHAN e identifica as EXIGÊNCIAS '
    'feitas pelo IPHAN (ex.: no TRE, ofícios, pareceres): o que o órgão SOLICITOU que fosse apresentado '
    '(um estudo, uma complementação, uma correção). Para cada exigência, indique o estudo solicitado quando '
    'houver, usando uma das siglas: PAPIPA, RAPIPA, PAIPA, RAIPA, PGPA, RAIPI, FCA, TRE, educacao_patrimonial, '
    'ou "outro". NÃO invente além dos trechos; se não houver exigências claras, devolva lista vazia. '
    'Responda SOMENTE um objeto JSON com a chave "exigencias": uma lista de objetos '
    '{"exigencia": texto curto do que foi exigido, "estudo": uma das siglas acima ou "outro"}.'
)


class TramitacaoInput(BaseModel):
    requirement: str = Field(min_length=3, max_length=3000)
    study_type: str | None = Field(default=None, max_length=60)
    requirement_doc_id: str | None = Field(default=None, max_length=64)
    submission_doc_id: str | None = Field(default=None, max_length=64)
    manifestation_doc_id: str | None = Field(default=None, max_length=64)
    situation: Literal['solicitado', 'apresentado', 'em_complementacao', 'aprovado', 'pendente'] = 'solicitado'
    notes: str = Field(default='', max_length=3000)


class TramitacaoUpdate(BaseModel):
    study_type: str | None = Field(default=None, max_length=60)
    requirement_doc_id: str | None = Field(default=None, max_length=64)
    submission_doc_id: str | None = Field(default=None, max_length=64)
    manifestation_doc_id: str | None = Field(default=None, max_length=64)
    situation: Literal['solicitado', 'apresentado', 'em_complementacao', 'aprovado', 'pendente'] | None = None
    notes: str | None = Field(default=None, max_length=3000)


def register(appmod):
    a = appmod
    app = a.app
    with a.db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS process_tramitacao('
                  'id TEXT PRIMARY KEY,process_id TEXT NOT NULL,requirement TEXT NOT NULL,study_type TEXT,'
                  'requirement_doc_id TEXT,submission_doc_id TEXT,manifestation_doc_id TEXT,'
                  'situation TEXT NOT NULL,source TEXT,created_by TEXT,validator TEXT,notes TEXT,'
                  'created REAL NOT NULL,updated REAL NOT NULL)')

    def _doc_ok(c, did, pid):
        if did is None:
            return None
        row = c.execute('SELECT id FROM documents WHERE id=? AND process_id=?', (did, pid)).fetchone()
        if not row:
            raise HTTPException(422, 'Documento vinculado não pertence a este processo')
        return did

    def _payload(row):
        return dict(row)

    @app.get('/v1/processes/{pid}/tramitacao')
    def listar(pid: str, user=Depends(a.identity)):
        with a.db() as c:
            process = a.process_access(c, pid, user, 'read')
            rows = c.execute('SELECT * FROM process_tramitacao WHERE process_id=? ORDER BY created', (process['id'],)).fetchall()
            return [_payload(r) for r in rows]

    @app.post('/v1/processes/{pid}/tramitacao', status_code=201)
    def criar(pid: str, body: TramitacaoInput, user=Depends(a.identity)):
        with a.db() as c:
            c.execute('BEGIN IMMEDIATE')
            process = a.process_access(c, pid, user, 'review')
            if body.study_type is not None and body.study_type not in STUDY_TYPES:
                raise HTTPException(422, 'Estudo fora da taxonomia')
            req_doc = _doc_ok(c, body.requirement_doc_id, process['id'])
            sub_doc = _doc_ok(c, body.submission_doc_id, process['id'])
            man_doc = _doc_ok(c, body.manifestation_doc_id, process['id'])
            # Regra: apresentação não equivale a aprovação — aprovar exige o documento de manifestação.
            if body.situation == 'aprovado' and not man_doc:
                raise HTTPException(422, 'Para marcar "aprovado" é obrigatório vincular o documento de manifestação do IPHAN')
            tid = a.uid(); now = time.time()
            c.execute('INSERT INTO process_tramitacao VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                      (tid, process['id'], body.requirement, body.study_type, req_doc, sub_doc, man_doc,
                       body.situation, 'humano', user['id'], None, body.notes, now, now))
            a.event(c, user.get('_actor_id', user['id']), 'tramitacao.created', tid)
            return {'id': tid, 'process_id': process['id'], 'situation': body.situation}

    @app.patch('/v1/tramitacao/{tid}')
    def atualizar(tid: str, body: TramitacaoUpdate, user=Depends(a.identity)):
        with a.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT * FROM process_tramitacao WHERE id=?', (tid,)).fetchone()
            if not row:
                raise HTTPException(404, 'Tramitação não encontrada')
            a.process_access(c, row['process_id'], user, 'review')
            pid = row['process_id']
            study = row['study_type'] if body.study_type is None else body.study_type
            if study is not None and study not in STUDY_TYPES:
                raise HTTPException(422, 'Estudo fora da taxonomia')
            req_doc = row['requirement_doc_id'] if body.requirement_doc_id is None else _doc_ok(c, body.requirement_doc_id, pid)
            sub_doc = row['submission_doc_id'] if body.submission_doc_id is None else _doc_ok(c, body.submission_doc_id, pid)
            man_doc = row['manifestation_doc_id'] if body.manifestation_doc_id is None else _doc_ok(c, body.manifestation_doc_id, pid)
            situation = row['situation'] if body.situation is None else body.situation
            if situation == 'aprovado' and not man_doc:
                raise HTTPException(422, 'Para marcar "aprovado" é obrigatório vincular o documento de manifestação do IPHAN')
            notes = row['notes'] if body.notes is None else body.notes
            c.execute('UPDATE process_tramitacao SET study_type=?,requirement_doc_id=?,submission_doc_id=?,'
                      'manifestation_doc_id=?,situation=?,notes=?,validator=?,source=?,updated=? WHERE id=?',
                      (study, req_doc, sub_doc, man_doc, situation, notes, user['id'], 'humano', time.time(), tid))
            a.event(c, user.get('_actor_id', user['id']), 'tramitacao.' + situation, tid)
            return {'id': tid, 'situation': situation}

    @app.post('/v1/processes/{pid}/tramitacao/suggest')
    def sugerir(pid: str, user=Depends(a.identity)):
        """A IA SUGERE as exigências a partir do texto dos documentos; cada uma nasce pendente, para o humano confirmar."""
        if not ai_classifier.available():
            raise HTTPException(503, 'IA indisponível: configure OPENAI_API_KEY para sugerir exigências')
        with a.db() as c:
            process = a.process_access(c, pid, user, 'operate')
            trechos = [r['text'] for r in c.execute(
                'SELECT e.text FROM evidence e JOIN revisions r ON r.id=e.revision_id JOIN documents d ON d.id=r.document_id '
                'WHERE d.process_id=? AND e.text IS NOT NULL ORDER BY e.rowid LIMIT 20', (process['id'],)).fetchall()]
        if not trechos:
            raise HTTPException(409, 'Sem texto extraído neste processo; extraia os documentos antes de sugerir exigências')
        contexto = 'Trechos dos documentos do processo:\n\n' + '\n---\n'.join(t[:900] for t in trechos)
        key = os.getenv('OPENAI_API_KEY')
        try:
            raw = ai_classifier._complete(key, ai_classifier._model(), [
                {'role': 'system', 'content': _SUGGEST_SYSTEM},
                {'role': 'user', 'content': contexto},
            ])
            parsed = json.loads(ai_classifier._strip_json(raw))
            exigencias = parsed.get('exigencias') if isinstance(parsed, dict) else None
            if not isinstance(exigencias, list):
                raise ValueError
        except ai_classifier.AIError as exc:
            raise HTTPException(502, str(exc))
        except (ValueError, TypeError):
            raise HTTPException(502, 'Resposta da IA ilegível')
        criadas = []
        with a.db() as c:
            c.execute('BEGIN IMMEDIATE')
            for item in exigencias[:SUGGEST_LIMIT]:
                if not isinstance(item, dict):
                    continue
                texto = str(item.get('exigencia') or '').strip()[:3000]
                if not texto:
                    continue
                estudo = item.get('estudo') if item.get('estudo') in STUDY_TYPES else None
                tid = a.uid(); now = time.time()
                c.execute('INSERT INTO process_tramitacao VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                          (tid, process['id'], texto, estudo, None, None, None, 'pendente', 'ia', user['id'], None, '', now, now))
                criadas.append({'id': tid, 'requirement': texto, 'study_type': estudo})
            a.event(c, user.get('_actor_id', user['id']), 'tramitacao.suggested', process['id'])
        return {'process_id': process['id'], 'criadas': criadas, 'total': len(criadas), 'modelo': ai_classifier._model(),
                'notice': 'Exigências sugeridas pela IA; confirme, vincule os documentos e defina a situação. Nada vira "aprovado" sem o parecer vinculado.'}
