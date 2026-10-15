from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import authorization
import repository_migration
import task_queue
import support
import app

class CanonicalMigrationTests(unittest.TestCase):
    def setUp(self):
        self.path=Path(tempfile.mkdtemp())/'legacy.sqlite'
        @contextmanager
        def db():
            c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
            try:
                with c: yield c
            finally: c.close()
        self.db=db
        with db() as c:
            c.executescript(app.SCHEMA)
            for u in ('u1','u2'): c.execute('INSERT INTO users VALUES(?,?,?,?,?)',(u,u,'synthetic','operator',1))
            for pid,owner in [('p1','u1'),('p2','u2')]:
                c.execute('INSERT INTO processes VALUES(?,?,?,?,?)',(pid,owner,'01450.123/2026-01','Processo '+pid,'Pasta '+pid))
                c.execute('INSERT INTO documents VALUES(?,?,?)',('d'+pid,pid,'mesmo.pdf'))
                c.execute('INSERT OR IGNORE INTO blobs VALUES(?,?,?)',('h',1,'text/plain'))
                c.execute('INSERT INTO revisions VALUES(?,?,?,?,?)',('r'+pid,'d'+pid,'h',None,1))
                c.execute('INSERT INTO occurrences VALUES(?,?,?,?,?)',('o'+pid,'r'+pid,'https://origem/'+pid,'mesmo.pdf',1))
                c.execute('INSERT INTO evidence VALUES(?,?,?,?,?)',('e'+pid,'r'+pid,1,'Fonte '+pid,'legacy'))
        task_queue.migrate(db);repository_migration.migrate(db)
    def test_duplicates_are_quarantined_without_implicit_permission_union(self):
        with self.db() as c:
            plan=repository_migration.duplicate_plan(c)
            self.assertEqual(len(plan),1)
            self.assertEqual(len(plan[0]['processes']),2)
            self.assertTrue(all(p['document_count']==1 and p['permissions'][0]['role']=='admin' for p in plan[0]['processes']))
            self.assertTrue(all(p['domain'].startswith('legacy:') for p in plan[0]['processes']))
            self.assertFalse(authorization.allows_principal(c,'p1','u2','read'))
            self.assertEqual(c.execute('SELECT count(*) FROM revisions').fetchone()[0],2)
    def test_explicit_merge_preserves_ids_revisions_origins_evidence_and_aliases(self):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE');repository_migration.merge(c,app.event,'auditor','p1',['p2'])
        with self.db() as c:
            self.assertEqual(authorization.resolve(c,'p2')['id'],'p1')
            self.assertTrue(authorization.allows_principal(c,'p1','u2','read'))
            self.assertEqual(c.execute('SELECT count(*) FROM revisions').fetchone()[0],2)
            self.assertEqual(c.execute('SELECT source FROM occurrences WHERE id=?',('op2',)).fetchone()[0],'https://origem/p2')
            self.assertEqual(c.execute('SELECT text FROM evidence WHERE id=?',('ep2',)).fetchone()[0],'Fonte p2')
            self.assertEqual(c.execute('SELECT process_id FROM documents WHERE id=?',('dp2',)).fetchone()[0],'p1')
            self.assertEqual(c.execute('SELECT count(*) FROM blobs').fetchone()[0],1)
            self.assertEqual(c.execute("SELECT count(*) FROM process_registry WHERE domain='central'").fetchone()[0],1)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(repository_migration.duplicate_plan(c),[])
    def test_failed_merge_rolls_back_everything_and_migration_is_idempotent(self):
        with self.assertRaises(ValueError):
            with self.db() as c: repository_migration.merge(c,app.event,'auditor','p1',['p2','missing'])
        repository_migration.migrate(self.db)
        with self.db() as c:
            self.assertIsNone(c.execute('SELECT canonical_id FROM processes WHERE id=?',('p2',)).fetchone()[0])
            self.assertEqual(c.execute('SELECT count(*) FROM resource_grants').fetchone()[0],2)
            self.assertEqual(c.execute('SELECT count(*) FROM process_aliases').fetchone()[0],0)
