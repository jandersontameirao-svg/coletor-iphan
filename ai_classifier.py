"""Adaptador opcional de IA (OpenAI) para SUGERIR categoria de documentos.

Nunca aplica automaticamente: devolve sugestão + justificativa para revisão
humana, como exige a especificação. Fica indisponível (capability.available=False)
quando OPENAI_API_KEY não está definida; a ausência nunca inventa classificação.
Segredos não são gravados em log nem retornados ao cliente.
"""
import json
import os

import httpx

import archive_policy as policy

CATEGORIES = ('Georreferenciados', *policy.STUDIES)
MAX_CHARS = 12000


class AIError(Exception):
    """Falha previsível ao consultar a IA (sem configuração, rede ou resposta inválida)."""


def _endpoint():
    base = (os.getenv('OPENAI_BASE_URL') or 'https://api.openai.com').rstrip('/')
    return base + '/v1/chat/completions'


def _model():
    return os.getenv('OPENAI_MODEL') or 'gpt-4o-mini'


def available():
    return bool(os.getenv('OPENAI_API_KEY'))


def capability():
    """Estado exposto à interface; nunca inclui a chave."""
    return {
        'available': available(),
        'provider': 'openai',
        'model': _model() if available() else None,
        'human_review': True,
        'categories': list(CATEGORIES),
    }


_SYSTEM = (
    'Você classifica documentos de processos de arqueologia do IPHAN. '
    'Escolha UMA categoria entre: ' + ', '.join(CATEGORIES) + '. '
    'As siglas (PAPIPA, RAPIPA, PAIPA, RAIPA, PGPA, RAIPI) são tipos de projeto/relatório; '
    '"Educacao patrimonial" para ações educativas; "Georreferenciados" para dados espaciais; '
    '"Outros documentos" para peças administrativas (ofício, despacho, parecer, portaria). '
    'Seja CONSERVADOR: se não houver evidência clara no texto, responda "A classificar". '
    'Nunca invente. Responda SOMENTE um objeto JSON com as chaves: '
    'category (uma das opções), confidence (número 0 a 1) e rationale '
    '(justificativa curta em português citando a evidência do texto).'
)


def suggest_category(text, name='', title=''):
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        raise AIError('OPENAI_API_KEY não configurada')
    snippet = (text or '')[:MAX_CHARS]
    if not snippet.strip():
        raise AIError('Documento sem texto para analisar')
    user = (
        f'Nome do arquivo: {name}\n'
        f'Título do processo: {title}\n\n'
        f'Trecho do documento (pode estar truncado):\n{snippet}'
    )
    payload = {
        'model': _model(),
        'temperature': 0,
        'max_tokens': 500,
        'response_format': {'type': 'json_object'},
        'messages': [
            {'role': 'system', 'content': _SYSTEM},
            {'role': 'user', 'content': user},
        ],
    }
    try:
        response = httpx.post(
            _endpoint(),
            headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
            json=payload,
            timeout=60,
        )
    except httpx.HTTPError as exc:
        raise AIError('Falha de rede ao contatar a IA') from exc
    if response.status_code != 200:
        # Não ecoa a chave; limita o corpo para não vazar detalhes sensíveis.
        raise AIError('A IA respondeu com erro ' + str(response.status_code))
    try:
        content = response.json()['choices'][0]['message']['content']
        parsed = json.loads(content)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AIError('Resposta da IA ilegível') from exc
    category = parsed.get('category')
    if category not in CATEGORIES:
        category = 'A classificar'
    confidence = parsed.get('confidence')
    try:
        confidence = round(float(confidence), 2)
    except (TypeError, ValueError):
        confidence = None
    rationale = str(parsed.get('rationale') or '')[:600]
    return {
        'category': category,
        'confidence': confidence,
        'rationale': rationale,
        'model': _model(),
        'provider': 'openai',
        'human_review': True,
    }
