"""Passo de background: classifica com IA os documentos que a regra deixou em 'A classificar'.

Roda no worker ocioso, ANTES do upload ao SharePoint, para que o arquivo já suba na pasta
correta. Aplica a categoria automaticamente só com confiança alta (ai_classifier.auto_classify);
caso contrário marca como já tentado ('ai_skipped') e mantém em 'A classificar' para revisão
humana, como exige o escopo. Nunca quebra a fila: qualquer erro deixa o documento como está.
"""
import os
import time

import ai_classifier


# Métodos de rótulo que ainda merecem uma tentativa da IA: vieram da regra, sem tipo explícito.
PENDING_METHODS = ('no_explicit_type', 'ambiguous_acronyms')


def _enabled():
    if os.getenv('COLLECTOR_AI_AUTOCLASSIFY', '1').strip().lower() in ('0', 'false', 'no', ''):
        return False
    return ai_classifier.available()


def run_once(app):
    """Classifica UM documento pendente. Devolve True se agiu (pode haver mais), False se nada havia."""
    if not _enabled():
        return False
    with app.db() as c:
        row = c.execute(
            "SELECT l.document_id AS document_id,r.blob AS blob,d.name AS name,p.title AS title,b.mime AS mime "
            "FROM archive_labels l "
            "JOIN documents d ON d.id=l.document_id "
            "JOIN processes p ON p.id=d.process_id "
            "JOIN revisions r ON r.rowid=(SELECT max(x.rowid) FROM revisions x WHERE x.document_id=l.document_id) "
            "JOIN blobs b ON b.hash=r.blob "
            "WHERE l.category='A classificar' AND l.method IN (?,?) "
            "ORDER BY l.updated LIMIT 1",
            PENDING_METHODS,
        ).fetchone()
    if not row:
        return False
    row = dict(row)
    path = app.ROOT / 'blobs' / row['blob']
    try:
        raw = path.read_bytes()
    except OSError:
        _mark_skipped(app, row['document_id'])
        return True
    text = app.document_text(raw, row['mime'], path)
    result = ai_classifier.auto_classify(text, name=row['name'], title=row['title'])
    if not result:
        _mark_skipped(app, row['document_id'])
        return True
    _apply(app, row['document_id'], result['category'])
    return True


def _mark_skipped(app, document_id):
    """A IA olhou e não teve confiança suficiente: não tenta de novo, mas mantém em 'A classificar'."""
    with app.db() as c:
        c.execute('BEGIN IMMEDIATE')
        cur = c.execute('SELECT method FROM archive_labels WHERE document_id=?', (document_id,)).fetchone()
        if not cur or cur['method'] not in PENDING_METHODS:
            return
        c.execute("UPDATE archive_labels SET method='ai_skipped',updated=? WHERE document_id=?", (time.time(), document_id))


def _apply(app, document_id, category):
    """Aplica a categoria sugerida pela IA e reencaminha o upload para a pasta correta."""
    stamp = time.time()
    with app.db() as c:
        c.execute('BEGIN IMMEDIATE')
        cur = c.execute('SELECT method FROM archive_labels WHERE document_id=?', (document_id,)).fetchone()
        if not cur or cur['method'] not in PENDING_METHODS:
            return  # revisão humana ou outro passo já decidiu nesse meio-tempo; não sobrescreve.
        c.execute(
            "UPDATE archive_labels SET category=?,method='ai_auto',actor='ai-autoclassify',updated=? WHERE document_id=?",
            (category, stamp, document_id),
        )
        c.execute(
            'INSERT INTO archive_label_history VALUES(?,?,?,?,?,?)',
            (app.uid(), document_id, category, 'ai_auto', 'ai-autoclassify', stamp),
        )
        # Transferências ainda pendentes: basta corrigir a categoria (define a pasta de destino).
        c.execute(
            "UPDATE cloud_transfers SET category=?,updated=? WHERE revision_id IN "
            "(SELECT id FROM revisions WHERE document_id=?) AND status IN ('queued','waiting_for_connection','failed')",
            (category, stamp, document_id),
        )
        # Já enviadas à pasta errada: reenfileira para o worker movê-las ao destino correto.
        c.execute(
            "UPDATE cloud_transfers SET category=?,status='queued',attempts=0,available=0,updated=? WHERE revision_id IN "
            "(SELECT id FROM revisions WHERE document_id=?) AND status='uploaded' AND category!=?",
            (category, stamp, document_id, category),
        )
