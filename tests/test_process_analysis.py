import unittest
from support import Fixture


class ProcessAnalysisTests(Fixture):
    def test_process_without_documents_is_not_started(self):
        response = self.client.get('/v1/analysis/processes', headers=self.h)
        self.assertEqual(response.status_code, 200)
        item = next(row for row in response.json()['items'] if row['process_id'] == self.pid)
        self.assertEqual(item['status'], 'not_started')
        self.assertEqual(item['progress_percent'], 0)

    def test_process_becomes_analyzed_only_after_extraction_and_validated_classification(self):
        document = self.upload(b'Fonte rastreavel para analise', self.h, 'analysis.txt')
        pending = self.client.get('/v1/analysis/processes', headers=self.h).json()
        item = next(row for row in pending['items'] if row['process_id'] == self.pid)
        self.assertEqual(item['status'], 'pending')
        extraction = self.client.post('/v1/document-revisions/%s/extract' % document['revision_id'], headers=self.h)
        self.assertEqual(extraction.status_code, 200, extraction.text)
        mid = self.client.get('/v1/analysis/processes', headers=self.h).json()
        item = next(row for row in mid['items'] if row['process_id'] == self.pid)
        self.assertEqual(item['status'], 'in_progress')
        classification = self.client.post('/v1/documents/%s/classifications' % document['document_id'], headers=self.h, json={'revision_id': document['revision_id'], 'study_type': 'PAPIPA', 'status': 'validated', 'notes': 'Revisado'})
        self.assertEqual(classification.status_code, 201, classification.text)
        final = self.client.get('/v1/analysis/processes', headers=self.h).json()
        item = next(row for row in final['items'] if row['process_id'] == self.pid)
        self.assertEqual(item['status'], 'analyzed')
        self.assertEqual(item['extracted_documents'], 1)
        self.assertEqual(item['classified_documents'], 1)
        self.assertEqual(item['progress_percent'], 100)
        self.assertEqual(final['totals']['analyzed'], 1)


if __name__ == '__main__':
    unittest.main()
