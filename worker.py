"""Worker comum para links explícitos, páginas públicas SEI e extração isolada."""
import argparse
import json
import logging
import signal
import threading
import time

import app
import extraction
import safe_fetch
import sei_public
import task_queue
from fastapi import HTTPException

stop = threading.Event()
log = logging.getLogger("collector.worker")
BATCH_QUOTA_BYTES = 100 * 1024 * 1024
MAX_DISCOVERED_DOCUMENTS_PER_JOB = 25_000


class LeaseKeeper:
    def __init__(self, job):
        self.job = job
        self.end = threading.Event()
        self.lost = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        interval = max(0.1, min(20, task_queue.LEASE_SECONDS / 3))
        while not self.end.wait(interval):
            try:
                if not task_queue.renew(app.db, self.job):
                    self.lost.set()
                    return
            except Exception:
                self.lost.set()
                return

    def guard(self):
        if self.lost.is_set():
            raise extraction.LostLease()
        with app.db() as c:
            if not task_queue.held(c, self.job):
                raise extraction.LostLease()

    def __enter__(self):
        self.guard()
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.end.set()
        self.thread.join(timeout=2)


def link_summary(c, jid):
    rows = [dict(row) for row in c.execute("SELECT * FROM link_items WHERE job_id=? ORDER BY position", (jid,))]
    source_rows = [row for row in rows if row.get("kind") != "sei_document"]
    document_rows = [row for row in rows if row.get("kind") == "sei_document"]
    counts = {
        "links_received": len(source_rows),
        "process_pages_discovered": sum(row.get("kind") == "sei_process_page" and row["status"] == "process_discovered" for row in rows),
        "documents_discovered": len(document_rows),
        "downloaded": sum(row["status"] in ("downloaded", "already_exists") for row in rows),
        "already_existing": sum(row["status"] in ("already_exists", "duplicate") for row in rows),
        "manually_imported": sum(row["status"] == "manual_imported" for row in rows),
        "blocked": sum(row["status"] == "invalid" for row in rows),
        "failed": sum(row["status"] == "failed" for row in rows),
        "pending": sum(row["status"] in ("waiting_for_user", "received", "duplicate_pending") for row in rows),
        "extracted": 0,
        "validated": 0,
    }
    return {
        "stage": "links_processed",
        "counts": counts,
        "items": [{"id": row["id"], "status": row["status"], "revision_id": row["revision_id"]} for row in rows],
    }


def _metadata(item):
    try:
        value = json.loads(item.get("metadata") or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _set_waiting(job, item, user, keeper, code, detail):
    with app.db() as c:
        c.execute("BEGIN IMMEDIATE")
        if not task_queue.held(c, job):
            raise extraction.LostLease()
        c.execute("UPDATE link_items SET status='waiting_for_user',detail=? WHERE id=?", (f"{code}: {detail}", item["id"]))
        app.event(c, user.get("_actor_id", user["id"]), "collection.item.waiting_for_user", item["id"])


def _discover_process_page(job, item, user, keeper):
    """Expande uma página de processo em itens filhos, sem requisitar itens restritos."""
    try:
        if item.get("process_id"):
            with app.db() as c:
                app.process_access(c, item["process_id"], user, "operate")
        page = sei_public.fetch_process_page(item["url"], keeper.guard)
        keeper.guard()
        with app.db() as c:
            c.execute("BEGIN IMMEDIATE")
            if not task_queue.held(c, job):
                raise extraction.LostLease()
            current = dict(c.execute("SELECT * FROM link_items WHERE id=?", (item["id"],)).fetchone())
            if current["status"] != "received":
                return
            if current.get("process_id"):
                process = app.process_access(c, current["process_id"], user, "operate")
                if app.repository_migration.number_key(process["number"]) != app.repository_migration.number_key(page["number"]):
                    raise safe_fetch.FetchError("process_mismatch", "A página SEI declara outro número de processo; remova a associação ou corrija o link")
                process_id = process["id"]
            else:
                process_id = app.ensure_discovered_process(c, page["number"], page["title"], user)
            existing = c.execute("SELECT 1 FROM sei_process_pages WHERE parent_item_id=?", (current["id"],)).fetchone()
            task_limit_reached = False
            if not existing:
                next_position = c.execute("SELECT coalesce(max(position),-1)+1 FROM link_items WHERE job_id=?", (job["id"],)).fetchone()[0]
                discovered_count = c.execute("SELECT count(*) FROM link_items WHERE job_id=? AND kind='sei_document'", (job["id"],)).fetchone()[0]
                remaining_capacity = max(0, MAX_DISCOVERED_DOCUMENTS_PER_JOB - discovered_count)
                documents = page["documents"][:remaining_capacity]
                task_limit_reached = len(documents) < len(page["documents"])
                existing_urls = {row["url"]: row["id"] for row in c.execute("SELECT id,url FROM link_items WHERE job_id=?", (job["id"],)) if row["url"]}
                for offset, document in enumerate(documents):
                    child_id = app.uid()
                    document_url = document.get("url")
                    metadata = {**document, "access": "public" if document_url else "restricted", "source_process_url": page["source_url"]}
                    duplicate_of = existing_urls.get(document_url) if document_url else None
                    if document_url and duplicate_of:
                        status = "duplicate_pending"
                        detail = "Documento público repetido nesta tarefa; aguarda o primeiro resultado"
                    elif document_url:
                        status = "received"
                        detail = "Documento público identificado na página do processo; ainda não acessado"
                    else:
                        status = "waiting_for_user"
                        detail = "Documento sem link público ou marcado como restrito no SEI; importe manualmente somente se autorizado"
                    display_name = f"{document['document_number']} — {document['title']}"[:300]
                    c.execute(
                        "INSERT INTO link_items(id,job_id,position,url,status,detail,process_id,revision_id,duplicate_of,created,kind,parent_item_id,display_name,metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (child_id, job["id"], next_position + offset, document_url or current["url"], status, detail, process_id, None, duplicate_of, time.time(), "sei_document", current["id"], display_name, json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))),
                    )
                    if document_url:
                        existing_urls[document_url] = child_id
                c.execute(
                    "INSERT INTO sei_process_pages(parent_item_id,job_id,source_url,process_id,process_number,process_title,process_type,interested,page_restricted_notice,document_total,public_documents,restricted_documents,truncated,discovered_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (current["id"], job["id"], page["source_url"], process_id, page["number"], page["title"], page["process_type"], page["interested"], int(page["page_restricted_notice"]), page["document_total"], page["public_documents"], page["restricted_documents"], int(page["truncated"]), time.time()),
                )
            detail = f"Processo {page['number']} lido; {page['public_documents']} documentos públicos identificados e {page['restricted_documents']} sem link público"
            if page["truncated"]:
                detail += f"; limite de {sei_public.MAX_DOCUMENTS_PER_PROCESS} itens atingido"
            if task_limit_reached:
                detail += f"; limite de {MAX_DISCOVERED_DOCUMENTS_PER_JOB} documentos por tarefa atingido, envie esta página em nova tarefa para continuar"
            status = "waiting_for_user" if task_limit_reached else "process_discovered"
            c.execute("UPDATE link_items SET status=?,process_id=?,detail=?,metadata=? WHERE id=?", (status, process_id, detail, json.dumps({"number": page["number"], "title": page["title"], "task_limit_reached": task_limit_reached}, ensure_ascii=False, separators=(",", ":")), current["id"]))
            app.event(c, user.get("_actor_id", user["id"]), "collection.process_page.discovered", current["id"])
    except safe_fetch.FetchError as exc:
        _set_waiting(job, item, user, keeper, exc.code, exc.action)
    except HTTPException as exc:
        _set_waiting(job, item, user, keeper, f"process_access_{exc.status_code}", str(exc.detail))


def _reuse_duplicate(job, item, keeper):
    with app.db() as c:
        c.execute("BEGIN IMMEDIATE")
        if not task_queue.held(c, job):
            raise extraction.LostLease()
        first = c.execute("SELECT * FROM link_items WHERE id=?", (item["duplicate_of"],)).fetchone()
        if first and first["revision_id"]:
            c.execute("UPDATE link_items SET status='duplicate',revision_id=?,process_id=?,detail='Resultado do link repetido reutilizado' WHERE id=?", (first["revision_id"], first["process_id"], item["id"]))
        else:
            c.execute("UPDATE link_items SET status='waiting_for_user',detail='Link repetido aguarda resolução do primeiro item' WHERE id=?", (item["id"],))


def _download_document(job, item, user, keeper):
    try:
        if not item.get("process_id"):
            raise safe_fetch.FetchError("process_required", "Cadastre ou selecione processo e informe process_id na retomada; não foi realizado acesso externo")
        with app.db() as c:
            app.process_access(c, item["process_id"], user, "operate")
        data = safe_fetch.fetch(item["url"], keeper.guard)
        keeper.guard()
        with app.db() as c:
            total = c.execute("SELECT coalesce(sum(b.size),0) FROM link_items i JOIN revisions r ON r.id=i.revision_id JOIN blobs b ON b.hash=r.blob WHERE i.job_id=? AND i.status IN ('downloaded','already_exists','manual_imported')", (job["id"],)).fetchone()[0]
        if total + len(data["data"]) > BATCH_QUOTA_BYTES:
            raise safe_fetch.FetchError("batch_quota", "Limite de 100 MiB por tarefa; divida a lista")
        metadata = _metadata(item)
        name = sei_public.document_filename(metadata, data) if item.get("kind") == "sei_document" else data["name"]
        blob = app.put_blob(data["data"], name)
        original_name = item.get("display_name") or data.get("original_name", data["name"])
        with app.db() as c:
            c.execute("BEGIN IMMEDIATE")
            if not task_queue.held(c, job):
                raise extraction.LostLease()
            total = c.execute("SELECT coalesce(sum(b.size),0) FROM link_items i JOIN revisions r ON r.id=i.revision_id JOIN blobs b ON b.hash=r.blob WHERE i.job_id=? AND i.status IN ('downloaded','already_exists','manual_imported')", (job["id"],)).fetchone()[0]
            if total + blob[2] > BATCH_QUOTA_BYTES:
                raise safe_fetch.FetchError("batch_quota", "Limite de 100 MiB por tarefa; divida a lista")
            result = app.persist_document(c, item["process_id"], name, item["url"], user, blob, from_link=True, original_name=original_name)
            detail = "Documento público obtido; extração é etapa separada" if item.get("kind") == "sei_document" else "Documento obtido; extração é etapa separada"
            c.execute("UPDATE link_items SET status=?,revision_id=?,detail=? WHERE id=?", ("downloaded" if result["changed"] else "already_exists", result["revision_id"], detail, item["id"]))
            c.execute("INSERT INTO link_captures VALUES(?,?,?,?,?,?,?)", (app.uid(), item["id"], item["url"], data["final_url"], result["sha256"], data["mime"], time.time()))
            checkpoint = link_summary(c, job["id"])
            c.execute("UPDATE jobs SET checkpoint=?,detail=? WHERE id=?", (json.dumps(checkpoint), "Documentos confirmados preservados; processando itens restantes", job["id"]))
            app.event(c, user.get("_actor_id", user["id"]), "collection.item.obtained", item["id"])
    except safe_fetch.FetchError as exc:
        _set_waiting(job, item, user, keeper, exc.code, exc.action)


def process_links(job, user, keeper):
    while True:
        keeper.guard()
        with app.db() as c:
            row = c.execute("SELECT * FROM link_items WHERE job_id=? AND status IN ('received','duplicate_pending') ORDER BY position LIMIT 1", (job["id"],)).fetchone()
        if not row:
            break
        item = dict(row)
        if item.get("kind") == "sei_process_page":
            _discover_process_page(job, item, user, keeper)
        elif item.get("duplicate_of"):
            _reuse_duplicate(job, item, keeper)
        else:
            _download_document(job, item, user, keeper)
        if keeper.end.wait(0.2):
            raise extraction.LostLease()

    with app.db() as c:
        c.execute("BEGIN IMMEDIATE")
        if not task_queue.held(c, job):
            raise extraction.LostLease()
        checkpoint = link_summary(c, job["id"])
        counts = checkpoint["counts"]
        success = any(row["revision_id"] for row in c.execute("SELECT revision_id FROM link_items WHERE job_id=?", (job["id"],)))
        problems = counts["pending"] + counts["blocked"] + counts["failed"]
        state = ("partial" if success else "waiting_for_user" if counts["pending"] else "failed") if problems else "completed"
        if state == "completed":
            detail = "Documentos dos links obtidos ou importados; extração e validação não presumidas"
        elif state == "failed":
            detail = "Nenhum documento obtido; links inválidos. Corrija-os e envie novo comando"
        else:
            detail = "Alguns links ou documentos exigem correção, retomada ou importação manual"
        task_queue.finish(c, app.event, job, state, detail, checkpoint)


def run_once(worker_id="local-worker"):
    job = task_queue.claim(app.db, app.event, worker_id)
    if not job:
        return False
    run_id = None
    try:
        with LeaseKeeper(job) as keeper:
            payload = json.loads(job["input"])
            with app.db() as c:
                owner = c.execute("SELECT * FROM users WHERE id=? AND active=1", (job["owner"],)).fetchone()
            if not owner:
                raise extraction.LostLease()
            user = {**dict(owner), "_guard": keeper.guard, "_lease_token": job["lease_token"]}
            if job.get("delegation_id"):
                user.update({"_delegation": job["delegation_id"], "_actor_id": job["actor_id"]})
            if payload.get("operation") in ("collect_process", "collect_links"):
                process_links(job, user, keeper)
                return True
            rid = payload["input"]["revision_id"]
            reservation = app.reserve_extraction(rid, user, job["id"], payload["input"].get("reprocess", False), job["lease_token"])
            run_id = reservation["id"]
            cached = reservation.get("cached")
            if isinstance(cached, dict):
                result = {**cached, "reused": True}
            else:
                user["_run_id"] = run_id
                pages = app.prepare_extraction(rid, user)
                keeper.guard()
                with app.db() as c:
                    c.execute("BEGIN IMMEDIATE")
                    if not task_queue.held(c, job):
                        raise extraction.LostLease()
                    result = app.save_extraction(c, rid, user, pages)
                    task_queue.finish(c, app.event, job, "partial" if result["ocr_required"] else "completed", "OCR necessário; extração nativa parcial" if result["ocr_required"] else "Extração concluída", {"stage": "extraction_committed", "revision_id": rid, "result": result, "counts": {"extracted": 1, "validated": 0}})
                return True
            with app.db() as c:
                c.execute("BEGIN IMMEDIATE")
                if not task_queue.held(c, job):
                    raise extraction.LostLease()
                task_queue.finish(c, app.event, job, "partial" if result["ocr_required"] else "completed", "Execução anterior reutilizada sem duplicar evidências", {"stage": "extraction_reused", "revision_id": rid, "result": result, "counts": {"extracted": 0, "reused": 1, "validated": 0}})
    except extraction.LostLease:
        if run_id:
            app.fail_extraction(run_id, "lease_lost", "cancelled")
    except HTTPException as exc:
        if run_id:
            app.fail_extraction(run_id, "http_" + str(exc.status_code))
        if exc.status_code == 409:
            task_queue.fail(app.db, app.event, job)
        else:
            with app.db() as c:
                c.execute("BEGIN IMMEDIATE")
                if task_queue.held(c, job):
                    task_queue.finish(c, app.event, job, "failed", f"Extração impedida: HTTP {exc.status_code}", {"stage": "extraction_failed", "run_id": run_id})
    except Exception:
        if run_id:
            app.fail_extraction(run_id, "execution_error")
        log.error("job_execution_error job_id=%s", job["id"])
        task_queue.fail(app.db, app.event, job)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    worker_id = app.uid()
    if args.once:
        run_once(worker_id)
    else:
        while not stop.is_set():
            if not run_once(worker_id):
                stop.wait(1)
