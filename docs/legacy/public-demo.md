# Demonstração pública isolada — Coletor IPHAN 0.5

Esta publicação serve para avaliar a interface e os fluxos implementados na versão 0.5. Durante a fase de construção, o acesso demonstrativo abre automaticamente e **não exige senha**. A aplicação emite uma sessão temporária para o usuário sintético `Visualização demonstrativa`.

A sessão permite consultar os dados sintéticos iniciais e criar ou retomar tarefas de descoberta em páginas públicas de processo do SEI/IPHAN que sejam explicitamente fornecidas pelo usuário. A descoberta registra os metadados da página e os documentos com link público. Ela somente baixa PDF/TXT quando a resposta passa pela verificação de tipo, tamanho e origem. Consultas textuais e espaciais continuam permitidas.

A sessão não permite criar processos pela interface, usuários, grupos, contas de serviço, permissões, delegações, uploads, alterações de classificações, edição/exclusão de originais ou autenticação externa. Também não realiza pesquisa de processo por número, login, preenchimento de formulário, resolução de CAPTCHA, geração de PDF da página ou tentativa de abrir documentos marcados como restritos. Registros sem link público permanecem pendentes para solução no ambiente operacional autorizado.

O container usa SQLite em filesystem efêmero e executa o worker somente para esta fila de construção. Os dados podem ser recriados após reinício ou nova publicação. Não existem documentos reais pré-carregados, credenciais operacionais, tokens, banco local de produção nem integração institucional homologada com IPHAN, ATENA ou Geoportal.
