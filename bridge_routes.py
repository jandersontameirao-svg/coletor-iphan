"""Interface de ponte e biblioteca de originais; consumidores seguem a mesma ACL."""
import hashlib
import io
import json
import time
from pathlib import Path
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
import archive_policy as policy
import sharepoint_store as cloud
import ai_classifier as ai
import document_extractors as extractors
import ocr_optional


def _document_text(raw, mime, path):
    """Texto determinístico para a IA ler; PDF tenta pypdf e depois OCR opcional."""
    if mime == 'application/pdf':
        text = ''
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(raw))
            text = '\n'.join((page.extract_text() or '') for page in reader.pages[:40])
        except Exception:
            text = ''
        if not text.strip() and ocr_optional.capability()['available']:
            try:
                text = '\n'.join(page for _, page in ocr_optional.extract_pdf(path))
            except Exception:
                text = ''
        return text
    try:
        return extractors.extract(raw, mime)
    except ValueError:
        return ''

class Destination(BaseModel):
    folder_url: str = Field(min_length=1,max_length=4096)
class Label(BaseModel):
    category: str
class AuthPoll(BaseModel):
    id: str

def register(appmod):
    a=appmod;app=a.app
    cloud.migrate(a.db)
    def admin(user):
        a.platform_admin(user)
        if a.DEMO_MODE: raise HTTPException(403,'Conexão externa indisponível no modo demonstrativo')
    def translate(fn,*args):
        try: return fn(*args)
        except cloud.CloudError as e: raise HTTPException(e.status if e.status in (401,403,404,409,422,429) else 503, e.code)

    @app.get('/v1/bridge/library')
    def library(process_id: str|None=None,category: str|None=None,format: str|None=None,text: str='',limit: int=100,offset: int=0,user=Depends(a.identity)):
        if limit<1 or limit>200 or offset<0: raise HTTPException(422,'Paginação inválida')
        target=cloud.configuration(a.db); dest=hashlib.sha256(target['folder_url'].encode()).hexdigest()
        result=[]
        with a.db() as c:
            for row in c.execute('SELECT r.id AS revision_id,r.blob AS sha256,r.created,d.id AS document_id,d.name,d.process_id,p.number,p.title,b.mime,b.size,l.category,l.method FROM documents d JOIN processes p ON p.id=d.process_id JOIN revisions r ON r.document_id=d.id JOIN blobs b ON b.hash=r.blob LEFT JOIN archive_labels l ON l.document_id=d.id WHERE r.rowid=(SELECT max(x.rowid) FROM revisions x WHERE x.document_id=d.id) ORDER BY p.number,d.name').fetchall():
                try: pid=a.process_access(c,row['process_id'],user)['id']
                except HTTPException: continue
                if process_id and pid!=process_id: continue
                item=dict(row); item['category']=item['category'] or 'A classificar'
                if category and item['category']!=category: continue
                if format and Path(item['name']).suffix.lower()!=format.lower(): continue
                if text and text.casefold() not in (item['name']+' '+item['number']+' '+item['title']).casefold(): continue
                transfer=c.execute('SELECT id,status,category,web_url,remote_path,error FROM cloud_transfers WHERE revision_id=? AND destination=?',(item['revision_id'],dest)).fetchone()
                item['sharepoint']=dict(transfer) if transfer else {'status':'not_queued'}
                item['folder']=policy.relative_folder(item['number'],item['category'])
                item['download_url']='/v1/document-revisions/'+item['revision_id']+'/download'
                item['permissions']=[permission for permission in ('read','operate','review','admin') if _has(a,c,pid,user,permission)]
                item['occurrences']=[dict(x) for x in c.execute('SELECT source,name,created FROM occurrences WHERE revision_id=? ORDER BY created',(item['revision_id'],))]
                result.append(item)
        return {'items':result[offset:offset+limit],'total':len(result),'limit':limit,'offset':offset,'categories':['Georreferenciados',*policy.STUDIES]}

    @app.patch('/v1/bridge/documents/{did}/category')
    def classify(did: str,body: Label,user=Depends(a.identity)):
        if body.category not in ('Georreferenciados',*policy.STUDIES): raise HTTPException(422,'Categoria inválida')
        with a.db() as c:
            c.execute('BEGIN IMMEDIATE')
            d=c.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone()
            if not d: raise HTTPException(404)
            a.process_access(c,d['process_id'],user,'review')
            if c.execute("SELECT 1 FROM cloud_transfers t JOIN revisions r ON r.id=t.revision_id WHERE r.document_id=? AND t.status='uploading'",(did,)).fetchone(): raise HTTPException(409,'Aguarde a transferência em andamento')
            stamp=time.time()
            c.execute('INSERT OR REPLACE INTO archive_labels VALUES(?,?,?,?,?)',(did,body.category,'human_review',user['id'],stamp))
            c.execute('INSERT INTO archive_label_history VALUES(?,?,?,?,?,?)',(a.uid(),did,body.category,'human_review',user['id'],stamp))
            # Upload confirmado permanece no local histórico até mover explicitamente.
            c.execute("UPDATE cloud_transfers SET category=? WHERE revision_id IN (SELECT id FROM revisions WHERE document_id=?) AND status IN ('queued','waiting_for_connection','failed')",(body.category,did))
            a.event(c,user.get('_actor_id',user['id']),'archive.category.reviewed',did)
        return {'document_id':did,'category':body.category,'notice':'Classificação atualizada; arquivos já enviados preservam o caminho histórico. Use mover para reorganizá-los.'}

    @app.get('/v1/bridge/ai')
    def ai_status(user=Depends(a.identity)):
        return ai.capability()

    @app.post('/v1/bridge/documents/{did}/ai-suggest-category')
    def ai_suggest(did: str,user=Depends(a.identity)):
        if not ai.available(): raise HTTPException(503,'IA não configurada: defina OPENAI_API_KEY no servidor')
        with a.db() as c:
            d=c.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone()
            if not d: raise HTTPException(404)
            a.process_access(c,d['process_id'],user,'review')
            r=c.execute('SELECT r.id,r.blob,d.name,p.title,b.mime FROM revisions r JOIN documents d ON d.id=r.document_id JOIN processes p ON p.id=d.process_id JOIN blobs b ON b.hash=r.blob WHERE r.document_id=? ORDER BY r.rowid DESC LIMIT 1',(did,)).fetchone()
            if not r: raise HTTPException(404,'Documento sem revisão')
        path=a.ROOT/'blobs'/r['blob']
        try: raw=path.read_bytes()
        except OSError: raise HTTPException(404,'Original indisponível no cache')
        text=_document_text(raw,r['mime'],path)
        if not (text or '').strip():
            raise HTTPException(422,'Sem texto extraível para a IA analisar (ex.: PDF escaneado sem OCR instalado).')
        try: result=ai.suggest_category(text,name=r['name'],title=r['title'])
        except ai.AIError as e: raise HTTPException(502,str(e))
        with a.db() as c:
            a.event(c,user.get('_actor_id',user['id']),'archive.category.ai_suggested',did)
        return {'document_id':did,**result}

    @app.post('/v1/bridge/documents/{did}/move',status_code=202)
    def move(did: str,user=Depends(a.identity)):
        if a.DEMO_MODE: raise HTTPException(403,'Envio indisponível na demonstração')
        with a.db() as c:
            c.execute('BEGIN IMMEDIATE')
            d=c.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone()
            if not d: raise HTTPException(404)
            a.process_access(c,d['process_id'],user,'operate')
            label=c.execute('SELECT category FROM archive_labels WHERE document_id=?',(did,)).fetchone()
            if not label: raise HTTPException(409,'Classifique o documento antes de mover')
            changed=c.execute("UPDATE cloud_transfers SET category=?,status='queued',attempts=0,available=0,owner=?,actor_id=?,delegation_id=? WHERE revision_id IN (SELECT id FROM revisions WHERE document_id=?) AND status='uploaded' AND category!=?",(label['category'],user['id'],user.get('_actor_id',user['id']),user.get('_delegation'),did,label['category'])).rowcount
            a.event(c,user.get('_actor_id',user['id']),'sharepoint.move.queued',did)
        return {'status':'queued','transfers':changed}

    @app.post('/v1/bridge/revisions/{rid}/transfer',status_code=202)
    def queue(rid: str,user=Depends(a.identity)):
        if a.DEMO_MODE: raise HTTPException(403,'Envio indisponível no modo demonstrativo')
        with a.db() as c:
            c.execute('BEGIN IMMEDIATE');r=a.revision_access(c,rid,user,'operate')
            label=c.execute('SELECT category FROM archive_labels WHERE document_id=?',(r['document_id'],)).fetchone()
            cloud.queue_revision(c,rid,user,label['category'] if label else 'A classificar',a.uid)
            a.event(c,user.get('_actor_id',user['id']),'sharepoint.transfer.queued',rid)
        return {'status':'queued'}

    @app.get('/v1/bridge/transfers')
    def transfers(user=Depends(a.identity)):
        result=[]
        with a.db() as c:
            for row in c.execute('SELECT t.*,d.name,p.number FROM cloud_transfers t JOIN revisions r ON r.id=t.revision_id JOIN documents d ON d.id=r.document_id JOIN processes p ON p.id=d.process_id ORDER BY t.created DESC').fetchall():
                try: a.revision_access(c,row['revision_id'],user)
                except HTTPException: continue
                item=dict(row)
                for key in ('lease','actor_id','delegation_id'): item.pop(key,None)
                result.append(item)
        return result

    @app.post('/v1/bridge/transfers/{tid}/retry',status_code=202)
    def retry(tid: str,user=Depends(a.identity)):
        with a.db() as c:
            c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM cloud_transfers WHERE id=?',(tid,)).fetchone()
            if not row: raise HTTPException(404)
            a.revision_access(c,row['revision_id'],user,'operate')
            if row['status'] in ('uploaded','uploading'): raise HTTPException(409,'Envio já confirmado ou em andamento')
            c.execute("UPDATE cloud_transfers SET status='queued',attempts=0,available=0,error=NULL,owner=?,actor_id=?,delegation_id=? WHERE id=?",(user['id'],user.get('_actor_id',user['id']),user.get('_delegation'),tid))
            a.event(c,user.get('_actor_id',user['id']),'sharepoint.transfer.retry',tid)
        return {'status':'queued'}

    @app.get('/v1/bridge/sharepoint')
    def settings(user=Depends(a.identity)):
        a.platform_admin(user);cfg=cloud.configuration(a.db)
        with a.db() as c: connected=bool(c.execute('SELECT 1 FROM bridge_credentials').fetchone())
        try: cloud.app_ids();configured=True
        except cloud.CloudError: configured=False
        return {**cfg,'authenticated':connected,'app_configured':configured,'categories':['Georreferenciados',*policy.STUDIES],'background_access':'delegated_refresh_token','notice':'Autorização pode expirar ou ser revogada pelas políticas Microsoft 365.'}

    @app.put('/v1/bridge/sharepoint')
    def destination(body: Destination,user=Depends(a.identity)):
        admin(user);translate(cloud.validate_folder,body.folder_url)
        with a.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT 1 FROM cloud_transfers WHERE status='uploading'").fetchone(): raise HTTPException(409,'Aguarde as transferências antes de alterar o destino')
            c.execute('UPDATE bridge_settings SET folder_url=?,drive_id=NULL,folder_id=NULL,web_url=NULL,checked=NULL WHERE id=1',(body.folder_url,))
            a.event(c,user['id'],'sharepoint.destination.changed','1')
        return {'status':'needs_validation'}

    @app.post('/v1/bridge/sharepoint/connect')
    def connect(user=Depends(a.identity)):
        admin(user);return translate(cloud.start_auth,a.db,a.ROOT,user['id'])

    @app.post('/v1/bridge/sharepoint/poll')
    def poll(body: AuthPoll,user=Depends(a.identity)):
        admin(user);return translate(cloud.poll_auth,a.db,a.ROOT,user['id'],body.id)

    @app.post('/v1/bridge/sharepoint/test')
    def test_destination(user=Depends(a.identity)):
        admin(user);cfg=cloud.configuration(a.db);graph=cloud.Graph(a.db,a.ROOT)
        resolved=translate(graph.resolve,cfg['folder_url'])
        # Teste explicitamente acionado: cria, confere e remove apenas o próprio arquivo.
        raw=('Coletor IPHAN teste '+a.uid()).encode();name='coletor_teste_'+a.uid()+'.txt'
        item=translate(graph.put,resolved['drive_id'],resolved['folder_id'],name,raw)
        try: translate(graph.verify,resolved['drive_id'],item['id'],raw)
        finally: translate(graph.request,'DELETE','/drives/'+resolved['drive_id']+'/items/'+item['id'])
        with a.db() as c:
            if c.execute('SELECT folder_url FROM bridge_settings WHERE id=1').fetchone()[0]!=cfg['folder_url']: raise HTTPException(409,'Destino foi alterado; repita a validação')
            c.execute('UPDATE bridge_settings SET drive_id=?,folder_id=?,web_url=?,checked=? WHERE id=1',(resolved['drive_id'],resolved['folder_id'],resolved['web_url'],time.time()))
            c.execute("UPDATE cloud_transfers SET status='queued',available=0 WHERE status='waiting_for_connection'")
            a.event(c,user['id'],'sharepoint.destination.verified','1')
        return {'status':'verified',**resolved}

    @app.delete('/v1/bridge/sharepoint/connect',status_code=204)
    def disconnect(user=Depends(a.identity)):
        admin(user)
        with a.db() as c:
            c.execute('DELETE FROM bridge_credentials');c.execute('DELETE FROM bridge_auth');c.execute('UPDATE bridge_settings SET checked=NULL')
            a.event(c,user['id'],'sharepoint.disconnected','1')

    @app.get('/v1/bridge/manifest/{pid}')
    def manifest(pid: str,user=Depends(a.identity)):
        with a.db() as c:
            process=dict(a.process_access(c,pid,user));items=[]
            for r in c.execute('SELECT r.*,d.name,b.size,b.mime FROM revisions r JOIN documents d ON d.id=r.document_id JOIN blobs b ON b.hash=r.blob WHERE d.process_id=? ORDER BY r.rowid',(process['id'],)):
                items.append({**dict(r),'occurrences':[dict(o) for o in c.execute('SELECT source,name,created FROM occurrences WHERE revision_id=?',(r['id'],))],'transfers':[{k:v for k,v in dict(t).items() if k not in ('lease','owner','actor_id','delegation_id')} for t in c.execute('SELECT * FROM cloud_transfers WHERE revision_id=?',(r['id'],))]})
            return {'version':'0.7.0','process':{k:v for k,v in process.items() if k!='owner'},'revisions':items,'source_snapshots':[dict(s) for s in c.execute('SELECT id,source_url,blob AS sha256,created FROM source_snapshots WHERE process_id=?',(process['id'],))]}

def _has(a,c,pid,user,permission):
    try: a.process_access(c,pid,user,permission);return True
    except HTTPException: return False
