import io,json,time,zipfile
from unittest.mock import patch
from support import Fixture
import app
import archive_policy as policy
import sharepoint_store as cloud
import geo_domain as geo
import sei_public,safe_fetch

class BridgeTests(Fixture):
    def test_raipi_and_ambiguous_classification(self):
        self.assertEqual(policy.category('8765432_RAIPI.pdf')[0],'RAIPI')
        self.assertEqual(policy.relative_folder('01422.000120/2011-70','RAIPI'),'01422.000120-2011-70/Documentos/RAIPI')
        self.assertEqual(policy.category('PAIPA e RAIPA.pdf')[0],'A classificar')
        self.assertEqual(policy.category('mapa.kml')[0],'Georreferenciados')
    def test_archive_blocks_traversal_and_preserves_shapefile_bundle(self):
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z:z.writestr('../evil.txt','x')
        with self.assertRaises(ValueError):policy.inspect_zip(raw.getvalue())
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z:z.writestr('sitios/a.shp',b'x');z.writestr('sitios/a.dbf',b'x')
        self.assertEqual(policy.category('anexo.zip',data=raw.getvalue())[0],'Georreferenciados')
    def test_native_html_preserved_acl_and_queued(self):
        raw=b'<html><body>Documento SEI original</body></html>';r=self.upload(raw,name='8765432_RAIPI.html')
        item=next(i for i in self.client.get('/v1/bridge/library?category=RAIPI',headers=self.h).json()['items'] if i['revision_id']==r['revision_id'])
        self.assertEqual(item['sharepoint']['status'],'queued')
        self.assertEqual(self.client.get(item['download_url'],headers=self.h).content,raw)
        self.assertEqual(self.client.get('/v1/bridge/library',headers=self.other_h).json()['total'],0)
    def test_native_sei_html_download_and_barrier(self):
        url='https://sei.iphan.gov.br/sei/modulos/pesquisa/md_pesq_documento_consulta_externa.php?x'
        with patch('safe_fetch.resolve_public',return_value=['8.8.8.8']),patch('safe_fetch.request_once',return_value=(200,{'content-type':'text/html'},b'<html><body>SEI documento</body></html>')):
            self.assertEqual(safe_fetch.fetch(url)['mime'],'text/html')
        with patch('safe_fetch.resolve_public',return_value=['8.8.8.8']),patch('safe_fetch.request_once',return_value=(200,{'content-type':'text/html'},b'<html>captcha</html>')):
            with self.assertRaises(safe_fetch.FetchError):safe_fetch.fetch(url)
    def test_line_hole_and_missing_srs(self):
        f={'geometries':[{'type':'LineString','coordinates':[[-1,0],[1,0]]}]}
        self.assertAlmostEqual(geo.feature_distance_m(f,[0,0]),0,places=4)
        k=b'<kml><Placemark><Polygon><outerBoundaryIs><LinearRing><coordinates>-2,-2 2,-2 2,2 -2,2 -2,-2</coordinates></LinearRing></outerBoundaryIs><innerBoundaryIs><LinearRing><coordinates>-1,-1 -1,1 1,1 1,-1 -1,-1</coordinates></LinearRing></innerBoundaryIs></Polygon></Placemark></kml>'
        self.assertGreater(geo.feature_distance_m(geo.parse_kml(k)['features'][0],[0,0]),0)
        with self.assertRaises(ValueError):geo._check_prj(None)
    def test_equal_sei_dates_keep_unit(self):
        page=b'Pesquisa Processual<table><tr><td>Processo:</td><td>01422.000120/2011-70</td></tr></table><table id="tblDocumentos"><tr><td>1234567</td><td>Parecer</td><td>01/01/2026</td><td>01/01/2026</td><td>COTEC</td></tr></table>'
        url='https://sei.iphan.gov.br/sei/modulos/pesquisa/md_pesq_processo_exibir.php?x'
        self.assertEqual(sei_public.parse_process_page(page,url)['documents'][0]['unit'],'COTEC')
    def test_discovered_metadata_hidden_after_acl_revoked(self):
        jid=self.create_job({'source':'iphan','operation':'collect_links','input':{'urls':['https://www.gov.br/iphan/a.txt']}})
        with app.db() as c:
            c.execute('UPDATE link_items SET process_id=? WHERE job_id=?',(self.pid,jid))
            c.execute('UPDATE resource_grants SET active=0 WHERE process_id=? AND subject_id=?',(self.pid,self.owner))
        self.assertEqual(self.client.get('/v1/collection-jobs/'+jid+'/links',headers=self.h).status_code,404)
        with app.db() as c:
            import authorization
            self.assertFalse(authorization.job_authorized(c,dict(c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())))
    def test_unconfigured_cloud_never_fakes_confirmation(self):
        self.upload(name='RAIPI.txt')
        with app.db() as c:c.execute('UPDATE bridge_settings SET checked=NULL')
        self.assertFalse(cloud.sync_once(app))
    def test_token_encryption_and_destination(self):
        cloud.save_tokens(app.db,app.ROOT,{'access_token':'synthetic-access','refresh_token':'synthetic-refresh','expires_in':3600})
        with app.db() as c:self.assertNotIn('synthetic',c.execute('SELECT ciphertext FROM bridge_credentials').fetchone()[0])
        self.assertEqual(cloud.access_token(app.db,app.ROOT),'synthetic-access')
        with self.assertRaises(cloud.CloudError):cloud.validate_folder('https://evil.example/test')
        with self.assertRaises(cloud.CloudError):cloud.validate_folder('http://arqueogis.sharepoint.com/a')
    def test_verified_transfer_and_hash_failure(self):
        revision=self.upload(b'RAIPI preservado',name='1234567_RAIPI.txt')
        with app.db() as c:
            c.execute('UPDATE bridge_settings SET checked=?,drive_id=?,folder_id=?',(time.time(),'drive-fixture','root-fixture'))
            c.execute("UPDATE cloud_transfers SET status='cancelled' WHERE revision_id!=?",(revision['revision_id'],))
        with patch.object(cloud.Graph,'ensure_folder',return_value='folder') as folder,patch.object(cloud.Graph,'put',return_value={'id':'remote','size':len(b'RAIPI preservado'),'webUrl':'https://arqueogis.sharepoint.com/file'}) as put,patch.object(cloud.Graph,'verify',return_value={}) as verify:
            self.assertTrue(cloud.sync_once(app));verify.assert_called_once()
            self.assertEqual(put.call_args.args[3],b'RAIPI preservado')
            self.assertIn('RAIPI',[call.args[2] for call in folder.call_args_list])
        with app.db() as c:
            row=c.execute('SELECT * FROM cloud_transfers WHERE revision_id=?',(revision['revision_id'],)).fetchone()
            self.assertEqual(row['status'],'uploaded');self.assertIn('/Documentos/RAIPI/',row['remote_path'])
            c.execute("UPDATE cloud_transfers SET status='queued',attempts=0 WHERE revision_id=?",(revision['revision_id'],))
        with patch.object(cloud.Graph,'ensure_folder',return_value='folder'),patch.object(cloud.Graph,'request',return_value={'id':'remote','size':len(b'RAIPI preservado')}),patch.object(cloud.Graph,'put',return_value={'id':'remote','size':len(b'RAIPI preservado')}),patch.object(cloud.Graph,'verify',side_effect=cloud.CloudError('remote_integrity_mismatch')):
            cloud.sync_once(app)
        with app.db() as c:self.assertNotEqual(c.execute('SELECT status FROM cloud_transfers WHERE revision_id=?',(revision['revision_id'],)).fetchone()[0],'uploaded')
        self.assertTrue((app.ROOT/'blobs'/revision['sha256']).is_file())
    def test_four_tabs_and_human_category_history(self):
        self.assertEqual(self.client.get('/').text.count('data-tab='),4)
        revision=self.upload(name='desconhecido.txt');did=revision['document_id']
        r=self.client.patch('/v1/bridge/documents/'+did+'/category',headers=self.h,json={'category':'RAIPI'})
        self.assertEqual(r.status_code,200,r.text)
        with app.db() as c:self.assertEqual(c.execute('SELECT category FROM archive_label_history WHERE document_id=?',(did,)).fetchone()[0],'RAIPI')
    def test_graph_rejects_absolute_bearer_destination(self):
        with self.assertRaises(cloud.CloudError):cloud.Graph(app.db,app.ROOT).request('GET','https://evil.example')

    def page_fixture(self,restricted=True,truncated=False):
        return {'source_url':'https://sei.iphan.gov.br/sei/modulos/pesquisa/md_pesq_processo_exibir.php?fixture','number':self.number,'title':'Processo de teste','process_type':'Teste','interested':'Teste','document_total':1,'public_documents':0 if restricted else 1,'restricted_documents':1 if restricted else 0,'page_restricted_notice':restricted,'truncated':truncated,'documents':[] if truncated else [{'document_number':'1234567','title':'RAIPI','date':'01/01/2026','included_at':'01/01/2026','unit':'COTEC','url':None if restricted else 'https://sei.iphan.gov.br/sei/modulos/pesquisa/md_pesq_documento_consulta_externa.php?fixture'}]}

    def test_restricted_resume_never_downloads_placeholder_and_manual_finishes(self):
        page=self.page_fixture();jid=self.create_job({'source':'iphan','operation':'collect_links','input':{'urls':[page['source_url']],'process_id':self.pid}})
        with patch('sei_public.fetch_process_page',return_value=page),patch('safe_fetch.fetch') as fetch:
            self.assertEqual(self.run_job(jid)['status'],'waiting_for_user');fetch.assert_not_called()
        self.assertEqual(self.client.post('/v1/collection-jobs/'+jid+'/resume',headers=self.h,json={}).status_code,202)
        with patch('safe_fetch.fetch') as fetch:
            self.run_job(jid);fetch.assert_not_called()
        with app.db() as c:item=c.execute("SELECT id FROM link_items WHERE job_id=? AND kind='sei_document'",(jid,)).fetchone()[0]
        r=self.client.post('/v1/collection-jobs/'+jid+'/links/'+item+'/import?name=RAIPI.txt',headers=self.h,content=b'Original autorizado')
        self.assertEqual(r.status_code,201,r.text)
        self.assertEqual(self.client.get('/v1/collection-jobs/'+jid,headers=self.h).json()['status'],'completed')

    def test_page_truncation_is_never_completed(self):
        page=self.page_fixture(truncated=True);jid=self.create_job({'source':'iphan','operation':'collect_links','input':{'urls':[page['source_url']],'process_id':self.pid}})
        with patch('sei_public.fetch_process_page',return_value=page):self.assertEqual(self.run_job(jid)['status'],'waiting_for_user')

    def test_new_revision_invalidates_old_analysis(self):
        r=self.upload(name='RAIPI.txt')
        self.assertEqual(self.client.post('/v1/document-revisions/'+r['revision_id']+'/extract',headers=self.h).status_code,200)
        self.assertEqual(self.client.post('/v1/documents/'+r['document_id']+'/classifications',headers=self.h,json={'revision_id':r['revision_id'],'study_type':'RAIPI','status':'validated'}).status_code,201)
        self.upload(b'Nova revisao ainda sem analise',name='RAIPI.txt')
        item=next(i for i in self.client.get('/v1/analysis/processes',headers=self.h).json()['items'] if i['process_id']==self.pid)
        self.assertNotEqual(item['status'],'analyzed');self.assertEqual(item['extracted_documents'],0)

    def test_two_restricted_documents_preserve_distinct_identity(self):
        page=self.page_fixture();page['documents'].append({**page['documents'][0],'document_number':'7654321','title':'PAIPA'})
        page.update(document_total=2,restricted_documents=2)
        jid=self.create_job({'source':'iphan','operation':'collect_links','input':{'urls':[page['source_url']],'process_id':self.pid}})
        with patch('sei_public.fetch_process_page',return_value=page):self.run_job(jid)
        with app.db() as c:items=c.execute("SELECT id FROM link_items WHERE job_id=? AND kind='sei_document' ORDER BY position",(jid,)).fetchall()
        revisions=[]
        for i,item in enumerate(items):
            r=self.client.post('/v1/collection-jobs/'+jid+'/links/'+item['id']+'/import?name=original.txt',headers=self.h,content=('Original '+str(i)).encode())
            self.assertEqual(r.status_code,201,r.text);revisions.append(r.json()['document_id'])
        self.assertNotEqual(*revisions)
