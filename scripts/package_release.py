"""Empacota código/contratos/evidências; exclui acervo, segredos e ambientes."""
from pathlib import Path
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
import zipfile

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,default=root.parent/'Coletor_IPHAN_0.7_Ponte_SharePoint_Revisavel.zip')
args=parser.parse_args()
excluded={'data','__pycache__','.git','.venv','.pytest_cache','node_modules','finance_domain.py'}
extensions={'.py','.json','.txt','.md','.html','.css','.js','.lock'}
configured=Path(os.environ['COLLECTOR_DATA']).resolve() if os.getenv('COLLECTOR_DATA') else root/'data'
entries={}
for path in sorted(root.rglob('*')):
    rel=path.relative_to(root)
    if not path.is_file() or path.is_symlink() or any(part in excluded for part in rel.parts): continue
    if configured!=root and path.is_relative_to(configured): continue
    allowed=path.suffix in extensions or rel.as_posix() in ('.env.example','.gitignore','group-arqueo-logo.png') or (rel.parts and rel.parts[0]=='docs' and path.suffix=='.png')
    if not allowed or path.name=='.env' or path.name.startswith('.env.priv'): continue
    entries['coletor-iphan/'+rel.as_posix()]=path.read_bytes()
entries['LEIA_PRIMEIRO.txt']='''COLETOR IPHAN 0.7 — PONTE SHAREPOINT
Comece por coletor-iphan/README.md, docs/SHAREPOINT.md e docs/release-0.7.json.
A fundação de processos, ACL, fila, extração, evidências, geografia e descoberta SEI foi preservada.
A ponte adiciona catálogo organizado, categorias humanas, fila SharePoint com conferência SHA-256 e participantes documentais conservadores.
O parser SEI só lê páginas públicas fornecidas e links públicos que elas apresentam; não pesquisa processos por número, não faz login e não resolve CAPTCHA.
Participantes exigem fonte e revisão humana; não há inferência de cliente final, contrato, vínculo empregatício ou módulo financeiro.
Fixture/HTTP local/Chromium não homologam SharePoint, IPHAN, ATENA ou Geoportal institucionais.
Não há banco/acervo/segredos operacionais. Testes têm credenciais sintéticas.
'''.encode()
manifest={'version':'0.7.0','packaged_at_utc':datetime.now(timezone.utc).isoformat(),'files':{name:{'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)} for name,data in sorted(entries.items())}}
entries['MANIFESTO_SHA256.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
args.output.parent.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(args.output,'w',zipfile.ZIP_DEFLATED) as archive:
    for name,data in sorted(entries.items()): archive.writestr(name,data)
with zipfile.ZipFile(args.output) as archive:
    assert archive.testzip() is None
    for name,record in manifest['files'].items(): assert hashlib.sha256(archive.read(name)).hexdigest()==record['sha256']
checksum=hashlib.sha256(args.output.read_bytes()).hexdigest()
args.output.with_suffix(args.output.suffix+'.sha256').write_text(f'{checksum}  {args.output.name}\n')
print(json.dumps({'file':str(args.output),'bytes':args.output.stat().st_size,'entries':len(entries),'sha256':checksum},indent=2))
