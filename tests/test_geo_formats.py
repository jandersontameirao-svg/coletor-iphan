import io
import json
import struct
import unittest
import zipfile

import geo_domain
from support import Fixture


class GeoFormatTests(Fixture):
    def make_shapefile_zip(self):
        point = (-47.995, -14.995)
        shp = bytearray(100)
        struct.pack_into('>i', shp, 0, 9994)
        struct.pack_into('<i', shp, 28, 1000)
        struct.pack_into('<i', shp, 32, 1)
        struct.pack_into('<dddd', shp, 36, point[0], point[1], point[0], point[1])
        record = struct.pack('<idd', 1, point[0], point[1])
        shp.extend(struct.pack('>ii', 1, len(record) // 2))
        shp.extend(record)
        struct.pack_into('>i', shp, 24, len(shp) // 2)

        field = bytearray(32)
        field[:4] = b'NAME'
        field[11] = ord('C')
        field[16] = 12
        dbf = bytearray(32)
        dbf[0] = 3
        struct.pack_into('<I', dbf, 4, 1)
        struct.pack_into('<H', dbf, 8, 65)
        struct.pack_into('<H', dbf, 10, 13)
        dbf.extend(field)
        dbf.append(0x0D)
        dbf.extend(b' ' + b'Ponto teste '.ljust(12))
        dbf.append(0x1A)
        prj = b'GEOGCS["WGS 84",DATUM["WGS_1984"]]'
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('area.shp', bytes(shp))
            archive.writestr('area.dbf', bytes(dbf))
            archive.writestr('area.prj', prj)
        return output.getvalue()

    def test_geojson_and_json_are_normalized_to_wgs84(self):
        payload = json.dumps({'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'properties': {'name': 'Área JSON'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-48, -15], [-47.99, -15], [-47.99, -14.99], [-48, -14.99], [-48, -15]]] }},
            {'type': 'Feature', 'properties': {'nome': 'Ponto JSON'}, 'geometry': {'type': 'Point', 'coordinates': [-49, -16]}},
        ]}).encode()
        parsed = geo_domain.parse_resource(payload, 'areas.json')
        self.assertEqual(parsed['srs'], 'EPSG:4326')
        self.assertEqual(parsed['format'], 'geojson')
        self.assertEqual([item['name'] for item in parsed['features']], ['Área JSON', 'Ponto JSON'])
        self.assertEqual(len(geo_domain.search(parsed['features'], -14.995, -47.995, 0)), 1)

    def test_gpx_waypoint_and_track_are_imported(self):
        payload = b'''<?xml version="1.0"?><gpx version="1.1" creator="test"><wpt lat="-14.995" lon="-47.995"><name>Sitio GPX</name></wpt><trk><name>Trilha GPX</name><trkseg><trkpt lat="-15" lon="-48"/><trkpt lat="-14.99" lon="-47.99"/></trkseg></trk></gpx>'''
        parsed = geo_domain.parse_resource(payload, 'track.gpx')
        self.assertEqual(parsed['srs'], 'EPSG:4326')
        self.assertEqual(parsed['format'], 'gpx')
        self.assertEqual(len(parsed['features']), 2)
        self.assertEqual(parsed['features'][0]['name'], 'Sitio GPX')

    def test_shapefile_zip_imports_shape_dbf_and_prj(self):
        parsed = geo_domain.parse_resource(self.make_shapefile_zip(), 'area.zip')
        self.assertEqual(parsed['srs'], 'EPSG:4326')
        self.assertEqual(parsed['format'], 'shapefile')
        self.assertEqual(len(parsed['features']), 1)
        self.assertEqual(parsed['features'][0]['name'], 'Ponto teste')
        result = self.client.post('/v1/spatial-resources', headers=self.h, params={'process_id': self.pid, 'name': 'Área SHP', 'filename': 'area.zip'}, content=self.make_shapefile_zip())
        self.assertEqual(result.status_code, 201, result.text)
        self.assertEqual(result.json()['feature_count'], 1)

    def test_capabilities_declare_formats_and_pdf_document_import(self):
        data = self.client.get('/v1/capabilities', headers=self.h).json()
        self.assertEqual(data['spatial_formats'], ['kml', 'kmz', 'shp', 'shapefile_zip', 'geojson', 'json', 'gpx'])
        integration = self.client.get('/v1/integration/capabilities', headers=self.h).json()
        self.assertTrue(integration['spatial']['shapefile_zip'])
        self.assertTrue(integration['spatial']['geojson'])
        self.assertTrue(integration['spatial']['gpx'])
        self.assertTrue(integration['spatial']['pdf_document_import'])


if __name__ == '__main__':
    unittest.main()
