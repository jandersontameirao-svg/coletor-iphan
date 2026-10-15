"""Dados sintéticos e sessão limitada para a demonstração pública do Coletor IPHAN."""
import hashlib
import json
import secrets
import time

DEMO_USER_ID = "demo-user-v04"
DEMO_PROCESS_ID = "demo-process-v04"
DEMO_DOCUMENT_ID = "demo-document-v04"
DEMO_REVISION_ID = "demo-revision-v04"
DEMO_EVIDENCE_ID = "demo-evidence-v04"
DEMO_RESOURCE_ID = "demo-resource-v04"
DEMO_RESOURCE_REVISION_ID = "demo-resource-revision-v04"
DEMO_ASSERTION_ID = "demo-assertion-v04"


def seed(db, root, password_hash, event):
    """Cria somente registros sintéticos, de modo idempotente, para visualização pública."""
    content = (
        "Registro sintético de demonstração do Coletor IPHAN 0.4. "
        "Este conteúdo não representa processo, documento, coordenada ou parecer real."
    ).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    now = time.time()
    with db() as c:
        existing = c.execute("SELECT id FROM users WHERE id=?", (DEMO_USER_ID,)).fetchone()
        if existing:
            return
        c.execute(
            "INSERT INTO users(id,name,password,role,active,kind) VALUES(?,?,?,?,?,?)",
            (DEMO_USER_ID, "Visualização demonstrativa", password_hash(secrets.token_urlsafe(40)), "reader", 1, "human"),
        )
        c.execute(
            "INSERT INTO processes(id,owner,number,title,folder,domain,number_key,canonical_id) VALUES(?,?,?,?,?,?,?,?)",
            (
                DEMO_PROCESS_ID,
                DEMO_USER_ID,
                "01506.000001/2026-00",
                "Acervo demonstrativo — Patrimônio Cultural",
                "01506.000001-2026 · Acervo demonstrativo",
                "central",
                "01506000001202600",
                None,
            ),
        )
        c.execute(
            "INSERT INTO process_registry(domain,number_key,process_id) VALUES(?,?,?)",
            ("central", "01506000001202600", DEMO_PROCESS_ID),
        )
        c.execute(
            "INSERT INTO resource_grants(id,process_id,subject_type,subject_id,role,active,created) VALUES(?,?,?,?,?,?,?)",
            ("demo-grant-read-v04", DEMO_PROCESS_ID, "user", DEMO_USER_ID, "read", 1, now),
        )
        blob = root / "blobs" / digest
        blob.write_bytes(content)
        c.execute("INSERT INTO blobs(hash,size,mime) VALUES(?,?,?)", (digest, len(content), "text/plain"))
        c.execute(
            "INSERT INTO documents(id,process_id,name) VALUES(?,?,?)",
            (DEMO_DOCUMENT_ID, DEMO_PROCESS_ID, "nota-tecnica-demonstrativa.txt"),
        )
        c.execute(
            "INSERT INTO revisions(id,document_id,blob,predecessor,created) VALUES(?,?,?,?,?)",
            (DEMO_REVISION_ID, DEMO_DOCUMENT_ID, digest, None, now),
        )
        c.execute(
            "INSERT INTO occurrences(id,revision_id,source,name,created) VALUES(?,?,?,?,?)",
            ("demo-occurrence-v04", DEMO_REVISION_ID, "synthetic-demo", "nota-tecnica-demonstrativa.txt", now),
        )
        c.execute(
            "INSERT INTO evidence(id,revision_id,page,text,method,run_id) VALUES(?,?,?,?,?,?)",
            (
                DEMO_EVIDENCE_ID,
                DEMO_REVISION_ID,
                None,
                "Evidência sintética: a área demonstrativa deve ser interpretada exclusivamente como material de avaliação visual e funcional.",
                "synthetic-demo",
                None,
            ),
        )
        c.execute(
            "INSERT INTO knowledge_assertions(id,process_id,document_id,revision_id,evidence_id,statement,kind,status,confidence,author,validator,validated_at,rationale,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                DEMO_ASSERTION_ID,
                DEMO_PROCESS_ID,
                DEMO_DOCUMENT_ID,
                DEMO_REVISION_ID,
                DEMO_EVIDENCE_ID,
                "A demonstração expõe uma afirmação rastreável e vinculada à evidência sintética.",
                "fact",
                "validated",
                1.0,
                DEMO_USER_ID,
                DEMO_USER_ID,
                now,
                "Validação demonstrativa; não se trata de conclusão técnica real.",
                now,
                now,
            ),
        )
        features = [
            {
                "index": 0,
                "name": "Área demonstrativa",
                "geometries": [
                    {
                        "type": "Polygon",
                        "coordinates": [[-48.000, -15.000], [-47.990, -15.000], [-47.990, -14.990], [-48.000, -14.990], [-48.000, -15.000]],
                    }
                ],
                "bbox": [-48.000, -15.000, -47.990, -14.990],
                "centroid": [-47.996, -14.996],
                "role": "mentioned",
                "precision": "exact",
            }
        ]
        spatial_digest = hashlib.sha256(json.dumps(features, sort_keys=True).encode()).hexdigest()
        c.execute(
            "INSERT INTO spatial_resources(id,process_id,name,source_filename,source_sha256,created_by,created) VALUES(?,?,?,?,?,?,?)",
            (DEMO_RESOURCE_ID, DEMO_PROCESS_ID, "Área demonstrativa", "area-demonstrativa.kml", spatial_digest, DEMO_USER_ID, now),
        )
        c.execute(
            "INSERT INTO spatial_resource_revisions(id,resource_id,version,source_sha256,srs,feature_json,created_by,created) VALUES(?,?,?,?,?,?,?,?)",
            (DEMO_RESOURCE_REVISION_ID, DEMO_RESOURCE_ID, 1, spatial_digest, "EPSG:4326", json.dumps(features), DEMO_USER_ID, now),
        )
        event(c, DEMO_USER_ID, "demo.seeded", DEMO_PROCESS_ID)


def issue_session(db):
    """Emite token temporário apenas para o usuário sintético de leitura."""
    import secrets

    token = secrets.token_urlsafe(40)
    with db() as c:
        c.execute(
            "INSERT INTO sessions(token,user_id,expires) VALUES(?,?,?)",
            (hashlib.sha256(token.encode()).hexdigest(), DEMO_USER_ID, time.time() + 3600),
        )
    return token
