# Matriz de requisitos — versão 0.3

A especificação original continua vigente, com substituição da busca automática por entrada exclusiva de links. Esta matriz registra escopo demonstrado, não conclusão integral de F0–F6. Evidências de fixture não homologam IPHAN/ATENA reais.

| Requisito | Implementação | Teste | Evidência | Pendência/bloqueio |
|---|---|---|---|---|
| Preservar base/22 testes | Fundação FastAPI/SQLite mantida; testes sem edição | Suite original antes/depois | baseline-2026-10-15.txt; original-test-preservation.json | Pacote antigo ATENA/auditoria A01–A15 ausentes |
| Processo canônico por domínio | Registry central, número normalizado, creator separado de ACL | test_canonical_process_shared_without_folder_or_blob_copy; test_concurrent_registration_has_one_canonical | validation-v0.3.txt | Organizações/múltiplos domínios reais |
| Equipe sem cópia | ACL por usuário/grupo no mesmo processo | test_group_revocation_hides_documents_evidence_library_and_search | validation-v0.3.txt | Gestão avançada de equipes/paginação |
| Migração de duplicatas | Quarentena, plano, união revisada, aliases e histórico | CanonicalMigrationTests; MigrationTests | migration.md; validation-v0.3.txt | União operacional depende de revisão/backup explícitos |
| Pasta imediata sem projeto | Campo lógico criado na transação | test_folder_and_rename_idempotence | validation-v0.3.txt | Entidade folder/aliases de nome mais completa |
| Projeto somente nome/código | Cadastro original mantido | Contrato e UI | openapi.json; app.py | Vínculos opcionais temporais de projeto |
| Blobs/revisões/ocorrências | SHA-256, A-B-A e recaptura | test_revision_a_b_a_and_occurrences | validation-v0.3.txt | Retenção/exclusão/garbage collection |
| Integridade e download | Hash verificado, acesso do processo | test_integrity_failure; test_isolation_download_evidence | validation-v0.3.txt | Adapter S3 e anti-malware |
| Permissões read/operate/review/admin | ACL comum a API/catálogo/derivados | test_reader_operator_reviewer_and_resource_admin | validation-v0.3.txt | Hardening/escala/PostgreSQL |
| Criador independente de acesso | Desativação não elimina direitos da equipe | test_deactivating_creator_does_not_remove_team_access | validation-v0.3.txt | Políticas de sucessão/organização |
| Concessão/revogação/auditoria | Eventos, invalidação de tarefas e fencing | test_revocation_fences_worker_and_is_audited | validation-v0.3.txt | UI de auditoria/alertas |
| Serviços e delegação | Token hash, emissor humano, escopos e expiração | test_service_delegation_is_bound_to_identity_scopes_and_revocation; test_expired_delegation_rejects | validation-v0.3.txt | ATENA real; rotação avançada de credenciais |
| Não confiar em usuário no corpo | Identidade autenticada/interseção de escopos | test_service_cannot_impersonate_user_through_body | validation-v0.3.txt | Integração federada externa |
| Entrada link/lista, sem busca | url/urls, validação individual, operação legada compatível só com links | test_link_limit_number_search_and_invalid_items | validation-v0.3.txt | Busca automática deliberadamente fora do escopo |
| Registro ≠ coleta concluída | 202/queued/received, resultados por item | test_received_link_without_process_is_pending_without_network | validation-v0.3.txt | Homologação positiva com documento autorizado real |
| Lista mista/duplicatas | Estados independentes, resultado parcial, reutilização | test_mixed_list_validation_duplicate_barrier_and_manual_resume | validation-v0.3.txt | Origens reais variáveis |
| Idempotência/limites | Chaves separadas, até 50 URLs/256 KiB/100 jobs; quota sem contar duplicatas | test_list_idempotency_and_conflict; test_deduplicated_request_keys_still_reject_different_inputs; test_duplicate_references_do_not_consume_download_quota_again; test_manual_resolution_cannot_bypass_batch_quota | validation-v0.3.txt | Quotas de armazenamento por organização/gateway |
| SSRF antes de acesso | Allowlist HTTPS, DNS público, pinning/SNI, validação por redirect | SsrfTests | validation-v0.3.txt | Revisão independente/pen-test; configuração de egress de produção |
| Não salvar login como PDF | Rejeitar HTML/indicadores, formato/extensão verificados | test_login_and_html_are_not_saved_as_pdf | validation-v0.3.txt | Heurística não homologa todos os mecanismos SEI |
| Obter documentos/proveniência | Fetch direto, hash, filename/origem e captura original/final | test_actual_fetch_pipeline_fixture_not_mocked_fetch; test_same_basename_distinct_links_preserve_logical_identity | validation-v0.3.txt | Fixture de transporte; acesso externo positivo não comprovado |
| waiting_for_user completo | Corrigir/importar/associar/retomar preservando resultados | LinkTests; test_human_issuer_can_resume_own_delegated_pending_job_after_expiry | validation-v0.3.txt | Limite de 3 aquisições; novas origens exigem homologação |
| Manual não vira download | Conclusão manual com contagem própria | test_manual_resolution_finishes_without_fake_download_or_retry | validation-v0.3.txt | Outros formatos de importação |
| Fila durável/recovery | SQLite persistente, attempts, retry e lease | QueueTests | validation-v0.3.txt | PostgreSQL/CI/Compose |
| Heartbeat e cancelamento | Renovação autorizada, supervisor aborta filho | test_heartbeat_keeps_slow_valid_execution_and_stops_after_cancel; test_cancel_during_extraction_commits_no_evidence | validation-v0.3.txt | Isolamento de infraestrutura de produção |
| Fencing de extrações recuperadas | Run novo por lease, run velho não altera novo | test_recovered_worker_uses_new_run_and_old_worker_cannot_cancel_it | validation-v0.3.txt | Chaos/concorrência distribuída ampliados |
| Parser isolado e limites | Subprocesso POSIX, CPU/memória/tempo/tamanho | test_process_limits_timeout_memory_and_cancellation | validation-v0.3.txt | Sandbox de filesystem/rede e métricas de desempenho |
| PDF inválido/digitalizado | Sem páginas falha; sem texto sinaliza OCR | test_pdf_without_pages_fails_and_scanned_pdf_signals_ocr | validation-v0.3.txt | OCR operacional |
| Página verdadeira/fonte | PDF nativo por página, TXT sem página fictícia | test_native_pdf_has_real_page_and_txt_has_no_fictional_page_count | validation-v0.3.txt | Página impressa, tabelas, DOCX/XLSX/imagens |
| ExtractionRun/reuso/reprocessar | Ferramenta/versão/estado/evidência, reserva/dedup/histórico | test_default_reuse_and_explicit_reprocess_preserve_history; test_concurrent_async_requests_create_one_job_and_run | validation-v0.3.txt | Pipeline completo/versionamento de demais ferramentas |
| Biblioteca por tipos | Classificação autorizada por revisão, taxonomia seed, índice canônico | AccessTests/group/library/search | validation-v0.3.txt | Aprovação técnica, taxonomia extensível e classificação automática |
| Busca autorizada | Texto sobre evidências, sem coleta silenciosa | test_group_revocation_hides_documents_evidence_library_and_search | validation-v0.3.txt | Busca semântica e espacial |
| UI oito telas | Navegação superior, contexto, filtros, capacidades reais e indicadores planejados sem contador fictício | test_navigation_upload_worker_evidence_and_logout | browser-validation.txt; screenshots/overview.png | E2E de todos os papéis/casos ampliado; mapa futuro |
| Contrato comum/consumidores | OpenAPI e cliente Python, mesmos jobs/ACLs | test_reference_client_with_real_server_and_worker | validation-v0.3.txt; contracts.md | ATENA/Geoportal reais; envelopes/event delivery |
| Instalação/lock | 17 deps runtime/testes com hashes Linux/Py3.12 | Venv nova + suite | clean-install-validation.txt; requirements.lock | Imagem/Compose/CI; browser opcional separado |
| Backup/restauração | Offline, banco/objetos/hashes/vínculos | test_backup_restore | validation-v0.3.txt | Backup online, PostgreSQL/S3, RPO/RTO medidos |
| Homologação IPHAN | Tentativas reais independentes da suite | verify_external.py | external-verification-history-v0.3.json | HTML com indicadores de barreira e timeout DNS; nenhum documento obtido |
| OCR/geografia/KML/entorno | Mantidos no planejamento, capabilities=false | Não operacional | release-0.3.md | F3/F4, SRC/metros/precisão/Geoportal |
| Conhecimento/especialistas | Não operacional; métricas retornam null/planejado | UI distingue capacidade futura | overview/capabilities; release-0.3.md | F5 evidências/validação humana, agentes reais e consumidores |
| Homologação/segurança/produção | Testes locais e pacote auditável | Suite/Chromium/instalação | validation-v0.3.txt | F6 completa, brute-force, isolamento, observabilidade, deploy |

**Nenhuma integração externa está declarada homologada. F1 não está integralmente concluída conforme o aceite PostgreSQL da especificação original.**
