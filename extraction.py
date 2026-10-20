"""Supervisor de parser: prazo real, limites de memória/CPU e cancelamento."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from fastapi import HTTPException

TOOL='native-text'
VERSION='pypdf-6.10.0/utf8-v3-formats-ocr'
TIME_LIMIT=35
MEMORY_BYTES=512*1024*1024
CPU_SECONDS=30

class LostLease(Exception): pass


def parse(path,mime,digest,guard=lambda:None):
    script=Path(__file__).with_name('extraction_child.py')
    # Segredos/proxy do pai não são necessários para o parser de arquivos locais.
    child_env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL','PYTHONPATH','VIRTUAL_ENV')}
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        proc=subprocess.Popen([sys.executable,str(script),str(path),mime,digest,str(MEMORY_BYTES),str(CPU_SECONDS)],stdout=output,stderr=errors,env=child_env,start_new_session=True)
        deadline=time.monotonic()+TIME_LIMIT
        try:
            while proc.poll() is None:
                guard()
                if time.monotonic()>deadline:
                    raise HTTPException(422,'Extração excedeu limite de tempo')
                if output.tell()>16*1024*1024: raise HTTPException(422,'Saída da extração excedeu limite')
                time.sleep(.05)
            guard()
            output.seek(0);raw=output.read(16*1024*1024+1)
            if len(raw)>16*1024*1024 or proc.returncode!=0: raise HTTPException(422,'Documento sem extração válida ou limite de recursos atingido')
            try: result=json.loads(raw)
            except (ValueError,UnicodeDecodeError): raise HTTPException(422,'Resposta do parser inválida')
            pages=result.get('pages')
            if not pages: raise HTTPException(422,'Documento sem páginas/conteúdo extraível')
            return [(page,text) for page,text in pages]
        finally:
            if proc.poll() is None: proc.kill()
            proc.wait()
