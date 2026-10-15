"""Worker comum para links explícitos e extração isolada, com heartbeat e fencing."""
import argparse
import json
import logging
import signal
import threading
import time
import app
import task_queue
import extraction
import safe_fetch
from fastapi import HTTPException

stop=threading.Event()
log=logging.getLogger('collector.worker')
BATCH_QUOTA_BYTES=100*1024*1024

class LeaseKeeper:
    def __init__(self,job):
        self.job=job;self.end=threading.Event();self.lost=threading.Event()
        self.thread=threading.Thread(target=self._loop,daemon=True)
    def _loop(self):
        interval=max(.1,min(20,task_queue.LEASE_SECONDS/3))
        while not self.end.wait(interval):
            try:
                if not task_queue.renew(app.db,self.job): self.lost.set();return
            except Exception:
                # Não renovar um lease cuja validade não pôde ser comprovada.
                self.lost.set();return
    def guard(self):
        if self.lost.is_set(): raise extraction.LostLease()
        with app.db() as c:
            if not task_queue.held(c,self.job): raise extraction.LostLease()
    def __enter__(self): self.guard();self.thread.start();return self
    def __exit__(self,*_): self.end.set();self.thread.join(timeout=2)


def link_summary(c,jid):
    rows=[dict(r) for r in c.execute('SELECT * FROM link_items WHERE job_id=? ORDER BY position',(jid,))]
    counts={'links_received':len(rows),'downloaded':sum(r['status'] in ('downloaded','already_exists') for r in rows),'already_existing':sum(r['status'] in ('already_exists','duplicate') for r in rows),'manually_imported':sum(r['status']=='manual_imported' for r in rows),'blocked':sum(r['status']=='invalid' for r in rows),'failed':sum(r['status']=='failed' for r in rows),'pending':sum(r['status'] in ('waiting_for_user','received','duplicate_pending') for r in rows),'extracted':0,'validated':0}
    return {'stage':'links_processed','counts':counts,'items':[{'id':r['id'],'status':r['status'],'revision_id':r['revision_id']} for r in rows]}


def process_links(job,user,keeper):
    with app.db() as c: items=c.execute('SELECT * FROM link_items WHERE job_id=? ORDER BY position',(job['id'],)).fetchall()
    if not items:
        with app.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if task_queue.held(c,job): task_queue.finish(c,app.event,job,'waiting_for_user','Tarefa legada sem links individuais; envie novo comando com URL/lista',{'stage':'legacy_input_needs_resolution'})
        return
    for original in items:
        keeper.guard()
        with app.db() as c: item=dict(c.execute('SELECT * FROM link_items WHERE id=?',(original['id'],)).fetchone())
        if item['status'] in ('downloaded','already_exists','manual_imported','duplicate','invalid','failed'): continue
        if item['status']=='waiting_for_user' and not item['duplicate_of']: continue
        if item['duplicate_of']:
            with app.db() as c:
                c.execute('BEGIN IMMEDIATE')
                if not task_queue.held(c,job): raise extraction.LostLease()
                first=c.execute('SELECT * FROM link_items WHERE id=?',(item['duplicate_of'],)).fetchone()
                if first and first['revision_id']:
                    c.execute("UPDATE link_items SET status='duplicate',revision_id=?,process_id=?,detail='Resultado do link repetido reutilizado' WHERE id=?",(first['revision_id'],first['process_id'],item['id']))
                else:
                    c.execute("UPDATE link_items SET status='waiting_for_user',detail='Link repetido aguarda resolução do primeiro item' WHERE id=?",(item['id'],))
            continue
        try:
            if not item['process_id']: raise safe_fetch.FetchError('process_required','Cadastre/selecione processo e informe process_id na retomada; não foi realizado acesso externo')
            with app.db() as c: app.process_access(c,item['process_id'],user,'operate')
            data=safe_fetch.fetch(item['url'],keeper.guard)
            keeper.guard()
            with app.db() as c:
                total=c.execute("SELECT coalesce(sum(b.size),0) FROM link_items i JOIN revisions r ON r.id=i.revision_id JOIN blobs b ON b.hash=r.blob WHERE i.job_id=? AND i.status IN ('downloaded','already_exists','manual_imported')",(job['id'],)).fetchone()[0]
            if total+len(data['data'])>BATCH_QUOTA_BYTES: raise safe_fetch.FetchError('batch_quota','Limite de originais confirmados por tarefa; divida a lista')
            blob=app.put_blob(data['data'])
            with app.db() as c:
                c.execute('BEGIN IMMEDIATE')
                if not task_queue.held(c,job): raise extraction.LostLease()
                total=c.execute("SELECT coalesce(sum(b.size),0) FROM link_items i JOIN revisions r ON r.id=i.revision_id JOIN blobs b ON b.hash=r.blob WHERE i.job_id=? AND i.status IN ('downloaded','already_exists','manual_imported')",(job['id'],)).fetchone()[0]
                if total+blob[2]>BATCH_QUOTA_BYTES: raise safe_fetch.FetchError('batch_quota','Limite de 100 MiB por tarefa; divida a lista')
                result=app.persist_document(c,item['process_id'],data['name'],item['url'],user,blob,from_link=True,original_name=data.get('original_name',data['name']))
                c.execute('UPDATE link_items SET status=?,revision_id=?,detail=? WHERE id=?',('downloaded' if result['changed'] else 'already_exists',result['revision_id'],'Documento obtido; extração é etapa separada',item['id']))
                c.execute('INSERT INTO link_captures VALUES(?,?,?,?,?,?,?)',(app.uid(),item['id'],item['url'],data['final_url'],result['sha256'],data['mime'],time.time()))
                checkpoint=link_summary(c,job['id'])
                c.execute('UPDATE jobs SET checkpoint=?,detail=? WHERE id=?',(json.dumps(checkpoint),'Documentos confirmados preservados; processando itens restantes',job['id']))
                app.event(c,user.get('_actor_id',user['id']),'collection.item.obtained',item['id'])
        except safe_fetch.FetchError as exc:
            with app.db() as c:
                c.execute('BEGIN IMMEDIATE')
                if not task_queue.held(c,job): raise extraction.LostLease()
                c.execute("UPDATE link_items SET status='waiting_for_user',detail=? WHERE id=?",(exc.code+': '+exc.action,item['id']))
                app.event(c,user.get('_actor_id',user['id']),'collection.item.waiting_for_user',item['id'])
        # Limite conservador de cadência, sem varrer portais ou iniciar buscas.
        if keeper.end.wait(.2): raise extraction.LostLease()
    with app.db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not task_queue.held(c,job): raise extraction.LostLease()
        checkpoint=link_summary(c,job['id']);counts=checkpoint['counts']
        success=any(r['revision_id'] for r in c.execute('SELECT revision_id FROM link_items WHERE job_id=?',(job['id'],)))
        problems=counts['pending']+counts['blocked']+counts['failed']
        state=('partial' if success else 'waiting_for_user' if counts['pending'] else 'failed') if problems else 'completed'
        detail=('Nenhum documento obtido; links inválidos. Corrija-os e envie novo comando' if state=='failed' else 'Alguns links exigem correção, retomada ou importação manual') if problems else 'Documentos dos links obtidos ou importados; extração/validação não presumidas'
        task_queue.finish(c,app.event,job,state,detail,checkpoint)


def run_once(worker_id='local-worker'):
    job=task_queue.claim(app.db,app.event,worker_id)
    if not job: return False
    run_id=None
    try:
        with LeaseKeeper(job) as keeper:
            payload=json.loads(job['input'])
            with app.db() as c: owner=c.execute('SELECT * FROM users WHERE id=? AND active=1',(job['owner'],)).fetchone()
            if not owner: raise extraction.LostLease()
            user={**dict(owner),'_guard':keeper.guard,'_lease_token':job['lease_token']}
            if job.get('delegation_id'): user.update({'_delegation':job['delegation_id'],'_actor_id':job['actor_id']})
            if payload.get('operation') in ('collect_process','collect_links'):
                process_links(job,user,keeper);return True
            rid=payload['input']['revision_id']
            reservation=app.reserve_extraction(rid,user,job['id'],payload['input'].get('reprocess',False),job['lease_token']);run_id=reservation['id']
            if reservation.get('cached'): result={**reservation['cached'],'reused':True}
            else:
                user['_run_id']=run_id;pages=app.prepare_extraction(rid,user)
                keeper.guard()
                with app.db() as c:
                    c.execute('BEGIN IMMEDIATE')
                    if not task_queue.held(c,job): raise extraction.LostLease()
                    result=app.save_extraction(c,rid,user,pages)
                    task_queue.finish(c,app.event,job,'partial' if result['ocr_required'] else 'completed','OCR necessário; extração nativa parcial' if result['ocr_required'] else 'Extração concluída',{'stage':'extraction_committed','revision_id':rid,'result':result,'counts':{'extracted':1,'validated':0}})
                return True
            with app.db() as c:
                c.execute('BEGIN IMMEDIATE')
                if not task_queue.held(c,job): raise extraction.LostLease()
                task_queue.finish(c,app.event,job,'partial' if result['ocr_required'] else 'completed','Execução anterior reutilizada sem duplicar evidências',{'stage':'extraction_reused','revision_id':rid,'result':result,'counts':{'extracted':0,'reused':1,'validated':0}})
    except extraction.LostLease:
        if run_id: app.fail_extraction(run_id,'lease_lost','cancelled')
    except HTTPException as exc:
        if run_id: app.fail_extraction(run_id,'http_'+str(exc.status_code))
        if exc.status_code==409:
            task_queue.fail(app.db,app.event,job)
        else:
            with app.db() as c:
                c.execute('BEGIN IMMEDIATE')
                if task_queue.held(c,job): task_queue.finish(c,app.event,job,'failed',f'Extração impedida: HTTP {exc.status_code}',{'stage':'extraction_failed','run_id':run_id})
    except Exception:
        if run_id: app.fail_extraction(run_id,'execution_error')
        log.error('job_execution_error job_id=%s',job['id'])
        task_queue.fail(app.db,app.event,job)
    return True


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');args=parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    for sig in (signal.SIGTERM,signal.SIGINT): signal.signal(sig,lambda *_:stop.set())
    worker_id=app.uid()
    if args.once: run_once(worker_id)
    else:
        while not stop.is_set():
            if not run_once(worker_id): stop.wait(1)
