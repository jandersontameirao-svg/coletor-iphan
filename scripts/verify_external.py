"""Verificação real de um link explícito; não pesquisa nem persiste acervo."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import safe_fetch
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',required=True);a=p.parse_args()
report={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'test_kind':'external_real','url':a.url,'received':True,'document_obtained':False,'iphan_process_collection_homologated':False}
try:
    result=safe_fetch.fetch(a.url)
    report.update({'document_obtained':True,'mime':result['mime'],'bytes':len(result['data']),'sha256':hashlib.sha256(result['data']).hexdigest(),'final_url':result['final_url']})
except safe_fetch.FetchError as exc: report.update({'state':'waiting_for_user','code':exc.code,'action':exc.action})
print(json.dumps(report,ensure_ascii=False,indent=2))
