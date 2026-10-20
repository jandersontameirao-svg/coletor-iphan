"""Rotas 0.4: conhecimento rastreável, geografia versionada e contratos consumidores."""
import hashlib
import json
import time
from pathlib import Path
from typing import Literal
from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import authorization
import geo_domain
import knowledge_domain

MAX_SPATIAL_BYTES = 20 * 1024 * 1024

class AssertionInput(BaseModel):
    process_id: str
    evidence_id: str
    statement: str = Field(min_length=3, max_length=5000)
    kind: Literal['fact','interpretation','transcription','inference','bibliography'] = 'fact'
    confidence: float | None = Field(default=None, ge=0, le=1)

class AssertionReview(BaseModel):
    status: Literal['proposed','validated','rejected','conflict']
    rationale: str = Field(default='', max_length=3000)

class RelationInput(BaseModel):
    related_id: str
    relation: Literal['supports','contradicts','derived_from']

class SpatialQuery(BaseModel):
    process_id: str | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_m: float = Field(default=0, ge=0, le=1000000)


def _body_bytes(request):
    async def read():
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_SPATIAL_BYTES:
                raise HTTPException(413, 'Recurso espacial acima de 20 MiB')
            raw.extend(chunk)
        if not raw:
            raise HTTPException(422, 'Recurso espacial vazio')
        return bytes(raw)
    return read()


def register(app, db, identity, uid, event, process_access, revision_access):
    def visible_assertion(c, aid, user, permission='read'):
        row = c.execute('SELECT * FROM knowledge_assertions WHERE id=?', (aid,)).fetchone()
        if not row:
            raise HTTPException(404, 'Afirmação não encontrada')
        process_access(c, row['process_id'], user, permission)
        return row

    @app.get('/v1/knowledge/assertions')
    def assertions(process_id: str | None = None, user=Depends(identity)):
        with db() as c:
            rows = c.execute('SELECT * FROM knowledge_assertions ORDER BY created').fetchall()
            result = []
            for row in rows:
                if process_id and authorization.resolve(c, process_id)['id'] != row['process_id']:
                    continue
                try:
                    process_access(c, row['process_id'], user, 'read')
                except HTTPException:
                    continue
                relations = c.execute('SELECT id,assertion_id,related_id,relation,created_by,created FROM knowledge_relations WHERE assertion_id=? OR related_id=?', (row['id'], row['id'])).fetchall()
                result.append(knowledge_domain.assertion_payload(row, relations))
            return result

    @app.post('/v1/knowledge/assertions', status_code=201)
    def create_assertion(body: AssertionInput, user=Depends(identity)):
        with db() as c:
            process = process_access(c, body.process_id, user, 'operate')
            evidence = c.execute('SELECT e.*,r.document_id,d.process_id FROM evidence e JOIN revisions r ON r.id=e.revision_id JOIN documents d ON d.id=r.document_id WHERE e.id=?', (body.evidence_id,)).fetchone()
            if not evidence or evidence['process_id'] != process['id']:
                raise HTTPException(422, 'Evidência não pertence ao processo informado')
            aid = uid(); now = time.time()
            c.execute('INSERT INTO knowledge_assertions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (aid, process['id'], evidence['document_id'], evidence['revision_id'], evidence['id'], body.statement, body.kind, 'proposed', body.confidence, user['id'], None, None, '', now, now))
            event(c, user.get('_actor_id', user['id']), 'knowledge.assertion.proposed', aid)
            return {'id': aid, 'status': 'proposed', 'process_id': process['id'], 'evidence_id': body.evidence_id}

    @app.get('/v1/knowledge/assertions/{aid}')
    def get_assertion(aid: str, user=Depends(identity)):
        with db() as c:
            row = visible_assertion(c, aid, user)
            relations = c.execute('SELECT * FROM knowledge_relations WHERE assertion_id=? OR related_id=?', (aid, aid)).fetchall()
            return knowledge_domain.assertion_payload(row, relations)

    @app.patch('/v1/knowledge/assertions/{aid}')
    def review_assertion(aid: str, body: AssertionReview, user=Depends(identity)):
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            row = visible_assertion(c, aid, user, 'review')
            if body.status == 'validated' and not row['evidence_id']:
                raise HTTPException(422, 'Afirmação validada exige evidência')
            stamp = time.time()
            c.execute('UPDATE knowledge_assertions SET status=?,validator=?,validated_at=?,rationale=?,updated=? WHERE id=?', (body.status, user['id'], stamp, body.rationale, stamp, aid))
            event(c, user.get('_actor_id', user['id']), 'knowledge.assertion.' + body.status, aid)
            return {'id': aid, 'status': body.status, 'validator': user['id']}

    @app.post('/v1/knowledge/assertions/{aid}/relations', status_code=201)
    def relate_assertion(aid: str, body: RelationInput, user=Depends(identity)):
        with db() as c:
            first = visible_assertion(c, aid, user, 'review')
            second = visible_assertion(c, body.related_id, user, 'review')
            if first['process_id'] != second['process_id']:
                raise HTTPException(422, 'Relações devem permanecer no mesmo processo')
            rid = uid()
            try:
                c.execute('INSERT INTO knowledge_relations VALUES(?,?,?,?,?,?)', (rid, aid, body.related_id, body.relation, user['id'], time.time()))
            except Exception:
                raise HTTPException(409, 'Relação já registrada')
            event(c, user.get('_actor_id', user['id']), 'knowledge.relation.created', rid)
            return {'id': rid, 'relation': body.relation}

    @app.get('/v1/spatial-resources')
    def spatial_resources(process_id: str | None = None, user=Depends(identity)):
        with db() as c:
            rows = c.execute('SELECT r.*,x.version,x.srs,x.feature_json FROM spatial_resources r JOIN spatial_resource_revisions x ON x.resource_id=r.id WHERE x.version=(SELECT max(x2.version) FROM spatial_resource_revisions x2 WHERE x2.resource_id=r.id) ORDER BY r.created').fetchall()
            result = []
            for row in rows:
                if process_id and authorization.resolve(c, process_id)['id'] != row['process_id']:
                    continue
                try:
                    process_access(c, row['process_id'], user, 'read')
                except HTTPException:
                    continue
                item = dict(row); item.pop('feature_json', None); item['feature_count'] = len(json.loads(row['feature_json']))
                result.append(item)
            return result

    @app.post('/v1/spatial-resources', status_code=201)
    async def create_spatial(request: Request, process_id: str, name: str, filename: str, user=Depends(identity)):
        raw = await _body_bytes(request)
        with db() as c:
            process = process_access(c, process_id, user, 'operate')
            try:
                parsed = geo_domain.parse_resource(raw, filename)
            except ValueError as exc:
                raise HTTPException(422, str(exc))
            resource_id, revision_id = uid(), uid(); now = time.time(); digest = hashlib.sha256(raw).hexdigest()
            c.execute('INSERT INTO spatial_resources VALUES(?,?,?,?,?,?,?)', (resource_id, process['id'], name[:300], filename[:300], digest, user['id'], now))
            c.execute('INSERT INTO spatial_resource_revisions VALUES(?,?,?,?,?,?,?,?)', (revision_id, resource_id, 1, digest, parsed['srs'], geo_domain.dumps_features(parsed['features']), user['id'], now))
            event(c, user.get('_actor_id', user['id']), 'spatial.resource.created', resource_id)
            return {'id': resource_id, 'revision_id': revision_id, 'version': 1, 'feature_count': len(parsed['features']), 'srs': parsed['srs']}

    @app.post('/v1/spatial-resources/{resource_id}/revisions', status_code=201)
    async def new_spatial_revision(resource_id: str, request: Request, filename: str, user=Depends(identity)):
        raw = await _body_bytes(request)
        with db() as c:
            resource = c.execute('SELECT * FROM spatial_resources WHERE id=?', (resource_id,)).fetchone()
            if not resource:
                raise HTTPException(404, 'Recurso espacial não encontrado')
            process_access(c, resource['process_id'], user, 'operate')
            try:
                parsed = geo_domain.parse_resource(raw, filename)
            except ValueError as exc:
                raise HTTPException(422, str(exc))
            version = c.execute('SELECT coalesce(max(version),0)+1 FROM spatial_resource_revisions WHERE resource_id=?', (resource_id,)).fetchone()[0]
            rid, now = uid(), time.time(); digest = hashlib.sha256(raw).hexdigest()
            c.execute('INSERT INTO spatial_resource_revisions VALUES(?,?,?,?,?,?,?,?)', (rid, resource_id, version, digest, parsed['srs'], geo_domain.dumps_features(parsed['features']), user['id'], now))
            c.execute('UPDATE spatial_resources SET source_filename=?,source_sha256=? WHERE id=?', (filename[:300], digest, resource_id))
            event(c, user.get('_actor_id', user['id']), 'spatial.resource.revised', resource_id)
            return {'id': resource_id, 'revision_id': rid, 'version': version, 'feature_count': len(parsed['features']), 'srs': parsed['srs']}

    @app.get('/v1/spatial-resources/{resource_id}')
    def get_spatial(resource_id: str, user=Depends(identity)):
        with db() as c:
            resource = c.execute('SELECT * FROM spatial_resources WHERE id=?', (resource_id,)).fetchone()
            if not resource:
                raise HTTPException(404)
            process_access(c, resource['process_id'], user, 'read')
            revisions = [dict(row) for row in c.execute('SELECT * FROM spatial_resource_revisions WHERE resource_id=? ORDER BY version', (resource_id,)).fetchall()]
            for item in revisions:
                item['features'] = json.loads(item.pop('feature_json'))
            result = dict(resource); result['revisions'] = revisions
            return result

    @app.post('/v1/spatial-search')
    def spatial_search(body: SpatialQuery, user=Depends(identity)):
        with db() as c:
            if body.process_id:
                process_ids = [process_access(c, body.process_id, user, 'read')['id']]
            else:
                process_ids = [row['id'] for row in c.execute('SELECT id FROM processes WHERE canonical_id IS NULL').fetchall() if _can_read(c, row['id'], user)]
            results = []
            for pid in process_ids:
                rows = c.execute('SELECT r.*,x.version,x.srs,x.feature_json FROM spatial_resources r JOIN spatial_resource_revisions x ON x.resource_id=r.id WHERE r.process_id=? AND x.version=(SELECT max(x2.version) FROM spatial_resource_revisions x2 WHERE x2.resource_id=r.id)', (pid,)).fetchall()
                for row in rows:
                    for feature in geo_domain.search(json.loads(row['feature_json']), body.latitude, body.longitude, body.radius_m):
                        results.append({'resource_id': row['id'], 'resource_name': row['name'], 'process_id': pid, 'version': row['version'], 'srs': row['srs'], 'feature': feature})
            return {'items': sorted(results, key=lambda item: item['feature']['distance_m']), 'spatial_available': True, 'units': 'metres', 'source': 'KML/KMZ, Shapefile, GeoJSON/JSON e GPX em WGS84'}

    @app.get('/v1/overview/advanced')
    def advanced_overview(user=Depends(identity)):
        with db() as c:
            assertions = sum(1 for row in c.execute('SELECT process_id FROM knowledge_assertions') if _can_read(c, row['process_id'], user))
            resources = sum(1 for row in c.execute('SELECT process_id FROM spatial_resources') if _can_read(c, row['process_id'], user))
            revisions = c.execute('SELECT count(*) FROM spatial_resource_revisions').fetchone()[0]
            return {'knowledge_assertions': assertions, 'spatial_resources': resources, 'spatial_revisions': revisions, 'knowledge_validation': 'human_review_required', 'external_homologation': False}

    @app.get('/v1/integration/capabilities')
    def integration_capabilities(user=Depends(identity)):
        return {'version': '0.5.0', 'consumer_contract': True, 'atena_real_homologated': False, 'geoportal_real_homologated': False, 'explicit_links_only': True, 'knowledge': {'assertions': True, 'human_validation': True, 'automatic_facts': False}, 'spatial': {'kml': True, 'kmz': True, 'shapefile_zip': True, 'geojson': True, 'json': True, 'gpx': True, 'pdf_document_import': True, 'srs': ['EPSG:4326'], 'distance_units': 'metres'}, 'external_collection': {'implemented': True, 'homologated': False}}


def _can_read(c, pid, user):
    try:
        authorization.process_access(c, pid, user, 'read')
        return True
    except HTTPException:
        return False
