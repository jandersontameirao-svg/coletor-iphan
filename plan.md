# Plano de entrega — Coletor IPHAN 0.5

## Objetivo

Entregar e publicar a versão 0.5 do Coletor IPHAN como repositório técnico rastreável de processos, documentos, evidências, conhecimento e geografia. O produto não possui módulos financeiros, comerciais, de empresas, contratos, fluxo de caixa, DRE ou EBITDA. Esses temas não pertencem ao aplicativo nem a esta entrega.

## Escopo implementado

A fundação preserva processos canônicos, ACL por processo, grupos, contas de serviço, delegações e auditoria. Originais PDF/TXT são guardados por SHA-256 com revisões, ocorrências, proveniência, download protegido e extração assíncrona. Conhecimento só pode ser registrado mediante evidência autorizada e passa por revisão humana. Recursos espaciais KML/KMZ, Shapefile ZIP, GeoJSON/JSON e GPX são versionados em WGS84 e consultados por ponto e entorno em metros; PDF permanece no fluxo documental.

A versão 0.5 adiciona descoberta de documentos em páginas públicas do SEI/IPHAN fornecidas explicitamente pelo usuário. Ela reconhece apenas o endpoint público de processo, registra número/título do processo e os documentos exibidos na tabela, e acessa somente os links públicos de documentos que a própria página apresenta. Processos são criados ou reutilizados canonicamente para o solicitante humano; uma associação manual a processo divergente é recusada. Cada documento guarda a URL pública, o identificador exibido, título, datas, unidade e resultado individual.

Documentos sem link público ou sinalizados como restritos não recebem requisição: ficam pendentes para solução autorizada. Respostas de login, CAPTCHA, HTML, restrição, redirecionamento indevido, erro ou formato não permitido também permanecem pendentes. O aplicativo não pesquisa processos por número, não preenche formulários, não autentica em sistemas externos, não resolve CAPTCHA e não tenta contornar controles de acesso.

A entrada limpa cabeçalhos e textos não URL, remove duplicatas e divide listas com mais de 50 URLs em tarefas de até 50 itens. A descoberta limita 1.000 documentos por página e 25.000 por tarefa. O limite de 100 MiB de originais confirmados por tarefa, 20 MiB por arquivo, TLS validado, DNS público fixado, allowlist, SNI, redirects validados e cadência mínima permanecem ativos.

## Interface e identidade visual

A interface FastAPI servida pelo backend tem telas para Visão geral, Entrada de links, Tarefas, Processos, Documentos, Biblioteca, Integrações, Administração, Conhecimento e Pesquisa espacial. A camada de entrada diferencia links diretos de páginas públicas SEI, exibe a origem do processo e o status de cada documento descoberto. Mantém a identidade local do Grupo Arqueo, linguagem técnica e indicações transparentes de capacidade.

## Demonstração e publicação

O modo de construção abre sem senha e usa dados efêmeros. Ele permite somente a criação/retomada da fila de descoberta pública SEI e a coleta de documentos publicamente expostos. Criação de usuários, grupos, permissões, contas de serviço, uploads, importações, edição, exclusão, classificação, login externo e administração continuam bloqueados. O worker é habilitado apenas por variável explícita neste ambiente de construção.

O container usa Python 3.12, responde em `/_app/health`, respeita `PORT` e pode ser incorporado no Preview Manus. SQLite é efêmero no container; por isso a publicação é destinada à avaliação funcional e não deve receber acervo ou credenciais operacionais reais.

## Estrutura

- `app.py`: API FastAPI, autenticação, recursos de acervo, demonstração, saúde e assets.
- `catalog_routes.py`, `access_routes.py` e `advanced_routes.py`: catálogo, ACL, fila, conhecimento, geografia e contratos.
- `task_queue.py`, `worker.py`, `extraction.py` e `safe_fetch.py`: fila persistente, obtenção segura e extração isolada.
- `sei_public.py` e `sei_domain.py`: parser e migrações da descoberta pública de processos SEI.
- `index.html`, `ui.js`, `advanced_ui.js`, `public_sei_ui.js` e `styles.css`: interface preservada e extensão visual 0.5.
- `demo_mode.py`: dados sintéticos, sessão de construção e limites de acesso.
- `tests/`: regressão da base, extensão 0.4 e descoberta pública SEI 0.5.
- `Dockerfile`: execução do container de construção.
