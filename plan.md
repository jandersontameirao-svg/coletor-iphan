# Plano de publicação — Coletor IPHAN 0.4

## Objetivo

Publicar uma **demonstração isolada** da versão 0.4 já validada do Coletor IPHAN, para avaliação visual e funcional. A publicação não recebe acervo, usuários, tokens, banco ou segredos da versão local. O estado do container é temporário e contém apenas registros sintéticos.

## Implementação

A aplicação FastAPI existente será publicada em um container Python 3.12. O listener usará `PORT` e responderá ao health check não autenticado em `/_app/health`. O projeto manterá os assets e as rotas existentes, com uma adaptação condicional para permitir o iframe de Preview/Webdev apenas quando `COLLECTOR_ALLOW_EMBED=1`.

O modo de demonstração é habilitado exclusivamente por `COLLECTOR_DEMO_MODE=1`. Nesse modo, a inicialização cria um usuário público com permissão somente de leitura, um processo sintético, um documento com evidência, uma afirmação validada e um recurso espacial KML normalizado. Uma sessão de visualização é emitida por endpoint público específico do modo de demonstração. Não são criados privilégios de operação, revisão, administração, coleta externa ou alteração dos dados.

A publicação usa filesystem temporário para SQLite e não inicia o worker. Consequentemente, a demonstração não deve receber dados reais nem ser usada como produção. A versão local 0.3 e a prévia 0.4 existente permanecem sem modificações.

## Design

- **Movimento:** interface de acervo técnico institucional, usando a identidade visual já aplicada do Grupo Arqueo.
- **Princípios:** rastreabilidade, hierarquia documental, contraste funcional e exposição explícita de limites operacionais.
- **Cores:** azul-marinho para confiança e navegação; laranja para ações; vinho em marcadores institucionais; fundos neutros para leitura de metadados.
- **Layout:** navegação horizontal, contexto de processo lateral e painéis sequenciais de evidências.
- **Elementos distintivos:** marca local, chips de permissão/status e painéis de proveniência.
- **Interações:** a demonstração oferece acesso de leitura em um clique; ações mutáveis permanecem indisponíveis para o usuário demonstrativo.
- **Animação:** transições nativas discretas; sem animações que possam ocultar estado do acervo.
- **Tipografia:** pilha de sistema para densidade e legibilidade técnica.
- **Essência da marca:** acervo técnico rastreável para patrimônio cultural; preciso, responsável e institucional.
- **Voz:** direta e verificável. Exemplos: “A evidência antecede a conclusão.” e “Consulta demonstrativa com dados sintéticos.”
- **Wordmark:** o logo oficial local do Grupo Arqueo acompanha o nome Coletor IPHAN sem substituir a identidade do produto.
- **Cor de assinatura:** laranja institucional aplicado somente a ações e estados de foco.

## Estrutura

- `app.py`: API FastAPI, interface e modo de demonstração condicional.
- `demo_mode.py`: dados sintéticos e emissão de sessão pública de leitura.
- `Dockerfile`: runtime Python 3.12 publicado.
- `index.html`, `ui.js`, `advanced_ui.js`, `styles.css`: interface existente da versão 0.4.
- `manus-routes.json`: manifesto de rota do site.
- `docs/`: contratos, escopo e relatório técnico já validado.
