# Relatório da entrega 0.5 — descoberta pública SEI/IPHAN

A versão 0.5 preserva a fundação 0.3 e as extensões 0.4: API FastAPI, autenticação, ACL, grupos, delegação, fila persistente, armazenamento por hash, extração documental, conhecimento rastreável, análise de processos e pesquisa espacial. Esta entrega acrescenta leitura de páginas públicas do SEI/IPHAN que tenham sido explicitamente fornecidas na entrada.

## Implementado

A entrada da interface aceita links diretos PDF/TXT e páginas de processo no endpoint público `md_pesq_processo_exibir.php` de `sei.iphan.gov.br`. Ela ignora cabeçalhos e linhas não URL HTTPS, remove URLs repetidas e separa automaticamente mais de 50 URLs em tarefas de até 50 itens.

O parser lê os metadados expostos na página e a tabela de documentos. Para cada documento, armazena o número exibido, título, tipo, data, data de inclusão, unidade, URL pública quando disponível e a URL da página de origem. Um processo sem associação é criado ou reutilizado no registro canônico apenas para o usuário humano que iniciou a tarefa. Uma associação a processo com número divergente é recusada antes de qualquer download.

Somente links já expostos pela página para `md_pesq_documento_consulta_externa.php` são obtidos. O download preserva as verificações existentes de DNS público, HTTPS, TLS/SNI, allowlist, redirect, MIME, PDF/TXT, tamanho e hash. Documentos públicos entram no acervo somente após essa verificação. Linhas sem link público ou marcadas como restritas não são requisitadas e ficam em `waiting_for_user`.

A descoberta possui limite de 1.000 documentos por página e 25.000 por tarefa. A quota existente de 100 MiB por tarefa e 20 MiB por arquivo continua válida. As descobertas, documentos filhos, proveniência e limites são persistidos de modo aditivo, sem alterar registros anteriores.

A demonstração de construção abre sem senha, tem dados efêmeros e executa o worker somente para a descoberta pública habilitada. Administração e alterações de acervo continuam bloqueadas para a sessão demonstrativa.

## Formatos e análise

Uploads manuais aceitam PDF, TXT, CSV, DOCX e XLSX. CSV é convertido para texto tabular; DOCX lê somente `word/document.xml`; XLSX lê células e strings compartilhadas sem executar macros, scripts ou fórmulas. PDF digitalizado tenta OCR somente quando `tesseract` e `pdftoppm` estão disponíveis; sem motor ou sem texto reconhecido, a execução permanece `needs_ocr` e não cria evidência vazia.

Recursos espaciais aceitam KML/KMZ, Shapefile ZIP, GeoJSON/JSON e GPX, apenas em WGS84/EPSG:4326, com limite de tamanho/expansão e consulta geodésica em metros. O painel `GET /v1/analysis/processes` apresenta, por processo autorizado, documentos, extrações, classificações validadas, evidências, conhecimento pendente e status `not_started`, `pending`, `in_progress` ou `analyzed`.

## Verificado

Testes específicos cobrem parser SEI, extração apenas de links públicos, criação canônica de processo, download público simulado, documentos restritos como pendência, limites de descoberta, CSV/DOCX/XLSX, GeoJSON/GPX/Shapefile ZIP e transições do painel de análise. A regressão integral final executou **82 testes aprovados** em 20/10/2026. A interface foi validada no Chromium com acesso automático sem senha, navegação das telas e ausência de erros JavaScript.

Uma página pública fornecida pelo usuário foi lida sem persistência de documentos reais. Ela declarou o processo `01401.000108/2022-66`, listou 311 documentos, dos quais 309 tinham link público de documento e 2 não tinham link público. Três URLs de documento extraídas dessa página responderam `200 application/pdf` durante a verificação de estrutura. A URL opaca da consulta não é incluída neste repositório ou relatório.

## Não declarado como concluído

Não existe pesquisa por número de processo, varredura do portal, paginação externa, login, autenticação externa, CAPTCHA, geração de PDF da página ou contorno de restrições. Não há homologação institucional com IPHAN, ATENA ou Geoportal. PostgreSQL/PostGIS em servidor real e operação com dados persistentes de produção continuam fora desta publicação de construção. OCR depende dos binários instalados; a imagem Docker agora instala Poppler e Tesseract com inglês/português.
