import json
import os
from unittest.mock import patch
from support import Fixture
import ai_classifier


class TramitacaoTests(Fixture):
    def _doc(self, text=b'conteudo do documento', name='doc.txt'):
        return self.upload(text, name=name)

    def test_create_and_approval_requires_manifestation(self):
        d = self._doc()
        r = self.client.post('/v1/processes/' + self.pid + '/tramitacao', headers=self.h,
                             json={'requirement': 'Apresentar PGPA', 'study_type': 'PGPA', 'situation': 'solicitado'})
        self.assertEqual(r.status_code, 201, r.text)
        tid = r.json()['id']
        # "apresentação não equivale a aprovação": aprovar sem manifestação é barrado.
        bad = self.client.patch('/v1/tramitacao/' + tid, headers=self.h, json={'situation': 'aprovado'})
        self.assertEqual(bad.status_code, 422)
        # Com o documento de manifestação vinculado, aprova.
        ok = self.client.patch('/v1/tramitacao/' + tid, headers=self.h,
                              json={'situation': 'aprovado', 'manifestation_doc_id': d['document_id']})
        self.assertEqual(ok.status_code, 200, ok.text)
        lst = self.client.get('/v1/processes/' + self.pid + '/tramitacao', headers=self.h).json()
        self.assertEqual(lst[0]['situation'], 'aprovado')
        self.assertEqual(lst[0]['manifestation_doc_id'], d['document_id'])

    def test_create_approved_directly_requires_manifestation(self):
        r = self.client.post('/v1/processes/' + self.pid + '/tramitacao', headers=self.h,
                             json={'requirement': 'X', 'situation': 'aprovado'})
        self.assertEqual(r.status_code, 422)

    def test_link_doc_from_other_process_rejected(self):
        r = self.client.post('/v1/processes/' + self.pid + '/tramitacao', headers=self.h,
                             json={'requirement': 'X', 'situation': 'solicitado', 'requirement_doc_id': 'nao-existe'})
        self.assertEqual(r.status_code, 422)

    def test_ai_suggests_requirements_as_pending(self):
        rev = self._doc(b'O IPHAN exige a apresentacao do PGPA e a complementacao do RAIPI.', name='tre.txt')
        self.client.post('/v1/document-revisions/' + rev['revision_id'] + '/extract', headers=self.h)

        def fake(key, model, messages):
            self.assertIn('IPHAN', messages[-1]['content'])
            return json.dumps({'exigencias': [{'exigencia': 'Apresentar PGPA', 'estudo': 'PGPA'},
                                               {'exigencia': 'Complementar RAIPI', 'estudo': 'RAIPI'}]})

        with patch.dict(os.environ, {'OPENAI_API_KEY': 'k'}), patch.object(ai_classifier, '_complete', side_effect=fake):
            s = self.client.post('/v1/processes/' + self.pid + '/tramitacao/suggest', headers=self.h)
        self.assertEqual(s.status_code, 200, s.text)
        self.assertEqual(s.json()['total'], 2)
        lst = self.client.get('/v1/processes/' + self.pid + '/tramitacao', headers=self.h).json()
        self.assertEqual(len(lst), 2)
        self.assertTrue(all(x['situation'] == 'pendente' and x['source'] == 'ia' for x in lst))

    def test_suggest_requires_ai_configured(self):
        rev = self._doc()
        self.client.post('/v1/document-revisions/' + rev['revision_id'] + '/extract', headers=self.h)
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            s = self.client.post('/v1/processes/' + self.pid + '/tramitacao/suggest', headers=self.h)
        self.assertEqual(s.status_code, 503)

    def test_suggest_without_evidence_does_not_call_ai(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'k'}), patch.object(ai_classifier, '_complete') as complete:
            s = self.client.post('/v1/processes/' + self.pid + '/tramitacao/suggest', headers=self.h)
        self.assertEqual(s.status_code, 409)
        complete.assert_not_called()
