"""Fila de extração local, proveniência e revisão humana de participantes."""
import hashlib,json,time,secrets
from fastapi import HTTPException
import extraction,market_extract,authorization

SUPPORTED={'application/pdf','text/plain','text/html','text/csv','application/vnd.openxmlformats-officedocument.wordprocessingml.document','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}

def migrate(db):
    with db() as c:c.executescript('''
    CREATE TABLE IF NOT EXISTS market_jobs(id TEXT PRIMARY KEY,revision_id TEXT NOT NULL REFERENCES revisions(id),version TEXT NOT NULL,generation INTEGER NOT NULL,owner TEXT NOT NULL,actor_id TEXT,delegation_id TEXT,state TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,lease TEXT,lease_until REAL,error TEXT,created REAL NOT NULL,finished REAL,UNIQUE(revision_id,version,generation));
    CREATE TABLE IF NOT EXISTS market_facts(id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES market_jobs(id),payload TEXT NOT NULL,created REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS market_reviews(id TEXT PRIMARY KEY,fact_id TEXT NOT NULL REFERENCES market_facts(id),status TEXT NOT NULL,rationale TEXT NOT NULL,actor TEXT NOT NULL,created REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS market_ready ON market_jobs(state,created);
    CREATE INDEX IF NOT EXISTS market_fact_run ON market_facts(run_id);
    ''')

def enqueue(c,rid,user,uid,reprocess=False):
    previous=c.execute('SELECT * FROM market_jobs WHERE revision_id=? AND version=? ORDER BY generation DESC LIMIT 1',(rid,market_extract.VERSION)).fetchone()
    if previous and (not reprocess or previous['state'] in ('queued','running')):return previous['id']
    generation=previous['generation']+1 if previous else 0;jid=uid()
    c.execute('INSERT INTO market_jobs(id,revision_id,version,generation,owner,actor_id,delegation_id,state,created) VALUES(?,?,?,?,?,?,?,?,?)',(jid,rid,market_extract.VERSION,generation,user['id'],user.get('_actor_id',user['id']),user.get('_delegation'),'queued',time.time()))
    return jid

def authorized(a,c,job):
    owner=c.execute('SELECT * FROM users WHERE id=? AND active=1',(job['owner'],)).fetchone()
    if not owner:raise HTTPException(404,'Autorização da extração revogada')
    user=dict(owner)
    if job['delegation_id']:user.update(_delegation=job['delegation_id'],_actor_id=job['actor_id'])
    if user['kind']=='service' and not c.execute('SELECT 1 FROM service_tokens WHERE user_id=? AND active=1 AND expires>?',(user['id'],time.time())).fetchone():raise HTTPException(404)
    a.revision_access(c,job['revision_id'],user,'operate')
    return user

def run_once(a):
    now=time.time();lease=secrets.token_hex(24)
    with a.db() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute("UPDATE market_jobs SET state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'queued' END,lease=NULL,error='worker_interrupted' WHERE state='running' AND lease_until<?",(now,))
        row=c.execute("SELECT * FROM market_jobs WHERE state='queued' AND attempts<3 ORDER BY created LIMIT 1").fetchone()
        if not row:return False
        job=dict(row)
        c.execute("UPDATE market_jobs SET state='running',attempts=attempts+1,lease=?,lease_until=? WHERE id=?",(lease,now+120,job['id']))
    def guard():
        with a.db() as c:
            if not c.execute("SELECT 1 FROM market_jobs WHERE id=? AND state='running' AND lease=? AND lease_until>?",(job['id'],lease,time.time())).fetchone():raise extraction.LostLease()
            authorized(a,c,job)
    try:
        guard()
        with a.db() as c:
            user=authorized(a,c,job);r=dict(a.revision_access(c,job['revision_id'],user,'operate'))
        path=a.ROOT/'blobs'/r['blob']
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=r['blob']:raise ValueError('integrity_failed')
        if r['mime'] not in SUPPORTED:pages=[];state='not_supported'
        elif path.stat().st_size>20*1024*1024:pages=[];state='size_limit'
        else:
            pages=extraction.parse(path,r['mime'],r['blob'],guard)
            state='partial_needs_ocr' if any(not text.strip() for _,text in pages) else 'completed'
            if pages and all(not text.strip() for _,text in pages):state='needs_ocr'
        facts=market_extract.extract(pages)
        if state=='completed' and not facts:state='completed_no_matches'
        guard()
        with a.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute("SELECT 1 FROM market_jobs WHERE id=? AND state='running' AND lease=? AND lease_until>?",(job['id'],lease,time.time())).fetchone():raise extraction.LostLease()
            authorized(a,c,job)
            for f in facts:c.execute('INSERT INTO market_facts VALUES(?,?,?,?)',(a.uid(),job['id'],json.dumps(f,ensure_ascii=False),time.time()))
            c.execute('UPDATE market_jobs SET state=?,finished=?,lease=NULL,error=NULL WHERE id=?',(state,time.time(),job['id']))
            a.event(c,job['actor_id'],'market.extraction.'+state,job['id'])
    except (HTTPException,extraction.LostLease):
        with a.db() as c:c.execute("UPDATE market_jobs SET state='cancelled',error='access_revoked_or_cancelled',lease=NULL,finished=? WHERE id=? AND lease=?",(time.time(),job['id'],lease))
    except Exception:
        with a.db() as c:c.execute("UPDATE market_jobs SET state='failed',error='extraction_failed',lease=NULL,finished=? WHERE id=? AND lease=?",(time.time(),job['id'],lease))
    return True

def process_data(a,c,pid,user,history=False):
    process=dict(a.process_access(c,pid,user));facts=[];runs=[]
    rows=c.execute('SELECT j.*,d.id AS document_id,d.name,d.process_id,r.blob,l.category FROM market_jobs j JOIN revisions r ON r.id=j.revision_id JOIN documents d ON d.id=r.document_id LEFT JOIN archive_labels l ON l.document_id=d.id WHERE d.process_id=? ORDER BY j.created,j.rowid',(process['id'],)).fetchall()
    latest={}
    for row in rows:
        if row['state'] in ('completed','completed_no_matches','partial_needs_ocr','needs_ocr'):latest[row['revision_id']]=row['id']
    for row in rows:
        current=c.execute('SELECT id FROM revisions WHERE document_id=? ORDER BY rowid DESC LIMIT 1',(row['document_id'],)).fetchone()[0]==row['revision_id']
        run={k:v for k,v in dict(row).items() if k not in ('lease','owner','actor_id','delegation_id')};run['is_current_revision']=current;runs.append(run)
        for f in c.execute('SELECT * FROM market_facts WHERE run_id=? ORDER BY rowid',(row['id'],)):
            active=current and latest.get(row['revision_id'])==row['id']
            if not history and not active:continue
            review=c.execute('SELECT * FROM market_reviews WHERE fact_id=? ORDER BY rowid DESC LIMIT 1',(f['id'],)).fetchone()
            occurrences=[dict(x) for x in c.execute('SELECT source,name,created FROM occurrences WHERE revision_id=? ORDER BY created',(row['revision_id'],))]
            metadata=[json.loads(x['metadata']) for x in c.execute('SELECT metadata FROM link_items WHERE revision_id=?',(row['revision_id'],))]
            facts.append({**json.loads(f['payload']),'id':f['id'],'run_id':row['id'],'revision_id':row['revision_id'],'document_id':row['document_id'],'document_name':row['name'],'sha256':row['blob'],'process_id':process['id'],'process_number':process['number'],'family':market_extract.family(row['name'],row['category']),'category':row['category'],'method':market_extract.VERSION,'extracted_at':f['created'],'is_current':active,'review_status':review['status'] if review else 'proposed','review':dict(review) if review else None,'sources':occurrences,'source_metadata':metadata,'download_url':'/v1/document-revisions/'+row['revision_id']+'/download'})
    return {'process_id':process['id'],'process_number':process['number'],'runs':runs,'facts':facts,'cross_references':market_extract.cross_reference(facts),'automatic_client_final_inference':False,'identity_policy':'CNPJ válido ou agrupamento candidato por nome; não constitui confirmação de contrato.'}
