"""Detecção explícita de OCR opcional; ausência do motor nunca vira texto inventado."""
import shutil
import subprocess
import tempfile
from pathlib import Path


def capability():
    available = bool(shutil.which('tesseract') and shutil.which('pdftoppm'))
    return {'available': available, 'engine': 'tesseract+pdftoppm' if available else None, 'homologated': False}


def extract_pdf(path, timeout=90):
    if not capability()['available']:
        raise RuntimeError('OCR indisponível: instale tesseract e pdftoppm')
    path = Path(path)
    with tempfile.TemporaryDirectory(prefix='iphan-ocr-') as temp:
        prefix = str(Path(temp) / 'page')
        subprocess.run(['pdftoppm', '-r', '180', '-png', str(path), prefix], check=True, timeout=timeout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        pages = []
        for image in sorted(Path(temp).glob('page-*.png')):
            result = subprocess.run(['tesseract', str(image), 'stdout', '-l', 'por+eng'], check=False, timeout=timeout, capture_output=True, text=True)
            pages.append((len(pages) + 1, result.stdout))
        return pages
