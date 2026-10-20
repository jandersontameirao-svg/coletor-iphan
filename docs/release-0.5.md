# Relatório da entrega 0.5 — descoberta pública SEI/IPHAN

A versão 0.5 preserva a fundação 0.3 e as extensões 0.4: API FastAPI, autenticação, ACL, grupos, delegação, fila persistente, armazenamento por hash, extração PDF/TXT, conhecimento rastreável, KML/KMZ e pesquisa espacial. Esta entrega acrescenta leitura de páginas públicas do SEI/IPHAN que tenham sido explicitamente fornecidas na entrada.

## Implementado

A entrada da interface aceita links diretos PDF/TXT e páginas de processo no endpoint público `md_pesq_processo_exibir.php` de `sei.iphan.gov.br`. Ela ignora cabeçalhos e linhas não URL HTTPS, remove URLs repetidas e separa automaticamente mais de 50 URLs em tarefas de até 50 itens.

O parser lê os metadados expostos na página e a tabela de documentos. Para cada documento, armazena o número exibido, título, tipo, data, data de inclusão, unidade, URL pública quando disponível e a URL da página de origem. Um processo sem associação é criado ou reutilizado no registro canônico apenas para o usuário humano que iniciou a tarefa. Uma associação a processo com número divergente é recusada antes de qualquer download.

Somente links já expostos pela página para `md_pesq_documento_consulta_externa.php` são obtidos. O download preserva as verificações existentes de DNS público, HTTPS, TLS/SNI, allowlist, redirect, MIME, PDF/TXT, tamanho e hash. Documentos públicos entram no acervo somente após essa verificação. Linhas sem link público ou marcadas como restritas não são requisitadas e ficam em `waiting_for_user`.

A descoberta possui limite de 1.000 documentos por página e 25.000 por tarefa. A quota existente de 100 MiB por tarefa e 20 MiB por arquivo continua válida. As descobertas, documentos filhos, proveniência e limites são persistidos de modo aditivo, sem alterar registros anteriores.

A demonstração de construção abre sem senha, tem dados efêmeros e executa o worker somente para a descoberta pública habilitada. Administração e alterações de acervo continuam bloqueadas para a sessão demonstrativa.

## Verificado

Quatro testes específicos cobrem: parser de tabela, extração apenas de links públicos, criação canônica de processo, download público simulado, documentos restritos como pendência, prevenção de associação a processo divergente e limite global de descoberta. A regressão integral executou **73 testes aprovados** em 19/10/2026. A interface foi validada no Chromium com acesso automático sem senha, navegação para a nova tela, texto de orientação e ausência de erros JavaScript. A navegação não teve respostas HTTP 4xx/5xx.

Uma página pública fornecida pelo usuário foi lida sem persistência de documentos reais. Ela declarou o processo `01401.000108/2022-66`, listou 311 documentos, dos quais 309 tinham link público de documento e 2 não tinham link público. Três URLs de documento extraídas dessa página responderam `200 application/pdf` durante a verificação de estrutura. A URL opaca da consulta não é incluída neste repositório ou relatório.

## Não declarado como concluído

Não existe pesquisa por número de processo, varredura do portal, paginação externa, login, autenticação externa, CAPTCHA, geração de PDF da página ou contorno de restrições. Não há homologação institucional com IPHAN, ATENA ou Geoportal. OCR efetivo, PostgreSQL/PostGIS em servidor real e operação com dados persistentes de produção continuam fora desta publicação de construção.
