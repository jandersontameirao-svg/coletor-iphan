import json,time
from fastapi import Depends,HTTPException
from pydantic import BaseModel,Field
from typing import Literal
import market_domain as domain

class Reprocess(BaseModel):
    reprocess: bool=False
class Review(BaseModel):
    status:Literal['validated','rejected','proposed']
    rationale:str=Field(min_length=5,max_length=2000)

def register(a):
    app=a.app;domain.migrate(a.db)
    @app.post('/v1/market/processes/{pid}/extract',status_code=202)
    def queue_process(pid:str,body:Reprocess,user=Depends(a.identity)):
        if a.DEMO_MODE:raise HTTPException(403,'Extração indisponível na demonstração')
        with a.db() as c:
            c.execute('BEGIN IMMEDIATE');pid=a.process_access(c,pid,user,'operate')['id'];jobs=[]
            for r in c.execute('SELECT r.id FROM revisions r JOIN documents d ON d.id=r.document_id WHERE d.process_id=? AND r.rowid=(SELECT max(r2.rowid) FROM revisions r2 WHERE r2.document_id=d.id)',(pid,)).fetchall():jobs.append(domain.enqueue(c,r['id'],user,a.uid,body.reprocess))
            a.event(c,user.get('_actor_id',user['id']),'market.process.queued',pid)
        return {'jobs':jobs,'status':'queued_or_reused'}
    @app.get('/v1/market/processes/{pid}')
    def get_process(pid:str,history:bool=False,user=Depends(a.identity)):
        with a.db() as c:return domain.process_data(a,c,pid,user,history)
    @app.get('/v1/market/processes/{pid}/export')
    def export(pid:str,history:bool=False,user=Depends(a.identity)):
        with a.db() as c:return {'schema_version':'1.0','exported_at':time.time(),**domain.process_data(a,c,pid,user,history)}
    @app.get('/v1/market/facts/{fid}')
    def fact(fid:str,user=Depends(a.identity)):
        with a.db() as c:
            row=c.execute('SELECT d.process_id FROM market_facts f JOIN market_jobs j ON j.id=f.run_id JOIN revisions r ON r.id=j.revision_id JOIN documents d ON d.id=r.document_id WHERE f.id=?',(fid,)).fetchone()
            if not row:raise HTTPException(404)
            data=domain.process_data(a,c,row['process_id'],user,True)
            return next(f for f in data['facts'] if f['id']==fid)
    @app.patch('/v1/market/facts/{fid}')
    def review(fid:str,body:Review,user=Depends(a.identity)):
        with a.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT d.process_id FROM market_facts f JOIN market_jobs j ON j.id=f.run_id JOIN revisions r ON r.id=j.revision_id JOIN documents d ON d.id=r.document_id WHERE f.id=?',(fid,)).fetchone()
            if not row:raise HTTPException(404)
            a.process_access(c,row['process_id'],user,'review')
            rid=a.uid();c.execute('INSERT INTO market_reviews VALUES(?,?,?,?,?,?)',(rid,fid,body.status,body.rationale,user.get('_actor_id',user['id']),time.time()))
            a.event(c,user.get('_actor_id',user['id']),'market.fact.'+body.status,fid)
        return {'id':fid,'review_id':rid,'status':body.status}
