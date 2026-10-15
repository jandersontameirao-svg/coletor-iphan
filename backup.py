"""Backup/restauração offline: pare o servidor antes de executar."""
import argparse, hashlib, json, shutil, sqlite3
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=['backup','restore']);p.add_argument('source',type=Path);p.add_argument('target',type=Path);a=p.parse_args()
if a.target.exists(): raise SystemExit('Destino deve ser inexistente para impedir sobrescrita')
if not (a.source/'catalog.sqlite').is_file(): raise SystemExit('Catálogo ausente')
if a.operation=='restore':
    manifest=json.loads((a.source/'backup-manifest.json').read_text())
    for name,digest in manifest.items():
        path=a.source/name
        if path.parent.resolve() not in (a.source.resolve(),(a.source/'blobs').resolve()): raise SystemExit('Caminho inválido')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest: raise SystemExit('Hash inválido: '+name)
a.target.mkdir(parents=True);(a.target/'blobs').mkdir()
try:
    src=sqlite3.connect(a.source/'catalog.sqlite');dst=sqlite3.connect(a.target/'catalog.sqlite');src.backup(dst);src.close()
    if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise RuntimeError('Banco inválido')
    for (digest,) in dst.execute('SELECT hash FROM blobs'):
        if len(digest)!=64 or any(ch not in '0123456789abcdef' for ch in digest): raise RuntimeError('Hash inválido')
        blob=a.source/'blobs'/digest
        if hashlib.sha256(blob.read_bytes()).hexdigest()!=digest: raise RuntimeError('Blob inválido: '+digest)
        shutil.copyfile(blob,a.target/'blobs'/digest)
    if dst.execute('PRAGMA foreign_key_check').fetchall(): raise RuntimeError('Vínculos inválidos')
    dst.close()
    files=[a.target/'catalog.sqlite',*(a.target/'blobs').iterdir()]
    manifest={str(f.relative_to(a.target)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    (a.target/'backup-manifest.json').write_text(json.dumps(manifest,indent=2))
except Exception:
    shutil.rmtree(a.target)
    raise
print('Concluído; banco e blobs verificados:',a.target)
