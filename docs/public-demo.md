# Demonstração pública isolada — Coletor IPHAN 0.4

Esta publicação serve exclusivamente para visualização da interface e dos fluxos implementados na versão 0.4. Durante a fase de construção, o acesso demonstrativo é aberto automaticamente e **não exige senha**. A aplicação emite uma sessão temporária para o usuário sintético `Visualização demonstrativa`.

A sessão permite consultar um processo sintético, documento, evidência, afirmação validada, recursos KML/KMZ e pesquisa espacial. Consultas textuais e espaciais são permitidas. Operações de escrita, coleta por links, importação, alteração de permissões, classificação, criação de processos, usuários ou contas de serviço são bloqueadas pela camada do modo demonstrativo.

O container usa SQLite em filesystem efêmero e não inicia worker. Dados podem ser recriados após reinício ou nova publicação. Não existem documentos reais, credenciais operacionais, tokens, banco local de produção nem integração homologada com IPHAN, ATENA ou Geoportal.
