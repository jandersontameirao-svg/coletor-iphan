"""Processo dedicado de pós-processamento, separado do coletor-worker.

Enquanto o coletor-worker baixa documentos a plena velocidade, este processo
roda em paralelo e:

  1. Envia ao SharePoint (PRIORIDADE) os documentos já prontos — vários em
     paralelo (COLLECTOR_SHAREPOINT_CONCURRENCY, padrão 5) — para que cada
     processo apareça na sua respectiva pasta o mais rápido possível, sem
     esperar a coleta inteira terminar.
  2. Em uma thread dedicada, avança a classificação por IA dos documentos ainda
     "A classificar" (filtra os processos).

É seguro rodar em paralelo: sharepoint_store.sync_once reserva cada envio com
lease atômico (BEGIN IMMEDIATE + WHERE lease=?), então threads concorrentes
reivindicam itens diferentes e nunca sobem o mesmo arquivo. A classificação
roda em UMA thread só para não haver corrida na seleção do documento.
"""
import concurrent.futures
import logging
import os
import signal
import threading

import app

log = logging.getLogger("coletor-sync")
stop = threading.Event()

UPLOAD_CONCURRENCY = max(1, min(8, int(os.getenv("COLLECTOR_SHAREPOINT_CONCURRENCY", "5"))))


def upload_loop():
    """Envia ao SharePoint continuamente. Roda em várias threads em paralelo."""
    while not stop.is_set():
        try:
            busy = bool(app.sharepoint_store.sync_once(app))
        except Exception:
            log.exception("upload_error")
            busy = False
        if not busy:
            stop.wait(2)


def classify_loop():
    """Avança a classificação por IA. Roda em UMA thread só (evita corrida)."""
    while not stop.is_set():
        try:
            busy = bool(app.ai_autoclassify.run_once(app))
        except Exception:
            log.exception("classify_error")
            busy = False
        if not busy:
            stop.wait(5)


def main():
    logging.basicConfig(level=logging.INFO)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    log.info("coletor-sync iniciado: %d envios paralelos ao SharePoint + classificacao", UPLOAD_CONCURRENCY)
    workers = [upload_loop] * UPLOAD_CONCURRENCY + [classify_loop]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(workers)) as pool:
        futures = [pool.submit(w) for w in workers]
        for future in futures:
            future.result()


if __name__ == "__main__":
    main()
