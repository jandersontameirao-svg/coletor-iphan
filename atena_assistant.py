"""Atena — assistente operacional com IA, embutido no Coletor IPHAN.

Três modos no mesmo chat, decididos pelo system prompt. A IA sempre devolve um
JSON estruturado {resposta, memoriaSugerida, categoria, acaoSugerida}:

  1. Responde — sobre como usar o sistema e sobre o que REALMENTE aconteceu,
     lendo um "retrato" dos dados reais do banco a cada mensagem (buildRealData).
  2. Aprende — quando o usuário ensina uma regra/custo/preferência, propõe uma
     diretriz imperativa reutilizável (atena_memory) que o usuário salva e que
     passa a ser injetada em toda geração de IA.
  3. Executa (com confirmação) — propõe ações estruturadas; NUNCA executa
     sozinha. O front só chama /v1/assistant/execute após o usuário confirmar,
     e a execução passa por permissão (process_access) + auditoria (event).

Isolado da integração externa "Atena OS" (que usa /v1/atena/* com token de
serviço): aqui são rotas /v1/assistant/* para usuários HUMANOS da equipe.
"""
import json
import os
import re
import time

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

import ai_classifier
import archive_policy as policy
import atena_memory
import authorization

# Busca com IA (RAG) sobre o conteúdo extraído dos documentos (tabela evidence).
RETRIEVE_CANDIDATES = 400   # linhas de evidência consideradas antes do ranking
RETRIEVE_TOP = 10           # melhores trechos enviados à IA
EXCERPT_CHARS = 1200        # limite por trecho (controla o tamanho do prompt)
_STOPWORDS = {
    'a', 'o', 'os', 'as', 'de', 'da', 'do', 'das', 'dos', 'e', 'em', 'no', 'na', 'nos', 'nas',
    'um', 'uma', 'uns', 'umas', 'que', 'com', 'por', 'para', 'pra', 'ao', 'aos', 'se', 'sua',
    'seu', 'suas', 'seus', 'qual', 'quais', 'quem', 'onde', 'quando', 'como', 'sobre', 'entre',
    'ou', 'the', 'foi', 'ser', 'era', 'são', 'tem', 'ha', 'há', 'esta', 'este', 'isso', 'esse',
    'essa', 'pelo', 'pela', 'mais', 'menos', 'ja', 'já', 'nao', 'não', 'sim',
}


def _terms(question):
    """Palavras significativas da pergunta, sem acentos/repetição, para recuperar trechos."""
    tokens = re.findall(r'[0-9a-zA-ZÀ-ÿ]+', (question or '').lower())
    return [t for t in dict.fromkeys(tokens) if len(t) >= 3 and t not in _STOPWORDS]


_SEARCH_SYSTEM = (
    'Você é a Atena, assistente do Coletor IPHAN. Responda à PERGUNTA do usuário USANDO SOMENTE os '
    'TRECHOS DE DOCUMENTOS fornecidos abaixo. Cada trecho traz seu document_id, o processo e a página. '
    'Se a resposta não estiver nos trechos, diga claramente que não encontrou nos documentos — NUNCA '
    'invente nem use conhecimento externo. Cite as fontes que embasam a resposta. '
    'Responda SOMENTE um objeto JSON com as chaves exatas: "resposta" (texto em português, objetivo, '
    'baseado no que os trechos dizem) e "fontes" (lista de objetos {document_id, pagina}); use apenas '
    'document_id que apareçam nos trechos. Se não encontrar, explique isso em "resposta" e deixe "fontes" vazio.'
)

WRITE_CATEGORIES = ('Georreferenciados', *policy.STUDIES)
ACTION_TYPES = ('classificar_documento', 'solicitar_envio')
HISTORY_LIMIT = 12          # mensagens recentes da thread injetadas como contexto conversacional
AUDIT_LIMIT = 120           # últimos eventos reais lidos a cada mensagem
PROPOSALS_LIMIT = 20

_SYSTEM = (
    'Você é a Atena, assistente operacional do Coletor IPHAN — um sistema que coleta '
    'documentos de processos de arqueologia (SEI/IPHAN), preserva os originais, classifica '
    'por tipo documental e os transfere ao SharePoint. Você conversa com a EQUIPE sobre os '
    'dados reais do sistema e ajuda a operá-lo.\n'
    'MODOS (decida pelo contexto da mensagem):\n'
    '1) RESPONDER: tire dúvidas de uso e explique o que aconteceu. Sobre eventos reais, '
    'responda SOMENTE com base no RETRATO DE DADOS REAIS abaixo; se a informação não constar '
    'nele, diga que não consta em vez de supor ou inventar.\n'
    '2) APRENDER: se o usuário ensinar uma regra, custo, prazo, preferência ou diretriz, '
    'formule em "memoriaSugerida" uma diretriz imperativa curta e reutilizável (ex.: "Sempre '
    'classificar ofícios como Outros documentos"). Caso contrário, deixe "memoriaSugerida" vazio.\n'
    '3) EXECUTAR: se o usuário claramente pedir uma ação que o sistema faz, proponha em '
    '"acaoSugerida" um objeto estruturado; NUNCA afirme que já executou — quem aplica é o '
    'usuário, confirmando na tela. Se não houver ação clara, use null.\n'
    'Ações possíveis (acaoSugerida.tipo):\n'
    ' - "classificar_documento": dados {document_id, category}. category deve ser uma de: '
    + ', '.join(WRITE_CATEGORIES) + '.\n'
    ' - "solicitar_envio": dados {revision_id, note}. Registra PEDIDO de envio ao SharePoint; '
    'o envio real depende de aprovação humana.\n'
    'Use só document_id/revision_id que apareçam no contexto; nunca invente identificadores.\n'
    'RESPONDA SOMENTE um objeto JSON com as chaves exatas: '
    '"resposta" (texto ao usuário, em português), '
    '"memoriaSugerida" (string; vazio se não houver), '
    '"categoria" (uma de: custo, processo, preferencia, comercial, tecnico, prazo, modelo_escopo, geral), '
    '"acaoSugerida" (objeto {tipo, dados} ou null).'
)


class ChatInput(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    process_id: str | None = Field(default=None, max_length=64)


class MemoryInput(BaseModel):
    content: str = Field(min_length=3, max_length=1000)
    category: str = Field(default='geral', max_length=40)


class ExecuteInput(BaseModel):
    tipo: str = Field(max_length=40)
    dados: dict = Field(default_factory=dict)


class AssistantSearch(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    process_id: str | None = Field(default=None, max_length=64)


def register(appmod):
    a = appmod
    app = a.app
    with a.db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS atena_chat_messages('
                  'id TEXT PRIMARY KEY,process_id TEXT,role TEXT,content TEXT,author TEXT,created REAL)')
    atena_memory.migrate(a.db)

    def _human(user):
        if user.get('kind', 'human') != 'human' or user.get('_delegation'):
            raise HTTPException(403, 'A Atena é para usuários humanos da equipe')
        if a.DEMO_MODE:
            raise HTTPException(403, 'Assistente indisponível no modo demonstrativo')

    def _accessible_pids(c, user):
        rows = c.execute('SELECT id FROM processes WHERE canonical_id IS NULL').fetchall()
        return [r['id'] for r in rows if authorization.allows_principal(c, r['id'], user['id'], 'read')]

    def _count(c, sql, params=()):
        return c.execute(sql, params).fetchone()[0]

    def build_real_data_context(c, user):
        """Retrato dos dados reais que o usuário pode ver — é o que torna a Atena útil, não genérica."""
        pids = _accessible_pids(c, user)
        if not pids:
            return 'RETRATO DE DADOS REAIS:\n(O usuário ainda não tem acesso a nenhum processo.)'
        marks = ','.join('?' * len(pids))
        docs = _count(c, f'SELECT count(*) FROM documents WHERE process_id IN ({marks})', pids)
        revs = _count(c, f'SELECT count(*) FROM revisions r JOIN documents d ON d.id=r.document_id WHERE d.process_id IN ({marks})', pids)
        classificados = _count(c, f'SELECT count(*) FROM archive_labels l JOIN documents d ON d.id=l.document_id WHERE d.process_id IN ({marks}) AND l.category NOT IN (?,?)', (*pids, 'A classificar', ''))
        sem_classe = docs - classificados
        pend_jobs = _count(c, "SELECT count(*) FROM jobs WHERE owner=? AND status IN ('queued','running','waiting_for_user','partial')", (user['id'],))
        pend_sp = _count(c, f"SELECT count(*) FROM atena_sharepoint_requests WHERE status='pending' AND process_id IN ({marks})", pids) if _table_exists(c, 'atena_sharepoint_requests') else 0
        linhas = [
            'RETRATO DE DADOS REAIS (use SOMENTE isto para falar de fatos; o que não estiver aqui, diga que não consta):',
            f'- Processos acessíveis: {len(pids)}',
            f'- Documentos: {docs} (classificados: {classificados}; a classificar/sem pasta: {sem_classe})',
            f'- Revisões (originais preservados): {revs}',
            f'- Coletas em andamento do usuário: {pend_jobs}',
            f'- Pedidos de envio ao SharePoint pendentes de aprovação: {pend_sp}',
        ]
        proc_rows = c.execute(f'SELECT id,number,title FROM processes WHERE id IN ({marks}) ORDER BY number LIMIT ?', (*pids, PROPOSALS_LIMIT)).fetchall()
        if proc_rows:
            linhas.append('Processos (amostra): ' + '; '.join(f"{r['number']} {r['title']}" for r in proc_rows))
        audit = c.execute(
            'SELECT au.action,au.resource,au.created,u.name AS actor_name '
            'FROM audit au LEFT JOIN users u ON u.id=au.actor ORDER BY au.created DESC LIMIT ?',
            (AUDIT_LIMIT,)).fetchall()
        if audit:
            linhas.append('Últimos eventos reais (quem / o quê / quando):')
            for r in audit:
                quando = time.strftime('%Y-%m-%d %H:%M', time.localtime(r['created'] or 0))
                linhas.append(f"  · {r['actor_name'] or r['resource'] or 'sistema'} — {r['action']} — {quando}")
        return '\n'.join(linhas)

    def _table_exists(c, name):
        return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())

    def build_process_context(c, pid):
        p = c.execute('SELECT number,title FROM processes WHERE id=?', (pid,)).fetchone()
        if not p:
            return ''
        docs = c.execute(
            'SELECT d.id AS document_id,d.name,l.category,'
            '(SELECT r.id FROM revisions r WHERE r.document_id=d.id ORDER BY r.rowid DESC LIMIT 1) AS revision_id '
            'FROM documents d LEFT JOIN archive_labels l ON l.document_id=d.id WHERE d.process_id=? ORDER BY d.name LIMIT 60',
            (pid,)).fetchall()
        linhas = [f'ESTADO DO PROCESSO EM FOCO: {p["number"]} — {p["title"]}',
                  f'Documentos ({len(docs)}), com identificadores para ações:']
        for d in docs:
            linhas.append(f"  · {d['name']} | document_id={d['document_id']} | revision_id={d['revision_id'] or '-'} | categoria={d['category'] or 'A classificar'}")
        return '\n'.join(linhas)

    def _thread(c, pid):
        if pid:
            return c.execute('SELECT * FROM atena_chat_messages WHERE process_id=? ORDER BY created', (pid,)).fetchall()
        return c.execute('SELECT * FROM atena_chat_messages WHERE process_id IS NULL ORDER BY created').fetchall()

    @app.get('/v1/assistant/messages')
    def messages(process_id: str | None = None, user=Depends(a.identity)):
        _human(user)
        with a.db() as c:
            if process_id:
                a.process_access(c, process_id, user, 'read')
            return [dict(r) for r in _thread(c, process_id)]

    @app.post('/v1/assistant/chat')
    def chat(body: ChatInput, user=Depends(a.identity)):
        _human(user)
        if not ai_classifier.available():
            raise HTTPException(503, 'IA indisponível: configure OPENAI_API_KEY para usar a Atena')
        pid = body.process_id or None
        actor = user.get('_actor_id', user['id'])
        with a.db() as c:
            if pid:
                a.process_access(c, pid, user, 'read')
            context = build_real_data_context(c, user)
            proc_ctx = build_process_context(c, pid) if pid else ''
            history = [dict(r) for r in _thread(c, pid)][-HISTORY_LIMIT:]
        directives = atena_memory.directives_text()
        system = _SYSTEM
        if directives:
            system += '\n\n' + directives
        system += '\n\n' + context
        if proc_ctx:
            system += '\n\n' + proc_ctx
        messages_payload = [{'role': 'system', 'content': system}]
        for h in history:
            messages_payload.append({'role': 'assistant' if h['role'] == 'assistant' else 'user', 'content': h['content']})
        messages_payload.append({'role': 'user', 'content': body.message})
        key = os.getenv('OPENAI_API_KEY')
        try:
            raw = ai_classifier._complete(key, ai_classifier._model(), messages_payload)
            parsed = json.loads(ai_classifier._strip_json(raw))
            if not isinstance(parsed, dict):
                raise ValueError
        except ai_classifier.AIError as exc:
            raise HTTPException(502, str(exc))
        except (ValueError, TypeError):
            raise HTTPException(502, 'Resposta da IA ilegível')
        resposta = str(parsed.get('resposta') or '').strip() or 'Não consegui formular uma resposta.'
        memoria = str(parsed.get('memoriaSugerida') or '').strip()[:1000]
        categoria = atena_memory.normalize_category(parsed.get('categoria'))
        acao = _validate_action(parsed.get('acaoSugerida'))
        with a.db() as c:
            c.execute('INSERT INTO atena_chat_messages VALUES(?,?,?,?,?,?)', (a.uid(), pid, 'user', body.message, user['name'], time.time()))
            c.execute('INSERT INTO atena_chat_messages VALUES(?,?,?,?,?,?)', (a.uid(), pid, 'assistant', resposta, 'Atena', time.time()))
            a.event(c, actor, 'assistant.message', pid or 'geral')
        return {'resposta': resposta, 'memoriaSugerida': memoria, 'categoria': categoria, 'acaoSugerida': acao}

    def _validate_action(acao):
        if not isinstance(acao, dict):
            return None
        tipo = acao.get('tipo')
        if tipo not in ACTION_TYPES:
            return None
        dados = acao.get('dados') if isinstance(acao.get('dados'), dict) else {}
        return {'tipo': tipo, 'dados': dados}

    def _retrieve(c, user, question, pid):
        """Recupera os trechos mais relevantes do conteúdo extraído (evidence), respeitando a ACL."""
        terms = _terms(question)
        if not terms:
            return []
        pids = [a.process_access(c, pid, user)['id']] if pid else _accessible_pids(c, user)
        if not pids:
            return []
        marks = ','.join('?' * len(pids))
        like = ' OR '.join(["e.text LIKE ? ESCAPE '\\'"] * len(terms))
        patterns = ['%' + t.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%' for t in terms]
        rows = c.execute(
            'SELECT e.id AS evidence_id,e.page,e.text,r.id AS revision_id,d.id AS document_id,d.name,'
            'p.number,p.title,p.id AS process_id '
            'FROM evidence e JOIN revisions r ON r.id=e.revision_id JOIN documents d ON d.id=r.document_id '
            'JOIN processes p ON p.id=d.process_id '
            f'WHERE d.process_id IN ({marks}) AND ({like}) ORDER BY e.rowid LIMIT ?',
            (*pids, *patterns, RETRIEVE_CANDIDATES)).fetchall()
        scored = []
        for row in rows:
            low = (row['text'] or '').lower()
            coverage = sum(1 for t in terms if t in low)
            occurrences = sum(low.count(t) for t in terms)
            scored.append((coverage, occurrences, dict(row)))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [item[2] for item in scored[:RETRIEVE_TOP]]

    @app.post('/v1/assistant/search')
    def assistant_search(body: AssistantSearch, user=Depends(a.identity)):
        """Pergunta em linguagem natural; a IA responde a partir do CONTEÚDO dos arquivos, citando fontes."""
        _human(user)
        if not ai_classifier.available():
            raise HTTPException(503, 'IA indisponível: configure OPENAI_API_KEY para usar a busca com IA')
        actor = user.get('_actor_id', user['id'])
        pid = body.process_id or None
        with a.db() as c:
            if pid:
                a.process_access(c, pid, user, 'read')
            chunks = _retrieve(c, user, body.question, pid)
        if not chunks:
            with a.db() as c:
                a.event(c, actor, 'assistant.search', pid or 'geral')
            return {'resposta': 'Não encontrei nada no conteúdo extraído dos documentos a que você tem acesso. '
                                'Verifique se os documentos já passaram por extração de texto (ou OCR) ou refine os termos.',
                    'fontes': [], 'trechos_considerados': 0, 'modelo': ai_classifier._model()}
        blocos = []
        for ch in chunks:
            pagina = ch['page'] if ch['page'] is not None else '-'
            blocos.append(f"[documento: {ch['name']} | document_id: {ch['document_id']} | "
                          f"processo: {ch['number']} | página: {pagina}]\n{(ch['text'] or '')[:EXCERPT_CHARS]}")
        directives = atena_memory.directives_text()
        system = _SEARCH_SYSTEM + ('\n\n' + directives if directives else '')
        user_content = 'PERGUNTA:\n' + body.question + '\n\nTRECHOS DE DOCUMENTOS (responda só com base nestes):\n\n' + '\n\n---\n\n'.join(blocos)
        key = os.getenv('OPENAI_API_KEY')
        try:
            raw = ai_classifier._complete(key, ai_classifier._model(), [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user_content},
            ])
            parsed = json.loads(ai_classifier._strip_json(raw))
            if not isinstance(parsed, dict):
                raise ValueError
        except ai_classifier.AIError as exc:
            raise HTTPException(502, str(exc))
        except (ValueError, TypeError):
            raise HTTPException(502, 'Resposta da IA ilegível')
        resposta = str(parsed.get('resposta') or '').strip() or 'Não consegui formular uma resposta a partir dos trechos.'
        by_doc = {ch['document_id']: ch for ch in chunks}
        fontes, seen = [], set()
        for f in (parsed.get('fontes') or []):
            if not isinstance(f, dict):
                continue
            did = str(f.get('document_id') or '')
            if did in by_doc and did not in seen:
                seen.add(did)
                ch = by_doc[did]
                pagina = f.get('pagina') if isinstance(f.get('pagina'), int) else ch['page']
                fontes.append({'document_id': did, 'documento': ch['name'], 'processo': ch['number'],
                               'pagina': pagina, 'revision_id': ch['revision_id'],
                               # O arquivo em si: baixar o original preservado e, se já enviado, abrir no SharePoint.
                               'download_url': '/v1/document-revisions/' + ch['revision_id'] + '/download',
                               'sharepoint_url': None})
        with a.db() as c:
            for fonte in fontes:
                transfer = c.execute(
                    "SELECT web_url FROM cloud_transfers WHERE revision_id=? AND web_url IS NOT NULL "
                    "ORDER BY rowid DESC LIMIT 1", (fonte['revision_id'],)).fetchone()
                if transfer:
                    fonte['sharepoint_url'] = transfer['web_url']
            a.event(c, actor, 'assistant.search', pid or 'geral')
        return {'resposta': resposta, 'fontes': fontes, 'trechos_considerados': len(chunks), 'modelo': ai_classifier._model()}

    @app.get('/v1/assistant/memories')
    def list_memories(user=Depends(a.identity)):
        _human(user)
        with a.db() as c:
            return atena_memory.all_memories(c)

    @app.post('/v1/assistant/memories', status_code=201)
    def save_memory(body: MemoryInput, user=Depends(a.identity)):
        _human(user)
        with a.db() as c:
            c.execute('BEGIN IMMEDIATE')
            mid = atena_memory.add(c, body.content, body.category, user['name'])
            a.event(c, user.get('_actor_id', user['id']), 'assistant.memory.saved', mid)
        return {'id': mid, 'notice': 'Diretriz salva; passa a valer em todas as gerações de IA.'}

    @app.delete('/v1/assistant/memories/{mid}', status_code=204)
    def delete_memory(mid: str, user=Depends(a.identity)):
        _human(user)
        with a.db() as c:
            c.execute('BEGIN IMMEDIATE')
            atena_memory.remove(c, mid)
            a.event(c, user.get('_actor_id', user['id']), 'assistant.memory.deleted', mid)

    @app.post('/v1/assistant/execute')
    def execute(body: ExecuteInput, user=Depends(a.identity)):
        """Aplica uma ação SÓ depois da confirmação do usuário na tela. Permissão + auditoria."""
        _human(user)
        if body.tipo not in ACTION_TYPES:
            raise HTTPException(422, 'Ação não suportada')
        actor = user.get('_actor_id', user['id'])
        if body.tipo == 'classificar_documento':
            did = str(body.dados.get('document_id') or '')
            category = body.dados.get('category')
            if category not in WRITE_CATEGORIES:
                raise HTTPException(422, 'Categoria inválida')
            with a.db() as c:
                c.execute('BEGIN IMMEDIATE')
                d = c.execute('SELECT * FROM documents WHERE id=?', (did,)).fetchone()
                if not d:
                    raise HTTPException(404, 'Documento não encontrado')
                a.process_access(c, d['process_id'], user, 'review')
                stamp = time.time()
                c.execute('INSERT OR REPLACE INTO archive_labels VALUES(?,?,?,?,?)', (did, category, 'human_review', user['id'], stamp))
                c.execute('INSERT INTO archive_label_history VALUES(?,?,?,?,?,?)', (a.uid(), did, category, 'human_review', user['id'], stamp))
                c.execute("UPDATE cloud_transfers SET category=? WHERE revision_id IN (SELECT id FROM revisions WHERE document_id=?) AND status IN ('queued','waiting_for_connection','failed')", (category, did))
                a.event(c, actor, 'archive.category.reviewed', did)
            return {'tipo': body.tipo, 'document_id': did, 'category': category, 'notice': 'Classificação aplicada.'}
        # solicitar_envio: registra pedido PENDENTE; envio real exige aprovação humana (atena_routes).
        rid = str(body.dados.get('revision_id') or '')
        note = str(body.dados.get('note') or '')[:500]
        with a.db() as c:
            c.execute('BEGIN IMMEDIATE')
            r = a.revision_access(c, rid, user, 'operate')
            label = c.execute('SELECT category FROM archive_labels WHERE document_id=? AND category NOT IN (?,?)', (r['document_id'], 'A classificar', '')).fetchone()
            if not label:
                raise HTTPException(409, 'Classifique o documento antes de solicitar o envio')
            if c.execute("SELECT 1 FROM atena_sharepoint_requests WHERE revision_id=? AND status='pending'", (rid,)).fetchone():
                raise HTTPException(409, 'Já existe solicitação pendente para esta revisão')
            req_id = a.uid()
            c.execute('INSERT INTO atena_sharepoint_requests VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (req_id, rid, r['process_id'], label['category'], 'pending', actor, time.time(), None, None, note))
            a.event(c, actor, 'atena.sharepoint.requested', req_id)
        return {'tipo': body.tipo, 'id': req_id, 'status': 'pending', 'notice': 'Pedido registrado; um revisor humano precisa aprovar o envio real.'}
