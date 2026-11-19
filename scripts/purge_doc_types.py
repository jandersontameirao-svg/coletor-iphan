"""Remove definitivamente documentos de tipos indesejados (e-mail, portaria) já coletados.

Apaga do SharePoint (Graph DELETE) E do catálogo, mantendo os dois em sincronia e sem
deixar linhas órfãs. Por segurança roda em DRY-RUN por padrão: só lista o que apagaria.
Para apagar de verdade, passe --apply.

Uso (na VPS):
  /var/www/coletor/.venv/bin/python scripts/purge_doc_types.py            # dry-run
  /var/www/coletor/.venv/bin/python scripts/purge_doc_types.py --apply    # apaga
  ... --collection Zanettini --types "e-mail,portaria"

O escopo padrão é a coleção 'Zanettini' e os tipos 'e-mail,portaria'.
"""
import argparse
import os
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def _load_env():
    """Carrega o .env de produção para o ambiente antes de importar o app (DB, chaves, SharePoint)."""
    env = ROOT_DIR / '.env'
    if not env.exists():
        return
    for line in env.read_text(encoding='utf-8', errors='replace').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _pattern(types):
    terms = [t.strip() for t in types.split(',') if t.strip()]
    if not terms:
        raise SystemExit('Nenhum tipo informado em --types.')
    return re.compile(r'\b(?:' + '|'.join(re.escape(t) for t in terms) + r')', re.I)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--collection', default='Zanettini', help="Coleção a limpar (padrão: Zanettini). Use '' para todas.")
    parser.add_argument('--types', default='e-mail,portaria', help='Tipos a remover, separados por vírgula.')
    parser.add_argument('--apply', action='store_true', help='Apaga de verdade (sem isto, só lista).')
    args = parser.parse_args()

    _load_env()
    import app
    import sharepoint_store as cloud

    pattern = _pattern(args.types)

    with app.db() as c:
        if args.collection:
            rows = c.execute('SELECT d.id,d.name,d.process_id,p.number,p.collection FROM documents d JOIN processes p ON p.id=d.process_id WHERE p.collection=?', (args.collection,)).fetchall()
        else:
            rows = c.execute('SELECT d.id,d.name,d.process_id,p.number,p.collection FROM documents d JOIN processes p ON p.id=d.process_id').fetchall()
    targets = [dict(r) for r in rows if pattern.search(r['name'] or '')]

    print(f"Coleção: {args.collection or '(todas)'} | tipos: {args.types}")
    print(f"Documentos encontrados para remover: {len(targets)}")
    if not targets:
        print('Nada a fazer.')
        return

    # Levanta transferências remotas (uploaded) de cada documento.
    plano = []
    with app.db() as c:
        for d in targets:
            transfers = [dict(t) for t in c.execute(
                "SELECT t.id,t.status,t.item_id,t.remote_path,t.revision_id FROM cloud_transfers t "
                "JOIN revisions r ON r.id=t.revision_id WHERE r.document_id=?", (d['id'],)).fetchall()]
            plano.append({**d, 'transfers': transfers})

    uploaded = sum(1 for d in plano for t in d['transfers'] if t['status'] == 'uploaded' and t['item_id'])
    uploading = sum(1 for d in plano for t in d['transfers'] if t['status'] == 'uploading')
    print(f"  arquivos já no SharePoint a apagar: {uploaded}")
    if uploading:
        print(f"  ATENÇÃO: {uploading} transferência(s) em andamento (uploading) — esses documentos serão pulados.")
    for d in plano[:40]:
        marca = next((t['remote_path'] for t in d['transfers'] if t['status'] == 'uploaded'), '(ainda não no SharePoint)')
        print(f"   - {d['number']}  |  {d['name']}  ->  {marca}")
    if len(plano) > 40:
        print(f"   ... e mais {len(plano) - 40}.")

    if not args.apply:
        print('\nDRY-RUN: nada foi apagado. Rode de novo com --apply para remover de verdade.')
        return

    graph = None
    drive_id = None
    try:
        target = cloud.configuration(app.db)
        drive_id = target.get('drive_id')
        if drive_id:
            graph = cloud.Graph(app.db, app.ROOT)
    except Exception as exc:  # noqa: BLE001
        print(f'Aviso: não foi possível preparar o SharePoint ({exc}). Abortando para não dessincronizar.')
        sys.exit(1)

    removed_docs = 0
    removed_remote = 0
    skipped = 0
    freed_blobs = 0
    for d in plano:
        if any(t['status'] == 'uploading' for t in d['transfers']):
            skipped += 1
            print(f"PULADO (upload em andamento): {d['name']}")
            continue
        # 1) Apaga os arquivos remotos; só segue para o catálogo se todos saírem.
        remote_ok = True
        for t in d['transfers']:
            if t['status'] == 'uploaded' and t['item_id']:
                if not (graph and drive_id):
                    print('SharePoint não conectado; não dá para apagar o arquivo remoto. Abortando.')
                    sys.exit(1)
                from urllib.parse import quote
                try:
                    graph.request('DELETE', '/drives/' + quote(drive_id, safe='') + '/items/' + quote(t['item_id'], safe=''))
                    removed_remote += 1
                except cloud.CloudError as exc:
                    if getattr(exc, 'status', None) == 404:
                        pass  # já não existe lá: segue
                    else:
                        remote_ok = False
                        print(f"FALHA ao apagar remoto de {d['name']}: {exc.code}")
                        break
        if not remote_ok:
            skipped += 1
            continue
        # 2) Apaga as linhas do catálogo deste documento, em ordem segura.
        with app.db() as c:
            c.execute('BEGIN IMMEDIATE')
            rids = [r['id'] for r in c.execute('SELECT id FROM revisions WHERE document_id=?', (d['id'],)).fetchall()]
            blobs = [r['blob'] for r in c.execute('SELECT blob FROM revisions WHERE document_id=?', (d['id'],)).fetchall()]
            qmarks = ','.join('?' * len(rids)) if rids else None
            if qmarks:
                c.execute(f'DELETE FROM knowledge_relations WHERE assertion_id IN (SELECT id FROM knowledge_assertions WHERE revision_id IN ({qmarks}))', rids)
                c.execute(f'DELETE FROM knowledge_assertions WHERE revision_id IN ({qmarks})', rids)
                c.execute(f'DELETE FROM evidence WHERE revision_id IN ({qmarks})', rids)
                c.execute(f'DELETE FROM market_jobs WHERE revision_id IN ({qmarks})', rids)
                c.execute(f'DELETE FROM extraction_runs WHERE revision_id IN ({qmarks})', rids)
                c.execute(f'DELETE FROM occurrences WHERE revision_id IN ({qmarks})', rids)
                c.execute(f'DELETE FROM cloud_transfers WHERE revision_id IN ({qmarks})', rids)
                c.execute(f"UPDATE link_items SET revision_id=NULL,status='purged',detail='Tipo excluído (e-mail/portaria) removido definitivamente' WHERE revision_id IN ({qmarks})", rids)
            c.execute('DELETE FROM classifications WHERE document_id=?', (d['id'],))
            c.execute('DELETE FROM document_keys WHERE document_id=?', (d['id'],))
            c.execute('DELETE FROM document_sources WHERE document_id=?', (d['id'],))
            c.execute('DELETE FROM archive_label_history WHERE document_id=?', (d['id'],))
            c.execute('DELETE FROM archive_labels WHERE document_id=?', (d['id'],))
            c.execute('DELETE FROM revisions WHERE document_id=?', (d['id'],))
            c.execute('DELETE FROM documents WHERE id=?', (d['id'],))
            # 3) Blobs órfãos (nenhuma revisão nem snapshot/geo referenciando): apaga registro e arquivo.
            for h in set(blobs):
                used = c.execute('SELECT 1 FROM revisions WHERE blob=? LIMIT 1', (h,)).fetchone()
                snap = c.execute('SELECT 1 FROM source_snapshots WHERE blob=? LIMIT 1', (h,)).fetchone()
                geo = c.execute('SELECT 1 FROM spatial_resource_revisions WHERE source_sha256=? LIMIT 1', (h,)).fetchone()
                if not used and not snap and not geo:
                    c.execute('DELETE FROM blobs WHERE hash=?', (h,))
                    try:
                        (app.ROOT / 'blobs' / h).unlink()
                        freed_blobs += 1
                    except OSError:
                        pass
        removed_docs += 1

    print(f"\nConcluído. Documentos removidos: {removed_docs} | arquivos apagados no SharePoint: {removed_remote} | blobs liberados: {freed_blobs} | pulados: {skipped}")


if __name__ == '__main__':
    main()
