import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import app

class MigrationTests(unittest.TestCase):
    def test_existing_v01_jobs_are_preserved(self):
        root=pathlib.Path(tempfile.mkdtemp(prefix='iphan-v01-'))
        with sqlite3.connect(root/'catalog.sqlite') as c:
            c.executescript(app.SCHEMA)
            c.execute('INSERT INTO users(id,name,password,role) VALUES(?,?,?,?)',('legacy-user','legacy','unused','operator'))
            c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)',('legacy-job','legacy-user','old-key','{}','waiting_for_user','{}','original detail',1))
        code="import json,app; c=app.db(); conn=c.__enter__(); print(json.dumps(dict(conn.execute(\"SELECT * FROM jobs WHERE id='legacy-job'\").fetchone()))); c.__exit__(None,None,None)"
        result=subprocess.run([sys.executable,'-c',code],env={**os.environ,'COLLECTOR_DATA':str(root)},capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        row=json.loads(result.stdout)
        self.assertEqual(row['status'],'waiting_for_user')
        self.assertEqual(row['idem'],'old-key')
        self.assertEqual(row['detail'],'original detail')
        self.assertEqual(row['attempt_count'],0)
        self.assertIsNone(row['lease_token'])
        with sqlite3.connect(root/'catalog.sqlite') as c:
            self.assertEqual(c.execute('SELECT version FROM schema_migrations').fetchone()[0],2)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
