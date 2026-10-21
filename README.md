# Coletor IPHAN 0.7 — ponte do acervo

Aplicativo na versão 0.7, com quatro abas: **Coleta, Acompanhamento, Biblioteca e Configurações**. Recebe links fornecidos, preserva originais e os envia para o SharePoint. Aplicativos consumidores consultam o mesmo catálogo e suas referências por API. Não há pesquisa automática de processos, login externo do IPHAN nem contorno de CAPTCHA.

## Organização aprovada

Uma pasta por número de processo (a barra vira hífen), contendo Georreferenciados e Documentos. Os documentos são separados em PAPIPA, RAPIPA, PAIPA, RAIPA, PGPA, **RAIPI**, Educação patrimonial, Outros documentos e A classificar. Pastas são criadas sob demanda. A Biblioteca mostra a pasta prevista, a classificação atual, a origem, o histórico e a confirmação do SharePoint.

Sigla explícita gera sugestão conservadora. Classificações ambíguas não são inventadas. Revisores podem corrigir a categoria. Arquivos já enviados podem ser movidos pela Biblioteca usando Atualizar pasta no SharePoint, sem duplicar o item remoto. Componentes geográficos em um compactado permanecem juntos. Arquivos sem classificação segura ficam em A classificar.

## Instalação local

Python **3.12**, Linux x86_64 ou Windows x64. No diretório do código:

```sh
python -m venv .venv
# Linux: . .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install --require-hashes -r requirements.lock
python bootstrap.py
uvicorn app:app --host 127.0.0.1 --port 8000
```

Em outro terminal, mesmo ambiente e COLLECTOR_DATA:

```sh
python worker.py
```

Abra http://127.0.0.1:8000. As variáveis podem ser definidas pelo servidor ou carregadas por seu gerenciador de ambiente. A execução Python simples **não lê .env automaticamente**. Para Uvicorn sem carregar .env, exporte as variáveis no terminal/serviço; o Compose carrega .env. Bootstrap solicita senha sem exibi-la. Não existe senha padrão. `COLLECTOR_EMBEDDED_WORKER=1` permite execução em um único processo servidor, se o provedor não oferecer worker separado; manter um único worker em desenvolvimento simplifica a operação.

## Instalação Docker/Compose

1. Copiar .env.example para .env e preencher os identificadores Microsoft conforme docs/SHAREPOINT.md.
2. Criar localmente secrets/bootstrap_password.txt com uma senha forte (mínimo de 12 caracteres). Não enviar esse arquivo nem .env ao repositório.
3. Executar docker compose up --build -d. O serviço init cria o primeiro administrador. API e worker compartilham o volume collector_data.
4. Configurar HTTPS no proxy do servidor e persistir o volume. A porta publicada é somente 127.0.0.1:8000. Para hospedagem em plataforma gerenciada, usar o PORT/proxy oferecido pela plataforma e manter autenticação.

Dockerfile e Compose foram escritos, mas o build do container não foi executado aqui: Docker Engine estava indisponível e WSL não instalado. Wheels Linux foram resolvidos e conferidos; isso não substitui teste de container no servidor.

## SharePoint

O link da pasta do site ATENA informado por Janderson é o destino inicial. Ele não dá permissão de escrita sozinho. A instalação precisa de um registro de aplicativo Microsoft Entra de cliente público (tenant/client IDs) com Files.ReadWrite delegado e consentimento da organização. O usuário conecta pela página oficial Microsoft; o Coletor guarda tokens criptografados. **Não é necessário fornecer senha Microsoft nem segredo de cliente ao Coletor.**

Depois de conectar, testar leitura/gravação pela interface. O teste cria, confere e remove seu próprio TXT de teste. A fila só usa destino validado. Transferências só viram uploaded após releitura e conferência SHA-256. Se houver falha, o original local permanece preservado; não há exclusão automática do cache. A permissão Microsoft deve estar alinhada às equipes que acessarão os links do SharePoint. Acesso Condicional ou revogação podem exigir nova autenticação.

Detalhes: [docs/SHAREPOINT.md](docs/SHAREPOINT.md).

## Formatos e limites

Preservação de PDF, HTML nativo documental do SEI, TXT/CSV, DOCX/XLSX, Office legado, imagens, ZIP/RAR/7z, KML/KMZ, componentes SHP, GeoJSON/GPX e outros formatos técnicos enumerados em archive_policy.py. Validação de assinatura/formato não equivale a antivírus. Compactados não são executados nem descompactados no filesystem. ZIPs têm inventário limitado e proteção contra traversal. RAR/7z são preservados, sem interpretação interna nesta versão.

Até 50 URLs por tarefa (listas maiores divididas pela interface), 1.000 documentos por página e 25.000 por tarefa. Truncamento é pendência explícita, nunca coleta integral. Até 128 MiB por arquivo e 2 GiB de originais confirmados por tarefa. Limites ampliados em relação à 0.5 para permitir anexos maiores; o download ainda usa buffer em memória, portanto dimensionar o servidor considerando esses limites. A extração legada tem limite independente de 20 MiB; capacidade de preservar não presume capacidade de interpretar.

## API e consumidores

OpenAPI vivo em /openapi.json e interface /docs. Snapshot em docs/openapi.json. Sessões e contas de serviço/delegação usam Bearer e ACLs por processo. Solicitações de coleta usam Idempotency-Key. Principais rotas:

- POST /v1/collection-jobs; GET /v1/collection-jobs/{id}/links; cancel/resume e importação manual.
- GET /v1/bridge/library — filtros, paginação, origem e SharePoint.
- GET /v1/bridge/manifest/{process_id} — revisões, hashes, ocorrências e referências remotas.
- GET /v1/document-revisions/{id}/download — original autorizado do cache.
- GET /v1/bridge/transfers; POST /v1/bridge/transfers/{id}/retry.
- PATCH /v1/bridge/documents/{id}/category; POST .../{id}/move.

As APIs históricas de extração/geografia/conhecimento permanecem para compatibilidade e migração, com correções da auditoria. Não têm abas no aplicativo ponte. Extração/análise não são disparadas automaticamente pela coleta. Não há integração real homologada com ATENA/Geoportal, webhooks externos ou treinamento de modelos. O contrato de leitura e os IDs já podem ser utilizados pelos consumidores.

## Testes e recuperação

```sh
python scripts/run_tests.py
pip install -r requirements-browser.txt
python scripts/browser_bridge.py
```

O E2E usa Chrome/Edge/Chromium local (CHROMIUM_PATH opcional) ou um Chromium instalado pelo Playwright. Ele cria dados sintéticos temporários. Os dois testes históricos de browser referem-se à interface antiga; o novo E2E cobre a interface de quatro abas. Resultados reais desta entrega estão em docs/validation-0.7.txt e docs/browser-0.7.txt.

Para backup/restauração, parar API e workers e usar backup.py, conforme a documentação histórica. O backup verifica catálogo, FKs e blobs e inclui o estado das transferências. A chave token.key fica separada do backup: guardar em cofre ou reconectar a conta Microsoft após a restauração; o acervo não depende do token para ser recuperado. Não excluir o volume local sem backup: ele contém catálogo, rastreabilidade e arquivos pendentes de envio. SharePoint é o destino documental central; SQLite/cache continuam necessários para operar o Coletor. Não hospedar o SQLite em pasta sincronizada do SharePoint/OneDrive.

Não há migração automática de uma base produtiva executada nesta entrega. Testar restauração e a migração de uma cópia antes de usar acervo real. RPO/RTO e concorrência de produção precisam ser medidos no servidor.

## Estado de entrega

Código implementado e testado localmente; não é apenas um comando para desenvolvimento. A homologação restante depende de acesso e infraestrutura: consentimento Microsoft, MFA, pasta real, coleta real representativa, deploy Linux/Compose e consumidores ATENA/Geoportal. Nenhum desses acessos foi simulado como homologação. O ZIP original foi preservado. Documentos de versões anteriores estão em docs/legacy e são evidência histórica, não relatórios da versão 0.7.


## Novo na versão 0.7: participantes para inteligência de mercado

Extração automática em segundo plano, cruzamento de documentos administrativos/técnicos, papéis separados, evidências por documento/revisão/página, revisão humana e exportação JSON. Acesso pelo botão Empresas e responsáveis da Biblioteca, mantendo as quatro abas. Detalhes e limites em [docs/MARKET.md](docs/MARKET.md). O extrator é determinístico e conservador; não infere cliente final nem contrato a partir de coocorrência.
