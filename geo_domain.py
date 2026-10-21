"""Importação geográfica verificável para KML/KMZ, GeoJSON/JSON, GPX e Shapefile."""
from __future__ import annotations

import io
import json
import math
import struct
import zipfile
import xml.etree.ElementTree as ET
from typing import Any

EARTH_RADIUS_M = 6371008.8
SUPPORTED_SRS = {'EPSG:4326', 'CRS84', 'WGS84', ''}
MAX_VECTOR_FILES = 200
MAX_VECTOR_UNCOMPRESSED = 50 * 1024 * 1024
MAX_FEATURES = 10000


def migrate(db):
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS spatial_resources(
            id TEXT PRIMARY KEY,
            process_id TEXT NOT NULL REFERENCES processes(id),
            name TEXT NOT NULL,
            source_filename TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            created_by TEXT NOT NULL REFERENCES users(id),
            created REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS spatial_resource_revisions(
            id TEXT PRIMARY KEY,
            resource_id TEXT NOT NULL REFERENCES spatial_resources(id),
            version INTEGER NOT NULL,
            source_sha256 TEXT NOT NULL,
            srs TEXT NOT NULL DEFAULT 'EPSG:4326',
            feature_json TEXT NOT NULL,
            created_by TEXT NOT NULL REFERENCES users(id),
            created REAL NOT NULL,
            UNIQUE(resource_id,version)
        );
        CREATE INDEX IF NOT EXISTS spatial_process_idx ON spatial_resources(process_id);
        ''')


def _local(element):
    return element.tag.rsplit('}', 1)[-1].lower() if isinstance(element.tag, str) else ''


def _children(element, name):
    return [child for child in element.iter() if _local(child) == name]


def _text(element, name):
    for child in element.iter():
        if _local(child) == name and child.text:
            return child.text.strip()
    return ''


def _finite(value):
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _point(value):
    if not isinstance(value, (list, tuple)) or len(value) < 2 or not _finite(value[0]) or not _finite(value[1]):
        raise ValueError('coordenada geográfica inválida')
    lon, lat = float(value[0]), float(value[1])
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise ValueError('coordenada fora dos limites WGS84')
    return [lon, lat]


def _coordinates(text):
    points = []
    for item in (text or '').replace('\n', ' ').replace('\t', ' ').split():
        bits = [piece for piece in item.split(',') if piece]
        if len(bits) < 2:
            continue
        try:
            points.append(_point((float(bits[0]), float(bits[1]))))
        except ValueError:
            raise
        except (TypeError, ValueError) as exc:
            raise ValueError('coordenada geográfica inválida') from exc
    return points


def _coordinate_sequence(value):
    if not isinstance(value, list):
        raise ValueError('geometria sem coordenadas válidas')
    return [_point(item) for item in value]


def _bbox(points):
    if not points:
        return None
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    return [min(lons), min(lats), max(lons), max(lats)]


def _centroid(points):
    if not points:
        return None
    return [sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points)]


def _ring_area(ring):
    if len(ring) < 3:
        return 0.0
    return sum(ring[index - 1][0] * ring[index][1] - ring[index][0] * ring[index - 1][1] for index in range(len(ring))) / 2


def _polygon_geometries(rings, oriented=False):
    valid = [ring for ring in rings if len(ring) >= 3]
    if not valid:
        return []
    geometries = []
    if not oriented:
        geometry = {'type': 'Polygon', 'coordinates': valid[0]}
        if len(valid) > 1:
            geometry['holes'] = valid[1:]
        return [geometry]
    outer = None
    for ring in valid:
        if outer is None or _ring_area(ring) < 0:
            outer = ring
            geometries.append({'type': 'Polygon', 'coordinates': ring})
        else:
            geometries[-1].setdefault('holes', []).append(ring)
    return geometries


def _feature(index, name, geometries, properties=None):
    points = []
    for geometry in geometries:
        coordinates = geometry.get('coordinates', [])
        if geometry.get('type') == 'Point' and coordinates:
            points.append(coordinates)
        else:
            points.extend(coordinates)
        for hole in geometry.get('holes', []):
            points.extend(hole)
    value = {
        'index': index,
        'name': str(name or f'Feição {index + 1}')[:300],
        'geometries': geometries,
        'bbox': _bbox(points),
        'centroid': _centroid(points),
        'role': 'mentioned',
        'precision': 'exact',
    }
    if properties:
        value['properties'] = properties
    return value


def parse_kml(data, filename='resource.kml'):
    """Retorna geometria normalizada e rejeita KML malformado ou SRS não suportado."""
    name = filename.lower()
    if name.endswith('.kmz'):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                _validate_zip(archive)
                candidates = [item for item in archive.namelist() if item.lower().endswith('.kml') and not item.startswith('__MACOSX/')]
                if not candidates:
                    raise ValueError('KMZ sem arquivo KML')
                data = archive.read(candidates[0])
        except zipfile.BadZipFile as exc:
            raise ValueError('KMZ inválido') from exc
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, UnicodeDecodeError) as exc:
        raise ValueError('KML inválido') from exc
    features = []
    for index, placemark in enumerate([node for node in root.iter() if _local(node) == 'placemark']):
        title = _text(placemark, 'name') or f'Feição {index + 1}'
        geometries = []
        for node in placemark.iter():
            tag = _local(node)
            if tag not in ('point', 'linestring', 'polygon'):
                continue
            coords = _coordinates(_text(node, 'coordinates'))
            if not coords:
                continue
            if tag == 'point':
                geometries.append({'type': 'Point', 'coordinates': coords[0]})
            elif tag == 'linestring':
                geometries.append({'type': 'LineString', 'coordinates': coords})
            else:
                boundaries=[n for n in node.iter() if _local(n) in ('outerboundaryis','innerboundaryis')]
                rings=[_coordinates(_text(boundary,'coordinates')) for boundary in boundaries]
                geometries.extend(_polygon_geometries(rings or [coords]))
        if geometries:
            features.append(_feature(index, title, geometries))
    if not features:
        raise ValueError('KML sem Placemark com geometria suportada')
    return {'srs': 'EPSG:4326', 'features': features, 'format': 'kml'}


def _geojson_srs(value):
    crs = value.get('crs') if isinstance(value, dict) else None
    if not crs:
        return 'EPSG:4326'
    name = json.dumps(crs, ensure_ascii=False).upper()
    if '4326' in name or 'CRS84' in name or 'WGS 84' in name or 'WGS84' in name:
        return 'EPSG:4326'
    raise ValueError('GeoJSON com SRC diferente de WGS84/EPSG:4326; reprojete antes da importação')


def _geojson_geometries(geometry):
    if not geometry:
        return []
    kind = geometry.get('type')
    coordinates = geometry.get('coordinates')
    if kind == 'Point':
        return [{'type': 'Point', 'coordinates': _point(coordinates)}]
    if kind == 'MultiPoint':
        return [{'type': 'Point', 'coordinates': _point(item)} for item in coordinates]
    if kind == 'LineString':
        return [{'type': 'LineString', 'coordinates': _coordinate_sequence(coordinates)}]
    if kind == 'MultiLineString':
        return [{'type': 'LineString', 'coordinates': _coordinate_sequence(line)} for line in coordinates]
    if kind == 'Polygon':
        rings = [_coordinate_sequence(ring) for ring in coordinates]
        return _polygon_geometries(rings)
    if kind == 'MultiPolygon':
        geometries = []
        for polygon in coordinates:
            geometries.extend(_polygon_geometries([_coordinate_sequence(ring) for ring in polygon]))
        return geometries
    if kind == 'GeometryCollection':
        geometries = []
        for child in geometry.get('geometries') or []:
            geometries.extend(_geojson_geometries(child))
        return geometries
    raise ValueError(f'GeoJSON geometry não suportada: {kind or "ausente"}')


def _geojson_name(properties, index):
    if isinstance(properties, dict):
        for key in ('name', 'Name', 'NAME', 'nome', 'NOME', 'title', 'id'):
            if properties.get(key) not in (None, ''):
                return str(properties[key])
    return f'Feição {index + 1}'


def parse_geojson(data, filename='resource.geojson'):
    try:
        value = json.loads(data.decode('utf-8-sig'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('JSON/GeoJSON inválido') from exc
    srs = _geojson_srs(value)
    kind = value.get('type') if isinstance(value, dict) else None
    raw_features = []
    if kind == 'FeatureCollection':
        raw_features = value.get('features') or []
    elif kind == 'Feature':
        raw_features = [value]
    elif kind in ('Point', 'MultiPoint', 'LineString', 'MultiLineString', 'Polygon', 'MultiPolygon', 'GeometryCollection'):
        raw_features = [{'type': 'Feature', 'geometry': value, 'properties': {}}]
    else:
        raise ValueError('JSON deve ser GeoJSON FeatureCollection, Feature ou Geometry')
    if len(raw_features) > MAX_FEATURES:
        raise ValueError(f'GeoJSON acima do limite de {MAX_FEATURES} feições')
    features = []
    for index, item in enumerate(raw_features):
        if not isinstance(item, dict) or item.get('type') != 'Feature':
            raise ValueError('Feature GeoJSON inválida')
        geometries = _geojson_geometries(item.get('geometry'))
        if not geometries:
            continue
        properties = item.get('properties') if isinstance(item.get('properties'), dict) else {}
        features.append(_feature(index, _geojson_name(properties, index), geometries, properties))
    if not features:
        raise ValueError('GeoJSON sem feições com geometria suportada')
    return {'srs': srs, 'features': features, 'format': 'geojson'}


def parse_gpx(data, filename='resource.gpx'):
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, UnicodeDecodeError) as exc:
        raise ValueError('GPX inválido') from exc
    features = []
    index = 0
    for waypoint in _children(root, 'wpt'):
        try:
            point = _point((float(waypoint.attrib['lon']), float(waypoint.attrib['lat'])))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('GPX contém waypoint inválido') from exc
        features.append(_feature(index, _text(waypoint, 'name') or f'Waypoint {index + 1}', [{'type': 'Point', 'coordinates': point}]))
        index += 1
    for route in _children(root, 'rte'):
        points = []
        for item in _children(route, 'rtept'):
            try:
                points.append(_point((float(item.attrib['lon']), float(item.attrib['lat']))))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError('GPX contém rota inválida') from exc
        if points:
            features.append(_feature(index, _text(route, 'name') or f'Rota {index + 1}', [{'type': 'LineString', 'coordinates': points}]))
            index += 1
    for track in _children(root, 'trk'):
        for segment in _children(track, 'trkseg'):
            points = []
            for item in _children(segment, 'trkpt'):
                try:
                    points.append(_point((float(item.attrib['lon']), float(item.attrib['lat']))))
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError('GPX contém trilha inválida') from exc
            if points:
                features.append(_feature(index, _text(track, 'name') or f'Trilha {index + 1}', [{'type': 'LineString', 'coordinates': points}]))
                index += 1
    if not features:
        raise ValueError('GPX sem waypoint, rota ou trilha com geometria')
    if len(features) > MAX_FEATURES:
        raise ValueError(f'GPX acima do limite de {MAX_FEATURES} feições')
    return {'srs': 'EPSG:4326', 'features': features, 'format': 'gpx'}


def _validate_zip(archive):
    infos = [item for item in archive.infolist() if not item.is_dir()]
    if len(infos) > MAX_VECTOR_FILES:
        raise ValueError(f'Arquivo compactado acima do limite de {MAX_VECTOR_FILES} arquivos')
    total = 0
    for item in infos:
        name = item.filename.replace('\\', '/')
        if name.startswith('/') or any(part in ('', '..') for part in name.split('/')):
            raise ValueError('Arquivo compactado contém caminho inválido')
        total += item.file_size
        if total > MAX_VECTOR_UNCOMPRESSED:
            raise ValueError('Arquivo compactado acima do limite de expansão')
    return infos


def _dbf_records(data):
    if len(data) < 32 or data[0] == 0:
        return []
    count = struct.unpack_from('<I', data, 4)[0]
    header_len = struct.unpack_from('<H', data, 8)[0]
    record_len = struct.unpack_from('<H', data, 10)[0]
    fields = []
    offset = 32
    while offset + 32 <= len(data) and data[offset] != 0x0D:
        raw_name = data[offset:offset + 11].split(b'\0', 1)[0]
        fields.append((raw_name.decode('latin-1', 'replace').strip(), data[offset + 16]))
        offset += 32
    records = []
    for row_index in range(min(count, MAX_FEATURES)):
        start = header_len + row_index * record_len
        if start + record_len > len(data):
            break
        row = data[start:start + record_len]
        if row[:1] == b'*':
            records.append({})
            continue
        cursor = 1
        result = {}
        for name, width in fields:
            raw = row[cursor:cursor + width]
            cursor += width
            result[name] = raw.decode('latin-1', 'replace').strip()
        records.append(result)
    return records


def _shapefile_files(data, filename):
    lower = filename.lower()
    if lower.endswith('.shp'):
        return data, None, None, None
    if not lower.endswith('.zip'):
        raise ValueError('Formato geográfico aceito: KML, KMZ, GeoJSON/JSON, GPX ou Shapefile ZIP')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = _validate_zip(archive)
            files = {item.filename.replace('\\', '/').lower(): item.filename for item in infos}
            shp_names = [name for name in files if name.endswith('.shp')]
            if not shp_names:
                vector_names = [name for name in files if name.endswith(('.geojson', '.json', '.gpx', '.kml'))]
                if len(vector_names) == 1:
                    internal = files[vector_names[0]]
                    return archive.read(internal), internal.lower(), None, None
                raise ValueError('ZIP de Shapefile deve conter arquivo .shp')
            shp_key = shp_names[0]
            stem = shp_key[:-4]
            def find(extension):
                return next((files[name] for name in files if name == stem + extension or name.endswith('/' + stem.split('/')[-1] + extension)), None)
            shp = archive.read(files[shp_key])
            shx_name = find('.shx')
            dbf_name = find('.dbf')
            prj_name = find('.prj')
            shx = archive.read(shx_name) if shx_name else None
            dbf = archive.read(dbf_name) if dbf_name else None
            prj = archive.read(prj_name) if prj_name else None
            return shp, '.shp', dbf, prj
    except zipfile.BadZipFile as exc:
        raise ValueError('ZIP de Shapefile inválido') from exc


def _check_prj(prj):
    if not prj:
        raise ValueError('Shapefile sem PRJ: informe SRC WGS84 explícito antes da importação')
    text = prj.decode('latin-1', 'replace').upper()
    if any(token in text for token in ('WGS_1984', 'WGS 84', 'EPSG","4326', '4326', 'CRS84')):
        return 'EPSG:4326'
    raise ValueError('Shapefile com SRC diferente de WGS84/EPSG:4326; reprojete antes da importação')


def parse_shapefile(data, filename='resource.zip'):
    shp, internal_name, dbf, prj = _shapefile_files(data, filename)
    if internal_name and internal_name.endswith(('.geojson', '.json', '.gpx', '.kml')):
        if internal_name.endswith(('.geojson', '.json')):
            return parse_geojson(shp, internal_name)
        if internal_name.endswith('.gpx'):
            return parse_gpx(shp, internal_name)
        return parse_kml(shp, internal_name)
    srs = _check_prj(prj)
    if len(shp) < 100 or struct.unpack_from('>i', shp, 0)[0] != 9994 or struct.unpack_from('<i', shp, 28)[0] != 1000:
        raise ValueError('Shapefile .shp inválido')
    records = _dbf_records(dbf) if dbf else []
    shape_type_header = struct.unpack_from('<i', shp, 32)[0]
    features = []
    offset = 100
    record_index = 0
    while offset + 8 <= len(shp):
        _, content_words = struct.unpack_from('>ii', shp, offset)
        offset += 8
        content_size = content_words * 2
        if content_size < 4 or offset + content_size > len(shp):
            raise ValueError('Shapefile contém registro truncado')
        content = shp[offset:offset + content_size]
        offset += content_size
        shape_type = struct.unpack_from('<i', content, 0)[0]
        family = shape_type if shape_type in (0, 1, 3, 5, 8) else shape_type - 10 if shape_type in (11, 13, 15, 18) else shape_type - 20 if shape_type in (21, 23, 25, 28) else shape_type
        geometries = []
        if family == 0:
            record_index += 1
            continue
        if family == 1:
            if len(content) < 20:
                raise ValueError('Shapefile Point inválido')
            geometries = [{'type': 'Point', 'coordinates': _point(struct.unpack_from('<dd', content, 4))}]
        elif family == 8:
            if len(content) < 40:
                raise ValueError('Shapefile MultiPoint inválido')
            count = struct.unpack_from('<i', content, 36)[0]
            if count < 0 or count > MAX_FEATURES or 40 + count * 16 > len(content):
                raise ValueError('Shapefile MultiPoint inválido')
            geometries = [{'type': 'Point', 'coordinates': _point(struct.unpack_from('<dd', content, 40 + index * 16))} for index in range(count)]
        elif family in (3, 5):
            if len(content) < 44:
                raise ValueError('Shapefile PolyLine/Polygon inválido')
            part_count, point_count = struct.unpack_from('<ii', content, 36)
            if part_count < 1 or point_count < 1 or part_count > point_count or point_count > MAX_FEATURES:
                raise ValueError('Shapefile PolyLine/Polygon inválido')
            parts_offset = 44
            points_offset = parts_offset + part_count * 4
            if points_offset + point_count * 16 > len(content):
                raise ValueError('Shapefile PolyLine/Polygon truncado')
            parts = list(struct.unpack_from('<' + 'i' * part_count, content, parts_offset))
            if parts[0] != 0 or any(parts[index] >= parts[index + 1] for index in range(len(parts) - 1)) or parts[-1] >= point_count:
                raise ValueError('Shapefile com partes inválidas')
            points = [_point(struct.unpack_from('<dd', content, points_offset + index * 16)) for index in range(point_count)]
            rings = []
            for index, start in enumerate(parts):
                end = parts[index + 1] if index + 1 < len(parts) else point_count
                ring = points[start:end]
                if family == 3:
                    geometries.append({'type': 'LineString', 'coordinates': ring})
                else:
                    rings.append(ring)
            if family == 5:
                geometries.extend(_polygon_geometries(rings, oriented=True))
        else:
            raise ValueError(f'Tipo de geometria Shapefile não suportado: {shape_type or shape_type_header}')
        if geometries:
            properties = records[record_index] if record_index < len(records) else {}
            features.append(_feature(record_index, _geojson_name(properties, record_index), geometries, properties))
        record_index += 1
        if len(features) > MAX_FEATURES:
            raise ValueError(f'Shapefile acima do limite de {MAX_FEATURES} feições')
    if not features:
        raise ValueError('Shapefile sem geometria suportada')
    return {'srs': srs, 'features': features, 'format': 'shapefile'}


def parse_resource(data, filename):
    lower = filename.lower()
    if lower.endswith(('.kml', '.kmz')):
        return parse_kml(data, filename)
    if lower.endswith(('.geojson', '.json')):
        return parse_geojson(data, filename)
    if lower.endswith('.gpx'):
        return parse_gpx(data, filename)
    if lower.endswith(('.shp', '.zip')):
        return parse_shapefile(data, filename)
    raise ValueError('Formato geográfico aceito: KML, KMZ, GeoJSON/JSON, GPX ou Shapefile ZIP')


def haversine_m(a, b):
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    dlon, dlat = lon2 - lon1, lat2 - lat1
    x = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1, math.sqrt(x)))


def _point_in_polygon(point, polygon):
    x, y = point
    inside = False
    for index in range(len(polygon)):
        x1, y1 = polygon[index - 1]
        x2, y2 = polygon[index]
        crosses = ((y1 > y) != (y2 > y)) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1
        if crosses:
            inside = not inside
    return inside


def feature_distance_m(feature, point):
    distances = []
    inside = False
    for geometry in feature.get('geometries', []):
        coordinates = geometry.get('coordinates', [])
        if geometry.get('type') == 'Point' and coordinates:
            coordinates = [coordinates]
        distances.extend(haversine_m(point, coordinate) for coordinate in coordinates)
        if geometry.get('type') in ('LineString','Polygon'):
            segments=list(zip(coordinates,coordinates[1:]))
            if geometry.get('type')=='Polygon' and coordinates: segments.append((coordinates[-1],coordinates[0]))
            for hole in geometry.get('holes',[]): segments.extend(zip(hole,hole[1:]+hole[:1]))
            distances.extend(segment_distance_m(point,a,b) for a,b in segments)
        if geometry.get('type') == 'Polygon' and len(coordinates) >= 3:
            in_hole = any(_point_in_polygon(point, hole) for hole in geometry.get('holes', []))
            inside = inside or (_point_in_polygon(point, coordinates) and not in_hole)
    return 0.0 if inside else (min(distances) if distances else None)


def search(features, latitude, longitude, radius_m: float = 0):
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError('latitude/longitude fora dos limites')
    if radius_m < 0 or radius_m > 1000000:
        raise ValueError('radius_m deve estar entre 0 e 1.000.000')
    point = [longitude, latitude]
    matches = []
    for feature in features:
        distance = feature_distance_m(feature, point)
        if distance is not None and distance <= radius_m:
            matches.append({**feature, 'distance_m': round(distance, 3), 'match_reason': 'inside_or_intersects' if distance == 0 else 'within_radius'})
    return sorted(matches, key=lambda item: item['distance_m'])


def dumps_features(features):
    return json.dumps(features, ensure_ascii=False, separators=(',', ':'))


def segment_distance_m(point,a,b):
    """Distância sobre esfera ao arco menor, com projeção limitada ao segmento."""
    def bearing(x,y):
        lat1,lat2=math.radians(x[1]),math.radians(y[1]);dlon=math.radians(y[0]-x[0])
        return math.atan2(math.sin(dlon)*math.cos(lat2),math.cos(lat1)*math.sin(lat2)-math.sin(lat1)*math.cos(lat2)*math.cos(dlon))
    length=haversine_m(a,b)
    if length<1e-8: return haversine_m(point,a)
    delta=haversine_m(a,point)/EARTH_RADIUS_M;theta=bearing(a,point)-bearing(a,b)
    along=math.atan2(math.sin(delta)*math.cos(theta),math.cos(delta))*EARTH_RADIUS_M
    if 0<=along<=length: return abs(math.asin(max(-1,min(1,math.sin(delta)*math.sin(theta)))))*EARTH_RADIUS_M
    return min(haversine_m(point,a),haversine_m(point,b))
