import concurrent.futures
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
os.environ['COLLECTOR_DATA']=tempfile.mkdtemp(prefix='iphan-queue-tests-')
import app
import task_queue
import worker
from fastapi.testclient import TestClient

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app.app)
        self.owner={'id':app.uid(),'name':app.uid(),'role':'operator'}
        with app.db() as c:
            c.execute('INSERT INTO users(id,name,password,role) VALUES(?,?,?,?)',(self.owner['id'],self.owner['name'],app.password_hash('test-password-123'),'operator'))
        token=self.client.post('/v1/sessions',json={'name':self.owner['name'],'password':'test-password-123'}).json()['access_token']
        self.h={'Authorization':'Bearer '+token}
        p=self.client.post('/v1/processes',headers=self.h,json={'number':app.uid(),'title':'Worker'}).json()['id']
        self.rid=self.client.post(f'/v1/processes/{p}/documents?name=worker.txt',headers=self.h,content=b'Evidencia de worker').json()['revision_id']
    def tearDown(self):
        with app.db() as c:
            c.execute("UPDATE jobs SET status='cancelled',lease_token=NULL,lease_until=NULL WHERE owner=? AND status IN ('queued','running')",(self.owner['id'],))
    def create(self):
        response=self.client.post('/v1/collection-jobs',headers={**self.h,'Idempotency-Key':app.uid()},json={'source':'repository','operation':'extract_revision','input':{'revision_id':self.rid}})
        self.assertEqual(response.status_code,202,response.text)
        return response.json()['job_id']
    def row(self,jid):
        return self.client.get('/v1/collection-jobs/'+jid,headers=self.h).json()
    def claim_own(self):
        for _ in range(100):
            job=task_queue.claim(app.db,app.event,'test')
            if job is None: self.fail('Tarefa ausente')
            if job['owner']==self.owner['id']: return job
            with app.db() as c:
                c.execute("UPDATE jobs SET status='cancelled' WHERE id=?",(job['id'],))
        self.fail('Fila inesperadamente longa')
    def drain(self,jid):
        for _ in range(100):
            if self.row(jid)['status']!='queued': return
            worker.run_once()
        self.fail('Tarefa não executada')
    def test_worker_persists_evidence_and_results(self):
        jid=self.create();self.drain(jid)
        row=self.row(jid);self.assertEqual(row['status'],'completed')
        result=json.loads(row['checkpoint'])['result']
        eid=result['evidence'][0]['id']
        self.assertEqual(self.client.get('/v1/evidence/'+eid,headers=self.h).json()['text'],'Evidencia de worker')
        self.assertEqual(len(self.client.get('/v1/collection-jobs/'+jid+'/attempts',headers=self.h).json()),1)
        self.assertFalse(self.row(jid)['lease_token'])
    def test_exclusive_claim(self):
        jid=self.create()
        # Isolar tarefas de outras fixtures antes de disputar a aquisição.
        with app.db() as c: c.execute("UPDATE jobs SET status='cancelled' WHERE status='queued' AND id!=?",(jid,))
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            claims=list(pool.map(lambda n:task_queue.claim(app.db,app.event,str(n)),range(5)))
        self.assertEqual(sum(j is not None for j in claims),1)
    def test_recovery_fences_old_worker(self):
        jid=self.create();old=self.claim_own()
        with app.db() as c: c.execute('UPDATE jobs SET lease_until=0 WHERE id=?',(jid,))
        new=self.claim_own()
        self.assertNotEqual(old['lease_token'],new['lease_token'])
        self.assertEqual(new['attempt_count'],2)
        with app.db() as c:
            self.assertFalse(task_queue.held(c,old));self.assertTrue(task_queue.held(c,new))
            attempts=c.execute('SELECT status FROM job_attempts WHERE job_id=? ORDER BY number',(jid,)).fetchall()
            self.assertEqual([r['status'] for r in attempts],['interrupted','running'])
    def test_cancel_prevents_inflight_result_and_resume(self):
        jid=self.create();job=self.claim_own()
        response=self.client.post('/v1/collection-jobs/'+jid+'/cancel',headers=self.h)
        self.assertEqual(response.status_code,200)
        with app.db() as c: self.assertFalse(task_queue.held(c,job))
        self.assertEqual(self.client.post('/v1/collection-jobs/'+jid+'/resume',headers=self.h).status_code,202)
        self.drain(jid);self.assertEqual(self.row(jid)['status'],'completed')
        self.assertEqual(self.client.post('/v1/collection-jobs/'+jid+'/cancel',headers=self.h).status_code,409)
    def test_retry_limit(self):
        jid=self.create()
        for _ in range(3):
            job=self.claim_own();task_queue.fail(app.db,app.event,job)
            with app.db() as c: c.execute('UPDATE jobs SET available_at=0 WHERE id=?',(jid,))
        self.assertEqual(self.row(jid)['status'],'failed')
        self.assertEqual(self.row(jid)['attempt_count'],3)
    def test_completed_job_does_not_duplicate_evidence(self):
        jid=self.create();self.drain(jid)
        before=self.row(jid)['checkpoint'];worker.run_once()
        self.assertEqual(self.row(jid)['checkpoint'],before)
        self.assertEqual(self.row(jid)['attempt_count'],1)
    def test_denied_input_and_attempts(self):
        jid=self.create()
        self.assertEqual(self.client.get('/v1/collection-jobs/'+jid+'/attempts').status_code,401)
        response=self.client.post('/v1/collection-jobs',headers={**self.h,'Idempotency-Key':app.uid()},json={'source':'repository','operation':'extract_revision','input':{'revision_id':app.uid()}})
        self.assertEqual(response.status_code,404)
    def test_cancel_during_extraction_commits_no_evidence(self):
        jid=self.create()
        with app.db() as c: c.execute("UPDATE jobs SET status='cancelled' WHERE status='queued' AND id!=?",(jid,))
        prepare=app.prepare_extraction
        def cancel_inflight(rid,user):
            pages=prepare(rid,user)
            self.client.post('/v1/collection-jobs/'+jid+'/cancel',headers=self.h)
            return pages
        with patch('app.prepare_extraction',side_effect=cancel_inflight): worker.run_once()
        self.assertEqual(self.row(jid)['status'],'cancelled')
        with app.db() as c: self.assertEqual(c.execute('SELECT count(*) FROM evidence WHERE revision_id=?',(self.rid,)).fetchone()[0],0)
    def test_deactivation_revokes_and_cancels(self):
        jid=self.create();job=self.claim_own()
        admin_name=app.uid()
        with app.db() as c: c.execute('INSERT INTO users(id,name,password,role) VALUES(?,?,?,?)',(app.uid(),admin_name,app.password_hash('admin-password-123'),'admin'))
        token=self.client.post('/v1/sessions',json={'name':admin_name,'password':'admin-password-123'}).json()['access_token']
        admin_h={'Authorization':'Bearer '+token}
        self.assertEqual(self.client.patch('/v1/users/'+self.owner['id'],headers=self.h,json={'active':False}).status_code,403)
        self.assertEqual(self.client.patch('/v1/users/'+self.owner['id'],headers=admin_h,json={'active':False}).status_code,200)
        self.assertEqual(self.client.get('/v1/processes',headers=self.h).status_code,401)
        with app.db() as c:
            self.assertFalse(task_queue.held(c,job))
            self.assertEqual(c.execute('SELECT status FROM jobs WHERE id=?',(jid,)).fetchone()[0],'cancelled')
    def test_crashed_process_claim_is_recovered(self):
        jid=self.create()
        with app.db() as c: c.execute("UPDATE jobs SET status='cancelled' WHERE status='queued' AND id!=?",(jid,))
        code="import os,app,task_queue; task_queue.claim(app.db,app.event,'crashed-worker'); os._exit(17)"
        result=subprocess.run([sys.executable,'-c',code],env={**os.environ,'COLLECTOR_DATA':str(app.ROOT)},capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,17)
        self.assertEqual(self.row(jid)['status'],'running')
        with app.db() as c: c.execute('UPDATE jobs SET lease_until=0 WHERE id=?',(jid,))
        worker.run_once()
        self.assertEqual(self.row(jid)['status'],'completed')
        self.assertEqual(self.row(jid)['attempt_count'],2)
    def test_extraction_rollback_retries_without_partial_evidence(self):
        jid=self.create()
        with app.db() as c: c.execute("UPDATE jobs SET status='cancelled' WHERE status='queued' AND id!=?",(jid,))
        save=app.save_extraction
        def interrupted(c,rid,user,pages):
            save(c,rid,user,pages)
            raise RuntimeError('Injected interruption after evidence insert')
        with patch('app.save_extraction',side_effect=interrupted): worker.run_once()
        self.assertEqual(self.row(jid)['status'],'queued')
        with app.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM evidence WHERE revision_id=?',(self.rid,)).fetchone()[0],0)
            c.execute('UPDATE jobs SET available_at=0 WHERE id=?',(jid,))
        worker.run_once();self.assertEqual(self.row(jid)['status'],'completed')
    def test_process_restart_executes_persisted_job(self):
        jid=self.create()
        with app.db() as c: c.execute("UPDATE jobs SET status='cancelled' WHERE status='queued' AND id!=?",(jid,))
        result=subprocess.run([sys.executable,'worker.py','--once'],env={**os.environ,'COLLECTOR_DATA':str(app.ROOT)},capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.row(jid)['status'],'completed')

if __name__=='__main__':unittest.main()
