"""Cliente de referência ATENA: links explícitos, extração, polling e evidências."""
import argparse
import json
import os
from pathlib import Path
import time
import urllib.request
import urllib.error
import uuid


def call(base,token,path,body=None,key=None):
    headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'}
    if key: headers['Idempotency-Key']=key
    delegation=os.getenv('COLLECTOR_DELEGATION_ID')
    if delegation: headers['X-Delegation-Id']=delegation
    request=urllib.request.Request(base.rstrip('/')+path,headers=headers,data=None if body is None else json.dumps(body).encode())
    with urllib.request.urlopen(request,timeout=15) as response: return json.load(response)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8000')
    choice=parser.add_mutually_exclusive_group()
    choice.add_argument('--revision-id');choice.add_argument('--url',action='append');choice.add_argument('--links-file',type=Path)
    parser.add_argument('--process-id');parser.add_argument('--reprocess',action='store_true')
    parser.add_argument('--idempotency-key');parser.add_argument('--timeout',type=float,default=30)
    args=parser.parse_args();token=os.getenv('COLLECTOR_TOKEN')
    if not token: raise SystemExit('Configure COLLECTOR_TOKEN sem inserir o segredo em argumentos')
    print(json.dumps(call(args.base_url,token,'/v1/capabilities'),ensure_ascii=False))
    is_collection=bool(args.url or args.links_file)
    if not args.revision_id and not is_collection: return
    if is_collection:
        if args.reprocess: parser.error('--reprocess é específico de extração')
        links=args.url or [x.strip() for x in args.links_file.read_text().splitlines() if x.strip()]
        body={'source':'iphan','operation':'collect_links','input':{'urls':links},'request_context':{'application':'atena-reference'}}
        if args.process_id: body['input']['process_id']=args.process_id
    else:
        body={'source':'repository','operation':'extract_revision','input':{'revision_id':args.revision_id}}
        if args.reprocess: body['input']['reprocess']=True
    result=call(args.base_url,token,'/v1/collection-jobs',body,args.idempotency_key or str(uuid.uuid4()))
    print(json.dumps(result));deadline=time.monotonic()+args.timeout
    while time.monotonic()<deadline:
        row=call(args.base_url,token,result['status_url'])
        if row['status'] in ('completed','partial','failed','cancelled','waiting_for_user'):
            checkpoint=json.loads(row['checkpoint'])
            print(json.dumps({'job_id':row['id'],'status':row['status'],'detail':row['detail'],'checkpoint':checkpoint},ensure_ascii=False))
            if is_collection:
                print(json.dumps(call(args.base_url,token,result['status_url']+'/links'),ensure_ascii=False))
            for ev in checkpoint.get('result',{}).get('evidence',[]):
                print(json.dumps(call(args.base_url,token,'/v1/evidence/'+ev['id']),ensure_ascii=False))
            if row['status'] not in ('completed','partial') or (is_collection and row['status']=='partial'): raise SystemExit(2)
            return
        time.sleep(.25)
    raise SystemExit('Timeout do cliente; tarefa permanece consultável por job_id')


if __name__=='__main__':
    try: main()
    except urllib.error.HTTPError as exc: raise SystemExit(f'HTTP {exc.code}: solicitação recusada')
    except urllib.error.URLError: raise SystemExit('Falha de conexão com API')
