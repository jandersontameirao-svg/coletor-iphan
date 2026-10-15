import os, tempfile, unittest, concurrent.futures, subprocess, sys, pathlib, sqlite3
os.environ['COLLECTOR_DATA']=tempfile.mkdtemp(prefix='iphan-tests-')
from fastapi.testclient import TestClient
import app

class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app.app)
        self.headers=[]
        for name in ('owner','other'):
            name+=app.uid()
            with app.db() as c: c.execute('INSERT INTO users(id,name,password,role) VALUES(?,?,?,?)',(app.uid(),name,app.password_hash('test-password-123'),'admin'))
            token=self.client.post('/v1/sessions',json={'name':name,'password':'test-password-123'}).json()['access_token']
            self.headers.append({'Authorization':'Bearer '+token})
        self.pid=self.client.post('/v1/processes',headers=self.headers[0],json={'number':app.uid(),'title':'Estudo'}).json()['id']
    def upload(self,data=b'A',name='report.txt'):
        r=self.client.post(f'/v1/processes/{self.pid}/documents?name={name}',headers=self.headers[0],content=data)
        self.assertEqual(r.status_code,201,r.text)
        return r.json()
    def test_revision_a_b_a_and_occurrences(self):
        a=self.upload();b=self.upload(b'B');again=self.upload();same=self.upload()
        self.assertNotEqual(a['revision_id'],again['revision_id'])
        self.assertEqual(a['sha256'],again['sha256'])
        self.assertEqual(same['revision_id'],again['revision_id'])
        revs=self.client.get('/v1/documents/'+a['document_id']+'/revisions',headers=self.headers[0]).json()
        self.assertEqual(len(revs),3)
        self.assertEqual(revs[2]['predecessor'],b['revision_id'])
    def test_isolation_download_evidence(self):
        a=self.upload(b'Fonte verificavel')
        path='/v1/document-revisions/'+a['revision_id']
        self.assertEqual(self.client.get(path+'/download',headers=self.headers[0]).content,b'Fonte verificavel')
        self.assertEqual(self.client.get(path+'/download',headers=self.headers[1]).status_code,404)
        ev=self.client.post(path+'/extract',headers=self.headers[0]).json()['evidence'][0]
        self.assertIsNone(ev['page'])
        self.assertEqual(self.client.get('/v1/evidence/'+ev['id'],headers=self.headers[1]).status_code,404)
    def test_concurrent_same_bytes(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool: results=list(pool.map(lambda _:self.upload(),range(12)))
        self.assertEqual(len({r['revision_id'] for r in results}),1)
    def test_idempotency_cancel(self):
        h={**self.headers[0],'Idempotency-Key':app.uid()}; body={'input':{'url':'https://example.invalid'}}
        a=self.client.post('/v1/collection-jobs',headers=h,json=body)
        b=self.client.post('/v1/collection-jobs',headers=h,json=body)
        self.assertEqual(a.status_code,202)
        self.assertEqual(a.json(),b.json())
        self.assertEqual(self.client.post('/v1/collection-jobs',headers=h,json={'input':{'url':'different'}}).status_code,409)
        jid=a.json()['job_id']
        self.assertEqual(self.client.get('/v1/collection-jobs/'+jid,headers=h).json()['status'],'queued')
        self.assertEqual(self.client.post('/v1/collection-jobs/'+jid+'/cancel',headers=h).json()['status'],'cancelled')
    def test_backup_restore(self):
        a=self.upload(b'backup-evidence')
        root=pathlib.Path(tempfile.mkdtemp())
        for operation,source,target in [('backup',app.ROOT,root/'backup'),('restore',root/'backup',root/'restored')]:
            result=subprocess.run([sys.executable,'backup.py',operation,str(source),str(target)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
        restored=root/'restored'
        self.assertEqual((restored/'blobs'/a['sha256']).read_bytes(),b'backup-evidence')
        with sqlite3.connect(restored/'catalog.sqlite') as c:
            self.assertEqual(c.execute('SELECT blob FROM revisions WHERE id=?',(a['revision_id'],)).fetchone()[0],a['sha256'])
    def test_session_revocation(self):
        self.client.delete('/v1/sessions',headers=self.headers[0])
        self.assertEqual(self.client.get('/v1/processes',headers=self.headers[0]).status_code,401)
    def test_integrity_failure(self):
        a=self.upload(); path=app.ROOT/'blobs'/a['sha256']; old=path.read_bytes();path.write_bytes(b'corrupt')
        try: self.assertEqual(self.client.get('/v1/document-revisions/'+a['revision_id']+'/download',headers=self.headers[0]).status_code,503)
        finally: path.write_bytes(old)
    def test_folder_and_rename_idempotence(self):
        rows=self.client.get('/v1/processes',headers=self.headers[0]).json();row=next(r for r in rows if r['id']==self.pid)
        self.assertIn('Estudo',row['folder'])
        body={'number':row['number'],'title':'Novo nome'}
        for _ in range(2): self.assertEqual(self.client.patch('/v1/processes/'+self.pid,headers=self.headers[0],json=body).status_code,200)
        with app.db() as c: self.assertEqual(c.execute("SELECT count(*) FROM audit WHERE resource=? AND action='process.renamed'",(self.pid,)).fetchone()[0],1)

if __name__=='__main__': unittest.main()
