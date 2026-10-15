import json
from unittest.mock import patch
from support import Fixture
import app
import safe_fetch
import worker

GOOD='https://www.gov.br/iphan/test.txt'
LOGIN='https://sei.iphan.gov.br/documento'

class LinkTests(Fixture):
    def body(self,urls,pid=True):
        data={'urls':urls}
        if pid: data['process_id']=self.pid
        return {'source':'iphan','operation':'collect_links','input':data}
    def mock_fetch(self,url,guard):
        guard()
        if url==LOGIN: raise safe_fetch.FetchError('access_barrier','Importe manualmente; login/CAPTCHA não será contornado')
        return {'data':b'Original do link','mime':'text/plain','name':'download.txt','source_url':url,'final_url':url}
    def test_mixed_list_validation_duplicate_barrier_and_manual_resume(self):
        jid=self.create_job(self.body([GOOD,GOOD,'https://127.0.0.1/secret',LOGIN]))
        initial=self.client.get('/v1/collection-jobs/'+jid+'/links',headers=self.h).json()
        self.assertEqual([r['status'] for r in initial],['received','duplicate_pending','invalid','received'])
        with patch('safe_fetch.fetch',side_effect=self.mock_fetch) as fetch:
            row=self.run_job(jid)
            self.assertEqual(fetch.call_count,2)
        self.assertEqual(row['status'],'partial')
        items=self.client.get('/v1/collection-jobs/'+jid+'/links',headers=self.h).json()
        self.assertEqual([r['status'] for r in items],['downloaded','duplicate','invalid','waiting_for_user'])
        self.assertEqual(items[0]['revision_id'],items[1]['revision_id'])
        resolved=self.client.post(f'/v1/collection-jobs/{jid}/links/{items[3]["id"]}/import?name=manual.txt',headers=self.h,content=b'Original importado')
        self.assertEqual(resolved.status_code,201,resolved.text)
        corrected=self.client.patch(f'/v1/collection-jobs/{jid}/links/{items[2]["id"]}',headers=self.h,json={'url':GOOD+'?other=1'})
        self.assertEqual(corrected.status_code,200,corrected.text)
        self.assertEqual(self.client.post('/v1/collection-jobs/'+jid+'/resume',headers=self.h).status_code,202)
        with patch('safe_fetch.fetch',side_effect=self.mock_fetch) as fetch:
            row=self.run_job(jid)
            self.assertEqual(fetch.call_count,1)
        self.assertEqual(row['status'],'completed')
        counts=json.loads(row['checkpoint'])['counts']
        self.assertEqual(counts['downloaded'],2)
        self.assertEqual(counts['manually_imported'],1)
        self.assertEqual(counts['extracted'],0);self.assertEqual(counts['validated'],0)
    def test_received_link_without_process_is_pending_without_network(self):
        jid=self.create_job(self.body([GOOD],False))
        with patch('safe_fetch.fetch') as fetch:
            row=self.run_job(jid);fetch.assert_not_called()
        self.assertEqual(row['status'],'waiting_for_user')
        response=self.client.post('/v1/collection-jobs/'+jid+'/resume',headers=self.h,json={'process_id':self.pid})
        self.assertEqual(response.status_code,202,response.text)
        with patch('safe_fetch.fetch',side_effect=self.mock_fetch): self.assertEqual(self.run_job(jid)['status'],'completed')
    def test_duplicate_references_do_not_consume_download_quota_again(self):
        jid=self.create_job(self.body([GOOD]*8+[GOOD+'?second=1']))
        with patch('worker.BATCH_QUOTA_BYTES',64),patch('safe_fetch.fetch',side_effect=self.mock_fetch) as fetch:
            row=self.run_job(jid)
            self.assertEqual(row['status'],'completed');self.assertEqual(fetch.call_count,2)
        counts=json.loads(row['checkpoint'])['counts']
        self.assertEqual(counts['downloaded'],2);self.assertEqual(counts['already_existing'],7)
    def test_link_limit_number_search_and_invalid_items(self):
        for data in ({'number':'01450/123'},{'urls':[GOOD]*51},{'urls':[]}):
            self.assertEqual(self.client.post('/v1/collection-jobs',headers={**self.h,'Idempotency-Key':app.uid()},json={'input':data}).status_code,422)
        jid=self.create_job(self.body([None,17,'javascript:alert(1)']))
        with patch('safe_fetch.fetch') as fetch:
            self.assertEqual(self.run_job(jid)['status'],'failed');fetch.assert_not_called()
    def test_manual_resolution_finishes_without_fake_download_or_retry(self):
        jid=self.create_job(self.body([LOGIN]))
        with patch('safe_fetch.fetch',side_effect=self.mock_fetch): self.run_job(jid)
        item=self.client.get('/v1/collection-jobs/'+jid+'/links',headers=self.h).json()[0]
        r=self.client.post(f'/v1/collection-jobs/{jid}/links/{item["id"]}/import?name=manual.txt',headers=self.h,content=b'Documento autorizado')
        self.assertEqual(r.status_code,201,r.text)
        row=self.client.get('/v1/collection-jobs/'+jid,headers=self.h).json()
        self.assertEqual(row['status'],'completed')
        counts=json.loads(row['checkpoint'])['counts']
        self.assertEqual(counts['downloaded'],0);self.assertEqual(counts['manually_imported'],1)
    def test_manual_resolution_cannot_bypass_batch_quota(self):
        jid=self.create_job(self.body([LOGIN,LOGIN+'?second=1']))
        with patch('safe_fetch.fetch',side_effect=safe_fetch.FetchError('access_barrier','Importe manualmente')): self.run_job(jid)
        items=self.client.get('/v1/collection-jobs/'+jid+'/links',headers=self.h).json()
        with patch('worker.BATCH_QUOTA_BYTES',12):
            first=self.client.post(f'/v1/collection-jobs/{jid}/links/{items[0]["id"]}/import?name=first.txt',headers=self.h,content=b'Manual A')
            self.assertEqual(first.status_code,201,first.text)
            before=set((app.ROOT/'blobs').iterdir())
            second=self.client.post(f'/v1/collection-jobs/{jid}/links/{items[1]["id"]}/import?name=second.txt',headers=self.h,content=b'Manual B')
            self.assertEqual(second.status_code,413,second.text)
            self.assertEqual(before,set((app.ROOT/'blobs').iterdir()))
        after=self.client.get('/v1/collection-jobs/'+jid+'/links',headers=self.h).json()
        self.assertIsNone(after[1]['revision_id'])
    def test_same_basename_distinct_links_preserve_logical_identity(self):
        jid=self.create_job(self.body([GOOD,GOOD+'?second=1']))
        with patch('safe_fetch.fetch',side_effect=self.mock_fetch): self.run_job(jid)
        items=self.client.get('/v1/collection-jobs/'+jid+'/links',headers=self.h).json()
        self.assertNotEqual(items[0]['revision_id'],items[1]['revision_id'])
        with app.db() as c:
            blobs=[c.execute('SELECT blob FROM revisions WHERE id=?',(item['revision_id'],)).fetchone()[0] for item in items]
            self.assertEqual(blobs[0],blobs[1])
            self.assertEqual(c.execute('SELECT count(*) FROM documents WHERE process_id=?',(self.pid,)).fetchone()[0],2)
            self.assertTrue(all(row['name'].endswith('.txt') for row in c.execute('SELECT name FROM documents WHERE process_id=?',(self.pid,))))
    def test_list_idempotency_and_conflict(self):
        key=app.uid();body=self.body([GOOD,LOGIN])
        jid=self.create_job(body,key=key)
        self.assertEqual(self.create_job(body,key=key),jid)
        response=self.client.post('/v1/collection-jobs',headers={**self.h,'Idempotency-Key':key},json=self.body([GOOD]))
        self.assertEqual(response.status_code,409)
        with app.db() as c: self.assertEqual(c.execute('SELECT count(*) FROM link_items WHERE job_id=?',(jid,)).fetchone()[0],2)
    def test_finished_item_origin_cannot_be_changed(self):
        jid=self.create_job(self.body([GOOD,LOGIN]))
        with patch('safe_fetch.fetch',side_effect=self.mock_fetch): self.run_job(jid)
        item=self.client.get('/v1/collection-jobs/'+jid+'/links',headers=self.h).json()[0]
        self.assertEqual(self.client.patch(f'/v1/collection-jobs/{jid}/links/{item["id"]}',headers=self.h,json={'url':LOGIN}).status_code,409)
    def test_team_reader_can_view_link_results_but_not_resume(self):
        self.grant(role='read')
        jid=self.create_job(self.body([GOOD,LOGIN]))
        with patch('safe_fetch.fetch',side_effect=self.mock_fetch): self.run_job(jid)
        self.assertEqual(self.client.get('/v1/collection-jobs/'+jid+'/links',headers=self.other_h).status_code,200)
        self.assertEqual(self.client.post('/v1/collection-jobs/'+jid+'/resume',headers=self.other_h).status_code,404)
    def test_actual_fetch_pipeline_fixture_not_mocked_fetch(self):
        jid=self.create_job(self.body([GOOD]))
        with patch('safe_fetch.resolve_public',return_value=['8.8.8.8']),patch('safe_fetch.request_once',return_value=(200,{'content-type':'text/plain'},b'Fixture de transporte')):
            row=self.run_job(jid)
        self.assertEqual(row['status'],'completed')
        item=self.client.get('/v1/collection-jobs/'+jid+'/links',headers=self.h).json()[0]
        self.assertEqual(self.client.get('/v1/document-revisions/'+item['revision_id']+'/download',headers=self.h).content,b'Fixture de transporte')
        with app.db() as c:
            capture=c.execute('SELECT * FROM link_captures WHERE item_id=?',(item['id'],)).fetchone()
            self.assertEqual(capture['source_url'],GOOD)
            self.assertEqual(capture['final_url'],GOOD)
