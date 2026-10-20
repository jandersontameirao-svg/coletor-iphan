"""Migrações aditivas para descoberta pública rastreável de páginas SEI/IPHAN."""


def migrate(db):
    with db() as c:
        columns = {row["name"] for row in c.execute("PRAGMA table_info(link_items)")}
        additions = {
            "kind": "TEXT NOT NULL DEFAULT 'direct_document'",
            "parent_item_id": "TEXT REFERENCES link_items(id)",
            "display_name": "TEXT NOT NULL DEFAULT ''",
            "metadata": "TEXT NOT NULL DEFAULT '{}'",
        }
        for name, definition in additions.items():
            if name not in columns:
                c.execute(f"ALTER TABLE link_items ADD COLUMN {name} {definition}")
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS sei_process_pages(
                parent_item_id TEXT PRIMARY KEY REFERENCES link_items(id),
                job_id TEXT NOT NULL REFERENCES jobs(id),
                source_url TEXT NOT NULL,
                process_id TEXT REFERENCES processes(id),
                process_number TEXT NOT NULL,
                process_title TEXT NOT NULL,
                process_type TEXT NOT NULL DEFAULT '',
                interested TEXT NOT NULL DEFAULT '',
                page_restricted_notice INTEGER NOT NULL DEFAULT 0,
                document_total INTEGER NOT NULL DEFAULT 0,
                public_documents INTEGER NOT NULL DEFAULT 0,
                restricted_documents INTEGER NOT NULL DEFAULT 0,
                truncated INTEGER NOT NULL DEFAULT 0,
                discovered_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS link_items_job_parent_idx ON link_items(job_id,parent_item_id,position);
            CREATE INDEX IF NOT EXISTS sei_process_pages_job_idx ON sei_process_pages(job_id,process_id);
            """
        )
        c.execute(
            """
            UPDATE link_items
               SET kind='sei_process_page'
             WHERE kind='direct_document'
               AND url LIKE '%/sei/modulos/pesquisa/md_pesq_processo_exibir.php%'
            """
        )
