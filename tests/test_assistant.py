import json
import os
import re
from unittest.mock import patch
from support import Fixture
import app
import ai_classifier


class AssistantSearchTests(Fixture):
    def _ingest(self, text, name='relatorio.txt', headers=None):
        rev = self.upload(text, headers=headers or self.h, name=name)
        r = self.client.post('/v1/document-revisions/' + rev['revision_id'] + '/extract', headers=headers or self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return rev

    def test_rag_answers_from_content_and_filters_invented_sources(self):
        rev = self._ingest(b'O sitio arqueologico de Pedra Furada contem pinturas rupestres pre-historicas.')

        def fake_complete(key, model, messages):
            content = messages[-1]['content']
            # O conteúdo do arquivo precisa ter chegado à IA:
            self.assertIn('Pedra Furada', content)
            did = re.search(r'document_id: (\S+)', content).group(1)
            # A IA cita o document_id real e um inventado; o inventado deve ser filtrado pelo endpoint.
            return json.dumps({'resposta': 'O sitio de Pedra Furada tem pinturas rupestres.',
                               'fontes': [{'document_id': did, 'pagina': 1},
                                          {'document_id': 'inventado-999', 'pagina': 2}]})

        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}), patch.object(ai_classifier, '_complete', side_effect=fake_complete):
            res = self.client.post('/v1/assistant/search', headers=self.h,
                                   json={'question': 'onde ficam as pinturas rupestres do sitio Pedra Furada?'})
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertIn('Pedra Furada', body['resposta'])
        self.assertEqual(body['trechos_considerados'], 1)
        self.assertEqual([f['document_id'] for f in body['fontes']], [rev['document_id']])
        # A fonte precisa permitir ABRIR O ARQUIVO em si (baixar o original), não só citar o nome.
        fonte = body['fontes'][0]
        self.assertEqual(fonte['revision_id'], rev['revision_id'])
        self.assertEqual(fonte['download_url'], '/v1/document-revisions/' + rev['revision_id'] + '/download')
        got = self.client.get(fonte['download_url'], headers=self.h)
        self.assertEqual(got.status_code, 200, got.text)
        self.assertIn(b'Pedra Furada', got.content)

    def test_rag_without_matches_does_not_call_ai(self):
        self._ingest(b'Relatorio sobre ceramica marajoara.')
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}), patch.object(ai_classifier, '_complete') as complete:
            res = self.client.post('/v1/assistant/search', headers=self.h,
                                   json={'question': 'termoinexistentexyz outrozzz'})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()['trechos_considerados'], 0)
        complete.assert_not_called()

    def test_rag_respects_acl(self):
        self._ingest(b'Documento confidencial sobre o sitio Lagoa Santa.')
        # self.other (operator) não recebeu permissão no processo self.pid.
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}), patch.object(ai_classifier, '_complete') as complete:
            res = self.client.post('/v1/assistant/search', headers=self.other_h,
                                   json={'question': 'o que diz sobre Lagoa Santa?'})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()['trechos_considerados'], 0)
        complete.assert_not_called()

    def test_rag_requires_ai_configured(self):
        self._ingest(b'texto qualquer sobre o sitio')
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            res = self.client.post('/v1/assistant/search', headers=self.h,
                                   json={'question': 'algo sobre o sitio'})
        self.assertEqual(res.status_code, 503)
