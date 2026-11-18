import json
import os
from unittest.mock import patch
from support import Fixture
import ai_classifier

GEOJSON = json.dumps({'type': 'FeatureCollection', 'features': [
    {'type': 'Feature', 'properties': {'name': 'Ponto'}, 'geometry': {'type': 'Point', 'coordinates': [-47.995, -14.995]}},
]}).encode()


class SpatialTypologyTests(Fixture):
    def _resource(self):
        r = self.client.post('/v1/spatial-resources', headers=self.h,
                             params={'process_id': self.pid, 'name': 'Área X', 'filename': 'area.json'}, content=GEOJSON)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()['id']

    def _search(self, validated_only):
        return self.client.post('/v1/spatial-search', headers=self.h, json={
            'process_id': self.pid, 'latitude': -14.995, 'longitude': -47.995, 'radius_m': 0, 'validated_only': validated_only}).json()['items']

    def test_ai_suggests_then_human_validates_and_geoportal_filters(self):
        rid = self._resource()

        def fake(key, model, messages):
            # O contexto precisa conter o nome do recurso.
            self.assertIn('Área X', messages[-1]['content'])
            return json.dumps({'tipologia': 'sitio_identificado', 'justificativa': 'trecho menciona sítio', 'confianca': 0.8})

        with patch.dict(os.environ, {'OPENAI_API_KEY': 'k'}), patch.object(ai_classifier, '_complete', side_effect=fake):
            s = self.client.post('/v1/spatial-resources/' + rid + '/suggest-typology', headers=self.h)
        self.assertEqual(s.status_code, 200, s.text)
        self.assertEqual(s.json()['typology'], 'sitio_identificado')
        self.assertEqual(s.json()['status'], 'pendente')  # IA só sugere; fica pendente
        # Antes de validar, o Geoportal (validated_only) NÃO enxerga a referência.
        self.assertEqual(self._search(True), [])
        # Humano confirma.
        v = self.client.patch('/v1/spatial-resources/' + rid + '/typology', headers=self.h,
                              json={'typology': 'sitio_identificado', 'status': 'validado', 'rationale': 'confirmo'})
        self.assertEqual(v.status_code, 200, v.text)
        items = self._search(True)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['typology'], 'sitio_identificado')
        self.assertEqual(items[0]['typology_status'], 'validado')

    def test_suggest_requires_ai_configured(self):
        rid = self._resource()
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            s = self.client.post('/v1/spatial-resources/' + rid + '/suggest-typology', headers=self.h)
        self.assertEqual(s.status_code, 503)

    def test_cannot_validate_as_nao_classificado(self):
        rid = self._resource()
        v = self.client.patch('/v1/spatial-resources/' + rid + '/typology', headers=self.h,
                              json={'typology': 'nao_classificado', 'status': 'validado'})
        self.assertEqual(v.status_code, 422)

    def test_search_without_validated_only_still_returns_pending(self):
        self._resource()
        # Busca interna (sem a trava) continua vendo tudo, inclusive pendente.
        self.assertEqual(len(self._search(False)), 1)
