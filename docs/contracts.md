# Contratos ATENA/consumidores — 0.3

OpenAPI: `openapi.json` neste diretório e `/openapi.json` no servidor. `collect_process` permanece alias legado para entrada de links; não implica busca por número ou descoberta integral de processo. Operação atual explícita: `collect_links`. Interface e clientes usam POST /v1/collection-jobs; não há fila paralela.

```json
{
  "source": "iphan",
  "operation": "collect_links",
  "input": {
    "urls": ["<link direto autorizado>", "<outro link autorizado>"],
    "process_id": "<processo autorizado>"
  },
  "refresh_policy": "if_changed",
  "request_context": {"application": "atena-master"}
}
```

Cabeçalhos: Authorization: Bearer <token>; Idempotency-Key: <identificador do comando>; para atuação delegada, X-Delegation-Id: <registro emitido pelo humano para este serviço>. IDs de usuário no corpo não são identidade/delegação. Uma chave repetida com mesmos parâmetros retorna o mesmo job; parâmetros diferentes retornam 409. Reuso de execução de extração ainda registra a associação da chave do novo pedido. Resume não reescreve o corpo originalmente guardado para idempotência.

202 retorna job_id/status_url. GET status_url fornece status/detalhe/checkpoint; GET status_url/links fornece cada URL, validação, ação requerida, processo e revisão obtida. GET .../attempts mostra tentativas. Contagens diferenciam links recebidos, downloads efetivos, resultados já existentes, importações manuais, bloqueados, falhos, pendentes, extraídos e validados. Percentual não é inventado. Campo lease_token do status é ocultado; tokens internos não são credenciais de cliente.

Retomada: POST status_url/resume com `{ "process_id": "<se necessário>", "retry_pending": true }`. Corrigir item: PATCH status_url/links/{id} com url. Importar: POST status_url/links/{id}/import?name=arquivo.pdf, corpo binário. Cancelar: POST status_url/cancel. Não se altera URL de item já confirmado.

Extração:

```json
{
  "source": "repository",
  "operation": "extract_revision",
  "input": {"revision_id": "<id>", "reprocess": false}
}
```

Checkpoint contém run_id/IDs de evidência; GET /v1/evidence/{id} fornece revisão, página real quando aplicável, trecho e método. TXT usa page=null. GET /v1/document-revisions/{id}/extractions fornece histórico. Download usa autorização do processo e verificação de hash, nunca URL pública por hash. Nenhuma consulta inicia coleta.

GET /v1/library retorna classificação mais recente não rejeitada e referências ao documento/revisão canônicos. POST /v1/search faz busca textual autorizada. Fatos, autores, referências e resumos não são gerados nesta entrega. Os consumidores de Geoportal/relatórios devem reutilizar estes IDs; endpoints espaciais e de afirmações ainda não existem e não aparecem como operacionais em capabilities.

Eventos persistidos: OutboxEvent tem id UUID, kind, payload JSON `{ "resource_id": "..." }` e created epoch. São gravados na mesma transação de domínio. Não há transporte/subscrição operacional, sequência global contratual, assinatura ou proteção de replay implementada. O esquema de envelope versionado e a entrega externa permanecem pendentes, não homologados.

Cliente de referência: reference_client.py cria tarefa, faz polling e consulta evidências/itens. Link parcial/pendente/falho retorna código de saída 2; timeout mantém o job consultável. Isso valida contrato local, não integração com ATENA Mestre real. Credenciais são lidas de ambiente/cofre, não argumentos impressos.
