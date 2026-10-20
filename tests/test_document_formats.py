import io
import zipfile
from support import Fixture

DOCX_XML = b'''<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Relatorio arqueologico</w:t></w:r></w:p><w:p><w:r><w:t>Conclusao verificavel</w:t></w:r></w:p></w:body></w:document>'''
SHARED = b'''<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>Categoria</t></si><si><t>Valor</t></si><si><t>Campo</t></si></sst>'''
SHEET = b'''<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row><row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>42</v></c></row></sheetData></worksheet>'''


def office_file(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return stream.getvalue()


class DocumentFormatTests(Fixture):
    def extract(self, data, name):
        uploaded = self.upload(data, self.h, name)
        response = self.client.post('/v1/document-revisions/%s/extract' % uploaded['revision_id'], headers=self.h)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertTrue(result['extractable'])
        return self.client.get('/v1/evidence/%s' % result['evidence'][0]['id'], headers=self.h).json()['text']

    def test_csv_is_stored_and_extracted_as_tabular_text(self):
        text = self.extract(b'Tipo;Quantidade\nSitio;2\n', 'dados.csv')
        self.assertIn('Tipo | Quantidade', text)
        self.assertIn('Sitio | 2', text)

    def test_docx_is_stored_and_extracted_without_running_content(self):
        data = office_file({'word/document.xml': DOCX_XML})
        text = self.extract(data, 'relatorio.docx')
        self.assertIn('Relatorio arqueologico', text)
        self.assertIn('Conclusao verificavel', text)

    def test_xlsx_is_stored_and_extracted_without_running_formulas(self):
        data = office_file({'xl/workbook.xml': b'<workbook/>', 'xl/sharedStrings.xml': SHARED, 'xl/worksheets/sheet1.xml': SHEET})
        text = self.extract(data, 'tabela.xlsx')
        self.assertIn('Categoria | Valor', text)
        self.assertIn('Campo | 42', text)


if __name__ == '__main__':
    import unittest
    unittest.main()
