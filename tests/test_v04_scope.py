"""Cobertura do escopo real implementado na versão 0.4."""
import json
import unittest
from support import Fixture

KML = b'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>Area licenciada</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
-48.000, -15.000,0 -47.990,-15.000,0 -47.990,-14.990,0 -48.000,-14.990,0 -48.000,-15.000,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>Ponto distante</name><Point><coordinates>-49.000,-16.000,0</coordinates></Point></Placemark>
</Document></kml>'''

KML_V2 = KML.replace(b'Area licenciada', b'Area licenciada revisada')


class V04ScopeTests(Fixture):
    def test_knowledge_assertion_requires_evidence_and_human_review(self):
        document = self.upload('Fonte de evidência conferível'.encode(), self.h, 'evidence.txt')
        extraction = self.client.post('/v1/document-revisions/%s/extract' % document['revision_id'], headers=self.h)
        self.assertEqual(extraction.status_code, 200, extraction.text)
        evidence_id = extraction.json()['evidence'][0]['id']
        created = self.client.post('/v1/knowledge/assertions', headers=self.h, json={
            'process_id': self.pid,
            'evidence_id': evidence_id,
            'statement': 'A fonte registra uma informação verificável.',
            'kind': 'fact',
            'confidence': 0.9,
        })
        self.assertEqual(created.status_code, 201, created.text)
        aid = created.json()['id']
        proposed = self.client.get('/v1/knowledge/assertions/%s' % aid, headers=self.h)
        self.assertEqual(proposed.json()['status'], 'proposed')
        reviewed = self.client.patch('/v1/knowledge/assertions/%s' % aid, headers=self.h, json={'status': 'validated', 'rationale': 'Revisão humana conferiu a página e o trecho.'})
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertEqual(reviewed.json()['status'], 'validated')

    def test_spatial_kml_version_and_metre_search(self):
        created = self.client.post('/v1/spatial-resources', headers=self.h, params={'process_id': self.pid, 'name': 'Área de pesquisa', 'filename': 'area.kml'}, content=KML)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()['version'], 1)
        listed = self.client.get('/v1/spatial-resources', headers=self.h, params={'process_id': self.pid})
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]['feature_count'], 2)
        inside = self.client.post('/v1/spatial-search', headers=self.h, json={'process_id': self.pid, 'latitude': -14.995, 'longitude': -47.995, 'radius_m': 0})
        self.assertEqual(inside.status_code, 200, inside.text)
        self.assertEqual(inside.json()['units'], 'metres')
        self.assertEqual(len(inside.json()['items']), 1)
        self.assertEqual(inside.json()['items'][0]['feature']['name'], 'Area licenciada')
        revised = self.client.post('/v1/spatial-resources/%s/revisions' % created.json()['id'], headers=self.h, params={'filename': 'area-v2.kml'}, content=KML_V2)
        self.assertEqual(revised.status_code, 201, revised.text)
        self.assertEqual(revised.json()['version'], 2)
        detail = self.client.get('/v1/spatial-resources/%s' % created.json()['id'], headers=self.h)
        self.assertEqual(len(detail.json()['revisions']), 2)

    def test_scope_capabilities_are_explicit(self):
        capabilities = self.client.get('/v1/capabilities', headers=self.h)
        self.assertEqual(capabilities.status_code, 200)
        data = capabilities.json()
        self.assertEqual(data['version'], '0.4.0')
        self.assertTrue(data['spatial_search'])
        self.assertTrue(data['knowledge_assertions'])
        self.assertFalse(data['automatic_facts'])
        self.assertIn('available', data['ocr'])
        integration = self.client.get('/v1/integration/capabilities', headers=self.h)
        self.assertFalse(integration.json()['atena_real_homologated'])
        self.assertFalse(integration.json()['geoportal_real_homologated'])


if __name__ == '__main__':
    unittest.main()
