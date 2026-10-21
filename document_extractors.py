"""Extratores locais para formatos documentais sem executar macros ou fórmulas."""
from __future__ import annotations

import csv
import io
import zipfile
import xml.etree.ElementTree as ET

MAX_UNCOMPRESSED = 30 * 1024 * 1024
MAX_FILES = 300
MAX_CELLS = 50_000
MAX_TEXT = 2_000_000


def _local(tag):
    return tag.rsplit('}', 1)[-1] if isinstance(tag, str) else ''


def _zip(data):
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError('Arquivo Office inválido') from exc
    infos = [item for item in archive.infolist() if not item.is_dir()]
    if len(infos) > MAX_FILES or sum(item.file_size for item in infos) > MAX_UNCOMPRESSED:
        archive.close()
        raise ValueError('Arquivo Office excede o limite de expansão')
    return archive


def _clean(parts):
    text = '\n'.join(part.strip() for part in parts if part and part.strip())
    if not text:
        raise ValueError('Documento sem texto extraível')
    if len(text) > MAX_TEXT:
        raise ValueError('Texto extraído excede o limite')
    return text


def extract_csv(data):
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('CSV deve estar em UTF-8') from exc
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=',;\t|')
    except csv.Error:
        dialect = csv.excel
    rows = []
    cells = 0
    for row in csv.reader(io.StringIO(text), dialect):
        cells += len(row)
        if cells > MAX_CELLS:
            raise ValueError('CSV excede o limite de células')
        rows.append(' | '.join(value.strip() for value in row))
    return _clean(rows)


def extract_docx(data):
    with _zip(data) as archive:
        try:
            raw = archive.read('word/document.xml')
        except KeyError as exc:
            raise ValueError('DOCX sem documento principal') from exc
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError('XML DOCX inválido') from exc
    paragraphs = []
    for paragraph in root.iter():
        if _local(paragraph.tag) != 'p':
            continue
        words = [node.text or '' for node in paragraph.iter() if _local(node.tag) == 't']
        if words:
            paragraphs.append(''.join(words))
    return _clean(paragraphs)


def _shared_strings(archive):
    try:
        raw = archive.read('xl/sharedStrings.xml')
    except KeyError:
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError('XLSX shared strings inválidas') from exc
    result = []
    for item in root.iter():
        if _local(item.tag) != 'si':
            continue
        result.append(''.join(node.text or '' for node in item.iter() if _local(node.tag) == 't'))
    return result


def extract_xlsx(data):
    with _zip(data) as archive:
        shared = _shared_strings(archive)
        sheets = sorted(name for name in archive.namelist() if name.startswith('xl/worksheets/') and name.endswith('.xml'))
        if not sheets:
            raise ValueError('XLSX sem planilha')
        lines = []
        cells = 0
        for sheet in sheets:
            try:
                root = ET.fromstring(archive.read(sheet))
            except ET.ParseError as exc:
                raise ValueError('Planilha XLSX inválida') from exc
            lines.append('Planilha: ' + sheet.rsplit('/', 1)[-1].rsplit('.', 1)[0])
            for row in root.iter():
                if _local(row.tag) != 'row':
                    continue
                values = []
                for cell in row:
                    if _local(cell.tag) != 'c':
                        continue
                    cells += 1
                    if cells > MAX_CELLS:
                        raise ValueError('XLSX excede o limite de células')
                    kind = cell.attrib.get('t')
                    value = next((node.text or '' for node in cell.iter() if _local(node.tag) == 'v'), '')
                    if kind == 's':
                        try:
                            value = shared[int(value)]
                        except (ValueError, IndexError):
                            value = ''
                    elif kind == 'inlineStr':
                        value = ''.join(node.text or '' for node in cell.iter() if _local(node.tag) == 't')
                    values.append(value.strip())
                if values:
                    lines.append(' | '.join(values))
    return _clean(lines)


def extract(data, mime):
    if mime == 'text/html':
        return extract_html(data)
    if mime == 'text/plain':
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise ValueError('Texto deve estar em UTF-8') from exc
    if mime == 'text/csv':
        return extract_csv(data)
    if mime == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
        return extract_docx(data)
    if mime == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
        return extract_xlsx(data)
    raise ValueError('Formato documental não suportado')


def extract_html(data):
    from html.parser import HTMLParser
    class Reader(HTMLParser):
        def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.hidden=0
        def handle_starttag(self,tag,attrs):
            if tag in ('script','style','noscript'):self.hidden+=1
            if not self.hidden and tag in ('p','div','br','tr','li','h1','h2','h3'):self.parts.append('\n')
        def handle_endtag(self,tag):
            if tag in ('script','style','noscript') and self.hidden:self.hidden-=1
            if not self.hidden and tag in ('p','div','tr','li'):self.parts.append('\n')
        def handle_data(self,text):
            if not self.hidden:self.parts.append(text)
    parser=Reader()
    try:text=data.decode('utf-8-sig')
    except UnicodeDecodeError:text=data.decode('iso-8859-1')
    parser.feed(text)
    return _clean(''.join(parser.parts).splitlines())
