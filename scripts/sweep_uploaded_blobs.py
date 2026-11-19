"""Remove do disco os blobs que já subiram ao SharePoint (todos os cloud_transfers
do conteúdo com status 'uploaded'), mantendo o catálogo intacto. Serve para liberar
espaço numa VPS compartilhada: o documento passa a existir só no SharePoint.

Nunca apaga um blob que ainda tenha envio pendente (queued/uploading/failed).
Dry-run por padrão (só lista e soma o espaço). Passe --apply para apagar de verdade.

Uso:
  /var/www/coletor/.venv/bin/python scripts/sweep_uploaded_blobs.py            # lista
  /var/www/coletor/.venv/bin/python scripts/sweep_uploaded_blobs.py --apply    # apaga
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Apaga de verdade (sem isto, só lista/soma).')
    args = parser.parse_args()
    blobs_dir = app.ROOT / 'blobs'
    with app.db() as c:
        rows = c.execute(
            "SELECT DISTINCT rv.blob FROM revisions rv JOIN cloud_transfers ct ON ct.revision_id=rv.id "
            "WHERE rv.blob NOT IN ("
            "  SELECT rv2.blob FROM revisions rv2 JOIN cloud_transfers ct2 ON ct2.revision_id=rv2.id"
            "  WHERE ct2.status!='uploaded')"
        ).fetchall()
    total = 0
    found = 0
    removed = 0
    for (h,) in rows:
        f = blobs_dir / h
        if not f.exists():
            continue
        found += 1
        total += f.stat().st_size
        if args.apply:
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    gb = total / 1e9
    if args.apply:
        print(f'Apagados {removed} blobs ja enviados; espaco liberado: {gb:.2f} GB')
    else:
        print(f'DRY-RUN: {found} blobs ja enviados no disco, {gb:.2f} GB a liberar. Rode com --apply para apagar.')


if __name__ == '__main__':
    main()
