import concurrent.futures
import json
from support import Fixture
import app
import task_queue

class AccessTests(Fixture):
    def test_canonical_process_shared_without_folder_or_blob_copy(self):
        original=self.upload()
        r=self.client.post('/v1/processes',headers=self.other_h,json={'number':self.number,'title':'Duplicado'})
        self.assertEqual(r.status_code,409)
        self.grant(role='read')
        rows=self.client.get('/v1/processes',headers=self.other_h).json()
        self.assertEqual([r['id'] for r in rows],[self.pid])
        self.assertEqual(self.client.get('/v1/document-revisions/'+original['revision_id']+'/download',headers=self.other_h).content,b'Fonte rastreavel')
        self.assertEqual(self.client.post('/v1/processes/'+self.pid+'/documents?name=x',headers=self.other_h,content=b'x').status_code,404)
        self.grant(role='operate')
        same=self.upload(headers=self.other_h)
        self.assertEqual(same['revision_id'],original['revision_id'])
        with app.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM processes WHERE number_key=? AND canonical_id IS NULL',(self.number.replace('-','').upper(),)).fetchone()[0],1)
    def test_group_revocation_hides_documents_evidence_library_and_search(self):
        original=self.upload();rid=original['revision_id'];did=original['document_id']
        ev=self.client.post('/v1/document-revisions/'+rid+'/extract',headers=self.h).json()['evidence'][0]['id']
        cl=self.client.post('/v1/documents/'+did+'/classifications',headers=self.h,json={'revision_id':rid,'study_type':'RAIPA','status':'validated'})
        self.assertEqual(cl.status_code,201)
        gid=self.client.post('/v1/groups',headers=self.h,json={'name':app.uid()}).json()['id']
        self.client.put('/v1/groups/'+gid+'/members',headers=self.h,json={'user_id':self.other})
        self.grant(gid,'read','group')
        self.assertEqual(self.client.get('/v1/evidence/'+ev,headers=self.other_h).status_code,200)
        self.assertEqual(len(self.client.get('/v1/library',headers=self.other_h).json()['items']),1)
        self.assertEqual(len(self.client.post('/v1/search',headers=self.other_h,json={'text':'Fonte'}).json()['items']),1)
        self.client.put('/v1/groups/'+gid+'/members',headers=self.h,json={'user_id':self.other,'active':False})
        self.assertEqual(self.client.get('/v1/evidence/'+ev,headers=self.other_h).status_code,404)
        self.assertEqual(self.client.get('/v1/document-revisions/'+rid+'/download',headers=self.other_h).status_code,404)
        self.assertEqual(self.client.get('/v1/library',headers=self.other_h).json()['items'],[])
        self.assertEqual(self.client.post('/v1/search',headers=self.other_h,json={'text':'Fonte'}).json()['items'],[])
    def test_reader_operator_reviewer_and_resource_admin(self):
        original=self.upload();rid=original['revision_id'];did=original['document_id']
        self.grant(role='review')
        self.assertEqual(self.client.post('/v1/documents/'+did+'/classifications',headers=self.other_h,json={'revision_id':rid,'study_type':'PAIPA','status':'validated'}).status_code,201)
        self.assertEqual(self.client.post('/v1/document-revisions/'+rid+'/extract',headers=self.other_h).status_code,404)
        self.assertEqual(self.client.post('/v1/processes/'+self.pid+'/permissions',headers=self.other_h,json={'subject_type':'user','subject_id':self.other,'role':'admin'}).status_code,404)
        self.grant(role='operate')
        self.assertEqual(self.client.post('/v1/document-revisions/'+rid+'/extract',headers=self.other_h).status_code,200)
    def test_concurrent_registration_has_one_canonical(self):
        number=app.uid()
        def create(h): return self.client.post('/v1/processes',headers=h,json={'number':number,'title':'Corrida'}).status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(create,[self.h,self.other_h]*4))
        self.assertEqual(results.count(201),1);self.assertEqual(results.count(409),7)
    def test_revocation_fences_worker_and_is_audited(self):
        rid=self.upload()['revision_id'];grant_id=self.grant(role='operate')
        jid=self.create_job({'source':'repository','operation':'extract_revision','input':{'revision_id':rid}},self.other_h)
        self.only_job(jid);job=task_queue.claim(app.db,app.event,'revocation')
        self.assertEqual(self.client.delete(f'/v1/processes/{self.pid}/permissions/{grant_id}',headers=self.h).status_code,204)
        with app.db() as c:
            self.assertFalse(task_queue.held(c,job))
            self.assertEqual(c.execute('SELECT status FROM jobs WHERE id=?',(jid,)).fetchone()[0],'cancelled')
            self.assertEqual(c.execute("SELECT count(*) FROM audit WHERE action='permission.revoked' AND resource=?",(grant_id,)).fetchone()[0],1)
    def test_service_delegation_is_bound_to_identity_scopes_and_revocation(self):
        rid=self.upload()['revision_id']
        service=self.client.post('/v1/service-accounts',headers=self.h,json={'name':app.uid()}).json()
        self.grant(service['id'],'operate')
        self.grant(role='operate')
        delegation=self.client.post('/v1/delegations',headers=self.other_h,json={'service_id':service['id'],'scopes':{self.pid:['read','operate']}})
        self.assertEqual(delegation.status_code,201,delegation.text)
        did=delegation.json()['id'];sh={'Authorization':'Bearer '+service['access_token'],'X-Delegation-Id':did}
        self.assertEqual(self.client.get('/v1/processes/'+self.pid,headers=sh).status_code,200)
        self.assertEqual(self.client.get('/v1/processes/'+self.pid,headers={**self.h,'X-Delegation-Id':did}).status_code,403)
        jid=self.create_job({'source':'repository','operation':'extract_revision','input':{'revision_id':rid}},sh)
        with app.db() as c:
            row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
            self.assertEqual(row['owner'],self.other);self.assertEqual(row['actor_id'],service['id'])
        self.client.delete('/v1/delegations/'+did,headers=self.other_h)
        self.assertEqual(self.client.get('/v1/processes/'+self.pid,headers=sh).status_code,403)
        with app.db() as c: self.assertEqual(c.execute('SELECT status FROM jobs WHERE id=?',(jid,)).fetchone()[0],'cancelled')
    def test_deactivating_creator_does_not_remove_team_access(self):
        original=self.upload();self.grant(role='read')
        admin,admin_h=self.user('admin')
        self.assertEqual(self.client.patch('/v1/users/'+self.owner,headers=admin_h,json={'active':False}).status_code,200)
        self.assertEqual(self.client.get('/v1/processes/'+self.pid,headers=self.h).status_code,401)
        self.assertEqual(self.client.get('/v1/processes/'+self.pid,headers=self.other_h).status_code,200)
        self.assertEqual(self.client.get('/v1/document-revisions/'+original['revision_id']+'/download',headers=self.other_h).status_code,200)
    def test_human_issuer_can_resume_own_delegated_pending_job_after_expiry(self):
        from unittest.mock import patch
        import safe_fetch
        service=self.client.post('/v1/service-accounts',headers=self.h,json={'name':app.uid()}).json()
        self.grant(service['id'],'operate')
        did=self.client.post('/v1/delegations',headers=self.h,json={'service_id':service['id'],'scopes':{self.pid:['read','operate']}}).json()['id']
        headers={'Authorization':'Bearer '+service['access_token'],'X-Delegation-Id':did}
        jid=self.create_job({'operation':'collect_links','input':{'url':'https://sei.iphan.gov.br/doc','process_id':self.pid}},headers)
        with patch('safe_fetch.fetch',side_effect=safe_fetch.FetchError('access_barrier','Importe manualmente')): self.run_job(jid)
        with app.db() as c: c.execute('UPDATE delegations SET expires=0 WHERE id=?',(did,))
        self.assertEqual(self.client.post('/v1/collection-jobs/'+jid+'/resume',headers=self.h).status_code,202)
        with app.db() as c:
            job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
            self.assertIsNone(job['delegation_id']);self.assertTrue(__import__('authorization').job_authorized(c,job))
    def test_expired_delegated_pending_run_does_not_block_new_authorized_request(self):
        rid=self.upload()['revision_id']
        service=self.client.post('/v1/service-accounts',headers=self.h,json={'name':app.uid()}).json()
        self.grant(service['id'],'operate')
        did=self.client.post('/v1/delegations',headers=self.h,json={'service_id':service['id'],'scopes':{self.pid:['read','operate']}}).json()['id']
        body={'source':'repository','operation':'extract_revision','input':{'revision_id':rid}}
        old=self.create_job(body,{'Authorization':'Bearer '+service['access_token'],'X-Delegation-Id':did})
        with app.db() as c: c.execute('UPDATE delegations SET expires=0 WHERE id=?',(did,))
        new=self.create_job(body)
        self.assertNotEqual(old,new)
        self.assertEqual(self.client.get('/v1/collection-jobs/'+old,headers=self.h).json()['status'],'cancelled')
        self.assertEqual(self.run_job(new)['status'],'completed')
    def test_service_cannot_impersonate_user_through_body(self):
        service=self.client.post('/v1/service-accounts',headers=self.h,json={'name':app.uid()}).json()
        sh={'Authorization':'Bearer '+service['access_token'],'Idempotency-Key':app.uid()}
        result=self.client.post('/v1/collection-jobs',headers=sh,json={'input':{'url':'https://www.gov.br/iphan/test.pdf','process_id':self.pid},'request_context':{'user_id':self.owner}})
        self.assertEqual(result.status_code,404)
        self.assertEqual(self.client.get('/v1/users',headers=sh).status_code,403)
    def test_expired_delegation_rejects(self):
        service=self.client.post('/v1/service-accounts',headers=self.h,json={'name':app.uid()}).json()
        self.grant(service['id'],'read')
        delegation=self.client.post('/v1/delegations',headers=self.h,json={'service_id':service['id'],'scopes':{self.pid:['read']}}).json()['id']
        with app.db() as c: c.execute('UPDATE delegations SET expires=0 WHERE id=?',(delegation,))
        self.assertEqual(self.client.get('/v1/processes/'+self.pid,headers={'Authorization':'Bearer '+service['access_token'],'X-Delegation-Id':delegation}).status_code,403)
