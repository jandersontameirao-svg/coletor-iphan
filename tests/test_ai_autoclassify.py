from unittest.mock import patch

from support import Fixture
import app
import ai_autoclassify


class AutoClassifyTests(Fixture):
    def _drain_pending(self):
        # Neutraliza documentos 'A classificar' de outros testes (o banco é compartilhado no processo).
        with app.db() as c:
            c.execute("UPDATE archive_labels SET method='ai_skipped' WHERE category='A classificar' AND method IN ('no_explicit_type','ambiguous_acronyms')")

    def _label(self, did):
        with app.db() as c:
            return dict(c.execute('SELECT category,method FROM archive_labels WHERE document_id=?', (did,)).fetchone())

    def test_high_confidence_is_applied_and_upload_redirected(self):
        self._drain_pending()
        up = self.upload(name='trecho_sem_sigla.pdf', data=b'%PDF-1.4 relatorio de pesquisa')
        did = up['document_id']
        self.assertEqual(self._label(did)['category'], 'A classificar')
        with patch.object(ai_autoclassify.ai_classifier, 'available', return_value=True), \
             patch.object(ai_autoclassify.ai_classifier, 'auto_classify', return_value={'category': 'RAIPI', 'confidence': 0.95}), \
             patch.object(app, 'document_text', return_value='texto extraido do relatorio'):
            acted = ai_autoclassify.run_once(app)
        self.assertTrue(acted)
        label = self._label(did)
        self.assertEqual(label['category'], 'RAIPI')
        self.assertEqual(label['method'], 'ai_auto')
        # O upload pendente é redirecionado para a pasta certa (quando há transferência enfileirada).
        with app.db() as c:
            row = c.execute("SELECT t.category FROM cloud_transfers t JOIN revisions r ON r.id=t.revision_id WHERE r.document_id=?", (did,)).fetchone()
        if row:
            self.assertEqual(row['category'], 'RAIPI')

    def test_low_confidence_stays_for_human_review(self):
        self._drain_pending()
        up = self.upload(name='outro_sem_sigla.pdf', data=b'%PDF-1.4 conteudo ambiguo')
        did = up['document_id']
        with patch.object(ai_autoclassify.ai_classifier, 'available', return_value=True), \
             patch.object(ai_autoclassify.ai_classifier, 'auto_classify', return_value=None), \
             patch.object(app, 'document_text', return_value='texto ambiguo sem evidencia'):
            acted = ai_autoclassify.run_once(app)
            second = ai_autoclassify.run_once(app)  # não reprocessa o já tentado
        self.assertTrue(acted)
        self.assertFalse(second)
        label = self._label(did)
        self.assertEqual(label['category'], 'A classificar')
        self.assertEqual(label['method'], 'ai_skipped')

    def test_human_reviewed_is_never_touched(self):
        self._drain_pending()
        up = self.upload(name='revisado_sem_sigla.pdf', data=b'%PDF-1.4 revisado por humano')
        did = up['document_id']
        r = self.client.patch(f'/v1/bridge/documents/{did}/category', headers=self.h, json={'category': 'FCA'})
        self.assertEqual(r.status_code, 200, r.text)
        calls = []
        with patch.object(ai_autoclassify.ai_classifier, 'available', return_value=True), \
             patch.object(ai_autoclassify.ai_classifier, 'auto_classify', side_effect=lambda *a, **k: calls.append(1)), \
             patch.object(app, 'document_text', return_value='x'):
            acted = ai_autoclassify.run_once(app)
        self.assertFalse(acted)
        self.assertEqual(calls, [])
        self.assertEqual(self._label(did)['category'], 'FCA')

    def test_disabled_by_env_does_nothing(self):
        self._drain_pending()
        up = self.upload(name='quando_desligado.pdf', data=b'%PDF-1.4 desligado')
        did = up['document_id']
        with patch.dict('os.environ', {'COLLECTOR_AI_AUTOCLASSIFY': '0'}), \
             patch.object(ai_autoclassify.ai_classifier, 'available', return_value=True), \
             patch.object(ai_autoclassify.ai_classifier, 'auto_classify', return_value={'category': 'RAIPI', 'confidence': 0.99}):
            acted = ai_autoclassify.run_once(app)
        self.assertFalse(acted)
        self.assertEqual(self._label(did)['category'], 'A classificar')
