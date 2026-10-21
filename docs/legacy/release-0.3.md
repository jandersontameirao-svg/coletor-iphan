# Relatório da entrega 0.3 — 15/10/2026

Continuação do repositório e pacote de auditoria 0.2 disponíveis no workspace. A especificação original foi preservada e a decisão de entrada exclusiva por links está documentada. Esta entrega conclui as correções locais descritas abaixo; não declara F0–F6 integralmente concluídas nem produção homologada.

## Corrigido e implementado

- **Repositório compartilhado:** número normalizado no domínio central, criação serializada de processo canônico, creator legado separado de ACL, grupos sobre o mesmo ID/pasta/original. Desativação do criador preserva direitos da equipe.
- **Migração:** aditiva e idempotente; duplicatas anteriores entram em quarentena sem ampliar acesso. Plano apresenta registros, contagens de documentos e permissões. União explícita preserva documentos/revisões/evidências/ocorrências, histórico de nome/processo e aliases; escopos/vínculos existentes são mantidos ou redirecionados. Não foi aplicado merge a acervo operacional.
- **Autorização:** read/operate/review/admin por recurso, usuários/grupos, contas de serviço e delegação server-side vinculada ao serviço/usuário/escopos/expiração. Permissões atuais aplicadas aos originais, históricos, derivados, catálogo e consultas. Concessões e revogações auditadas, tarefas sem autorização canceladas/fenced.
- **Links:** individual/lista, resultados por item, idempotência, limites, duplicatas e resultados mistos. Número não é entrada de coleta; não há busca automática. Interface/cliente usam a mesma API e fila.
- **Acesso externo:** implementação de download direto de PDF/texto público, allowlist HTTPS, DNS público com prazo, IP fixado/SNI/TLS, redirects revalidados, limites de resposta e HTML/barreiras tratados. Isso é uma capacidade implementada, não homologação IPHAN.
- **Proveniência:** origem e captura, URL original/final, arquivo por hash; links distintos com mesmo basename mantêm identidade lógica e extensão correta. Referências repetidas não consomem novamente a quota; importação manual também respeita a quota da tarefa.
- **Extração:** parser em subprocesso POSIX, limites de CPU/memória/tempo/tamanho/saída, abortável por perda de autorização/lease. PDF sem páginas e TXT vazio falham; digitalizado indica OCR pendente. PDF usa página real; TXT não inventa página.
- **Execuções:** ExtractionRun com ferramenta/versão/estado/resultado; reserva exclusiva, reutilização padrão e reprocessamento explícito com histórico. Novo lease recuperado cria run novo, impedindo o antigo de invalidá-lo. Job pendente com delegação expirada não bloqueia nova solicitação autorizada.
- **Pendências:** corrigir URL, associar processo, importar arquivo e retomar só o que falta. Resultado confirmado permanece. Conclusão manual distingue imported de downloaded; texto nativo parcial não simula OCR.
- **UI:** oito telas, navegação superior, processo contextual, busca central, biblioteca filtrável, gestão de usuários/grupos/serviços/delegações e revisão de duplicatas. Somente ações autorizadas; análise de estudos e conhecimento ainda indisponíveis usam null/“capacidade planejada”, sem contadores fictícios.
- **Biblioteca inicial:** taxonomia seed versionada e classificação pelo revisor autorizado, sempre vinculada à revisão. Índices não copiam originais. Busca textual observa a mesma ACL.
- **Entrega:** OpenAPI atualizado, incluindo Bearer/Idempotency-Key/delegação; contratos/eventos atuais, cliente de referência, lock transitivo com hashes, demonstração e matriz.

## Testado

| Verificação | Resultado e evidência |
|---|---|
| Baseline 0.2 | 22 testes aprovados antes das mudanças; baseline-2026-10-15.txt |
| Preservação | Quatro arquivos dos 22 testes byte a byte iguais ao pacote 0.2; original-test-preservation.json |
| Suite ampliada | 65 testes aprovados, sem skips, incluindo os 22 originais; validation-v0.3.txt |
| Instalação limpa | Venv nova, lock com 17 dependências/hashes; 65 testes descobertos, 64 aprovados e browser explicitamente ignorado por falta do extra Playwright; clean-install-validation.txt |
| E2E Chromium | Login, cadastro, upload, worker, evidência, oito telas e logout; screenshot sintética em screenshots/overview.png |
| Concorrência/recuperação | Registro canônico, upload simultâneo, dedup de extrações, aquisição exclusiva, worker encerrado abruptamente, heartbeat, fencing, rollback e retomada |
| ACLs/migração | Leitura/operar/revisar/admin; revogação em execução; grupo/serviço/delegação; deativação do criador; quarentena/merge/rollback/aliases e histórico |
| Lista mista | Download de fixture, duplicata, destino bloqueado, login, importação/correção/retomada sem repetir confirmados; quotas de duplicatas/manual |
| Parser | PDF nativo, digitalizado/sem texto, PDF sem páginas, TXT vazio, prazo/memória e histórico/reprocessamento |
| Recuperação | Backup/restauração offline em destino vazio com hashes e vínculos |
| Sintaxe/contrato | compileall, node --check e geração/asserts do OpenAPI 0.3 |

Ambiente completo: Python 3.12.14/Linux x86_64, Chromium 154.0.8037.57, Playwright 1.62.0. O browser é dependência de teste opcional; ausência é skip, nunca aprovação. Aviso de depreciação Starlette/httpx não é falha. Log job_execution_error vem de falha deliberadamente injetada para testar rollback. Os testes não constituem auditoria independente nem pen-test completo.

## Acesso externo real e bloqueios

Verificação real foi feita fora das fixtures no endereço institucional `https://sei.iphan.gov.br/pesquisapublica`. Uma tentativa recebeu HTML com indicadores de login/CAPTCHA, classificada conservadoramente como barreira; outra terminou em timeout DNS de cinco segundos. Não houve login, submissão de pesquisa, resolução de CAPTCHA ou obtenção de documento de processo. A heurística não prova que todo conteúdo do portal seja restrito. Evidências: external-verification-history-v0.3.json e iphan-verification.md.

**Homologação positiva IPHAN: pendente/bloqueada no caminho testado.** Falta demonstrar obtenção por um link autorizado real e conferível de documento/processo. Não existe descoberta/paginação automatizada de anexos SEI. **Integração ATENA OS real: pendente**, comprovado somente contrato com cliente local de referência. Geoportal/gerador não foram acessados ou construídos.

## Pendências mantidas no plano

| Fase | Próximo aceite |
|---|---|
| F0 | Inspeção do antigo pacote ATENA/auditoria A01–A15 ainda ausentes; Compose/CI e estabilização dessa base quando disponível |
| F1 | PostgreSQL e testes com banco real; modelo completo de folders/aliases de nomes, organizações/domínios, vínculos temporais de projetos, retenção e recuperação operacional |
| F2 | Links reais homologados, mecanismos oficiais verificados para documentos não diretos, integração ATENA e entrega de eventos; busca automática continua fora do escopo |
| F3 | Aprovação/extensão da taxonomia, OCR, demais formatos, tabelas/metadados/bibliografia e classificação como sugestão com revisão |
| F4 | Recursos espaciais versionados KML/KMZ, validação de SRC/geometria, entorno em metros, papéis de localização/precisão e contrato Geoportal |
| F5 | Afirmações/evidências/contradições, validação humana de conhecimento e execuções reais de especialistas; sem treinar modelo automaticamente |
| F6 | Hardening, pen-test/concorrência ampliados, isolamento filesystem/rede dos parsers, observabilidade/logs com correlation_id, limites/redação de logs no gateway, backup online/RPO/RTO e homologação integral |

SQLite/filesystem local foram preservados para continuidade/reprodutibilidade dos testes e escopo desta entrega. Não se afirma PostGIS/pgvector operacional. Parser isolado com rlimits não equivale a sandbox total; blobs podem ficar órfãos após rollback, sem GC automático; backup exige parada de todos os escritores; quotas globais por organização, proteção de força bruta/rotação avançada e transporte outbox não estão prontos. Deploy externo não foi realizado. A matriz em matrix.md separa cada requisito de sua implementação/teste/evidência/pendência.
