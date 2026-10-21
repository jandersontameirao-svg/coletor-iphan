# Plano — descoberta pública de documentos SEI

O Coletor IPHAN aceitará links explícitos de páginas públicas de processo do SEI/IPHAN além dos links diretos PDF/TXT já suportados. Ele não executará pesquisa por número, preenchimento de formulários, autenticação, CAPTCHA ou tentativa de acesso a conteúdo restrito.

Cada página de processo será obtida pelo mesmo transporte HTTPS com allowlist, DNS público fixado, SNI/TLS validado, limites de tamanho e cadência já aplicados aos links diretos. O parser reconhecerá somente o endpoint público `md_pesq_processo_exibir.php` em `sei.iphan.gov.br`. Ele extrairá o número e a descrição do processo, além dos links presentes para `md_pesq_documento_consulta_externa.php`. Linhas sem link público serão registradas como restritas ou não disponíveis, sem novas requisições.

O worker criará ou reutilizará o processo canônico sob a ACL do solicitante humano e gravará cada documento descoberto como item filho rastreável. A URL da página de processo, a URL pública do documento, o identificador exibido, título, tipo, data, unidade e resultado serão preservados. Um documento só se torna original do acervo depois da resposta verificada como PDF ou TXT. Documentos públicos que retornarem login, CAPTCHA, HTML, erro, redirecionamento indevido ou formato não permitido permanecerão como pendência individual.

A lista de entrada ignorará cabeçalhos e textos não URL, deduplicará links e criará lotes de até 50 páginas/links de origem. A descoberta terá limite de 1.000 documentos por página e de 25.000 documentos por tarefa; quando atingidos, o item exibirá pendência para o usuário dividir a operação. O limite existente de 100 MiB por tarefa e 20 MiB por arquivo continua aplicável aos originais obtidos.

Na versão pública de construção, a interface continuará sem senha. A coleta será habilitada somente sob a identidade sintética de construção, com dados efêmeros, URLs da allowlist e os mesmos limites. Administração, grupos, contas de serviço, permissões, usuários, classificação, importação manual e edição de originais permanecem bloqueados. A implantação operacional continua exigindo autenticação normal e ACL por processo.
