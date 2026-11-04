"""Memórias da Atena: diretrizes imperativas aprendidas com a equipe.

Quando o usuário ensina uma regra/custo/preferência, a Atena formula uma
diretriz reutilizável que passa a ser injetada no system prompt de TODA geração
de IA do sistema (o chat da Atena e a sugestão de categoria). Este módulo é
propositalmente leve e sem dependência do app para poder ser importado cedo
(inclusive pelo ai_classifier) sem risco de import circular.
"""
import os
import sqlite3
import time
import uuid
from pathlib import Path

CATEGORIES = ('custo', 'processo', 'preferencia', 'comercial', 'tecnico', 'prazo', 'modelo_escopo', 'geral')
_DB = Path(os.getenv('COLLECTOR_DATA', './data')).resolve() / 'catalog.sqlite'


def migrate(db):
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS atena_memories('
                  'id TEXT PRIMARY KEY,content TEXT NOT NULL,category TEXT,author TEXT,created REAL)')


def normalize_category(category):
    return category if category in CATEGORIES else 'geral'


def all_memories(c):
    return [dict(r) for r in c.execute('SELECT * FROM atena_memories ORDER BY created DESC')]


def add(c, content, category, author):
    mid = str(uuid.uuid4())
    c.execute('INSERT INTO atena_memories VALUES(?,?,?,?,?)',
              (mid, (content or '').strip()[:1000], normalize_category(category), author, time.time()))
    return mid


def remove(c, mid):
    c.execute('DELETE FROM atena_memories WHERE id=?', (mid,))


def directives_text():
    """Bloco de diretrizes para prefixar em qualquer system prompt.

    Defensivo: abre a própria conexão e nunca propaga erro — se o banco não
    estiver pronto, simplesmente não injeta diretriz nenhuma (a IA segue sem).
    """
    conn = None
    try:
        conn = sqlite3.connect(_DB, timeout=30)
        conn.row_factory = sqlite3.Row
        rows = conn.execute('SELECT content,category FROM atena_memories ORDER BY created').fetchall()
    except sqlite3.Error:
        return ''
    finally:
        if conn is not None:
            conn.close()
    if not rows:
        return ''
    linhas = '\n'.join('- [' + (r['category'] or 'geral') + '] ' + r['content'] for r in rows)
    return 'DIRETRIZES APRENDIDAS COM A EQUIPE (obrigatório respeitar em toda resposta):\n' + linhas
