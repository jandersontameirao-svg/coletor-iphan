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
    # Padrão recente: gpt-4o está sendo aposentado; a OpenAI recomenda GPT-5.6/GPT-6.
    return os.getenv('OPENAI_MODEL') or 'gpt-5.6'


def _is_reasoning_model(model):
    """Famílias que exigem max_completion_tokens e restringem temperature."""
    m = (model or '').lower()
    return m.startswith(('gpt-5', 'gpt-6', 'o1', 'o3', 'o4', 'o5'))


def _strip_json(text):
    """Extrai o objeto JSON mesmo que a resposta venha com markdown ou texto em volta."""
    t = (text or '').strip()
    start, end = t.find('{'), t.rfind('}')
    return t[start:end + 1] if start != -1 and end > start else t


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


def _post(key, payload):
    try:
        return httpx.post(
            _endpoint(),
            headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
            json=payload,
            timeout=60,
        )
    except httpx.HTTPError as exc:
        raise AIError('Falha de rede ao contatar a IA') from exc


def _complete(key, model, messages):
    """Monta o payload conforme a família do modelo e reenvia mínimo se faltar suporte a algum parâmetro."""
    reasoning = _is_reasoning_model(model)
    payload = {'model': model, 'messages': messages, 'response_format': {'type': 'json_object'}}
    if reasoning:
        # Modelos reasoning (gpt-5/gpt-6/o-series): max_completion_tokens e temperature padrão.
        payload['max_completion_tokens'] = 4000
        effort = os.getenv('OPENAI_REASONING_EFFORT')
        if effort:
            payload['reasoning_effort'] = effort
    else:
        payload['max_tokens'] = 600
        payload['temperature'] = 0
    response = _post(key, payload)
    if response.status_code == 400:
        # Algum parâmetro opcional pode não ser aceito por este modelo: tenta o mínimo.
        token_field = 'max_completion_tokens' if reasoning else 'max_tokens'
        response = _post(key, {'model': model, 'messages': messages, token_field: 4000})
    if response.status_code != 200:
        # Não ecoa a chave nem o corpo bruto, para não vazar detalhes sensíveis.
        raise AIError('A IA respondeu com erro ' + str(response.status_code))
    try:
        return response.json()['choices'][0]['message']['content']
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AIError('Resposta da IA ilegível') from exc


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
    model = _model()
    messages = [
        {'role': 'system', 'content': _SYSTEM},
        {'role': 'user', 'content': user},
    ]
    content = _complete(key, model, messages)
    try:
        parsed = json.loads(_strip_json(content))
    except (ValueError, TypeError) as exc:
        raise AIError('Resposta da IA ilegível') from exc
    if not isinstance(parsed, dict):
        raise AIError('Resposta da IA ilegível')
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
