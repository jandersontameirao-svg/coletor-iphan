import io,json,zipfile
from unittest.mock import patch
from support import Fixture
import app,market_domain as market,market_extract as rules

ADMIN='Empreendedor: Energia Exemplo Ltda\nCNPJ: 11.444.777/0001-61\nE-mail: contato@energia.example\nConsultoria ambiental: Ambiente Exemplo Ltda\nRepresentante legal: Maria Teste\n'
TECH='Contratante: Energia Exemplo SA\nCNPJ: 11.444.777/0001-61\nConsultoria arqueológica: Arqueologia Exemplo Ltda\nResponsável técnico: Ana Teste\nTelefone: (61) 99999-1234\n'

class MarketTests(Fixture):
    def process(self,*revisions):
        with app.db() as c:
            c.execute("UPDATE market_jobs SET state='cancelled' WHERE state='queued'")
            for r in revisions:c.execute("UPDATE market_jobs SET state='queued' WHERE revision_id=?",(r['revision_id'],))
        for r in revisions:self.assertTrue(market.run_once(app))
        return self.client.get('/v1/market/processes/'+self.pid,headers=self.h).json()

    def test_explicit_roles_do_not_infer_client_from_mentions(self):
        facts=rules.extract([(3,TECH+'\nOfício cita Outras Empresas.\n')])
        self.assertEqual({f['role'] for f in facts if f['field']=='participation'},{'contratante_declarado','consultoria_arqueologica','responsavel_tecnico'})
        self.assertTrue(all(f['page']==3 and f['quote'] for f in facts))
        self.assertFalse(any(f['role']=='cliente_final_declarado' for f in facts))
        self.assertEqual(rules.extract([(None,'Empreendedor\nEnergia Exemplo Ltda')])[0]['name'],'Energia Exemplo Ltda')

    def test_numeric_identifier_and_contacts_are_conservative(self):
        self.assertEqual(rules.cnpj_digits('11.444.777/0001-61'),'11444777000161')
        self.assertIsNone(rules.cnpj_digits('11.444.777/0001-62'))
        f=rules.extract([(None,'E-mail: geral@empresa.example\n')])[0]
        self.assertEqual(f['association'],'unassigned');self.assertEqual(f['role'],'unassigned')

    def test_administrative_technical_crossing_preserves_evidence(self):
        a=self.upload(ADMIN.encode(),name='1234567_FCA.txt');b=self.upload(TECH.encode(),name='7654321_RAIPI.txt')
        data=self.process(a,b)
        group=next(g for g in data['cross_references'] if g['cnpj']=='11444777000161')
        self.assertTrue(group['crosses_administrative_technical'])
        self.assertEqual(set(group['roles']),{'empreendedor','contratante_declarado'})
        self.assertEqual(len(group['documents']),2)
        fact=next(f for f in data['facts'] if f['role']=='empreendedor' and f['field']=='participation')
        self.assertIn('CNPJ',fact['quote']);self.assertIsNone(fact['page']);self.assertEqual(fact['sha256'],a['sha256'])
        self.assertTrue(fact['sources']);self.assertEqual(fact['review_status'],'proposed')
        self.assertEqual(self.client.get('/v1/market/processes/'+self.pid,headers=self.other_h).status_code,404)

    def test_review_and_revocation_never_expose_fact(self):
        r=self.upload(ADMIN.encode(),name='FCA.txt');data=self.process(r);f=data['facts'][0]
        response=self.client.patch('/v1/market/facts/'+f['id'],headers=self.other_h,json={'status':'validated','rationale':'Conferido na fonte'})
        self.assertEqual(response.status_code,404)
        self.assertEqual(self.client.patch('/v1/market/facts/'+f['id'],headers=self.h,json={'status':'validated','rationale':'Conferido na fonte'}).status_code,200)
        with app.db() as c:c.execute('UPDATE resource_grants SET active=0 WHERE process_id=? AND subject_id=?',(self.pid,self.owner))
        self.assertEqual(self.client.get('/v1/market/facts/'+f['id'],headers=self.h).status_code,404)

    def test_rejected_participation_is_excluded_from_crossing(self):
        r=self.upload(ADMIN.encode(),name='FCA.txt');data=self.process(r)
        f=next(f for f in data['facts'] if f['role']=='empreendedor' and f['field']=='participation')
        self.client.patch('/v1/market/facts/'+f['id'],headers=self.h,json={'status':'rejected','rationale':'Nome identificado incorretamente'})
        current=self.client.get('/v1/market/processes/'+self.pid,headers=self.h).json()
        self.assertFalse(any('empreendedor' in g['roles'] for g in current['cross_references']))
        self.assertEqual(self.client.get('/v1/market/facts/'+f['id'],headers=self.h).json()['quote'],f['quote'])

    def test_new_revision_preserves_history_without_current_old_assertions(self):
        r=self.upload(ADMIN.encode(),name='FCA.txt');self.process(r)
        new=self.upload(b'Empreendedor: Outro Empreendedor Ltda',name='FCA.txt');self.process(new)
        data=self.client.get('/v1/market/processes/'+self.pid,headers=self.h).json()
        self.assertTrue(all(f['revision_id']==new['revision_id'] for f in data['facts']))
        history=self.client.get('/v1/market/processes/'+self.pid+'?history=true',headers=self.h).json()
        self.assertTrue(any(not f['is_current'] for f in history['facts']))

    def test_reprocessing_is_explicit_and_previous_results_immutable(self):
        r=self.upload(ADMIN.encode(),name='FCA.txt');data=self.process(r);ids={f['id'] for f in data['facts']}
        response=self.client.post('/v1/market/processes/'+self.pid+'/extract',headers=self.h,json={'reprocess':True})
        self.assertEqual(response.status_code,202)
        with app.db() as c:
            for j in response.json()['jobs']:c.execute("UPDATE market_jobs SET state='queued' WHERE id=?",(j,))
        market.run_once(app)
        history=self.client.get('/v1/market/processes/'+self.pid+'?history=true',headers=self.h).json()
        self.assertTrue(ids<={f['id'] for f in history['facts']})
        self.assertTrue(any(not f['is_current'] for f in history['facts']))

    def test_html_fields_are_extracted_without_running_scripts(self):
        raw=b'<html><script>Empreendedor: Evil</script><p>Empreendedor: Energia Exemplo Ltda</p><p>Responsavel tecnico: Ana Teste</p></html>'
        r=self.upload(raw,name='FCA.html');data=self.process(r)
        self.assertTrue(any(f['name']=='Ana Teste' for f in data['facts']))
        self.assertFalse(any(f['name']=='Evil' for f in data['facts']))

    def test_unsupported_archive_does_not_block_original_or_transfer(self):
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:z.writestr('notas.txt',ADMIN)
        r=self.upload(buf.getvalue(),name='anexos.zip');data=self.process(r)
        self.assertEqual(data['runs'][-1]['state'],'not_supported')
        self.assertFalse(data['facts'])
        self.assertEqual(self.client.get('/v1/document-revisions/'+r['revision_id']+'/download',headers=self.h).content,buf.getvalue())
        with app.db() as c:self.assertTrue(c.execute('SELECT 1 FROM cloud_transfers WHERE revision_id=?',(r['revision_id'],)).fetchone())

    def test_revocation_during_processing_fences_commit(self):
        r=self.upload(ADMIN.encode(),name='FCA.txt')
        with app.db() as c:
            c.execute("UPDATE market_jobs SET state='cancelled' WHERE state='queued'");c.execute("UPDATE market_jobs SET state='queued' WHERE revision_id=?",(r['revision_id'],))
        def revoke(*args):
            with app.db() as c:c.execute('UPDATE resource_grants SET active=0 WHERE process_id=? AND subject_id=?',(self.pid,self.owner))
            return [(1,ADMIN)]
        with patch('market_domain.extraction.parse',side_effect=revoke):market.run_once(app)
        with app.db() as c:
            j=c.execute('SELECT * FROM market_jobs WHERE revision_id=?',(r['revision_id'],)).fetchone()
            self.assertEqual(j['state'],'cancelled');self.assertFalse(c.execute('SELECT 1 FROM market_facts WHERE run_id=?',(j['id'],)).fetchone())

    def test_same_names_without_id_are_candidates(self):
        f={'id':'a','name':'Empresa Exemplo','kind':'organization','field':'participation','role':'empreendedor','cnpj':None,'review_status':'proposed','is_current':True,'family':'administrative','document_id':'d'}
        g=rules.cross_reference([f,{**f,'id':'b','family':'technical','document_id':'e','role':'executora'}])[0]
        self.assertEqual(g['identity_basis'],'name_only_candidate')
        self.assertFalse('contratante_declarado' in g['roles'])

    def test_pdf_source_retains_real_page(self):
        r=self.upload(b'%PDF-1.4 fixture',name='RAIPA.pdf')
        with patch('market_domain.extraction.parse',return_value=[(4,TECH)]):data=self.process(r)
        self.assertTrue(data['facts']);self.assertTrue(all(f['page']==4 for f in data['facts']))
