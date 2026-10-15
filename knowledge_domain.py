"""Domínio de conhecimento rastreável; não gera fatos automaticamente."""
import json
import time

STATUSES = ('proposed', 'validated', 'rejected', 'conflict')
KINDS = ('fact', 'interpretation', 'transcription', 'inference', 'bibliography')
RELATIONS = ('supports', 'contradicts', 'derived_from')


def migrate(db):
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS knowledge_assertions(
            id TEXT PRIMARY KEY,
            process_id TEXT NOT NULL REFERENCES processes(id),
            document_id TEXT NOT NULL REFERENCES documents(id),
            revision_id TEXT NOT NULL REFERENCES revisions(id),
            evidence_id TEXT NOT NULL REFERENCES evidence(id),
            statement TEXT NOT NULL,
            kind TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'proposed',
            confidence REAL,
            author TEXT NOT NULL REFERENCES users(id),
            validator TEXT REFERENCES users(id),
            validated_at REAL,
            rationale TEXT NOT NULL DEFAULT '',
            created REAL NOT NULL,
            updated REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS knowledge_relations(
            id TEXT PRIMARY KEY,
            assertion_id TEXT NOT NULL REFERENCES knowledge_assertions(id),
            related_id TEXT NOT NULL REFERENCES knowledge_assertions(id),
            relation TEXT NOT NULL,
            created_by TEXT NOT NULL REFERENCES users(id),
            created REAL NOT NULL,
            UNIQUE(assertion_id,related_id,relation)
        );
        CREATE INDEX IF NOT EXISTS knowledge_process_idx ON knowledge_assertions(process_id,status);
        CREATE INDEX IF NOT EXISTS knowledge_evidence_idx ON knowledge_assertions(evidence_id);
        ''')


def row_dict(row):
    if not row:
        return None
    value = dict(row)
    value['confidence'] = None if value.get('confidence') is None else float(value['confidence'])
    return value


def validate_confidence(value):
    if value is None:
        return None
    value = float(value)
    if not 0 <= value <= 1:
        raise ValueError('confidence deve estar entre 0 e 1')
    return value


def assertion_payload(row, relations=()):
    value = row_dict(row)
    if value is not None:
        value['relations'] = [row_dict(item) for item in relations]
    return value


def now():
    return time.time()
