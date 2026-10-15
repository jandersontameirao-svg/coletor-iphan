"""Migração aditiva v3; duplicatas antigas ficam isoladas até revisão explícita."""
import json
import re
import time
import uuid
from collections import defaultdict
from pathlib import Path


def number_key(value):
    return re.sub(r'[^A-Z0-9]','',value.upper())


def migrate(db):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        for table,columns in {
            'users':[('kind',"TEXT NOT NULL DEFAULT 'human'")],
            'processes':[('domain',"TEXT NOT NULL DEFAULT 'central'"),('number_key',"TEXT NOT NULL DEFAULT ''"),('canonical_id','TEXT')],
            'jobs':[('actor_id','TEXT'),('delegation_id','TEXT'),('extraction_key','TEXT')],
            'evidence':[('run_id','TEXT')],
        }.items():
            existing={r['name'] for r in c.execute(f'PRAGMA table_info({table})')}
            for name,kind in columns:
                if name not in existing: c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {kind}')
        statements=[
            'CREATE TABLE IF NOT EXISTS process_registry(domain TEXT,number_key TEXT,process_id TEXT UNIQUE REFERENCES processes(id),PRIMARY KEY(domain,number_key))',
            'CREATE TABLE IF NOT EXISTS process_aliases(old_id TEXT PRIMARY KEY REFERENCES processes(id),canonical_id TEXT REFERENCES processes(id),created REAL)',
            'CREATE TABLE IF NOT EXISTS resource_grants(id TEXT PRIMARY KEY,process_id TEXT REFERENCES processes(id),subject_type TEXT,subject_id TEXT,role TEXT,active INTEGER,created REAL,UNIQUE(process_id,subject_type,subject_id,role))',
            'CREATE TABLE IF NOT EXISTS groups(id TEXT PRIMARY KEY,name TEXT UNIQUE)',
            'CREATE TABLE IF NOT EXISTS group_members(group_id TEXT REFERENCES groups(id),user_id TEXT REFERENCES users(id),active INTEGER,PRIMARY KEY(group_id,user_id))',
            'CREATE TABLE IF NOT EXISTS service_tokens(token TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),expires REAL,active INTEGER)',
            'CREATE TABLE IF NOT EXISTS delegations(id TEXT PRIMARY KEY,service_id TEXT REFERENCES users(id),user_id TEXT REFERENCES users(id),scopes TEXT,expires REAL,active INTEGER,created REAL)',
            'CREATE TABLE IF NOT EXISTS link_items(id TEXT PRIMARY KEY,job_id TEXT REFERENCES jobs(id),position INTEGER,url TEXT,status TEXT,detail TEXT,process_id TEXT REFERENCES processes(id),revision_id TEXT REFERENCES revisions(id),duplicate_of TEXT,created REAL,UNIQUE(job_id,position))',
            'CREATE TABLE IF NOT EXISTS extraction_runs(id TEXT PRIMARY KEY,revision_id TEXT REFERENCES revisions(id),job_id TEXT,tool TEXT,version TEXT,state TEXT,created REAL,finished REAL,error TEXT,result TEXT,lease_until REAL,request_key TEXT)',
            "CREATE UNIQUE INDEX IF NOT EXISTS extraction_job_key ON jobs(extraction_key) WHERE extraction_key IS NOT NULL",
            "CREATE UNIQUE INDEX IF NOT EXISTS active_extraction ON extraction_runs(revision_id,tool,version) WHERE state='running'",
            'CREATE TABLE IF NOT EXISTS document_sources(process_id TEXT REFERENCES processes(id),source_url TEXT,document_id TEXT REFERENCES documents(id),PRIMARY KEY(process_id,source_url))',
            'CREATE TABLE IF NOT EXISTS migration_documents(id TEXT PRIMARY KEY,document_id TEXT,source_process TEXT,source_name TEXT,target_process TEXT,target_name TEXT,actor TEXT,created REAL)',
            'CREATE TABLE IF NOT EXISTS link_edits(id TEXT PRIMARY KEY,item_id TEXT REFERENCES link_items(id),previous_url TEXT,new_url TEXT,actor TEXT,created REAL)',
            'CREATE TABLE IF NOT EXISTS link_captures(id TEXT PRIMARY KEY,item_id TEXT REFERENCES link_items(id),source_url TEXT,final_url TEXT,sha256 TEXT,mime TEXT,captured REAL)',
            'CREATE TABLE IF NOT EXISTS idempotency_requests(owner TEXT,key TEXT,input TEXT,job_id TEXT REFERENCES jobs(id),PRIMARY KEY(owner,key))',
            'CREATE TABLE IF NOT EXISTS classifications(id TEXT PRIMARY KEY,document_id TEXT REFERENCES documents(id),study_type TEXT,version TEXT,status TEXT,reviewer TEXT,created REAL,previous_id TEXT)',
        ]
        for sql in statements: c.execute(sql)
        if 'lease_token' not in {r['name'] for r in c.execute('PRAGMA table_info(extraction_runs)')}: c.execute('ALTER TABLE extraction_runs ADD COLUMN lease_token TEXT')
        for name,kind in [('revision_id','TEXT'),('notes',"TEXT NOT NULL DEFAULT ''")]:
            if name not in {r['name'] for r in c.execute('PRAGMA table_info(classifications)')}: c.execute(f'ALTER TABLE classifications ADD COLUMN {name} {kind}')
        c.execute('INSERT OR IGNORE INTO idempotency_requests SELECT owner,idem,input,id FROM jobs')
        if c.execute('SELECT 1 FROM schema_migrations WHERE version=3').fetchone(): return
        groups=defaultdict(list)
        for row in c.execute('SELECT * FROM processes ORDER BY rowid').fetchall(): groups[number_key(row['number'])].append(row)
        for key,rows in groups.items():
            for row in rows:
                # Não unir permissões implicitamente. Cada duplicata fica em domínio legado isolado.
                domain='central' if len(rows)==1 else 'legacy:'+row['id']
                c.execute('UPDATE processes SET domain=?,number_key=? WHERE id=?',(domain,key,row['id']))
                c.execute('INSERT INTO process_registry VALUES(?,?,?)',(domain,key,row['id']))
                c.execute('INSERT INTO resource_grants VALUES(?,?,?,?,?,?,?)',(str(uuid.uuid4()),row['id'],'user',row['owner'],'admin',1,time.time()))
        c.execute('INSERT INTO schema_migrations VALUES(3,?)',(time.time(),))
        c.execute('INSERT INTO audit VALUES(?,?,?,?,?)',(str(uuid.uuid4()),'migration-v3','repository.migrated','schema-v3',time.time()))


def duplicate_plan(c):
    groups=defaultdict(list)
    for row in c.execute('SELECT id,number,title,domain,number_key FROM processes WHERE canonical_id IS NULL ORDER BY rowid'):
        visible=dict(row)
        visible['permissions']=[dict(g) for g in c.execute('SELECT subject_type,subject_id,role,active FROM resource_grants WHERE process_id=?',(row['id'],)).fetchall()]
        visible['document_count']=c.execute('SELECT count(*) FROM documents WHERE process_id=?',(row['id'],)).fetchone()[0]
        groups[row['number_key']].append(visible)
    return [{'number_key':k,'processes':v,'action':'Escolher canônico e revisar união de permissões; não executada automaticamente'} for k,v in groups.items() if len(v)>1]


def merge(c,event,actor,canonical_id,source_ids):
    if canonical_id in source_ids or len(set(source_ids))!=len(source_ids) or not source_ids: raise ValueError('Seleção inválida')
    target=c.execute('SELECT * FROM processes WHERE id=? AND canonical_id IS NULL',(canonical_id,)).fetchone()
    if not target: raise ValueError('Canônico não encontrado')
    sources=[]
    for sid in source_ids:
        row=c.execute('SELECT * FROM processes WHERE id=? AND canonical_id IS NULL',(sid,)).fetchone()
        if not row or row['number_key']!=target['number_key']: raise ValueError('Processos não são duplicatas confirmadas')
        sources.append(row)
    other=c.execute("SELECT process_id FROM process_registry WHERE domain='central' AND number_key=?",(target['number_key'],)).fetchone()
    if other and other['process_id'] not in [canonical_id,*source_ids]: raise ValueError('Há outro canônico central')
    for source in sources:
        sid=source['id']
        for document in c.execute('SELECT * FROM documents WHERE process_id=?',(sid,)).fetchall():
            name=document['name']
            if c.execute('SELECT id FROM documents WHERE process_id=? AND name=?',(canonical_id,name)).fetchone():
                extension=Path(name).suffix
                stem=name[:-len(extension)] if extension else name
                name=f'{stem} [legado {document["id"]}]{extension}'
            c.execute('INSERT INTO migration_documents VALUES(?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),document['id'],sid,document['name'],canonical_id,name,actor,time.time()))
            c.execute('UPDATE documents SET process_id=?,name=? WHERE id=?',(canonical_id,name,document['id']))
        for mapping in c.execute('SELECT * FROM document_sources WHERE process_id=?',(sid,)).fetchall():
            if not c.execute('SELECT 1 FROM document_sources WHERE process_id=? AND source_url=?',(canonical_id,mapping['source_url'])).fetchone():
                c.execute('UPDATE document_sources SET process_id=? WHERE process_id=? AND source_url=?',(canonical_id,sid,mapping['source_url']))
        for grant in c.execute('SELECT * FROM resource_grants WHERE process_id=?',(sid,)).fetchall():
            existing=c.execute('SELECT id,active FROM resource_grants WHERE process_id=? AND subject_type=? AND subject_id=? AND role=?',(canonical_id,grant['subject_type'],grant['subject_id'],grant['role'])).fetchone()
            if existing:
                if grant['active']: c.execute('UPDATE resource_grants SET active=1 WHERE id=?',(existing['id'],))
            else: c.execute('UPDATE resource_grants SET process_id=? WHERE id=?',(canonical_id,grant['id']))
        for delegation in c.execute('SELECT id,scopes FROM delegations').fetchall():
            scopes=json.loads(delegation['scopes'])
            if sid in scopes:
                scopes[canonical_id]=sorted(set(scopes.get(canonical_id,[])+scopes.pop(sid)))
                c.execute('UPDATE delegations SET scopes=? WHERE id=?',(json.dumps(scopes),delegation['id']))
                event(c,actor,'delegation.scope.migrated',delegation['id'])
        c.execute('UPDATE link_items SET process_id=? WHERE process_id=?',(canonical_id,sid))
        c.execute('DELETE FROM process_registry WHERE process_id=?',(sid,))
        c.execute('UPDATE processes SET canonical_id=? WHERE id=?',(canonical_id,sid))
        c.execute('INSERT INTO process_aliases VALUES(?,?,?)',(sid,canonical_id,time.time()))
        c.execute('UPDATE process_aliases SET canonical_id=? WHERE canonical_id=?',(canonical_id,sid))
        c.execute('UPDATE processes SET canonical_id=? WHERE canonical_id=?',(canonical_id,sid))
        event(c,actor,'process.merge.source',sid)
    c.execute('DELETE FROM process_registry WHERE process_id=?',(canonical_id,))
    c.execute("UPDATE processes SET domain='central' WHERE id=?",(canonical_id,))
    c.execute("INSERT INTO process_registry VALUES('central',?,?)",(target['number_key'],canonical_id))
    event(c,actor,'process.merge.completed',canonical_id)
    return {'canonical_id':canonical_id,'aliases':source_ids,'permissions':'União explícita dos vínculos antigos; nenhuma revisão removida'}
