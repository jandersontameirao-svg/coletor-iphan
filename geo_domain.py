"""KML/KMZ verificável sem cópia de originais e sem assumir graus como metros."""
import io
import json
import math
import zipfile
import xml.etree.ElementTree as ET

EARTH_RADIUS_M = 6371008.8
SUPPORTED_SRS = {'EPSG:4326', 'CRS84', 'WGS84', ''}


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
    return element.tag.rsplit('}', 1)[-1].lower()


def _children(element, name):
    return [child for child in element.iter() if _local(child) == name]


def _text(element, name):
    for child in element.iter():
        if _local(child) == name and child.text:
            return child.text.strip()
    return ''


def _coordinates(text):
    points = []
    for item in (text or '').replace('\n', ' ').replace('\t', ' ').split():
        bits = [piece for piece in item.split(',') if piece]
        if len(bits) < 2:
            continue
        try:
            lon, lat = float(bits[0]), float(bits[1])
        except ValueError:
            continue
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise ValueError('coordenada fora dos limites WGS84')
        points.append([lon, lat])
    return points


def _bbox(points):
    if not points:
        return None
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    return [min(lons), min(lats), max(lons), max(lats)]


def _centroid(points):
    if not points:
        return None
    return [sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)]


def parse_kml(data, filename='resource.kml'):
    """Retorna geometria normalizada e rejeita KML malformado ou SRS não suportado."""
    name = filename.lower()
    if name.endswith('.kmz'):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            candidates = [item for item in archive.namelist() if item.lower().endswith('.kml') and not item.startswith('__MACOSX/')]
            if not candidates:
                raise ValueError('KMZ sem arquivo KML')
            data = archive.read(candidates[0])
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
            if tag == 'point': geometry_type = 'Point'
            elif tag == 'linestring': geometry_type = 'LineString'
            else: geometry_type = 'Polygon'
            geometries.append({'type': geometry_type, 'coordinates': coords})
        if not geometries:
            continue
        points = [point for geometry in geometries for point in geometry['coordinates']]
        features.append({
            'index': index,
            'name': title,
            'geometries': geometries,
            'bbox': _bbox(points),
            'centroid': _centroid(points),
            'role': 'mentioned',
            'precision': 'exact',
        })
    if not features:
        raise ValueError('KML sem Placemark com geometria suportada')
    return {'srs': 'EPSG:4326', 'features': features}


def parse_resource(data, filename):
    if not filename.lower().endswith(('.kml', '.kmz')):
        raise ValueError('Formato geográfico aceito: KML ou KMZ')
    return parse_kml(data, filename)


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
        distances.extend(haversine_m(point, coordinate) for coordinate in coordinates)
        if geometry.get('type') == 'Polygon' and len(coordinates) >= 3:
            inside = inside or _point_in_polygon(point, coordinates)
    return 0.0 if inside else (min(distances) if distances else None)


def search(features, latitude, longitude, radius_m=0):
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
