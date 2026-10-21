"""Microsoft Graph v1.0: destino por link e autenticação device-code delegada.

Nenhuma credencial é recebida pelo frontend. Cache de tokens criptografado.
Não segue redirects com Bearer e não faz chamadas externas na importação.
"""
import base64
import hashlib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
import httpx
from cryptography.fernet import Fernet, InvalidToken
import archive_policy

DEFAULT_FOLDER='https://arqueogis.sharepoint.com/:f:/s/ATENA/IgAiQ-amW5ZLQJfYiaoyBy11ATZa4qtZe8iPjpKGQoGpb0E?e=rrWu6g'
SCOPES='https://graph.microsoft.com/Files.ReadWrite offline_access'
GRAPH='https://graph.microsoft.com/v1.0'
LOCK=threading.RLock()

class CloudError(Exception):
    def __init__(self,code,status=503): self.code=code; self.status=status; super().__init__(code)

def migrate(db):
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS bridge_settings(id INTEGER PRIMARY KEY CHECK(id=1),folder_url TEXT NOT NULL,drive_id TEXT,folder_id TEXT,web_url TEXT,checked REAL);
        CREATE TABLE IF NOT EXISTS bridge_credentials(id INTEGER PRIMARY KEY CHECK(id=1),ciphertext TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS bridge_auth(id TEXT PRIMARY KEY,owner TEXT NOT NULL,encrypted TEXT NOT NULL,expires REAL NOT NULL,next_poll REAL NOT NULL,interval INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS archive_labels(document_id TEXT PRIMARY KEY REFERENCES documents(id),category TEXT NOT NULL,method TEXT NOT NULL,actor TEXT,updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS archive_label_history(id TEXT PRIMARY KEY,document_id TEXT NOT NULL REFERENCES documents(id),category TEXT NOT NULL,method TEXT NOT NULL,actor TEXT,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS source_snapshots(id TEXT PRIMARY KEY,process_id TEXT REFERENCES processes(id),source_url TEXT NOT NULL,blob TEXT NOT NULL REFERENCES blobs(hash),created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS document_keys(process_id TEXT REFERENCES processes(id),external_key TEXT,document_id TEXT REFERENCES documents(id),PRIMARY KEY(process_id,external_key));
        CREATE TABLE IF NOT EXISTS cloud_transfers(id TEXT PRIMARY KEY,revision_id TEXT NOT NULL REFERENCES revisions(id),destination TEXT NOT NULL,category TEXT NOT NULL,owner TEXT NOT NULL,actor_id TEXT,delegation_id TEXT,status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,available REAL NOT NULL DEFAULT 0,lease TEXT,lease_until REAL,item_id TEXT,web_url TEXT,remote_path TEXT,error TEXT,created REAL NOT NULL,updated REAL NOT NULL,UNIQUE(revision_id,destination));
        CREATE INDEX IF NOT EXISTS cloud_ready ON cloud_transfers(status,available,lease_until);
        ''')
        c.execute('INSERT OR IGNORE INTO bridge_settings(id,folder_url) VALUES(1,?)',(os.getenv('SHAREPOINT_FOLDER_URL',DEFAULT_FOLDER),))

def vault(root):
    key=os.getenv('COLLECTOR_TOKEN_KEY')
    path=Path(root)/'token.key'
    if not key:
        try:
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as f: f.write(Fernet.generate_key())
        except FileExistsError: pass
        key=path.read_bytes()
    try: return Fernet(key)
    except (ValueError,TypeError): raise CloudError('invalid_token_encryption_key',422)

def app_ids():
    tenant=os.getenv('MICROSOFT_TENANT_ID','')
    client=os.getenv('MICROSOFT_CLIENT_ID','')
    if not re.fullmatch(r'[a-zA-Z0-9.-]{1,255}',tenant) or not re.fullmatch(r'[a-fA-F0-9-]{36}',client):
        raise CloudError('microsoft_app_not_configured',409)
    return tenant,client

def validate_folder(value):
    try:
        u=urlsplit(value)
        port=u.port
    except ValueError: raise CloudError('invalid_sharepoint_folder',422)
    hosts={x.strip().lower() for x in os.getenv('SHAREPOINT_ALLOWED_HOSTS','arqueogis.sharepoint.com').split(',') if x.strip()}
    if u.scheme!='https' or u.hostname not in hosts or u.username or u.password or port not in (None,443) or u.fragment or len(value)>4096 or any(ord(x)<33 for x in value):
        raise CloudError('invalid_sharepoint_folder',422)
    return value

def oauth(endpoint,values):
    tenant,_=app_ids()
    try:
        with httpx.Client(timeout=25,follow_redirects=False) as client:
            response=client.post(f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/{endpoint}',data=values)
        result=response.json()
    except (httpx.HTTPError,ValueError): raise CloudError('microsoft_network_error')
    if 'error' in result:
        code=result['error']
        if not re.fullmatch(r'[a-z_]{1,80}',str(code)): code='oauth_error'
        raise CloudError(code,409)
    if response.status_code!=200: raise CloudError('oauth_unavailable')
    return result

def start_auth(db,root,owner):
    _,client=app_ids()
    result=oauth('devicecode',{'client_id':client,'scope':SCOPES})
    auth_id=secrets.token_urlsafe(24); interval=max(5,int(result.get('interval',5)))
    with db() as c:
        c.execute('DELETE FROM bridge_auth WHERE owner=? OR expires<?',(owner,time.time()))
        c.execute('INSERT INTO bridge_auth VALUES(?,?,?,?,?,?)',(auth_id,owner,vault(root).encrypt(result['device_code'].encode()).decode(),time.time()+int(result['expires_in']),time.time()+interval,interval))
    # URI oficial, não conteúdo remoto arbitrário navegável no frontend.
    return {'id':auth_id,'user_code':result['user_code'],'verification_uri':'https://microsoft.com/devicelogin','interval':interval,'expires_in':result['expires_in']}

def poll_auth(db,root,owner,auth_id):
    with LOCK:
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM bridge_auth WHERE id=? AND owner=?',(auth_id,owner)).fetchone()
            if not row or row['expires']<=time.time(): raise CloudError('authentication_expired',409)
            if row['next_poll']>time.time(): return {'status':'pending','interval':row['interval']}
            c.execute('UPDATE bridge_auth SET next_poll=? WHERE id=?',(time.time()+row['interval'],auth_id))
        _,client=app_ids()
        try:
            result=oauth('token',{'client_id':client,'grant_type':'urn:ietf:params:oauth:grant-type:device_code','device_code':vault(root).decrypt(row['encrypted'].encode()).decode()})
        except CloudError as e:
            if e.code in ('authorization_pending','slow_down'):
                interval=row['interval']+(5 if e.code=='slow_down' else 0)
                with db() as c: c.execute('UPDATE bridge_auth SET interval=?,next_poll=? WHERE id=?',(interval,time.time()+interval,auth_id))
                return {'status':'pending','interval':interval}
            raise
        save_tokens(db,root,result)
        with db() as c: c.execute('DELETE FROM bridge_auth WHERE id=?',(auth_id,))
        return {'status':'connected'}

def save_tokens(db,root,result):
    if not result.get('access_token'): raise CloudError('invalid_token_response')
    result={k:v for k,v in result.items() if k in ('access_token','refresh_token','scope','expires_in')}
    result['expires_at']=time.time()+int(result.get('expires_in',3600))-90
    encrypted=vault(root).encrypt(json.dumps(result).encode()).decode()
    with db() as c: c.execute('INSERT OR REPLACE INTO bridge_credentials VALUES(1,?)',(encrypted,))

def access_token(db,root):
    with LOCK:
        with db() as c: row=c.execute('SELECT ciphertext FROM bridge_credentials WHERE id=1').fetchone()
        if not row: raise CloudError('sharepoint_not_connected',409)
        try: cached=json.loads(vault(root).decrypt(row['ciphertext'].encode()))
        except (InvalidToken,ValueError): raise CloudError('token_cache_unreadable',409)
        if cached.get('expires_at',0)>time.time(): return cached['access_token']
        if not cached.get('refresh_token'): raise CloudError('reauthentication_required',409)
        _,client=app_ids()
        result=oauth('token',{'client_id':client,'grant_type':'refresh_token','refresh_token':cached['refresh_token'],'scope':SCOPES})
        result.setdefault('refresh_token',cached['refresh_token'])
        save_tokens(db,root,result)
        return result['access_token']

class Graph:
    def __init__(self,db,root): self.db=db;self.root=root
    def request(self,method,path,body=None,content=None,guard=lambda:None):
        if not path.startswith('/') or path.startswith('//'): raise CloudError('invalid_graph_path',422)
        guard(); token=access_token(self.db,self.root)
        try:
            with httpx.Client(timeout=45,follow_redirects=False) as client:
                response=client.request(method,GRAPH+path,headers={'Authorization':'Bearer '+token,'Content-Type':'application/octet-stream' if content is not None else 'application/json'},json=body,content=content)
        except httpx.HTTPError: raise CloudError('graph_network_error')
        guard()
        if response.status_code not in (200,201,204):
            codes={401:'reauthentication_required',403:'sharepoint_access_denied',404:'sharepoint_item_not_found',409:'sharepoint_conflict',429:'sharepoint_rate_limited'}
            raise CloudError(codes.get(response.status_code,'graph_unavailable'),response.status_code)
        return response.json() if response.content else {}
    def resolve(self,url):
        encoded='u!'+base64.urlsafe_b64encode(validate_folder(url).encode()).decode().rstrip('=')
        result=self.request('GET','/shares/'+encoded+'/driveItem')
        item=result.get('remoteItem') or result
        if 'folder' not in item: raise CloudError('destination_must_be_folder',422)
        drive=item.get('parentReference',{}).get('driveId')
        if not drive or not item.get('id'): raise CloudError('invalid_folder_response')
        return {'drive_id':drive,'folder_id':item['id'],'web_url':item.get('webUrl',''),'name':item.get('name','')}
    def ensure_folder(self,drive,parent,name,guard=lambda:None):
        base='/drives/'+quote(drive,safe='')+'/items/'+quote(parent,safe='')
        try:
            item=self.request('GET',base+':/'+quote(name,safe=''),guard=guard)
            if 'folder' not in item: raise CloudError('folder_name_is_file',409)
            return item['id']
        except CloudError as e:
            if e.status!=404: raise
        try: return self.request('POST',base+'/children',{'name':name,'folder':{},'@microsoft.graph.conflictBehavior':'fail'},guard=guard)['id']
        except CloudError as e:
            if e.status!=409: raise
            return self.request('GET',base+':/'+quote(name,safe=''),guard=guard)['id']
    def put(self,drive,parent,name,raw,guard=lambda:None):
        # Máximo 128 MiB no Coletor, inferior ao limite de 250 MB desta API.
        return self.request('PUT','/drives/'+quote(drive,safe='')+'/items/'+quote(parent,safe='')+':/'+quote(name,safe='')+':/content',content=raw,guard=guard)
    def verify(self,drive,item_id,raw,guard=lambda:None):
        # DownloadURL pré-autorizada só nasce de Graph autenticado. Nunca recebe Bearer.
        item=self.request('GET','/drives/'+quote(drive,safe='')+'/items/'+quote(item_id,safe=''),guard=guard)
        link=item.get('@microsoft.graph.downloadUrl',''); u=urlsplit(link)
        if u.scheme!='https' or not (u.hostname or '').endswith('.sharepoint.com') or u.username or u.password or u.port not in (None,443): raise CloudError('invalid_verification_url')
        digest=hashlib.sha256();size=0
        try:
            with httpx.Client(timeout=45,follow_redirects=False) as client:
                with client.stream('GET',link) as r:
                    if r.status_code!=200: raise CloudError('remote_verification_failed')
                    for chunk in r.iter_bytes(65536):
                        guard();size+=len(chunk)
                        if size>len(raw): raise CloudError('remote_integrity_mismatch')
                        digest.update(chunk)
        except httpx.HTTPError: raise CloudError('remote_verification_failed')
        if size!=len(raw) or digest.hexdigest()!=hashlib.sha256(raw).hexdigest(): raise CloudError('remote_integrity_mismatch')
        return item

def configuration(db):
    with db() as c: return dict(c.execute('SELECT * FROM bridge_settings WHERE id=1').fetchone())

def queue_revision(c,revision_id,user,category,uid):
    target=c.execute('SELECT * FROM bridge_settings WHERE id=1').fetchone()
    destination=hashlib.sha256(target['folder_url'].encode()).hexdigest()
    stamp=time.time()
    c.execute('INSERT OR IGNORE INTO cloud_transfers(id,revision_id,destination,category,owner,actor_id,delegation_id,status,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)',(uid(),revision_id,destination,category,user['id'],user.get('_actor_id',user['id']),user.get('_delegation'),'queued',stamp,stamp))

def sync_once(app):
    import authorization
    now=time.time();lease=secrets.token_hex(24)
    target=configuration(app.db); dest=hashlib.sha256(target['folder_url'].encode()).hexdigest()
    if not target.get('drive_id') or not target.get('checked'): return False
    with app.db() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute("UPDATE cloud_transfers SET status='queued',lease=NULL WHERE status='uploading' AND lease_until<?",(now,))
        row=c.execute("SELECT * FROM cloud_transfers WHERE destination=? AND status='queued' AND available<=? AND attempts<5 ORDER BY created LIMIT 1",(dest,now)).fetchone()
        if not row: return False
        row=dict(row)
        c.execute("UPDATE cloud_transfers SET status='uploading',lease=?,lease_until=?,attempts=attempts+1,updated=? WHERE id=?",(lease,now+180,now,row['id']))
    def guard():
        with app.db() as c:
            held=c.execute("SELECT 1 FROM cloud_transfers WHERE id=? AND status='uploading' AND lease=? AND lease_until>?",(row['id'],lease,time.time())).fetchone()
            if not held: raise CloudError('transfer_lease_lost',409)
            if configuration(app.db)['folder_url']!=target['folder_url']: raise CloudError('destination_changed',409)
            owner=c.execute('SELECT * FROM users WHERE id=? AND active=1',(row['owner'],)).fetchone()
            if not owner: raise CloudError('transfer_authorization_revoked',403)
            user=dict(owner)
            if row['delegation_id']: user.update(_delegation=row['delegation_id'],_actor_id=row['actor_id'])
            try: app.revision_access(c,row['revision_id'],user,'operate')
            except Exception: raise CloudError('transfer_authorization_revoked',403)
            if user['kind']=='service' and not c.execute('SELECT 1 FROM service_tokens WHERE user_id=? AND active=1 AND expires>?',(user['id'],time.time())).fetchone(): raise CloudError('transfer_authorization_revoked',403)
            c.execute('UPDATE cloud_transfers SET lease_until=? WHERE id=? AND lease=?',(time.time()+180,row['id'],lease))
    try:
        guard()
        with app.db() as c:
            r=c.execute('SELECT r.*,d.name,d.process_id,p.number FROM revisions r JOIN documents d ON d.id=r.document_id JOIN processes p ON p.id=d.process_id WHERE r.id=?',(row['revision_id'],)).fetchone()
        raw=(app.ROOT/'blobs'/r['blob']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=r['blob']: raise CloudError('local_integrity_mismatch')
        graph=Graph(app.db,app.ROOT);parent=target['folder_id']
        folders=archive_policy.relative_folder(r['number'],row['category']).split('/')
        for folder in folders: parent=graph.ensure_folder(target['drive_id'],parent,folder,guard)
        ext=Path(r['name']).suffix
        stem=r['name'][:-len(ext)] if ext else r['name']
        filename=archive_policy.safe_name(stem,125)+'__'+r['id']+ext[:15]
        if row.get('item_id'):
            result=graph.request('PATCH','/drives/'+quote(target['drive_id'],safe='')+'/items/'+quote(row['item_id'],safe=''),{'parentReference':{'id':parent},'name':filename},guard=guard)
        else:
            result=graph.put(target['drive_id'],parent,filename,raw,guard)
        if not result.get('id') or result.get('size')!=len(raw): raise CloudError('remote_size_mismatch')
        graph.verify(target['drive_id'],result['id'],raw,guard)
        guard()
        with app.db() as c:
            c.execute('BEGIN IMMEDIATE')
            updated=c.execute("UPDATE cloud_transfers SET status='uploaded',item_id=?,web_url=?,remote_path=?,error=NULL,lease=NULL,updated=? WHERE id=? AND lease=?",(result['id'],result.get('webUrl',''),'/'.join(folders+[filename]),time.time(),row['id'],lease))
            if updated.rowcount: app.event(c,row['actor_id'],'sharepoint.transfer.verified',row['id'])
    except (CloudError,OSError) as e:
        code=e.code if isinstance(e,CloudError) else 'local_file_missing'
        auth_errors={'sharepoint_not_connected','reauthentication_required','invalid_grant','token_cache_unreadable','microsoft_app_not_configured'}
        state='waiting_for_connection' if code in auth_errors else 'cancelled' if code in ('transfer_authorization_revoked','destination_changed') else 'failed' if row['attempts']>=4 else 'queued'
        with app.db() as c:
            c.execute('UPDATE cloud_transfers SET status=?,error=?,available=?,lease=NULL,updated=? WHERE id=? AND lease=?',(state,code,time.time()+min(300,2**(row['attempts']+2)),time.time(),row['id'],lease))
    except Exception:
        with app.db() as c: c.execute("UPDATE cloud_transfers SET status='failed',error='unexpected_transfer_error',lease=NULL,updated=? WHERE id=? AND lease=?",(time.time(),row['id'],lease))
    return True
