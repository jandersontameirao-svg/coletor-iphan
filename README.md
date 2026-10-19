# Coletor IPHAN — versão 0.4.0

Continuação da base 0.2, preservando seus quatro arquivos com 22 testes byte a byte. Nesta entrega: processo canônico compartilhado, ACLs por recurso, grupos, contas de serviço/delegação, entrada por link/lista, download direto protegido, resolução manual, extração isolada/versionada, conhecimento rastreável e geografia KML/KMZ. **Registro de tarefa não comprova obtenção de documento. Coleta de processo/anexos IPHAN e integração ATENA real não estão homologadas.**

A especificação original está em `docs/specification/original.txt`; a decisão atual de entrada exclusivamente por links está em `docs/specification/scope-2026-10-15.txt`. Não há busca automática de processos por número ou consulta ao portal. Número continua necessário para cadastrar a identidade de um processo no catálogo.

## Instalação local

Linux x86_64, Python 3.12. O parser utiliza limites POSIX e não oferece suporte nativo a Windows. Na pasta deste projeto:

```sh
python -m venv .venv
. .venv/bin/activate
pip install --require-hashes -r requirements.lock
python app.py
uvicorn app:app --host 127.0.0.1 --port 8000
```

Bootstrap solicita administrador/senha sem ecoar a senha; mínimo 12 caracteres e sem senha padrão. Em outro terminal, ative a mesma venv, use a mesma pasta e `COLLECTOR_DATA`, e execute:

```sh
python worker.py
```

Abra http://127.0.0.1:8000. As telas são visão geral, entrada de links, tarefas, processos, documentos/revisões, biblioteca, integrações e administração. Seleção de processo e filtro da biblioteca persistem durante a sessão. API/OpenAPI em `/openapi.json`, documentação interativa em `/docs`. O snapshot do contrato acompanha a entrega em `docs/openapi.json`. Quando `COLLECTOR_DEMO_MODE=1`, a interface abre automaticamente a sessão sintética sem senha e permanece somente de leitura; fora desse modo, o login continua obrigatório.

O lock inclui dependências transitivas de runtime e testes HTTP, com hashes de wheels para este ambiente. Instalação em venv nova foi realizada com os wheels previamente baixados, sem acesso ao índice durante a instalação. O ambiente de construção usou Python 3.12.14, Chromium 154.0.8037.57 e Playwright 1.62.0. Wheels não acompanham o ZIP; instalação a partir do índice depende de conectividade. Não confundir isso com uma imagem Docker ou homologação de implantação.

## Repositório e autorização

O banco continua SQLite, com migrações aditivas v2/v3. Registro canônico por número normalizado no domínio `central`; duplicatas legadas são isoladas até revisão. A coluna legada `owner` registra o criador e **não controla acesso**. A fonte autoritativa é `resource_grants`. Permissões:

| Permissão do processo | Operações |
|---|---|
| read | Catálogo, originais, evidências, histórico, biblioteca e consultas |
| operate | Leitura, upload, tarefas, extração, resolução manual/cancelamento/retomada |
| review | Leitura e classificações técnicas vinculadas à revisão |
| admin | Todas as anteriores, renomeação e concessão/revogação de acesso |

Administrador da plataforma gerencia usuários, grupos, serviços e migração. Esse papel não libera a leitura de todos os acervos. Equipes recebem acesso ao mesmo processo por grupo; não criam novas pastas nem cópias. Desativar o criador não remove o acesso dos demais membros. Concessões, revogações, delegações, uniões e operações ficam na auditoria/outbox.

Sessões de usuário: token aleatório em memória da página, hash no banco, expiração em oito horas e revogação no logout. Senhas: PBKDF2-SHA256 com salt e 310 mil iterações. Contas de serviço: token exibido uma vez pela API, armazenado por hash e válido por 30 dias; revogação desativa o serviço e invalida suas delegações/tarefas. Use cofre para a credencial. Delegação: registro emitido pelo próprio usuário humano, duração máxima de oito horas, serviço exato e escopos por processo. `X-Delegation-Id` exige token do serviço correspondente e interseção das permissões atuais do usuário e do serviço. `request_context.user_id` não concede identidade.

Bytes canônicos em `data/blobs/<sha256>`; pastas são lógicas no catálogo. A-B-A preserva três revisões e dois blobs. Recaptura idêntica gera ocorrência sem nova revisão. Links distintos com mesmo basename mantêm documentos lógicos distintos; o mapeamento por URL estabiliza recapturas. O filename de resposta, quando disponível, é preservado na ocorrência; nome de navegação recebe extensão compatível. Evidências, índices e classificações não alteram originais.

## Links: receber → obter → disponibilizar

`POST /v1/collection-jobs` aceita `input.url` ou `input.urls`, de 1 a 50 itens, e `process_id` opcional. Cada item tem validação e estado próprios. Comando limitado a 256 KiB e até 100 tarefas pendentes por solicitante. Resposta 202 com `job_id`/`status_url` significa **recebimento**. Consulte `/links` para resultados individuais.

Sem processo associado, o worker pede cadastro/seleção pela retomada antes de acessar a origem. Com processo autorizado, somente os links explícitos são acessados. Caminho implementado: download direto de PDF ou texto UTF-8 público; não há descoberta automática de anexos, navegação de páginas SEI, busca por número, paginação de processos ou automação de login.

SSRF: HTTPS/443, allowlist exata configurável, sem credenciais/fragmentos, resolução DNS com prazo de cinco segundos, rejeição de endereços não globais/transição IPv6, IP fixado na conexão e SNI/certificado do hostname original. Cada redirect é validado/resolvido novamente; máximo cinco. Proxy HTTPS herdado é mantido, com CONNECT ao IP validado; recusa pelo proxy vira pendência, sem fallback que contorne a política. TLS permanece verificado. Limites: 20 MiB por documento, 100 MiB de originais confirmados por tarefa, timeout de conexão/leitura, cadência mínima de 0,2 segundo entre itens. Não há varredura do portal.

HTML não é salvo como PDF. Login/CAPTCHA, 401/403, 404, 429, falhas de DNS/rede e respostas não documentais geram ação necessária/importação manual. A detecção de login/CAPTCHA é heurística por indicadores; não comprova que todo conteúdo da origem exija autenticação. Lista com documentos confirmados e problemas termina em `partial`; somente barreiras em `waiting_for_user`; lista totalmente inválida termina em `failed` e exige novo comando corrigido.

Corrija item pendente por `PATCH .../links/{item_id}`. Importe documento autorizado por `POST .../links/{item_id}/import?name=arquivo.pdf`, corpo binário. Quando todos os itens estão resolvidos manualmente, a tarefa pode concluir com `downloaded=0` e `manually_imported>0`. Retomada preserva itens confirmados e só repete pendências solicitadas. Há limite de três aquisições por tarefa; no esgotamento, importação manual continua disponível, mas nova tentativa de acesso exige novo comando. O emissor humano pode retomar sua própria tarefa delegada usando autorização humana atual, com evento específico, após expiração da delegação.

## Extração, biblioteca e evidências

Worker executa parser em subprocesso com ambiente sem credenciais herdadas: 512 MiB de memória, 30 segundos de CPU, 35 segundos de prazo real, saída limitada a 16 MiB, entrada a 20 MiB, 5 mil páginas e 2 milhões de caracteres. O supervisor termina o filho após cancelamento/perda de autorização/lease. Isso não é sandbox de filesystem/rede nem scanner antimalware.

Cada execução tem `ExtractionRun`: revisão, ferramenta, versão, estado, início/fim, falha e IDs das evidências. Extração padrão reutiliza execução concluída da mesma versão; pedidos assíncronos concorrentes compartilham a tarefa. Reprocessamento explícito cria novo histórico. PDF sem páginas, TXT vazio e parsing inválido falham; páginas sem texto sinalizam `needs_ocr` sem evidências vazias/fictícias. TXT não recebe página ou contagem de páginas fictícia. OCR permanece indisponível.

Biblioteca é índice sobre documentos, com tipos PAPIPA, RAPIPA, PAIPA, RAIPA, PGPA, RAIPI e educação patrimonial. Taxonomia seed versionada, ainda sem aprovação do responsável técnico. Classificação pelo revisor autorizado exige revisão existente e permissão review. Alterações preservam predecessor; não há classificador automático. Busca textual recupera somente evidências autorizadas; não há busca semântica nem afirmação factual automática. A busca espacial por KML/KMZ WGS84 e entorno em metros é uma capacidade específica da extensão 0.4.

Lease de 120 segundos renovado periodicamente por heartbeat; exclusividade/fencing da tarefa e da execução de extração. Recuperação cria uma nova execução vinculada ao novo lease: o worker antigo não altera o run do substituto. Resultados/checkpoint/outbox são transacionais. Uma unidade de extração interrompida reinicia essa unidade; coleta retoma a lista pelos itens já confirmados. Ver `docs/queue.md`.

## Testes, demonstração e recuperação

```sh
python scripts/run_tests.py
```

O runner usa base temporária. Os 22 testes originais foram preservados e passaram antes/depois das alterações; hashes em `docs/original-test-preservation.json`. Suite expandida: 65 testes. Com ambiente browser completo, todos passaram; na venv nova sem Playwright, 64 passaram e o E2E foi explicitamente ignorado. Para o E2E:

```sh
pip install -r requirements-browser.txt
# Instale Chromium do sistema em ambiente de teste; o teste usa /usr/bin/chromium.
python scripts/run_tests.py
```

Se Playwright/Chromium faltarem, o E2E registra skip, não aprovação. Reports em `docs/validation-v0.3.txt`, `docs/clean-install-validation.txt` e `docs/browser-validation.txt`; screenshot sintética em `docs/screenshots/overview.png`. O aviso Starlette/httpx é de depreciação. `job_execution_error` é esperado no teste que injeta rollback.

Roteiro completo em `docs/demo.md`. Para backup/restauração, pare API e todos os workers e aguarde término dos processos:

```sh
python backup.py backup data /tmp/iphan-backup
python backup.py restore /tmp/iphan-backup /tmp/iphan-restored
COLLECTOR_DATA=/tmp/iphan-restored uvicorn app:app --host 127.0.0.1 --port 8000
```

Destino deve ser inexistente. Script verifica banco, vínculos e hashes, gera manifesto derivado e não coordena escritores ativos. RPO/RTO não medidos. O ZIP de código não inclui acervo operacional, banco, usuários, tokens ou senhas.

## Integração e estado de entrega

Contrato e exemplos em `docs/contracts.md`. O cliente lê credenciais de `COLLECTOR_TOKEN` e, quando aplicável, `COLLECTOR_DELEGATION_ID`, sem argumentos de segredo:

```sh
python reference_client.py --revision-id ID_DA_REVISAO
python reference_client.py --links-file links.txt --process-id ID_DO_PROCESSO
```

Verificação externa é separada: `python scripts/verify_external.py --url LINK_AUTORIZADO`. Em 15/10, a pesquisa pública do SEI devolveu HTML com indicadores de barreira em uma tentativa e timeout DNS em outra. Nenhum documento de processo foi obtido nessa homologação; ATENA OS real não foi acessada. Detalhes em `docs/iphan-verification.md`.

F1 avançou, mas o aceite integral da especificação original ainda depende de PostgreSQL/PostGIS em servidor real e demais requisitos. OCR efetivo, outros formatos, especialistas, organizações/múltiplos domínios, vínculos temporais de projeto, transporte/consumidores da outbox, CI/Compose, retenção, hardening e homologação externa seguem pendentes. A base auditada antiga ATENA e seus achados A01–A15 continuam indisponíveis; o pacote 0.2 utilizado aqui é a base independente já criada. A publicação demonstrativa não equivale a implantação operacional. Ver relatório de corrigido/testado/pendente/bloqueado em `docs/release-0.4.md` e matriz em `docs/matrix.md`.

## Extensão 0.4 no escopo real do Coletor

A cópia 0.4 mantém a base 0.3 e adiciona capacidades previstas na especificação original, sem criar módulos financeiros ou comerciais:

- **Conhecimento rastreável:** afirmações sempre vinculadas a uma evidência autorizada, com tipos explícitos, validação humana, rejeição, conflito e relações entre afirmações. O sistema não gera fatos automaticamente.
- **Geografia:** importação de KML/KMZ, validação de coordenadas WGS84, revisões versionadas e consulta por ponto/entorno com distância geodésica em metros. Recursos espaciais são índices; não duplicam o original documental.
- **Contratos:** `/v1/integration/capabilities` registra o que consumidores podem usar e mantém `atena_real_homologated=false` e `geoportal_real_homologated=false` enquanto não houver homologação externa autorizada.
- **OCR:** a API informa explicitamente se `tesseract` e `pdftoppm` existem no host. PDF digitalizado sem texto continua como `needs_ocr`; nenhuma evidência vazia ou inventada é criada.

Rotas novas:

```text
GET  /v1/knowledge/assertions
POST /v1/knowledge/assertions
PATCH /v1/knowledge/assertions/{id}
POST /v1/knowledge/assertions/{id}/relations
GET  /v1/spatial-resources
POST /v1/spatial-resources?process_id=...&name=...&filename=...
POST /v1/spatial-resources/{id}/revisions?filename=...
GET  /v1/spatial-resources/{id}
POST /v1/spatial-search
GET  /v1/overview/advanced
GET  /v1/integration/capabilities
```

A ausência de PostgreSQL, Geoportal, ATENA real, OCR ou acesso positivo IPHAN no ambiente não é mascarada: cada capacidade aparece como disponível, condicional, pendente ou não homologada conforme o caso.
