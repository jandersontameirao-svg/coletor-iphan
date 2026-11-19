"""Processo dedicado de pós-processamento, separado do coletor-worker.

Enquanto o coletor-worker baixa documentos a plena velocidade, este processo
roda em paralelo e, continuamente:

  1. Envia ao SharePoint (PRIORIDADE) os documentos já prontos — cada processo
     aparece na sua respectiva pasta assim que seus arquivos ficam disponíveis,
     sem esperar a coleta inteira terminar.
  2. Avança a classificação por IA dos documentos ainda "A classificar"
     (filtra os processos), que antes só rodava quando o worker ficava ocioso.

É seguro rodar em paralelo: sharepoint_store.sync_once reserva cada envio com
lease atômico e só confirma com WHERE lease=?, então dois processos nunca
sobem o mesmo arquivo. Cada chamada processa UM item e retorna.
"""
import logging
import signal
import threading

import app

log = logging.getLogger("coletor-sync")
stop = threading.Event()


def run_once():
    # Prioriza o SharePoint: esvazia a fila de envio antes de gastar tempo com IA.
    if app.sharepoint_store.sync_once(app):
        return True
    # Sem nada para enviar: avança a classificação por IA (um documento por vez).
    return bool(app.ai_autoclassify.run_once(app))


def main():
    logging.basicConfig(level=logging.INFO)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    log.info("coletor-sync iniciado: SharePoint (prioridade) + classificacao continuos")
    while not stop.is_set():
        try:
            busy = run_once()
        except Exception:
            log.exception("sync_loop_error")
            busy = False
        if not busy:
            stop.wait(2)


if __name__ == "__main__":
    main()
