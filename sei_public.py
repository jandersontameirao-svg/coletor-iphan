"""Descoberta segura de documentos publicamente expostos em páginas de processo SEI/IPHAN."""
from __future__ import annotations

from html import unescape
import re
from urllib.parse import urljoin

import safe_fetch

PROCESS_HOST = "sei.iphan.gov.br"
PROCESS_PATH = "/sei/modulos/pesquisa/md_pesq_processo_exibir.php"
DOCUMENT_PATH = "/sei/modulos/pesquisa/md_pesq_documento_consulta_externa.php"
MAX_DOCUMENTS_PER_PROCESS = 1_000


def is_process_url(url: str) -> bool:
    """Retorna verdadeiro somente para o endpoint público de processo SEI/IPHAN."""
    try:
        parsed = safe_fetch.validate_url(url)
    except safe_fetch.FetchError:
        return False
    return parsed.hostname == PROCESS_HOST and parsed.path == PROCESS_PATH


def is_document_url(url: str) -> bool:
    """Retorna verdadeiro somente para o endpoint público de documento SEI/IPHAN."""
    try:
        parsed = safe_fetch.validate_url(url)
    except safe_fetch.FetchError:
        return False
    return parsed.hostname == PROCESS_HOST and parsed.path == DOCUMENT_PATH


def input_kind(url: str) -> str:
    return "sei_process_page" if is_process_url(url) else "direct_document"


def _clean_html(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]*>", " ", value)
    value = unescape(value).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def _field(page: str, label: str) -> str:
    pattern = rf"<td\b[^>]*>\s*{re.escape(label)}\s*</td>\s*<td\b[^>]*>(.*?)</td>"
    match = re.search(pattern, page, flags=re.I | re.S)
    return _clean_html(match.group(1)) if match else ""


def _document_table(page: str) -> str:
    match = re.search(r"<table\b[^>]*\bid\s*=\s*(['\"])tblDocumentos\1[^>]*>", page, flags=re.I)
    if not match:
        return ""
    end = re.search(r"</table\s*>", page[match.end():], flags=re.I)
    return page[match.end():match.end() + end.start()] if end else page[match.end():]


def _document_url(row: str, source_url: str) -> str | None:
    match = re.search(r"window\.open\(\s*['\"]([^'\"]+)", unescape(row), flags=re.I)
    if not match:
        return None
    candidate = urljoin(source_url, unescape(match.group(1)))
    return candidate if is_document_url(candidate) else None


def parse_process_page(page: bytes, source_url: str) -> dict:
    """Extrai metadados e links públicos de uma página já obtida pelo transporte seguro."""
    if not is_process_url(source_url):
        raise safe_fetch.FetchError("unsupported_process_page", "Informe uma página pública de processo do SEI/IPHAN")
    text = page.decode("iso-8859-1", "replace")
    if "tblDocumentos" not in text or "Pesquisa Processual" not in text:
        raise safe_fetch.FetchError("page_not_process", "A resposta não contém a página pública de processo esperada")

    number = _field(text, "Processo:")
    if not re.fullmatch(r"[0-9./-]{8,100}", number):
        raise safe_fetch.FetchError("process_number_missing", "A página não apresentou um número de processo utilizável")
    process_type = _field(text, "Tipo:")
    interested = _field(text, "Interessados:")
    title = process_type or "Processo público SEI/IPHAN"
    if interested:
        title = f"{title} · {interested}"
    title = title[:300]

    public_documents: list[dict] = []
    restricted_documents: list[dict] = []
    seen_urls: set[str] = set()
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr\s*>", _document_table(text), flags=re.I | re.S):
        cells = [_clean_html(cell) for cell in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]\s*>", row, flags=re.I | re.S)]
        document_index = next((i for i, value in enumerate(cells) if re.fullmatch(r"\d{4,}", value)), None)
        if document_index is None:
            continue
        document_number = cells[document_index]
        values = cells[document_index + 1:]
        document_title = values[0] if values else f"Documento {document_number}"
        dates = [value for value in values if re.fullmatch(r"\d{2}/\d{2}/\d{4}", value)]
        date = dates[0] if dates else ""
        included_at = dates[1] if len(dates) > 1 else ""
        unit = ""
        if included_at:
            after_included = values[values.index(included_at) + 1:]
            unit = next((value for value in after_included if value), "")
        elif len(values) > 1:
            unit = values[-1]
        record: dict[str, str | None] = {
            "document_number": document_number,
            "title": document_title[:300],
            "date": date,
            "included_at": included_at,
            "unit": unit[:300],
        }
        document_url = _document_url(row, source_url)
        if document_url and document_url not in seen_urls:
            record["url"] = document_url
            public_documents.append(record)
            seen_urls.add(document_url)
        elif not document_url:
            record["url"] = None
            restricted_documents.append(record)

    total = len(public_documents) + len(restricted_documents)
    truncated = total > MAX_DOCUMENTS_PER_PROCESS
    if truncated:
        remaining = MAX_DOCUMENTS_PER_PROCESS
        allowed_public = public_documents[:remaining]
        remaining -= len(allowed_public)
        public_documents = allowed_public
        restricted_documents = restricted_documents[:max(0, remaining)]

    return {
        "source_url": source_url,
        "number": number,
        "title": title,
        "process_type": process_type[:300],
        "interested": interested[:300],
        "page_restricted_notice": "acesso restrito" in text.lower(),
        "documents": public_documents + restricted_documents,
        "public_documents": len(public_documents),
        "restricted_documents": len(restricted_documents),
        "document_total": total,
        "truncated": truncated,
    }


def fetch_process_page(url: str, guard=lambda: None) -> dict:
    """Obtém uma página pública de processo com a mesma política de rede dos documentos."""
    if not is_process_url(url):
        raise safe_fetch.FetchError("unsupported_process_page", "Informe uma página pública de processo do SEI/IPHAN")
    current = url
    for hop in range(safe_fetch.MAX_REDIRECTS + 1):
        parsed = safe_fetch.validate_url(current)
        if parsed.hostname != PROCESS_HOST or parsed.path != PROCESS_PATH:
            raise safe_fetch.FetchError("redirect_not_allowed", "Redirecionamento fora da página pública de processo foi bloqueado")
        guard()
        ips = safe_fetch.resolve_public(parsed.hostname)
        status, headers, body = safe_fetch.request_once(current, ips[0], guard)
        if status in (301, 302, 303, 307, 308):
            if hop == safe_fetch.MAX_REDIRECTS or not headers.get("location"):
                raise safe_fetch.FetchError("redirect_limit", "Redirecionamento inválido ou excessivo")
            current = urljoin(current, headers["location"])
            continue
        if status in (401, 403):
            raise safe_fetch.FetchError("access_barrier", "A página exige autenticação; não será contornada")
        if status == 429:
            raise safe_fetch.FetchError("rate_limited", "O SEI limitou solicitações; aguarde e retome")
        if status == 404:
            raise safe_fetch.FetchError("not_found", "Página de processo não encontrada")
        if status != 200:
            raise safe_fetch.FetchError("origin_unavailable", "Página de processo indisponível; tente depois")
        content_type = headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type not in ("text/html", "application/xhtml+xml") and not body.lstrip().lower().startswith((b"<!doctype html", b"<html")):
            raise safe_fetch.FetchError("page_not_process", "A resposta não é uma página pública de processo")
        return parse_process_page(body, current)
    raise safe_fetch.FetchError("redirect_limit", "Limite de redirecionamentos")


def document_filename(metadata: dict, fetched: dict) -> str:
    """Gera nome lógico estável para documentos SEI sem confiar no nome do endpoint PHP."""
    title = str(metadata.get("title") or fetched.get("name") or "documento")
    number = str(metadata.get("document_number") or "")
    safe_title = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", " ", title)
    safe_title = re.sub(r"\s+", " ", safe_title).strip(" .")[:240] or "documento"
    prefix = f"{number} — " if number else ""
    extension = ".pdf" if fetched.get("mime") == "application/pdf" else ".txt"
    if safe_title.lower().endswith(extension):
        return (prefix + safe_title)[:300]
    return (prefix + safe_title)[:300 - len(extension)] + extension
