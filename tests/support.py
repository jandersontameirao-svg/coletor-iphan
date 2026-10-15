import os
import tempfile
import uuid
import unittest
import sys
if 'app' not in sys.modules: os.environ['COLLECTOR_DATA']=tempfile.mkdtemp(prefix='iphan-v03-tests-')
import app
from fastapi.testclient import TestClient

class Fixture(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app.app)
        self.owner,self.h=self.user('admin');self.other,self.other_h=self.user('operator')
        self.number=app.uid()
        r=self.client.post('/v1/processes',headers=self.h,json={'number':self.number,'title':'Compartilhado'})
        self.assertEqual(r.status_code,201,r.text);self.pid=r.json()['id']
    def user(self,role='operator'):
        user_id=app.uid();name=app.uid();password='synthetic-password-123'
        with app.db() as c: c.execute('INSERT INTO users(id,name,password,role) VALUES(?,?,?,?)',(user_id,name,app.password_hash(password),role))
        token=self.client.post('/v1/sessions',json={'name':name,'password':password}).json()['access_token']
        return user_id,{'Authorization':'Bearer '+token}
    def upload(self,data=b'Fonte rastreavel',headers=None,name='source.txt'):
        r=self.client.post(f'/v1/processes/{self.pid}/documents?name={name}',headers=headers or self.h,content=data)
        self.assertEqual(r.status_code,201,r.text);return r.json()
    def grant(self,subject=None,role='read',subject_type='user'):
        r=self.client.post(f'/v1/processes/{self.pid}/permissions',headers=self.h,json={'subject_type':subject_type,'subject_id':subject or self.other,'role':role})
        self.assertEqual(r.status_code,201,r.text);return r.json()['id']
    def create_job(self,body,headers=None,key=None):
        r=self.client.post('/v1/collection-jobs',headers={**(headers or self.h),'Idempotency-Key':key or app.uid()},json=body)
        self.assertEqual(r.status_code,202,r.text);return r.json()['job_id']
    def only_job(self,jid):
        with app.db() as c: c.execute("UPDATE jobs SET status='cancelled' WHERE status='queued' AND id!=?",(jid,))
    def run_job(self,jid):
        import worker
        self.only_job(jid);worker.run_once()
        return self.client.get('/v1/collection-jobs/'+jid,headers=self.h).json()
