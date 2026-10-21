"""Parser de documentos executado apenas em subprocesso com limites POSIX."""
import hashlib
import json
try: import resource
except ImportError: resource=None
import sys


def main():
    memory=int(sys.argv[4]);cpu=int(sys.argv[5])
    if resource is not None:
        resource.setrlimit(resource.RLIMIT_AS,(memory,memory))
        resource.setrlimit(resource.RLIMIT_CPU,(cpu,cpu))
        resource.setrlimit(resource.RLIMIT_FSIZE,(16*1024*1024,16*1024*1024))
        resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
    from pathlib import Path
    path=Path(sys.argv[1]);mime=sys.argv[2];expected=sys.argv[3]
    if path.stat().st_size>20*1024*1024: raise ValueError('too_large')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected: raise ValueError('integrity')
    if mime=='application/pdf':
        import io
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(raw))
        if not 0<len(reader.pages)<=5000: raise ValueError('invalid_page_count')
        pages=[];total=0
        for index,page in enumerate(reader.pages):
            text=page.extract_text() or '';total+=len(text)
            if total>2000000: raise ValueError('text_limit')
            pages.append([index+1,text])
        if any(not text.strip() for _,text in pages):
            try:
                import ocr_optional
                if ocr_optional.capability()['available']:
                    ocr_pages=dict(ocr_optional.extract_pdf(path, timeout=25))
                    pages=[[page, text if text.strip() else ocr_pages.get(page, '')] for page,text in pages]
            except Exception:
                # A PDF sem camada textual continua explicitamente needs_ocr.
                pass
    else:
        if mime=='text/plain':
            text=raw.decode('utf-8')
        else:
            from document_extractors import extract
            text=extract(raw,mime)
        if not text.strip(): raise ValueError('empty_text')
        if len(text)>2000000: raise ValueError('text_limit')
        pages=[[None,text]]
    print(json.dumps({'pages':pages},ensure_ascii=True))


if __name__=='__main__':
    try: main()
    except Exception:
        # Não propagar mensagens do parser ou conteúdo de documentos.
        print(json.dumps({'error':'document_not_extractable'}));raise SystemExit(2)
