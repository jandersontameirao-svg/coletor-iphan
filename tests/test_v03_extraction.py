import concurrent.futures
import io
import json
import time
from unittest.mock import patch
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
from support import Fixture
import app
import extraction
import task_queue
import worker

class ExtractionTests(Fixture):
    def test_default_reuse_and_explicit_reprocess_preserve_history(self):
        rid=self.upload()['revision_id']
        first=self.client.post('/v1/document-revisions/'+rid+'/extract',headers=self.h).json()
        second=self.client.post('/v1/document-revisions/'+rid+'/extract',headers=self.h).json()
        self.assertEqual(first['run_id'],second['run_id']);self.assertTrue(second['reused'])
        third=self.client.post('/v1/document-revisions/'+rid+'/extract?reprocess=true',headers=self.h).json()
        self.assertNotEqual(third['run_id'],first['run_id'])
        self.assertEqual(self.client.get('/v1/evidence/'+first['evidence'][0]['id'],headers=self.h).status_code,200)
        history=self.client.get('/v1/document-revisions/'+rid+'/extractions',headers=self.h).json()
        self.assertEqual(len(history),2)
        self.assertTrue(all(r['tool'] and r['version'] and r['state']=='completed' for r in history))
    def test_concurrent_async_requests_create_one_job_and_run(self):
        rid=self.upload()['revision_id'];body={'source':'repository','operation':'extract_revision','input':{'revision_id':rid}}
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            jids=list(pool.map(lambda _:self.create_job(body),range(8)))
        self.assertEqual(len(set(jids)),1)
        self.assertEqual(self.run_job(jids[0])['status'],'completed')
        with app.db() as c: self.assertEqual(c.execute('SELECT count(*) FROM extraction_runs WHERE revision_id=?',(rid,)).fetchone()[0],1)
    def test_deduplicated_request_keys_still_reject_different_inputs(self):
        rid=self.upload()['revision_id'];rid2=self.upload(b'outra fonte',name='other.txt')['revision_id']
        body={'source':'repository','operation':'extract_revision','input':{'revision_id':rid}}
        self.create_job(body);key=app.uid();self.create_job(body,key=key)
        response=self.client.post('/v1/collection-jobs',headers={**self.h,'Idempotency-Key':key},json={'source':'repository','operation':'extract_revision','input':{'revision_id':rid2}})
        self.assertEqual(response.status_code,409)
    def test_pdf_without_pages_fails_and_scanned_pdf_signals_ocr(self):
        out=io.BytesIO();writer=PdfWriter();writer.write(out)
        rid=self.upload(out.getvalue(),name='empty.pdf')['revision_id']
        r=self.client.post('/v1/document-revisions/'+rid+'/extract',headers=self.h)
        self.assertEqual(r.status_code,422,r.text)
        self.assertEqual(self.client.get('/v1/document-revisions/'+rid+'/extractions',headers=self.h).json()[0]['state'],'failed')
        out=io.BytesIO();writer=PdfWriter();writer.add_blank_page(width=100,height=100);writer.write(out)
        rid=self.upload(out.getvalue(),name='scan.pdf')['revision_id']
        result=self.client.post('/v1/document-revisions/'+rid+'/extract',headers=self.h).json()
        self.assertTrue(result['ocr_required']);self.assertFalse(result['extractable']);self.assertEqual(result['evidence'],[])
    def test_native_pdf_has_real_page_and_txt_has_no_fictional_page_count(self):
        writer=PdfWriter();page=writer.add_blank_page(width=200,height=200)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 10 50 Td (Evidence PDF) Tj ET')
        page[NameObject('/Contents')]=writer._add_object(stream);out=io.BytesIO();writer.write(out)
        rid=self.upload(out.getvalue(),name='native.pdf')['revision_id']
        result=self.client.post('/v1/document-revisions/'+rid+'/extract',headers=self.h).json()
        self.assertFalse(result['ocr_required']);self.assertEqual(result['pages'],1)
        ev=self.client.get('/v1/evidence/'+result['evidence'][0]['id'],headers=self.h).json()
        self.assertEqual(ev['page'],1);self.assertIn('Evidence PDF',ev['text'])
        rid=self.upload()['revision_id']
        text=self.client.post('/v1/document-revisions/'+rid+'/extract',headers=self.h).json()
        self.assertIsNone(text['pages']);self.assertIsNone(text['evidence'][0]['page'])
    def test_empty_text_is_not_success(self):
        rid=self.upload(b'  \n\t',name='empty.txt')['revision_id']
        self.assertEqual(self.client.post('/v1/document-revisions/'+rid+'/extract',headers=self.h).status_code,422)
    def test_process_limits_timeout_memory_and_cancellation(self):
        rid=self.upload()['revision_id']
        with patch('extraction.TIME_LIMIT',0):
            self.assertEqual(self.client.post('/v1/document-revisions/'+rid+'/extract',headers=self.h).status_code,422)
        with patch('extraction.MEMORY_BYTES',8*1024*1024):
            self.assertEqual(self.client.post('/v1/document-revisions/'+rid+'/extract',headers=self.h).status_code,422)
        with app.db() as c: revision=app.revision_access(c,rid,{'id':self.owner})
        with self.assertRaises(extraction.LostLease):
            extraction.parse(app.ROOT/'blobs'/revision['blob'],revision['mime'],revision['blob'],lambda:(_ for _ in ()).throw(extraction.LostLease()))
    def test_heartbeat_keeps_slow_valid_execution_and_stops_after_cancel(self):
        rid=self.upload()['revision_id'];jid=self.create_job({'source':'repository','operation':'extract_revision','input':{'revision_id':rid}})
        self.only_job(jid)
        with patch('task_queue.LEASE_SECONDS',.5):
            job=task_queue.claim(app.db,app.event,'heartbeat')
            with worker.LeaseKeeper(job) as lease:
                time.sleep(.9);lease.guard()
                self.assertEqual(self.client.post('/v1/collection-jobs/'+jid+'/cancel',headers=self.h).status_code,200)
                with self.assertRaises(extraction.LostLease): lease.guard()
        with app.db() as c: self.assertFalse(task_queue.renew(app.db,job))
    def test_recovered_worker_uses_new_run_and_old_worker_cannot_cancel_it(self):
        rid=self.upload()['revision_id'];jid=self.create_job({'source':'repository','operation':'extract_revision','input':{'revision_id':rid}})
        self.only_job(jid);old=task_queue.claim(app.db,app.event,'old')
        user={'id':self.owner};first=app.reserve_extraction(rid,user,jid,False,old['lease_token'])
        with app.db() as c: c.execute('UPDATE jobs SET lease_until=0 WHERE id=?',(jid,))
        new=task_queue.claim(app.db,app.event,'new');second=app.reserve_extraction(rid,user,jid,False,new['lease_token'])
        self.assertNotEqual(first['id'],second['id'])
        app.fail_extraction(first['id'],'old_worker_lost_lease','cancelled')
        with app.db() as c:
            self.assertEqual(c.execute('SELECT state FROM extraction_runs WHERE id=?',(second['id'],)).fetchone()[0],'running')
            self.assertEqual(c.execute('SELECT state FROM extraction_runs WHERE id=?',(first['id'],)).fetchone()[0],'interrupted')
            self.assertFalse(task_queue.held(c,old));self.assertTrue(task_queue.held(c,new))
        with self.assertRaises(extraction.LostLease): app.reserve_extraction(rid,user,jid,False,old['lease_token'])
    def test_revoked_reader_cannot_get_run_history(self):
        rid=self.upload()['revision_id'];self.client.post('/v1/document-revisions/'+rid+'/extract',headers=self.h)
        grant=self.grant(role='read')
        self.assertEqual(self.client.get('/v1/document-revisions/'+rid+'/extractions',headers=self.other_h).status_code,200)
        self.client.delete(f'/v1/processes/{self.pid}/permissions/{grant}',headers=self.h)
        self.assertEqual(self.client.get('/v1/document-revisions/'+rid+'/extractions',headers=self.other_h).status_code,404)
