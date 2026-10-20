"""Catálogo por tipo, consulta de evidências e indicadores de trabalho efetivo."""
import json
import time
from typing import Literal
from pydantic import BaseModel, Field
from fastapi import Depends, HTTPException
import authorization
import safe_fetch

TAXONOMY_VERSION='seed-2026-10'
STUDY_TYPES=['PAPIPA','RAPIPA','PAIPA','RAIPA','PGPA','RAIPI','educacao_patrimonial']
class Classification(BaseModel):
    revision_id: str
    study_type: str
    status: Literal['proposed','validated','rejected']='proposed'
    notes: str = Field(default='',max_length=2000)
class Search(BaseModel):
    text: str = Field(min_length=1,max_length=500)
    process_id: str | None = None
class LinkCorrection(BaseModel):
    url: str = Field(min_length=1,max_length=4096)


def _analysis_summary(c, process_id):
    process=c.execute('SELECT id,number,title,folder FROM processes WHERE id=?',(process_id,)).fetchone()
    documents=c.execute('SELECT count(*) FROM documents WHERE process_id=?',(process_id,)).fetchone()[0]
    extracted=c.execute("SELECT count(DISTINCT d.id) FROM documents d JOIN revisions r ON r.document_id=d.id JOIN extraction_runs x ON x.revision_id=r.id WHERE d.process_id=? AND x.state='completed'",(process_id,)).fetchone()[0]
    ocr_required=c.execute("SELECT count(DISTINCT d.id) FROM documents d JOIN revisions r ON r.document_id=d.id JOIN extraction_runs x ON x.revision_id=r.id WHERE d.process_id=? AND x.state='needs_ocr' AND NOT EXISTS (SELECT 1 FROM extraction_runs x2 JOIN revisions r2 ON r2.id=x2.revision_id WHERE r2.document_id=d.id AND x2.state='completed')",(process_id,)).fetchone()[0]
    classified=c.execute("SELECT count(*) FROM documents d WHERE d.process_id=? AND EXISTS (SELECT 1 FROM classifications cl WHERE cl.document_id=d.id AND cl.rowid=(SELECT max(cl2.rowid) FROM classifications cl2 WHERE cl2.document_id=d.id) AND cl.status='validated')",(process_id,)).fetchone()[0]
    pending_classification=c.execute("SELECT count(*) FROM documents d WHERE d.process_id=? AND (NOT EXISTS (SELECT 1 FROM classifications cl WHERE cl.document_id=d.id) OR EXISTS (SELECT 1 FROM classifications cl WHERE cl.document_id=d.id AND cl.rowid=(SELECT max(cl2.rowid) FROM classifications cl2 WHERE cl2.document_id=d.id) AND cl.status IN ('proposed','rejected'))) ",(process_id,)).fetchone()[0]
    evidence=c.execute('SELECT count(*) FROM evidence e JOIN revisions r ON r.id=e.revision_id JOIN documents d ON d.id=r.document_id WHERE d.process_id=?',(process_id,)).fetchone()[0]
    assertions=c.execute("SELECT count(*) FROM knowledge_assertions WHERE process_id=? AND status='validated'",(process_id,)).fetchone()[0]
    pending_review=c.execute("SELECT count(*) FROM knowledge_assertions WHERE process_id=? AND status IN ('proposed','conflict')",(process_id,)).fetchone()[0]
    if not documents:
        status='not_started'
    elif extracted==documents and classified==documents and ocr_required==0 and pending_review==0:
        status='analyzed'
    elif extracted or classified or evidence:
        status='in_progress'
    else:
        status='pending'
    progress=0 if not documents else round(((extracted+classified)/(documents*2))*100)
    return {'process_id':process_id,'number':process['number'],'title':process['title'],'folder':process['folder'],'status':status,'documents':documents,'extracted_documents':extracted,'ocr_required':ocr_required,'classified_documents':classified,'pending_classification':pending_classification,'evidence':evidence,'knowledge_validated':assertions,'knowledge_pending_review':pending_review,'progress_percent':progress}


def register(app,db,event,identity,uid,revision_access,job_status,authorize_job):
    @app.get('/v1/taxonomy')
    def taxonomy(user=Depends(identity)):
        return {'version':TAXONOMY_VERSION,'types':STUDY_TYPES,'technical_approval':'pending','automatic_classification':False}

    @app.get('/v1/documents/{did}')
    def document(did: str,user=Depends(identity)):
        with db() as c:
            row=c.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone()
            if not row: raise HTTPException(404)
            authorization.process_access(c,row['process_id'],user)
            result=dict(row)
            result['occurrences']=[dict(r) for r in c.execute('SELECT o.* FROM occurrences o JOIN revisions r ON r.id=o.revision_id WHERE r.document_id=? ORDER BY o.created',(did,))]
            result['classifications']=[dict(r) for r in c.execute('SELECT * FROM classifications WHERE document_id=? ORDER BY rowid',(did,))]
            return result

    @app.post('/v1/documents/{did}/classifications',status_code=201)
    def classify(did: str,body: Classification,user=Depends(identity)):
        if body.study_type not in STUDY_TYPES: raise HTTPException(422,'Tipo fora da taxonomia vigente')
        cid=uid()
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            revision=revision_access(c,body.revision_id,user,'review')
            if revision['document_id']!=did: raise HTTPException(422,'Revisão não pertence ao documento')
            last=c.execute('SELECT id FROM classifications WHERE document_id=? ORDER BY rowid DESC LIMIT 1',(did,)).fetchone()
            c.execute('INSERT INTO classifications(id,document_id,study_type,version,status,reviewer,created,previous_id,revision_id,notes) VALUES(?,?,?,?,?,?,?,?,?,?)',(cid,did,body.study_type,TAXONOMY_VERSION,body.status,user['id'],time.time(),last['id'] if last else None,body.revision_id,body.notes))
            event(c,user.get('_actor_id',user['id']),'classification.'+body.status,cid)
        return {'id':cid,'version':TAXONOMY_VERSION,'status':body.status}

    @app.get('/v1/library')
    def library(study_type: str | None=None,user=Depends(identity)):
        with db() as c:
            rows=c.execute("SELECT cl.*,d.name,d.process_id FROM classifications cl JOIN documents d ON d.id=cl.document_id WHERE cl.rowid=(SELECT max(cl2.rowid) FROM classifications cl2 WHERE cl2.document_id=cl.document_id) AND cl.status!='rejected'").fetchall()
            result=[]
            for row in rows:
                if study_type and row['study_type']!=study_type: continue
                try: authorization.process_access(c,row['process_id'],user)
                except HTTPException: continue
                result.append(dict(row))
        return {'items':result,'originals_copied':False}

    @app.get('/v1/analysis/processes')
    def analysis_processes(user=Depends(identity)):
        with db() as c:
            items=[]
            for row in c.execute('SELECT id FROM processes WHERE canonical_id IS NULL ORDER BY folder').fetchall():
                try: pid=authorization.process_access(c,row['id'],user)['id']
                except HTTPException: continue
                items.append(_analysis_summary(c,pid))
            totals={'processes':len(items),'analyzed':sum(item['status']=='analyzed' for item in items),'in_progress':sum(item['status']=='in_progress' for item in items),'pending':sum(item['status'] in ('pending','not_started') for item in items),'ocr_required':sum(item['ocr_required'] for item in items),'knowledge_pending_review':sum(item['knowledge_pending_review'] for item in items)}
            return {'items':items,'totals':totals}

    @app.post('/v1/search')
    def search(body: Search,user=Depends(identity)):
        result=[]
        with db() as c:
            if body.process_id: authorization.process_access(c,body.process_id,user)
            pattern='%'+body.text.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            for row in c.execute("SELECT e.*,d.process_id,d.name FROM evidence e JOIN revisions r ON r.id=e.revision_id JOIN documents d ON d.id=r.document_id WHERE e.text LIKE ? ESCAPE '\\' ORDER BY e.rowid",(pattern,)):
                try: pid=authorization.process_access(c,row['process_id'],user)['id']
                except HTTPException: continue
                if body.process_id and authorization.resolve(c,body.process_id)['id']!=pid: continue
                visible=dict(row);visible['text']=visible['text'][:2000];result.append(visible)
                if len(result)>=100: break
        return {'items':result,'spatial_available':False,'semantic_available':False}

    @app.get('/v1/overview')
    def overview(user=Depends(identity)):
        with db() as c:
            pids=[]
            for p in c.execute('SELECT id FROM processes WHERE canonical_id IS NULL').fetchall():
                try: pids.append(authorization.process_access(c,p['id'],user)['id'])
                except HTTPException: continue
            documents=0;extractions=0;classifications=0
            for pid in pids:
                documents+=c.execute('SELECT count(*) FROM documents WHERE process_id=?',(pid,)).fetchone()[0]
                extractions+=c.execute("SELECT count(*) FROM extraction_runs x JOIN revisions r ON r.id=x.revision_id JOIN documents d ON d.id=r.document_id WHERE d.process_id=? AND x.state='completed'",(pid,)).fetchone()[0]
                classifications+=c.execute("SELECT count(*) FROM classifications cl JOIN documents d ON d.id=cl.document_id WHERE d.process_id=? AND cl.status='validated'",(pid,)).fetchone()[0]
            received=downloaded=manual=0
            for job in c.execute('SELECT * FROM jobs').fetchall():
                try: authorize_job(c,job,user)
                except (HTTPException,KeyError): continue
                received+=c.execute('SELECT count(*) FROM link_items WHERE job_id=?',(job['id'],)).fetchone()[0]
                downloaded+=c.execute("SELECT count(*) FROM link_items WHERE job_id=? AND status IN ('downloaded','already_exists')",(job['id'],)).fetchone()[0]
                manual+=c.execute("SELECT count(*) FROM link_items WHERE job_id=? AND status='manual_imported'",(job['id'],)).fetchone()[0]
            return {'processes':len(pids),'documents':documents,'links_received':received,'documents_downloaded':downloaded,'documents_manually_imported':manual,'native_extractions_completed':extractions,'classifications_validated':classifications,'studies_analyzed':None,'knowledge_validated':None,'geographic_coverage':None}

    @app.patch('/v1/collection-jobs/{jid}/links/{item_id}')
    def correct(jid: str,item_id: str,body: LinkCorrection,user=Depends(identity)):
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
            if not row: raise HTTPException(404)
            authorize_job(c,row,user,'operate')
            if row['status'] not in ('waiting_for_user','partial','cancelled'): raise HTTPException(409,'Correção exige tarefa pendente')
            item=c.execute('SELECT * FROM link_items WHERE job_id=? AND id=?',(jid,item_id)).fetchone()
            if not item: raise HTTPException(404)
            if item['revision_id']: raise HTTPException(409,'Não altere origem de resultado confirmado')
            status='received';detail='Link corrigido; solicite retomada'
            try: safe_fetch.validate_url(body.url)
            except safe_fetch.FetchError as exc: status='invalid';detail=exc.code+': '+exc.action
            c.execute('INSERT INTO link_edits VALUES(?,?,?,?,?,?)',(uid(),item_id,item['url'],body.url,user.get('_actor_id',user['id']),time.time()))
            c.execute('UPDATE link_items SET url=?,status=?,detail=?,duplicate_of=NULL WHERE id=?',(body.url,status,detail,item_id))
            event(c,user.get('_actor_id',user['id']),'collection.item.corrected',item_id)
            return {'id':item_id,'status':status,'detail':detail}
