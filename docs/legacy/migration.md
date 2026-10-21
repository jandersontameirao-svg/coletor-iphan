# Migração conservadora da base 0.2

Startup aplica schema v2 e migração aditiva v3. O `SCHEMA` inicial mantém o formato legado para permitir bootstrap/upgrade, seguido da migração. Os arquivos dos 22 testes originais, incluindo seu teste de upgrade 0.1, estão preservados.

1. Adicionar metadados de identidade, ACLs, grupos/serviços/delegações, itens de link, captura/correções, execuções de extração e índices.
2. Normalizar número em chave alfanumérica maiúscula. Não alterar o número/título legados.
3. Para número único, registrar o processo no domínio central e conceder administração ao criador legado.
4. Para duplicatas, colocar **todos os registros** daquele número em domínios `legacy:<id>`, com seus acessos anteriores. Não unir permissões ou documentos no startup. Novos cadastros desse número são bloqueados até revisão, para não criar outro canônico.
5. Consultar `GET /v1/migrations/duplicates` como administrador da plataforma. Revisar IDs, responsáveis e conjunto de permissões. Parar API/workers e executar backup offline antes da união.
6. Aplicar `POST /v1/migrations/merge` com canônico, fontes e `acknowledge_permission_union: true`. A UI exige confirmação explícita da revisão/backup. Nenhuma união de acervo operacional foi executada nesta entrega; somente fixtures.

```json
{
  "canonical_id": "<id escolhido>",
  "source_ids": ["<duplicata revisada>"],
  "acknowledge_permission_union": true
}
```

A união é uma transação. Mantém os IDs de documento/revisão/evidência, blobs, ocorrências e processos de origem como aliases. Conflitos de nome de documento recebem sufixo de legado, sem concatenar cadeias de revisões nem eliminar histórico. `migration_documents` preserva processo/nome anteriores. Permissões são unidas somente nesta ação explícita. Escopos de delegação e vínculos de itens de links são atualizados; payloads antigos ainda resolvem os IDs de processo por alias. Mapeamentos de origem conflitantes permanecem preservados, sem apagar documentos.

Não existe reversão seletiva automática da união. Para desfazer a operação completa, restaure o backup em destino vazio. Startup não faz backup automático e o servidor não verifica se o backup declarado na UI realmente foi realizado. O merge existe para revisão administrativa autorizada, não para deduplicação silenciosa de equipes.

O domínio central é único nesta versão. Quarentenas legadas são uma proteção de migração, não implementação completa de múltiplas organizações. Vínculos de projeto temporais/geográficos não existiam na base 0.2 e não foram inventados nesta migração.

Evidências: `test_existing_v01_jobs_are_preserved`, `test_duplicates_are_quarantined_without_implicit_permission_union`, `test_explicit_merge_preserves_ids_revisions_origins_evidence_and_aliases` e `test_failed_merge_rolls_back_everything_and_migration_is_idempotent`.
