import json
from unittest.mock import patch

from support import Fixture
import app
import sei_public

PROCESS_URL = "https://sei.iphan.gov.br/sei/modulos/pesquisa/md_pesq_processo_exibir.php?opaque-process"
DOCUMENT_URL = "https://sei.iphan.gov.br/sei/modulos/pesquisa/md_pesq_documento_consulta_externa.php?opaque-document"


class SeiPublicTests(Fixture):
    def discovered_page(self):
        number = self.number + "-SEI"
        return {
            "source_url": PROCESS_URL,
            "number": number,
            "title": "LICENCIAMENTO AMBIENTAL · Interessado de teste",
            "process_type": "LICENCIAMENTO AMBIENTAL",
            "interested": "Interessado de teste",
            "page_restricted_notice": True,
            "document_total": 2,
            "public_documents": 1,
            "restricted_documents": 1,
            "truncated": False,
            "documents": [
                {"document_number": "4423167", "title": "Parecer Técnico 184", "date": "23/05/2023", "included_at": "23/05/2023", "unit": "COTEC IPHAN-MG", "url": DOCUMENT_URL},
                {"document_number": "7301804", "title": "Complementação", "date": "07/04/2026", "included_at": "07/04/2026", "unit": "DIVTEC IPHAN-MS", "url": None},
            ],
        }

    def create_process_job(self):
        return self.create_job({"source": "iphan", "operation": "collect_links", "input": {"urls": [PROCESS_URL]}})

    def test_parser_extracts_only_public_document_links(self):
        html = '''<html><body>Pesquisa Processual
        <table id="tblCabecalho"><tr><td>Processo:</td><td>01514.000143/2007-79</td></tr><tr><td>Tipo:</td><td>Licenciamento</td></tr></table>
        <table id="tblDocumentos"><tr><th>Documento</th></tr>
        <tr><td></td><td><a onclick="window.open('md_pesq_documento_consulta_externa.php?abc');">4423167</a></td><td>Parecer Técnico</td><td>23/05/2023</td><td>23/05/2023</td><td>IPHAN-MG</td></tr>
        <tr><td></td><td><span class="retiraAncoraPadraoAzul">7301804</span></td><td>Complementação</td><td>07/04/2026</td><td>07/04/2026</td><td>DIVTEC</td></tr></table></body></html>'''.encode("iso-8859-1")
        result = sei_public.parse_process_page(html, PROCESS_URL)
        self.assertEqual(result["number"], "01514.000143/2007-79")
        self.assertEqual(result["public_documents"], 1)
        self.assertEqual(result["restricted_documents"], 1)
        self.assertEqual(result["documents"][0]["url"], "https://sei.iphan.gov.br/sei/modulos/pesquisa/md_pesq_documento_consulta_externa.php?abc")
        self.assertIsNone(result["documents"][1]["url"])

    def test_worker_registers_process_downloads_public_document_and_keeps_restricted_item_pending(self):
        jid = self.create_process_job()
        fetched = {"data": b"%PDF-1.4 public document", "mime": "application/pdf", "name": "md_pesq_documento_consulta_externa.php.pdf", "original_name": "md_pesq_documento_consulta_externa.php", "source_url": DOCUMENT_URL, "final_url": DOCUMENT_URL}
        with patch("sei_public.fetch_process_page", return_value=self.discovered_page()) as discover, patch("safe_fetch.fetch", return_value=fetched) as download:
            row = self.run_job(jid)
        self.assertEqual(discover.call_count, 1)
        self.assertEqual(download.call_count, 1)
        self.assertEqual(row["status"], "partial")
        with app.db() as c:
            parent = c.execute("SELECT * FROM link_items WHERE job_id=? AND kind='sei_process_page'", (jid,)).fetchone()
            children = c.execute("SELECT * FROM link_items WHERE job_id=? AND kind='sei_document' ORDER BY position", (jid,)).fetchall()
            page = c.execute("SELECT * FROM sei_process_pages WHERE parent_item_id=?", (parent["id"],)).fetchone()
            process = c.execute("SELECT * FROM processes WHERE id=?", (parent["process_id"],)).fetchone()
            document = c.execute("SELECT * FROM documents WHERE process_id=?", (parent["process_id"],)).fetchone()
        self.assertEqual(parent["status"], "process_discovered")
        self.assertEqual(page["process_number"], self.number + "-SEI")
        self.assertEqual(page["public_documents"], 1)
        self.assertEqual(page["restricted_documents"], 1)
        self.assertEqual(process["number"], self.number + "-SEI")
        self.assertEqual([child["status"] for child in children], ["downloaded", "waiting_for_user"])
        self.assertEqual(document["name"], "4423167 — Parecer Técnico 184.pdf")
        counts = json.loads(row["checkpoint"])["counts"]
        self.assertEqual(counts["process_pages_discovered"], 1)
        self.assertEqual(counts["documents_discovered"], 2)
        self.assertEqual(counts["downloaded"], 1)

    def test_collection_tags_discovered_process_for_shared_folder(self):
        jid = self.create_job({"source": "iphan", "operation": "collect_links", "input": {"urls": [PROCESS_URL], "collection": "Zanettini"}})
        fetched = {"data": b"%PDF-1.4 x", "mime": "application/pdf", "name": "md_pesq_documento_consulta_externa.php.pdf", "original_name": "md_pesq_documento_consulta_externa.php", "source_url": DOCUMENT_URL, "final_url": DOCUMENT_URL}
        with patch("sei_public.fetch_process_page", return_value=self.discovered_page()), patch("safe_fetch.fetch", return_value=fetched):
            self.run_job(jid)
        with app.db() as c:
            parent = c.execute("SELECT process_id FROM link_items WHERE job_id=? AND kind='sei_process_page'", (jid,)).fetchone()
            process = c.execute("SELECT collection FROM processes WHERE id=?", (parent["process_id"],)).fetchone()
        self.assertEqual(process["collection"], "Zanettini")

    def test_real_process_page_with_captcha_script_is_stored_not_rejected(self):
        # A página real do SEI contém "captcha" (script de áudio-captcha embutido).
        # Antes, ao salvar o HTML, a heurística de login rejeitava a página boa (415).
        jid = self.create_process_job()
        page = {**self.discovered_page(), "_raw_html": b"<html><body>Pesquisa Processual <table id='tblDocumentos'></table><script>infra_gerar_audio_captcha()</script></body></html>"}
        fetched = {"data": b"%PDF-1.4 public document", "mime": "application/pdf", "name": "md_pesq_documento_consulta_externa.php.pdf", "original_name": "md_pesq_documento_consulta_externa.php", "source_url": DOCUMENT_URL, "final_url": DOCUMENT_URL}
        with patch("sei_public.fetch_process_page", return_value=page), patch("safe_fetch.fetch", return_value=fetched):
            row = self.run_job(jid)
        self.assertEqual(row["status"], "partial")
        with app.db() as c:
            parent = c.execute("SELECT * FROM link_items WHERE job_id=? AND kind='sei_process_page'", (jid,)).fetchone()
        # A página foi descoberta normalmente, sem cair em process_access_415.
        self.assertEqual(parent["status"], "process_discovered")
        self.assertNotIn("process_access_415", parent["detail"])

    def test_session_cookie_reaches_fetch_is_not_exposed_and_is_cleared(self):
        jid = self.create_job({"source": "iphan", "operation": "collect_links", "input": {"urls": [PROCESS_URL]}, "session_cookie": "PHPSESSID=segredo123"})
        seen = {}
        fetched = {"data": b"%PDF-1.4 public document", "mime": "application/pdf", "name": "md_pesq_documento_consulta_externa.php.pdf", "original_name": "md_pesq_documento_consulta_externa.php", "source_url": DOCUMENT_URL, "final_url": DOCUMENT_URL}

        def fake_discover(url, guard=None, cookie=None):
            seen["discover"] = cookie
            return self.discovered_page()

        def fake_download(url, guard=None, cookie=None):
            seen["download"] = cookie
            return fetched

        with patch("sei_public.fetch_process_page", side_effect=fake_discover), patch("safe_fetch.fetch", side_effect=fake_download):
            row = self.run_job(jid)
        # O cookie do usuário chega tanto na descoberta da página quanto no download do documento.
        self.assertEqual(seen["discover"], "PHPSESSID=segredo123")
        self.assertEqual(seen["download"], "PHPSESSID=segredo123")
        # Nunca é devolvido pela API...
        self.assertIsNone(row.get("session_cookie"))
        # ...nem persistido no comando/idempotência...
        self.assertNotIn("session_cookie", json.loads(row["input"]))
        # ...e é descartado do banco assim que a tarefa encerra.
        with app.db() as c:
            stored = c.execute("SELECT session_cookie FROM jobs WHERE id=?", (jid,)).fetchone()[0]
        self.assertIsNone(stored)

    def test_rejected_document_becomes_pendency_not_job_failure(self):
        # Sessão SEI expirada devolve página de erro no lugar do arquivo: o documento é recusado
        # (415), mas isso vira pendência DESTE item, nunca falha da tarefa inteira.
        jid = self.create_process_job()
        html = {"data": b"<html><body>Sessao expirada; refaca o login</body></html>", "mime": "application/pdf", "name": "doc.pdf", "original_name": "doc.pdf", "source_url": DOCUMENT_URL, "final_url": DOCUMENT_URL}
        with patch("sei_public.fetch_process_page", return_value=self.discovered_page()), patch("safe_fetch.fetch", return_value=html):
            row = self.run_job(jid)
        self.assertNotEqual(row["status"], "failed")
        self.assertEqual(row["status"], "waiting_for_user")
        with app.db() as c:
            public = c.execute("SELECT * FROM link_items WHERE job_id=? AND kind='sei_document' AND url=?", (jid, DOCUMENT_URL)).fetchone()
        self.assertEqual(public["status"], "waiting_for_user")
        self.assertIn("document_rejected_415", public["detail"])

    def test_existing_process_with_another_number_stays_pending_without_document_download(self):
        jid = self.create_job({"source": "iphan", "operation": "collect_links", "input": {"urls": [PROCESS_URL], "process_id": self.pid}})
        with patch("sei_public.fetch_process_page", return_value=self.discovered_page()):
            row = self.run_job(jid)
        self.assertEqual(row["status"], "waiting_for_user")
        with app.db() as c:
            parent = c.execute("SELECT * FROM link_items WHERE job_id=? AND kind='sei_process_page'", (jid,)).fetchone()
        self.assertEqual(parent["process_id"], self.pid)
        self.assertEqual(parent["status"], "waiting_for_user")
        self.assertIn("process_mismatch", parent["detail"])

    def test_job_document_discovery_limit_keeps_parent_as_action_required(self):
        jid = self.create_process_job()
        fetched = {"data": b"%PDF-1.4 public document", "mime": "application/pdf", "name": "document.pdf", "original_name": "document", "source_url": DOCUMENT_URL, "final_url": DOCUMENT_URL}
        with patch("sei_public.fetch_process_page", return_value=self.discovered_page()), patch("safe_fetch.fetch", return_value=fetched), patch("worker.MAX_DISCOVERED_DOCUMENTS_PER_JOB", 1):
            row = self.run_job(jid)
        self.assertEqual(row["status"], "partial")
        with app.db() as c:
            parent = c.execute("SELECT * FROM link_items WHERE job_id=? AND kind='sei_process_page'", (jid,)).fetchone()
            children = c.execute("SELECT * FROM link_items WHERE job_id=? AND kind='sei_document'", (jid,)).fetchall()
        self.assertEqual(parent["status"], "waiting_for_user")
        self.assertIn("limite de 1 documentos", parent["detail"])
        self.assertEqual(len(children), 1)
