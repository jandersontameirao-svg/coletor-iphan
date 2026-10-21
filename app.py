"""Coletor IPHAN: fundação local; capacidades externas não homologadas."""
import hashlib, io, json, os, secrets, sqlite3, threading, time, uuid, zipfile
from pathlib import Path
from contextlib import contextmanager
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Literal, Any
import task_queue
import authorization
import repository_migration
import extraction
import safe_fetch
import knowledge_domain
import geo_domain
import ocr_optional
import demo_mode
import sei_domain
import sei_public
import document_extractors
import archive_policy
import sharepoint_store
import market_domain
from pypdf import PdfReader

ROOT = Path(os.getenv('COLLECTOR_DATA', './data')).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
(ROOT / 'blobs').mkdir(exist_ok=True)
DB = ROOT / 'catalog.sqlite'
app = FastAPI(title='Coletor IPHAN — fundação local', version='0.7.0')
DEMO_MODE = os.getenv('COLLECTOR_DEMO_MODE', '').lower() in ('1', 'true', 'yes')
ALLOW_EMBED = os.getenv('COLLECTOR_ALLOW_EMBED', '').lower() in ('1', 'true', 'yes')
EMBEDDED_WORKER = os.getenv('COLLECTOR_EMBEDDED_WORKER', '').lower() in ('1', 'true', 'yes')

def uid(): return str(uuid.uuid4())
@contextmanager
def db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    try:
        with c: yield c
    finally: c.close()

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT UNIQUE,password TEXT,role TEXT,active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),expires REAL);
CREATE TABLE IF NOT EXISTS processes(id TEXT PRIMARY KEY,owner TEXT REFERENCES users(id),number TEXT,title TEXT,folder TEXT,UNIQUE(owner,number));
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,owner TEXT,name TEXT,code TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS blobs(hash TEXT PRIMARY KEY,size INTEGER,mime TEXT);
CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,process_id TEXT REFERENCES processes(id),name TEXT,UNIQUE(process_id,name));
CREATE TABLE IF NOT EXISTS revisions(id TEXT PRIMARY KEY,document_id TEXT REFERENCES documents(id),blob TEXT REFERENCES blobs(hash),predecessor TEXT,created REAL);
CREATE TABLE IF NOT EXISTS occurrences(id TEXT PRIMARY KEY,revision_id TEXT REFERENCES revisions(id),source TEXT,name TEXT,created REAL);
CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY,revision_id TEXT REFERENCES revisions(id),page INTEGER,text TEXT,method TEXT);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,owner TEXT,idem TEXT,input TEXT,status TEXT,checkpoint TEXT,detail TEXT,created REAL,UNIQUE(owner,idem));
CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY,kind TEXT,payload TEXT,created REAL);
CREATE TABLE IF NOT EXISTS audit(id TEXT PRIMARY KEY,actor TEXT,action TEXT,resource TEXT,created REAL);
'''
with db() as c: c.executescript(SCHEMA)
task_queue.migrate(db)
repository_migration.migrate(db)
knowledge_domain.migrate(db)
geo_domain.migrate(db)
sei_domain.migrate(db)

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt + ':' + hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 310000).hex()

def event(c, actor, action, resource):
    c.execute('INSERT INTO audit VALUES(?,?,?,?,?)', (uid(), actor, action, resource, time.time()))
    c.execute('INSERT INTO outbox VALUES(?,?,?,?)', (uid(), action, json.dumps({'resource_id':resource}), time.time()))

if DEMO_MODE:
    demo_mode.seed(db, ROOT, password_hash, event)

def identity(request: Request):
    header=request.headers.get('Authorization','')
    if not header.startswith('Bearer '): raise HTTPException(401,'Sessão inválida')
    token=hashlib.sha256(header[7:].encode()).hexdigest()
    with db() as c:
        row=c.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>? AND u.active=1 AND u.kind='human'",(token,time.time())).fetchone()
        if not row:
            row=c.execute("SELECT u.* FROM service_tokens s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>? AND s.active=1 AND u.active=1 AND u.kind='service'",(token,time.time())).fetchone()
        if not row: raise HTTPException(401,'Sessão inválida ou expirada')
        user=dict(row)
        delegation=request.headers.get('X-Delegation-Id')
        if delegation:
            if user['kind']!='service': raise HTTPException(403,'Delegação exige conta de serviço')
            delegated=c.execute('SELECT d.*,u.name,u.role,u.kind FROM delegations d JOIN users u ON u.id=d.user_id WHERE d.id=? AND d.service_id=? AND d.active=1 AND d.expires>? AND u.active=1',(delegation,user['id'],time.time())).fetchone()
            if not delegated: raise HTTPException(403,'Delegação inválida ou revogada')
            user={'id':delegated['user_id'],'name':delegated['name'],'role':delegated['role'],'kind':delegated['kind'],'_actor_id':user['id'],'_delegation':delegation}
        return user


def platform_admin(user):
    if user['role']!='admin' or user.get('_delegation') or user.get('kind','human')!='human':
        raise HTTPException(403,'Administrador humano necessário')


def process_access(c,process_id,user,permission='read'):
    return authorization.process_access(c,process_id,user,permission)


def ensure_discovered_process(c,number,title,user):
    """Cria somente para usuário humano o processo declarado em uma página pública SEI."""
    if user.get('_delegation') or user.get('kind','human')!='human':
        raise HTTPException(403,'Descoberta sem processo exige usuário humano sem delegação')
    number=''.join(number.split())
    key=repository_migration.number_key(number)
    if not key:
        raise HTTPException(422,'Número do processo público inválido')
    current=c.execute("SELECT process_id FROM process_registry WHERE domain='central' AND number_key=?",(key,)).fetchone()
    if current:
        return process_access(c,current['process_id'],user,'operate')['id']
    pid=uid()
    title=(title or 'Processo público SEI/IPHAN').strip()[:300]
    folder=f'{number} — {title}'
    try:
        c.execute('INSERT INTO processes(id,owner,number,title,folder,domain,number_key) VALUES(?,?,?,?,?,?,?)',(pid,user['id'],number,title,folder,'central',key))
        c.execute("INSERT INTO process_registry VALUES('central',?,?)",(key,pid))
        c.execute('INSERT INTO resource_grants VALUES(?,?,?,?,?,?,?)',(uid(),pid,'user',user['id'],'admin',1,time.time()))
    except sqlite3.IntegrityError:
        current=c.execute("SELECT process_id FROM process_registry WHERE domain='central' AND number_key=?",(key,)).fetchone()
        if not current:
            raise
        return process_access(c,current['process_id'],user,'operate')['id']
    event(c,user.get('_actor_id',user['id']),'process.discovered_from_public_page',pid)
    return pid

class Login(BaseModel):
    name: str
    password: str
class ProcessInput(BaseModel):
    number: str = Field(min_length=1,max_length=100)
    title: str = Field(min_length=1,max_length=300)
class ProjectInput(BaseModel):
    name: str = Field(min_length=1,max_length=300)
class JobInput(BaseModel):
    source: Literal['iphan','repository'] = 'iphan'
    operation: Literal['collect_process','collect_links','extract_revision'] = 'collect_process'
    input: dict[str,Any] = Field(examples=[{'urls':['https://www.gov.br/iphan/documento.pdf'],'process_id':'<processo autorizado>'},{'revision_id':'<revisão autorizada>','reprocess':False}])
    refresh_policy: Literal['if_changed'] = 'if_changed'
    request_context: dict[str,str] = {}
class UserInput(Login):
    role: str = 'operator'
class UserState(BaseModel):
    active: bool

@app.post('/v1/sessions')
def login(body: Login):
    with db() as c:
        u = c.execute("SELECT * FROM users WHERE name=? AND active=1 AND kind='human'",(body.name,)).fetchone()
        if not u or not secrets.compare_digest(password_hash(body.password,u['password'].split(':')[0]),u['password']):
            raise HTTPException(401,'Credenciais inválidas')
        token = secrets.token_urlsafe(40)
        c.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),u['id'],time.time()+28800))
    return {'access_token':token,'token_type':'bearer'}

@app.delete('/v1/sessions',status_code=204)
def logout(request: Request,user=Depends(identity)):
    with db() as c: c.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(request.headers['Authorization'].removeprefix('Bearer ').encode()).hexdigest(),))

@app.post('/v1/users',status_code=201)
def create_user(body: UserInput,user=Depends(identity)):
    platform_admin(user)
    if body.role not in ('reader','operator','reviewer','admin') or len(body.password)<12: raise HTTPException(422,'Papel inválido ou senha com menos de 12 caracteres')
    user_id=uid()
    with db() as c:
        try: c.execute('INSERT INTO users(id,name,password,role) VALUES(?,?,?,?)',(user_id,body.name,password_hash(body.password),body.role))
        except sqlite3.IntegrityError: raise HTTPException(409,'Nome já cadastrado')
        event(c,user['id'],'user.created',user_id)
    return {'id':user_id}

@app.get('/v1/users')
def list_users(user=Depends(identity)):
    platform_admin(user)
    with db() as c: return [dict(r) for r in c.execute('SELECT id,name,role,active FROM users ORDER BY name')]


@app.patch('/v1/users/{user_id}')
def user_state(user_id: str,body: UserState,user=Depends(identity)):
    platform_admin(user)
    if user_id==user['id'] and not body.active: raise HTTPException(409,'Não desative sua própria conta')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT id FROM users WHERE id=?',(user_id,)).fetchone(): raise HTTPException(404)
        c.execute('UPDATE users SET active=? WHERE id=?',(int(body.active),user_id))
        if not body.active:
            c.execute('DELETE FROM sessions WHERE user_id=?',(user_id,))
            c.execute('UPDATE service_tokens SET active=0 WHERE user_id=?',(user_id,))
            c.execute('UPDATE delegations SET active=0 WHERE service_id=? OR user_id=?',(user_id,user_id))
            pending=c.execute("SELECT id FROM jobs WHERE (owner=? OR actor_id=?) AND status IN ('queued','running','paused','waiting_for_user')",(user_id,user_id)).fetchall()
            for job in pending:
                c.execute("UPDATE jobs SET status='cancelled',lease_token=NULL,lease_until=NULL,detail='Conta desativada' WHERE id=?",(job['id'],))
                c.execute("UPDATE job_attempts SET status='cancelled',finished=? WHERE job_id=? AND status='running'",(time.time(),job['id']))
                c.execute("UPDATE extraction_runs SET state='cancelled',finished=? WHERE job_id=? AND state='running'",(time.time(),job['id']))
                event(c,user['id'],'collection.cancelled',job['id'])
        event(c,user['id'],'user.activated' if body.active else 'user.deactivated',user_id)
    return {'id':user_id,'active':body.active}


@app.post('/v1/processes',status_code=201)
def create_process(body: ProcessInput,user=Depends(identity)):
    if user.get('_delegation') or user.get('kind','human')!='human': raise HTTPException(403,'Criação de processo exige usuário humano sem delegação')
    number=''.join(body.number.split()); key=repository_migration.number_key(number)
    if not key: raise HTTPException(422,'Número inválido')
    pid=uid();folder=f'{number} — {body.title}'
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT id FROM processes WHERE number_key=? AND canonical_id IS NULL',(key,)).fetchone():
            raise HTTPException(409,'Processo já registrado no domínio; solicite acesso ao responsável')
        c.execute('INSERT INTO processes(id,owner,number,title,folder,domain,number_key) VALUES(?,?,?,?,?,?,?)',(pid,user['id'],number,body.title,folder,'central',key))
        c.execute("INSERT INTO process_registry VALUES('central',?,?)",(key,pid))
        c.execute('INSERT INTO resource_grants VALUES(?,?,?,?,?,?,?)',(uid(),pid,'user',user['id'],'admin',1,time.time()))
        event(c,user['id'],'process.created',pid)
    return {'id':pid,'folder':folder}


@app.get('/v1/processes')
def processes(user=Depends(identity)):
    result=[]
    with db() as c:
        for row in c.execute('SELECT * FROM processes WHERE canonical_id IS NULL ORDER BY rowid').fetchall():
            try:
                process_access(c,row['id'],user)
                visible=dict(row);visible.pop('owner',None)
                visible['permissions']=[permission for permission in ('read','operate','review','admin') if authorization.allows_principal(c,row['id'],user['id'],permission) and authorization.delegation_valid(c,user,row['id'],permission)]
                result.append(visible)
            except HTTPException: continue
    return result


@app.get('/v1/processes/{pid}')
def get_process(pid: str,user=Depends(identity)):
    with db() as c:
        row=dict(process_access(c,pid,user));row.pop('owner',None);return row

@app.patch('/v1/processes/{pid}')
def rename(pid: str,body: ProcessInput,user=Depends(identity)):
    with db() as c:
        row=process_access(c,pid,user,'admin')
        pid=row['id']
        if body.number!=''.join(row['number'].split()): raise HTTPException(422,'Número do processo é estável')
        if row['title']!=body.title:
            c.execute('UPDATE processes SET title=?,folder=? WHERE id=?',(body.title,f'{row["number"]} — {body.title}',pid))
            event(c,user['id'],'process.renamed',pid)
    return {'id':pid}

@app.post('/v1/projects',status_code=201)
def project(body: ProjectInput,user=Depends(identity)):
    if user.get('_delegation') or user.get('kind','human')!='human': raise HTTPException(403,'Criação de projeto exige usuário humano sem delegação')
    pid=uid(); code='PRJ-'+pid[:8].upper()
    with db() as c: c.execute('INSERT INTO projects VALUES(?,?,?,?)',(pid,user['id'],body.name,code))
    return {'id':pid,'code':code}

def put_blob(data, name=''):
    try: mime=archive_policy.detect(data,name,allow_html=Path(name).suffix.lower() in ('.html','.htm'))
    except ValueError as exc: raise HTTPException(415,str(exc))
    digest=hashlib.sha256(data).hexdigest();path=ROOT/'blobs'/digest
    temporary=ROOT/'blobs'/('.'+uid())
    with temporary.open('wb') as f:
        f.write(data);f.flush();os.fsync(f.fileno())
    try:
        try: os.link(temporary,path)
        except FileExistsError:
            if hashlib.sha256(path.read_bytes()).hexdigest()!=digest: os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)
    return digest,mime,len(data)


def persist_document(c,pid,name,source,user,blob,from_link=False,original_name=None,external_key=None):
    pid=process_access(c,pid,user,'operate')['id']
    original_name=original_name or name
    digest,mime,size=blob
    suffix=Path(name).suffix.lower()
    allowed_suffixes={
        'application/pdf': ('','.pdf'),
        'text/plain': ('','.txt'),
        'text/csv': ('','.csv'),
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ('','.docx'),
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ('','.xlsx'),
    }
    for extension,kind in archive_policy.MIMES.items():
        allowed_suffixes[kind]=tuple(set(allowed_suffixes.get(kind,('',)))|{extension})
    if suffix not in allowed_suffixes.get(mime, ('',)):
        raise HTTPException(415,'Extensão não corresponde ao conteúdo verificado')
    c.execute('INSERT OR IGNORE INTO blobs VALUES(?,?,?)',(digest,size,mime))
    if from_link:
        doc=c.execute('SELECT document_id AS id FROM document_sources WHERE process_id=? AND source_url=?',(pid,source)).fetchone()
        if external_key:
            keyed=c.execute('SELECT document_id AS id FROM document_keys WHERE process_id=? AND external_key=?',(pid,external_key)).fetchone()
            if keyed: doc=keyed
            elif doc and c.execute('SELECT 1 FROM document_keys WHERE document_id=?',(doc['id'],)).fetchone(): doc=None
        if not doc and c.execute('SELECT id FROM documents WHERE process_id=? AND name=?',(pid,name)).fetchone():
            extension=Path(name).suffix
            stem=name[:-len(extension)] if extension else name
            name=stem[:240]+' [link '+hashlib.sha256(source.encode()).hexdigest()[:16]+']'+extension
    else: doc=c.execute('SELECT id FROM documents WHERE process_id=? AND name=?',(pid,name)).fetchone()
    did=doc['id'] if doc else uid()
    if not doc:
        c.execute('INSERT INTO documents VALUES(?,?,?)',(did,pid,name))
        if from_link: c.execute('INSERT OR IGNORE INTO document_sources VALUES(?,?,?)',(pid,source,did))
    if from_link:
        c.execute('INSERT OR IGNORE INTO document_sources VALUES(?,?,?)',(pid,source,did))
        if external_key: c.execute('INSERT OR IGNORE INTO document_keys VALUES(?,?,?)',(pid,external_key,did))
    last=c.execute('SELECT * FROM revisions WHERE document_id=? ORDER BY rowid DESC LIMIT 1',(did,)).fetchone()
    rid=last['id'] if last and last['blob']==digest else uid()
    changed=not last or last['blob']!=digest
    if changed:
        c.execute('INSERT INTO revisions VALUES(?,?,?,?,?)',(rid,did,digest,last['id'] if last else None,time.time()))
        event(c,user.get('_actor_id',user['id']),'document.revision.created',rid)
    c.execute('INSERT INTO occurrences VALUES(?,?,?,?,?)',(uid(),rid,source,(original_name or name)[:300],time.time()))
    current=c.execute('SELECT * FROM archive_labels WHERE document_id=?',(did,)).fetchone()
    if not current or current['method']!='human_review':
        raw=(ROOT/'blobs'/digest).read_bytes() if Path(name).suffix.lower()=='.zip' else None
        label,method=archive_policy.category(original_name,name,raw)
        c.execute('INSERT OR REPLACE INTO archive_labels VALUES(?,?,?,?,?)',(did,label,method,user['id'],time.time()))
    else: label=current['category']
    if not DEMO_MODE:
        sharepoint_store.queue_revision(c,rid,user,label,uid)
        market_domain.enqueue(c,rid,user,uid)
    return {'document_id':did,'revision_id':rid,'sha256':digest,'changed':changed}



async def read_upload(request):
    data=bytearray()
    async for chunk in request.stream():
        if len(data)+len(chunk)>archive_policy.MAX_BYTES: raise HTTPException(413,'Limite de 128 MiB')
        data.extend(chunk)
    return bytes(data)


@app.post('/v1/processes/{pid}/documents',status_code=201)
async def upload(pid: str,request: Request,name: str,source: str='manual',user=Depends(identity)):
    if not name.strip() or len(name)>300 or len(source)>4096: raise HTTPException(422,'Nome/origem inválidos')
    with db() as c: pid=process_access(c,pid,user,'operate')['id']
    blob=put_blob(await read_upload(request),name)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        return persist_document(c,pid,name,source,user,blob)

@app.get('/v1/processes/{pid}/documents')
def documents(pid: str,user=Depends(identity)):
    with db() as c:
        pid=process_access(c,pid,user)['id']
        return [dict(r) for r in c.execute('SELECT * FROM documents WHERE process_id=?',(pid,))]

def revision_access(c,rid,user,permission='read'):
    r=c.execute('SELECT r.*,d.name,d.process_id,b.mime FROM revisions r JOIN documents d ON d.id=r.document_id JOIN blobs b ON b.hash=r.blob WHERE r.id=?',(rid,)).fetchone()
    if not r: raise HTTPException(404,'Revisão não encontrada')
    process_access(c,r['process_id'],user,permission)
    return r

@app.get('/v1/documents/{did}/revisions')
def revisions(did: str,user=Depends(identity)):
    with db() as c:
        d=c.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone()
        if not d: raise HTTPException(404)
        process_access(c,d['process_id'],user)
        return [dict(r) for r in c.execute('SELECT * FROM revisions WHERE document_id=? ORDER BY rowid',(did,))]

@app.get('/v1/document-revisions/{rid}/download')
def download(rid: str,user=Depends(identity)):
    with db() as c: r=revision_access(c,rid,user)
    path=ROOT/'blobs'/r['blob']
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=r['blob']: raise HTTPException(503,'Integridade do original não confirmada')
    return FileResponse(path,media_type=r['mime'],filename=Path(r['name']).name)

def prepare_extraction(rid,user):
    with db() as c: r=revision_access(c,rid,user,'operate')
    path=ROOT/'blobs'/r['blob']
    if not path.is_file() or path.stat().st_size>20*1024*1024 or hashlib.sha256(path.read_bytes()).hexdigest()!=r['blob']:
        raise HTTPException(503,'Falha de integridade ou tamanho')
    return extraction.parse(path,r['mime'],r['blob'],user.get('_guard',lambda:None))


def reserve_extraction(rid,user,job_id=None,reprocess=False,lease_token=None):
    with db() as c:
        c.execute('BEGIN IMMEDIATE');revision_access(c,rid,user,'operate')
        if job_id and not task_queue.held(c,{'id':job_id,'lease_token':lease_token}): raise extraction.LostLease()
        if not reprocess:
            cached=c.execute("SELECT * FROM extraction_runs WHERE revision_id=? AND tool=? AND version=? AND state IN ('completed','needs_ocr') ORDER BY rowid DESC LIMIT 1",(rid,extraction.TOOL,extraction.VERSION)).fetchone()
            if cached: return {'cached':json.loads(cached['result']),'id':cached['id']}
        running=c.execute("SELECT * FROM extraction_runs WHERE revision_id=? AND tool=? AND version=? AND state='running'",(rid,extraction.TOOL,extraction.VERSION)).fetchone()
        if running:
            if running['job_id']==job_id and job_id and running['lease_token']==lease_token: return {'id':running['id']}
            same_recovered_job=job_id and running['job_id']==job_id and running['lease_token']!=lease_token
            if running['lease_until']>time.time() and not same_recovered_job: raise HTTPException(409,'Extração já em execução; consulte histórico')
            c.execute("UPDATE extraction_runs SET state='interrupted',finished=? WHERE id=?",(time.time(),running['id']))
        run_id=uid()
        c.execute('INSERT INTO extraction_runs(id,revision_id,job_id,tool,version,state,created,finished,error,result,lease_until,request_key,lease_token) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(run_id,rid,job_id,extraction.TOOL,extraction.VERSION,'running',time.time(),None,None,None,time.time()+120,'explicit' if reprocess else 'default',lease_token))
        event(c,user.get('_actor_id',user['id']),'extraction.started',run_id)
        return {'id':run_id}


def save_extraction(c,rid,user,pages):
    revision_access(c,rid,user,'operate')
    run_id=user.get('_run_id')
    if not run_id: raise HTTPException(409,'Execução de extração não reservada')
    run=c.execute('SELECT * FROM extraction_runs WHERE id=? AND revision_id=?',(run_id,rid)).fetchone()
    if not run or run['state']!='running': raise HTTPException(409,'Execução não está ativa')
    if run['job_id'] and (run['lease_token']!=user.get('_lease_token') or not task_queue.held(c,{'id':run['job_id'],'lease_token':run['lease_token']})): raise extraction.LostLease()
    results=[]
    for page,text in pages:
        if not text.strip(): continue
        eid=uid(); c.execute('INSERT INTO evidence(id,revision_id,page,text,method,run_id) VALUES(?,?,?,?,?,?)',(eid,rid,page,text,extraction.VERSION,run_id))
        results.append({'id':eid,'page':page,'characters':len(text)})
    ocr_required=any(not text.strip() for _,text in pages)
    result={'run_id':run_id,'evidence':results,'ocr_required':ocr_required,'pages':len(pages) if any(page is not None for page,_ in pages) else None,'units':len(pages),'extractable':bool(results)}
    state='needs_ocr' if ocr_required else 'completed'
    c.execute('UPDATE extraction_runs SET state=?,finished=?,result=? WHERE id=?',(state,time.time(),json.dumps(result),run_id))
    event(c,user.get('_actor_id',user['id']),'extraction.'+state,run_id)
    return result


def fail_extraction(run_id,code,state='failed'):
    with db() as c:
        c.execute("UPDATE extraction_runs SET state=?,error=?,finished=? WHERE id=? AND state='running'",(state,code,time.time(),run_id))


@app.post('/v1/document-revisions/{rid}/extract')
def extract(rid: str,reprocess: bool=False,user=Depends(identity)):
    reservation=reserve_extraction(rid,user,reprocess=reprocess)
    cached=reservation.get('cached')
    if isinstance(cached,dict): return {**cached,'reused':True}
    user={**user,'_run_id':reservation['id']}
    try:
        pages=prepare_extraction(rid,user)
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            return save_extraction(c,rid,user,pages)
    except Exception:
        fail_extraction(reservation['id'],'extraction_failed');raise


@app.get('/v1/document-revisions/{rid}/extractions')
def extraction_history(rid: str,user=Depends(identity)):
    with db() as c:
        revision_access(c,rid,user)
        return [{k:v for k,v in dict(r).items() if k!='lease_token'} for r in c.execute('SELECT * FROM extraction_runs WHERE revision_id=? ORDER BY rowid',(rid,))]

@app.get('/v1/evidence/{eid}')
def evidence(eid: str,user=Depends(identity)):
    with db() as c:
        r=c.execute('SELECT * FROM evidence WHERE id=?',(eid,)).fetchone()
        if not r: raise HTTPException(404)
        revision_access(c,r['revision_id'],user)
        return dict(r)

@app.post('/v1/collection-jobs',status_code=202)
def job(body: JobInput,request: Request,user=Depends(identity)):
    key=request.headers.get('Idempotency-Key')
    if not key or len(key)>200: raise HTTPException(422,'Idempotency-Key obrigatório, até 200 caracteres')
    links=[];extraction_key=None
    if body.operation=='extract_revision':
        if body.source!='repository' or not set(body.input)<= {'revision_id','reprocess'} or not isinstance(body.input.get('revision_id'),str) or not isinstance(body.input.get('reprocess',False),bool):
            raise HTTPException(422,'Extração exige revision_id e reprocess booleano opcional')
        with db() as c: revision_access(c,body.input['revision_id'],user,'operate')
        if not body.input.get('reprocess',False): extraction_key=body.input['revision_id']+':'+extraction.VERSION
    else:
        if body.source!='iphan' or not set(body.input)<= {'url','urls','process_id'} or ('url' in body.input)==('urls' in body.input):
            raise HTTPException(422,'Coleta aceita somente url ou urls; busca por número não é suportada')
        links=[body.input['url']] if 'url' in body.input else body.input['urls']
        if not isinstance(links,list) or not 1<=len(links)<=50: raise HTTPException(422,'Informe entre 1 e 50 links')
        if body.input.get('process_id'):
            if not isinstance(body.input['process_id'],str): raise HTTPException(422,'process_id inválido')
            with db() as c: process_access(c,body.input['process_id'],user,'operate')
        elif user.get('_delegation'): raise HTTPException(422,'Delegação exige processo no escopo')
    payload=json.dumps(body.model_dump(),sort_keys=True,separators=(',',':')); jid=uid()
    if len(payload.encode())>256*1024: raise HTTPException(413,'Comando acima de 256 KiB')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        existing=c.execute('SELECT * FROM idempotency_requests WHERE owner=? AND key=?',(user['id'],key)).fetchone()
        if existing:
            if existing['input']!=payload: raise HTTPException(409,'Chave reutilizada com parâmetros diferentes')
            jid=existing['job_id']
        else:
            cached_job=c.execute('SELECT * FROM jobs WHERE extraction_key=?',(extraction_key,)).fetchone() if extraction_key else None
            if cached_job and (cached_job['status'] in ('completed','partial') or (cached_job['status'] not in ('failed','cancelled') and authorization.job_authorized(c,dict(cached_job)))):
                jid=cached_job['id']
            else:
                if cached_job:
                    if cached_job['status'] not in ('failed','cancelled','completed','partial'):
                        c.execute("UPDATE jobs SET status='cancelled',lease_token=NULL,lease_until=NULL,detail='Contexto de autorização expirado' WHERE id=?",(cached_job['id'],))
                        c.execute("UPDATE job_attempts SET status='cancelled',finished=? WHERE job_id=? AND status='running'",(time.time(),cached_job['id']))
                        c.execute("UPDATE extraction_runs SET state='cancelled',finished=? WHERE job_id=? AND state='running'",(time.time(),cached_job['id']))
                        event(c,user.get('_actor_id',user['id']),'collection.authorization_revoked',cached_job['id'])
                    c.execute('UPDATE jobs SET extraction_key=NULL WHERE id=?',(cached_job['id'],))
                if c.execute("SELECT count(*) FROM jobs WHERE owner=? AND status IN ('queued','running','waiting_for_user','paused')",(user['id'],)).fetchone()[0]>=100: raise HTTPException(429,'Limite de 100 tarefas pendentes')
                c.execute('INSERT INTO jobs(id,owner,idem,input,status,checkpoint,detail,created,actor_id,delegation_id,extraction_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(jid,user['id'],key,payload,'queued','{}','Links recebidos; acesso e obtenção ainda não executados' if links else 'Aguardando extração',time.time(),user.get('_actor_id',user['id']),user.get('_delegation'),extraction_key))
                seen={}
                for index,url in enumerate(links):
                    item_id=uid();status='received';detail='Recebido; ainda não acessado'
                    if not isinstance(url,str): status='invalid';detail='invalid_url: item deve ser um link textual';url=str(url)[:4096]
                    else:
                        try: safe_fetch.validate_url(url)
                        except safe_fetch.FetchError as exc: status='invalid';detail=exc.code+': '+exc.action
                    duplicate=seen.get(url)
                    if status=='received' and duplicate: status='duplicate_pending';detail='Link repetido nesta lista; resultado será reutilizado'
                    kind=sei_public.input_kind(url) if status=='received' else 'direct_document'
                    c.execute('INSERT INTO link_items(id,job_id,position,url,status,detail,process_id,revision_id,duplicate_of,created,kind,parent_item_id,display_name,metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(item_id,jid,index,url,status,detail,body.input.get('process_id'),None,duplicate,time.time(),kind,None,'','{}'))
                    seen.setdefault(url,item_id)
                event(c,user.get('_actor_id',user['id']),'collection.queued',jid)
        c.execute('INSERT OR IGNORE INTO idempotency_requests VALUES(?,?,?,?)',(user['id'],key,payload,jid))
    return {'job_id':jid,'status_url':f'/v1/collection-jobs/{jid}'}

def authorize_job(c,row,user,permission='read'):
    payload=json.loads(row['input'])
    if payload.get('operation')=='extract_revision': revision_access(c,payload['input']['revision_id'],user,permission)
    elif payload.get('input',{}).get('process_id'): process_access(c,payload['input']['process_id'],user,permission)
    elif row['owner']!=user['id']: raise HTTPException(404)
    # Tarefas sem associação inicial podem descobrir vários processos.
    for item in c.execute('SELECT DISTINCT process_id FROM link_items WHERE job_id=? AND process_id IS NOT NULL',(row['id'],)).fetchall():
        process_access(c,item['process_id'],user,permission)



@app.get('/v1/collection-jobs')
def jobs(user=Depends(identity)):
    result=[]
    with db() as c:
        for row in c.execute('SELECT * FROM jobs ORDER BY created DESC').fetchall():
            try: authorize_job(c,row,user);result.append({**dict(row),'lease_token':None})
            except (HTTPException,KeyError): continue
    return result


@app.get('/v1/collection-jobs/{jid}')
def job_status(jid: str,user=Depends(identity)):
    with db() as c:
        row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not row: raise HTTPException(404)
        authorize_job(c,row,user)
        return {**dict(row),'lease_token':None}


@app.get('/v1/collection-jobs/{jid}/links')
def link_results(jid: str,user=Depends(identity)):
    job_status(jid,user)
    with db() as c: return [dict(r) for r in c.execute('SELECT * FROM link_items WHERE job_id=? ORDER BY position',(jid,))]

@app.get('/v1/collection-jobs/{jid}/attempts')
def attempts(jid: str,user=Depends(identity)):
    job_status(jid,user)
    with db() as c: return [dict(r) for r in c.execute('SELECT * FROM job_attempts WHERE job_id=? ORDER BY number',(jid,))]


@app.post('/v1/collection-jobs/{jid}/cancel')
def cancel(jid: str,user=Depends(identity)):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not row: raise HTTPException(404)
        authorize_job(c,row,user,'operate')
        if row['status'] in ('completed','failed'): raise HTTPException(409,'Tarefa já encerrada')
        if row['status']!='cancelled':
            c.execute("UPDATE jobs SET status='cancelled',lease_token=NULL,lease_until=NULL WHERE id=?",(jid,))
            c.execute("UPDATE job_attempts SET status='cancelled',finished=? WHERE job_id=? AND status='running'",(time.time(),jid))
            c.execute("UPDATE extraction_runs SET state='cancelled',finished=? WHERE job_id=? AND state='running'",(time.time(),jid))
            event(c,user['id'],'collection.cancelled',jid)
    return {'status':'cancelled'}


class ResumeInput(BaseModel):
    process_id: str | None = None
    retry_pending: bool = True


@app.post('/v1/collection-jobs/{jid}/resume',status_code=202)
def resume(jid: str,body: ResumeInput | None=None,user=Depends(identity)):
    body=body or ResumeInput()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not row: raise HTTPException(404)
        authorize_job(c,row,user,'operate')
        payload=json.loads(row['input'])
        if row['status'] not in ('paused','cancelled','waiting_for_user','partial') or row['attempt_count']>=task_queue.MAX_ATTEMPTS:
            raise HTTPException(409,'Retomada não permitida neste estado ou limite atingido')
        if row['delegation_id'] and user.get('kind','human')=='human' and not user.get('_delegation') and user['id']==row['owner']:
            c.execute('UPDATE jobs SET actor_id=?,delegation_id=NULL WHERE id=?',(user['id'],jid))
            event(c,user['id'],'collection.resumed_by_delegating_user',jid)
        elif row['delegation_id']:
            if row['delegation_id']!=user.get('_delegation'): raise HTTPException(403,'Retomada exige a delegação original vigente; crie novo comando se revogada')
            if not authorization.job_authorized(c,dict(row)): raise HTTPException(403,'Delegação não vigente')
        if payload['operation']=='extract_revision':
            if row['status']=='partial': raise HTTPException(409,'Extração nativa já confirmada; OCR indisponível. Use reprocessamento explícito quando necessário')
            revision_access(c,payload['input']['revision_id'],user,'operate')
        else:
            if body.process_id:
                pid=process_access(c,body.process_id,user,'operate')['id']
                old=payload['input'].get('process_id')
                if old and process_access(c,old,user)['id']!=pid: raise HTTPException(409,'Não altere o processo de uma tarefa já vinculada')
                for attached in c.execute('SELECT DISTINCT process_id FROM link_items WHERE job_id=? AND process_id IS NOT NULL',(jid,)).fetchall():
                    if authorization.resolve(c,attached['process_id'])['id']!=pid: raise HTTPException(409,'Não remapeie processos já descobertos; retome sem alterar a associação')
                payload['input']['process_id']=pid
                c.execute('UPDATE link_items SET process_id=? WHERE job_id=? AND revision_id IS NULL',(pid,jid))
            if body.retry_pending:
                for item in c.execute("SELECT * FROM link_items WHERE job_id=? AND status='waiting_for_user' AND revision_id IS NULL",(jid,)).fetchall():
                    metadata=json.loads(item['metadata'] or '{}')
                    if metadata.get('access')=='restricted' or metadata.get('truncated') or metadata.get('task_limit_reached'): continue
                    c.execute("UPDATE link_items SET status='received',detail='Retomada solicitada' WHERE id=?",(item['id'],))
        c.execute("UPDATE jobs SET status='queued',available_at=0,input=?,detail='Retomada solicitada; resultados confirmados preservados' WHERE id=?",(json.dumps(payload,sort_keys=True,separators=(',',':')),jid))
        event(c,user.get('_actor_id',user['id']),'collection.resumed',jid)
    return {'job_id':jid,'status_url':f'/v1/collection-jobs/{jid}'}


@app.post('/v1/collection-jobs/{jid}/links/{item_id}/import',status_code=201)
async def manual_resolution(jid: str,item_id: str,request: Request,name: str,user=Depends(identity)):
    if not name.strip() or len(name)>300: raise HTTPException(422,'Nome inválido')
    with db() as c:
        row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not row: raise HTTPException(404)
        authorize_job(c,row,user,'operate')
        if row['status'] not in ('waiting_for_user','partial','cancelled'): raise HTTPException(409,'Tarefa não está em resolução manual')
        item=c.execute('SELECT * FROM link_items WHERE id=? AND job_id=?',(item_id,jid)).fetchone()
        if not item or not item['process_id']: raise HTTPException(422,'Vincule processo pela retomada antes de importar')
        process_access(c,item['process_id'],user,'operate')
        if item['revision_id']: raise HTTPException(409,'Item já possui resultado confirmado')
    import worker
    raw=await read_upload(request)
    with db() as c:
        total=c.execute("SELECT coalesce(sum(b.size),0) FROM link_items i JOIN revisions r ON r.id=i.revision_id JOIN blobs b ON b.hash=r.blob WHERE i.job_id=? AND i.status IN ('downloaded','already_exists','manual_imported')",(jid,)).fetchone()[0]
    if total+len(raw)>worker.BATCH_QUOTA_BYTES: raise HTTPException(413,'Limite de originais confirmados por tarefa')
    blob=put_blob(raw,name)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone();authorize_job(c,row,user,'operate')
        if row['status'] not in ('waiting_for_user','partial','cancelled'): raise HTTPException(409,'Estado alterado; aguarde resolução')
        item=c.execute('SELECT * FROM link_items WHERE id=? AND job_id=?',(item_id,jid)).fetchone()
        if item['revision_id']: raise HTTPException(409,'Item já resolvido')
        total=c.execute("SELECT coalesce(sum(b.size),0) FROM link_items i JOIN revisions r ON r.id=i.revision_id JOIN blobs b ON b.hash=r.blob WHERE i.job_id=? AND i.status IN ('downloaded','already_exists','manual_imported')",(jid,)).fetchone()[0]
        if total+blob[2]>worker.BATCH_QUOTA_BYTES: raise HTTPException(413,'Limite de originais confirmados por tarefa')
        metadata=json.loads(item['metadata'] or '{}')
        external_key=metadata.get('document_number')
        logical_name=(str(external_key)+' — '+name)[:300] if external_key and not name.startswith(str(external_key)) else name
        result=persist_document(c,item['process_id'],logical_name,item['url'],user,blob,from_link=True,original_name=name,external_key=external_key)
        c.execute("UPDATE link_items SET status='manual_imported',revision_id=?,detail='Importado manualmente com origem preservada' WHERE id=?",(result['revision_id'],item_id))
        event(c,user.get('_actor_id',user['id']),'collection.item.manual_imported',item_id)
        import worker
        checkpoint=worker.link_summary(c,jid)
        remaining=c.execute("SELECT count(*) FROM link_items WHERE job_id=? AND revision_id IS NULL AND status NOT IN ('process_discovered','duplicate')",(jid,)).fetchone()[0]
        c.execute('UPDATE jobs SET checkpoint=?,status=?,detail=? WHERE id=?',(json.dumps(checkpoint),'completed' if not remaining else row['status'],'Todos os itens resolvidos por obtenção/importação' if not remaining else 'Importação registrada; outras pendências preservadas',jid))
        if not remaining: event(c,user.get('_actor_id',user['id']),'collection.completed',jid)
        return result

@app.get('/v1/capabilities')
def capabilities(user=Depends(identity)):
    return {'manual_import':sorted(archive_policy.MIMES),'native_extraction':True,'external_collection':True,'external_homologated':False,'link_input':True,'link_lists':True,'public_sei_process_pages':True,'public_sei_document_discovery':True,'portal_search':False,'direct_download_formats':sorted(archive_policy.MIMES),'access_control':['read','operate','review','admin'],'technical_library':True,'taxonomy_version':'seed-2026-10','taxonomy_approved':False,'groups':True,'service_accounts':True,'delegation':True,'ocr':ocr_optional.capability(),'spatial_search':True,'spatial_formats':['kml','kmz','shp','shapefile_zip','geojson','json','gpx'],'spatial_srs':['EPSG:4326'],'process_analysis_dashboard':True,'knowledge_assertions':True,'knowledge_human_validation':True,'automatic_facts':False,'ai':False,'admin':user['role']=='admin' and not user.get('_delegation') and user.get('kind','human')=='human','storage':'sqlite-local','durable_queue':True,'async_extraction':True,'version':'0.7.0'}

@app.get('/v1/me')
def me(user=Depends(identity)):
    return {k:v for k,v in user.items() if k in ('id','name','role','kind','_actor_id','_delegation')}


@app.get('/_app/health')
def health():
    return {'status':'ok','version':'0.7.0','demo_mode':DEMO_MODE,'embedded_worker':EMBEDDED_WORKER}


@app.post('/v1/demo-session')
def demo_session():
    if not DEMO_MODE: raise HTTPException(404,'Demonstração não habilitada')
    return {'access_token':demo_mode.issue_session(db),'mode':'construction','notice':'Sessão de construção com dados efêmeros; somente descoberta pública SEI está habilitada.'}


@app.get('/manus-routes.json')
def manus_routes():
    return FileResponse(Path(__file__).with_name('manus-routes.json'),media_type='application/json')


@app.get('/assets/{name}')
def assets(name: str):
    allowed={'ui.js': 'text/javascript', 'bridge_ui.js':'text/javascript', 'bridge.css':'text/css', 'advanced_ui.js': 'text/javascript', 'public_sei_ui.js': 'text/javascript', 'analysis_ui.js': 'text/javascript', 'styles.css': 'text/css', 'group-arqueo-logo.png': 'image/png'}
    if name not in allowed: raise HTTPException(404)
    return FileResponse(Path(__file__).with_name(name),media_type=allowed[name])


@app.middleware('http')
async def demo_read_only(request: Request,call_next):
    """A sessão pública de construção só pode iniciar/retomar coleta pública controlada."""
    path=request.url.path
    safe_demo_request=request.method in ('GET','HEAD','OPTIONS') or (request.method=='DELETE' and path=='/v1/sessions') or (request.method=='POST' and (path in ('/v1/search','/v1/spatial-search','/v1/collection-jobs') or (path.startswith('/v1/collection-jobs/') and path.endswith('/resume'))))
    if DEMO_MODE and not safe_demo_request:
        header=request.headers.get('Authorization','')
        if header.startswith('Bearer '):
            token=hashlib.sha256(header[7:].encode()).hexdigest()
            with db() as c:
                row=c.execute('SELECT user_id FROM sessions WHERE token=? AND expires>?',(token,time.time())).fetchone()
            if row and row['user_id']==demo_mode.DEMO_USER_ID:
                return JSONResponse(status_code=403,content={'detail':'Demonstração pública disponível somente para leitura'})
    return await call_next(request)


embedded_worker_stop=threading.Event()
embedded_worker_thread=None

@app.on_event('startup')
def start_embedded_worker():
    """Executa a fila somente em containers de construção explicitamente habilitados."""
    global embedded_worker_thread
    if not EMBEDDED_WORKER or embedded_worker_thread:
        return
    def loop():
        import worker
        worker_id='embedded-'+uid()
        while not embedded_worker_stop.is_set():
            try:
                if not worker.run_once(worker_id):
                    embedded_worker_stop.wait(0.5)
            except Exception:
                if embedded_worker_stop.wait(1):
                    break
    embedded_worker_thread=threading.Thread(target=loop,name='coletor-embedded-worker',daemon=True)
    embedded_worker_thread.start()

@app.on_event('shutdown')
def stop_embedded_worker():
    embedded_worker_stop.set()


@app.middleware('http')
async def response_policy(request: Request,call_next):
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    if not ALLOW_EMBED: response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Cache-Control']='no-store'
    if request.url.path=='/':
        policy="default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'self'; form-action 'self'"
        response.headers['Content-Security-Policy']=policy if ALLOW_EMBED else policy+"; frame-ancestors 'none'"
    return response

@app.get('/',response_class=HTMLResponse)
def ui():
    page = Path(__file__).with_name('bridge.html').read_text(encoding='utf-8')
    if DEMO_MODE:
        replacements = {
            '{{LOGIN_LABEL}}': 'AMBIENTE DE CONSTRUÇÃO',
            '{{LOGIN_MESSAGE}}': 'Esta versão está aberta para avaliação visual e funcional, sem exigir senha.',
            '{{CREDENTIAL_LOGIN_HIDDEN}}': 'hidden',
            '{{DEMO_ACCESS_HIDDEN}}': '',
            '{{LOGIN_FOOTER}}': 'Para o ambiente operacional, a autenticação e as permissões continuam obrigatórias.',
        }
    else:
        replacements = {
            '{{LOGIN_LABEL}}': 'ACESSO AO ACERVO',
            '{{LOGIN_MESSAGE}}': 'Entre para consultar o repositório e acompanhar o trabalho da sua equipe.',
            '{{CREDENTIAL_LOGIN_HIDDEN}}': '',
            '{{DEMO_ACCESS_HIDDEN}}': 'hidden',
            '{{LOGIN_FOOTER}}': 'Credenciais definidas pelo administrador. Nenhuma senha padrão.',
        }
    for marker, value in replacements.items():
        page = page.replace(marker, value)
    return HTMLResponse(page)

import sys
import bridge_routes
bridge_routes.register(sys.modules[__name__])
import market_routes
market_routes.register(sys.modules[__name__])

import access_routes
import catalog_routes
import advanced_routes
catalog_routes.register(app,db,event,identity,uid,revision_access,job_status,authorize_job)
access_routes.register(app,db,event,identity,platform_admin,uid,password_hash)
advanced_routes.register(app,db,identity,uid,event,process_access,revision_access)

def documented_openapi():
    if app.openapi_schema: return app.openapi_schema
    from fastapi.openapi.utils import get_openapi
    schema=get_openapi(title=app.title,version=app.version,routes=app.routes)
    schema.setdefault('components',{})['securitySchemes']={
        'BearerAuth':{'type':'http','scheme':'bearer','description':'Token de usuário ou serviço; delegação exige X-Delegation-Id emitido pelo servidor.'}
    }
    for path,operations in schema['paths'].items():
        for method,operation in operations.items():
            if method not in ('get','post','put','patch','delete'): continue
            public=path in ('/','/_app/health','/assets/{name}','/manus-routes.json') or (path in ('/v1/sessions','/v1/demo-session') and method=='post')
            operation['security']=[] if public else [{'BearerAuth':[]}]
            if not public:
                operation.setdefault('parameters',[]).append({'name':'X-Delegation-Id','in':'header','required':False,'schema':{'type':'string'},'description':'Delegação vigente do usuário para a conta de serviço autenticada; não concede escopos extras.'})
    command=schema['paths']['/v1/collection-jobs']['post']
    command.setdefault('parameters',[]).append({'name':'Idempotency-Key','in':'header','required':True,'schema':{'type':'string','minLength':1,'maxLength':200},'description':'Mesma chave/parâmetros retorna o mesmo job; alteração retorna 409.'})
    command['description']='Recebe de 1 a 50 links explícitos, incluindo páginas públicas SEI/IPHAN já fornecidas, ou solicita extração. A página SEI pode revelar apenas seus links de documentos públicos; não há pesquisa por número, login ou CAPTCHA. 202 não confirma obtenção. Consulte status_url e /links.'
    app.openapi_schema=schema
    return schema

app.openapi=documented_openapi

if __name__=='__main__':
    import getpass
    name=input('Administrador: '); password=getpass.getpass('Senha (mínimo 12 caracteres): ')
    if len(password)<12: raise SystemExit('Senha muito curta')
    with db() as c: c.execute('INSERT INTO users(id,name,password,role) VALUES(?,?,?,?)',(uid(),name,password_hash(password),'admin'))
