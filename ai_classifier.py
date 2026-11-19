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
import atena_memory

CATEGORIES = ('Georreferenciados', *policy.STUDIES)
MAX_CHARS = 12000


class AIError(Exception):
    """Falha previsível ao consultar a IA (sem configuração, rede ou resposta inválida)."""


def _provider():
    """Dual: usa Anthropic (Claude) se ANTHROPIC_API_KEY estiver no ambiente; senão OpenAI."""
    if os.getenv('ANTHROPIC_API_KEY'):
        return 'anthropic'
    if os.getenv('OPENAI_API_KEY'):
        return 'openai'
    return None


def _active_key():
    return os.getenv('ANTHROPIC_API_KEY') or os.getenv('OPENAI_API_KEY')


def _endpoint():
    base = (os.getenv('OPENAI_BASE_URL') or 'https://api.openai.com').rstrip('/')
    return base + '/v1/chat/completions'


def _model():
    if _provider() == 'anthropic':
        # Família Claude 5 (mais capaz); ajuste por ANTHROPIC_MODEL se quiser outro.
        return os.getenv('ANTHROPIC_MODEL') or 'claude-sonnet-5-5'
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
    return _provider() is not None


def capability():
    """Estado exposto à interface; nunca inclui a chave."""
    return {
        'available': available(),
        'provider': _provider(),
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


def _complete(key=None, model=None, messages=None):
    """Roteia para o provedor ativo (Anthropic ou OpenAI). O `key` passado é ignorado:
    a chave e o modelo do provedor ativo são resolvidos internamente, para o dual funcionar
    sem mexer em quem chama."""
    provider = _provider()
    if not provider:
        raise AIError('Nenhuma chave de IA configurada (ANTHROPIC_API_KEY ou OPENAI_API_KEY)')
    active = _active_key()
    model = model if (model and ((provider == 'anthropic') == model.lower().startswith('claude'))) else _model()
    if provider == 'anthropic':
        return _complete_anthropic(active, model, messages or [])
    return _complete_openai(active, model, messages or [])


def _complete_anthropic(key, model, messages):
    """Messages API da Anthropic: o 'system' vai separado; a conversa só tem user/assistant."""
    system_parts = [m['content'] for m in messages if m.get('role') == 'system']
    convo = [{'role': m['role'], 'content': m['content']} for m in messages if m.get('role') in ('user', 'assistant')]
    while convo and convo[0]['role'] != 'user':
        convo.pop(0)
    if not convo:
        convo = [{'role': 'user', 'content': '(sem conteúdo)'}]
    payload = {'model': model, 'max_tokens': 8000, 'messages': convo}
    if system_parts:
        payload['system'] = '\n\n'.join(system_parts)
    base = (os.getenv('ANTHROPIC_BASE_URL') or 'https://api.anthropic.com').rstrip('/')
    try:
        response = httpx.post(base + '/v1/messages',
                              headers={'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'},
                              json=payload, timeout=60)
    except httpx.HTTPError as exc:
        raise AIError('Falha de rede ao contatar a IA') from exc
    if response.status_code != 200:
        raise AIError('A IA respondeu com erro ' + str(response.status_code))
    try:
        parts = response.json()['content']
        text = ''.join(block.get('text', '') for block in parts if block.get('type') == 'text')
        if not text:
            raise ValueError
        return text
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AIError('Resposta da IA ilegível') from exc


def _complete_openai(key, model, messages):
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


def auto_classify(text, name='', title=''):
    """Classificação automática da coleta: só devolve resultado APLICÁVEL (confiança alta).

    Devolve None — deixando o documento em 'A classificar' para revisão humana — quando:
    desligado por ambiente (COLLECTOR_AI_AUTOCLASSIFY=0), IA indisponível, sem texto,
    erro de IA, confiança abaixo do limiar (COLLECTOR_AI_MIN_CONFIDENCE, padrão 0.8) ou a
    própria IA respondeu 'A classificar'. Nunca levanta exceção: a coleta não pode quebrar
    por causa da classificação.
    """
    if os.getenv('COLLECTOR_AI_AUTOCLASSIFY', '1').strip().lower() in ('0', 'false', 'no', ''):
        return None
    if not available():
        return None
    if not (text or '').strip():
        return None
    try:
        threshold = float(os.getenv('COLLECTOR_AI_MIN_CONFIDENCE', '0.8'))
    except (TypeError, ValueError):
        threshold = 0.8
    try:
        result = suggest_category(text, name=name, title=title)
    except AIError:
        return None
    category = result.get('category')
    confidence = result.get('confidence')
    if category in (None, 'A classificar'):
        return None
    if confidence is None or confidence < threshold:
        return None
    return result


def suggest_category(text, name='', title=''):
    key = _active_key()
    if not key:
        raise AIError('Nenhuma chave de IA configurada (ANTHROPIC_API_KEY ou OPENAI_API_KEY)')
    snippet = (text or '')[:MAX_CHARS]
    if not snippet.strip():
        raise AIError('Documento sem texto para analisar')
    user = (
        f'Nome do arquivo: {name}\n'
        f'Título do processo: {title}\n\n'
        f'Trecho do documento (pode estar truncado):\n{snippet}'
    )
    model = _model()
    # Diretrizes aprendidas pela Atena valem para TODA geração de IA, inclusive esta.
    directives = atena_memory.directives_text()
    system = _SYSTEM + ('\n\n' + directives if directives else '')
    messages = [
        {'role': 'system', 'content': system},
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
        'provider': _provider(),
        'human_review': True,
    }
