"""Preservação de originais; classificação conservadora sem executar conteúdo."""
import io
import re
import unicodedata
import zipfile
from pathlib import Path

STUDIES = ('PAPIPA','RAPIPA','PAIPA','RAIPA','PGPA','RAIPI','Educacao patrimonial','Outros documentos','A classificar')
GEO_EXTENSIONS = {'.kml','.kmz','.shp','.shx','.dbf','.prj','.cpg','.geojson','.gpx','.gpkg','.qgz','.qgs','.tif','.tiff'}
MAX_BYTES = 128 * 1024 * 1024
MIMES = {'.pdf':'application/pdf','.txt':'text/plain','.csv':'text/csv','.html':'text/html','.htm':'text/html','.zip':'application/zip','.7z':'application/x-7z-compressed','.rar':'application/vnd.rar','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.tif':'image/tiff','.tiff':'image/tiff','.kml':'application/vnd.google-earth.kml+xml','.kmz':'application/vnd.google-earth.kmz','.gpx':'application/gpx+xml','.geojson':'application/geo+json','.json':'application/json','.xml':'application/xml','.shp':'application/octet-stream','.shx':'application/octet-stream','.dbf':'application/octet-stream','.prj':'text/plain','.cpg':'text/plain','.gpkg':'application/geopackage+sqlite3','.mdb':'application/x-msaccess','.accdb':'application/msaccess','.doc':'application/msword','.xls':'application/vnd.ms-excel','.qgz':'application/zip','.qgs':'application/xml'}

def safe_name(value, limit=180):
    value=re.sub(r'[\\/:*?"<>|\x00-\x1f#%]', '_', str(value))
    value=re.sub(r'\s+', ' ', value).strip(' .')
    return (value or 'sem_nome')[:limit]

def process_folder(number):
    return safe_name(str(number).replace('/','-'))

def inspect_zip(data):
    """Inventário limitado; nunca extrai, abre macros ou executa membros."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos=z.infolist()
        if len(infos)>2000 or sum(x.file_size for x in infos)>512*1024*1024:
            raise ValueError('Compactado excede os limites de inventário/expansão')
        for x in infos:
            name=x.filename.replace('\\','/')
            if name.startswith('/') or re.match(r'^[A-Za-z]:',name) or '..' in name.split('/'):
                raise ValueError('Compactado contém caminho inválido')
        return [{'name':x.filename,'size':x.file_size,'directory':x.is_dir()} for x in infos]

def detect(data, name, allow_html=False):
    if not data or len(data)>MAX_BYTES: raise ValueError('Arquivo vazio ou acima de 128 MiB')
    suffix=Path(name).suffix.lower()
    if data.startswith(b'%PDF-'): return 'application/pdf'
    if data.startswith(b'PK\x03\x04') or data.startswith(b'PK\x05\x06'):
        try: members=inspect_zip(data)
        except zipfile.BadZipFile as exc: raise ValueError('Compactado inválido') from exc
        names={r['name'] for r in members}
        if suffix=='.docx' and 'word/document.xml' not in names: raise ValueError('DOCX inválido')
        if suffix=='.xlsx' and 'xl/workbook.xml' not in names: raise ValueError('XLSX inválido')
        return MIMES.get(suffix,'application/zip') if suffix in ('.docx','.xlsx','.kmz','.qgz') else 'application/zip'
    signatures=[(b'7z\xbc\xaf\x27\x1c','application/x-7z-compressed'),(b'Rar!\x1a\x07','application/vnd.rar'),(b'\x89PNG\r\n\x1a\n','image/png'),(b'\xff\xd8\xff','image/jpeg'),(b'II*\x00','image/tiff'),(b'MM\x00*','image/tiff')]
    for sig,mime in signatures:
        if data.startswith(sig): return mime
    if suffix in ('.shp','.shx') and data[:4]==b'\x00\x00\x27\x0a': return MIMES[suffix]
    if suffix in ('.mdb','.accdb') and b'Standard' in data[:64]: return MIMES[suffix]
    if suffix in ('.doc','.xls') and data.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'): return MIMES[suffix]
    if suffix=='.gpkg' and data.startswith(b'SQLite format 3\x00'): return MIMES[suffix]
    if suffix=='.dbf' and len(data)>32 and data[0] in (2,3,4,5,0x30,0x31,0x32,0x43,0x63,0x83,0x8b,0xcb,0xf5): return MIMES[suffix]
    try: text=data.decode('utf-8-sig')
    except UnicodeDecodeError:
        if suffix in ('.html','.htm') and allow_html: text=data.decode('iso-8859-1')
        else: raise ValueError('Formato não reconhecido ou texto fora de UTF-8')
    html=bool(re.search(r'<(?:!doctype\s+html|html|head|body)\b',text[:10000],re.I))
    if html:
        if not allow_html: raise ValueError('Página HTML não é documento autorizado')
        if re.search(r'captcha|type\s*=\s*[\x27\"]password',text,re.I): raise ValueError('Página de autenticação/CAPTCHA')
        return 'text/html'
    if '\x00' in text: raise ValueError('Texto contém bytes binários')
    if suffix and suffix not in MIMES: raise ValueError('Extensão não suportada para preservação')
    return MIMES.get(suffix,'text/plain')

def category(name, title='', data=None):
    """Somente siglas explícitas; nunca infere conteúdo arqueológico de nomes vagos."""
    ext=Path(name).suffix.lower()
    if ext in GEO_EXTENSIONS: return 'Georreferenciados', 'extension'
    if ext=='.zip' and data:
        try:
            entries=[r['name'] for r in inspect_zip(data) if not r['directory']]
            if entries and any(Path(x).suffix.lower()=='.shp' for x in entries):
                return 'Georreferenciados','shapefile_bundle'
        except (ValueError,zipfile.BadZipFile): pass
    normalized=unicodedata.normalize('NFKD',str(title)+' '+str(name)).encode('ascii','ignore').decode().upper().replace('_',' ')
    found=set(re.findall(r'\b(?:PAPIPA|RAPIPA|PAIPA|RAIPA|PGPA|RAIPI)\b',normalized))
    if len(found)==1: return found.pop(),'explicit_acronym'
    if len(found)>1: return 'A classificar','ambiguous_acronyms'
    if 'EDUCACAO PATRIMONIAL' in normalized: return 'Educacao patrimonial','explicit_title'
    if re.search(r'\b(OFICIO|DESPACHO|PARECER|PORTARIA|LICENCA|ATA)\b',normalized): return 'Outros documentos','administrative_title'
    return 'A classificar','no_explicit_type'

def relative_folder(number, kind):
    return process_folder(number)+'/'+('Georreferenciados' if kind=='Georreferenciados' else 'Documentos/'+kind)
