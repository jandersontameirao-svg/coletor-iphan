# TODO — Coletor IPHAN 0.5

## Recursos entregues

- [x] Manter processos canônicos, documentos, revisões, evidências, origem, download protegido, extração assíncrona, fila persistente e armazenamento por SHA-256.
- [x] Manter ACL por processo com permissões de leitura, operação, revisão e administração, incluindo grupos, contas de serviço, delegação, revogação e auditoria.
- [x] Aceitar links explícitos e importação manual autorizada. Links para a página pública SEI/IPHAN fornecidos pelo usuário são lidos para identificar documentos que a própria página expõe publicamente; não há pesquisa de processo por número ou varredura do portal.
- [x] Registrar afirmações de conhecimento somente quando vinculadas a evidência autorizada, com revisão humana, validação, rejeição, conflito e relações rastreáveis.
- [x] Importar e versionar KML/KMZ, Shapefile ZIP, GeoJSON/JSON e GPX em WGS84/EPSG:4326 e realizar pesquisa espacial por ponto e entorno em metros.
- [x] Importar PDF, TXT, CSV, DOCX e XLSX com validação de conteúdo; DOCX/XLSX não executam macros ou fórmulas.
- [x] Tentar OCR real de PDF digitalizado quando `tesseract` e `pdftoppm` estiverem instalados; manter `needs_ocr` sem evidência fictícia quando não houver motor/resultado.
- [x] Exibir painel de Processos analisados com status calculado por extração, classificação, evidência e revisão pendente.
- [x] Manter contratos de integração sem declarar homologação real com IPHAN, ATENA ou Geoportal.
- [x] Aplicar a marca local e o padrão visual do Grupo Arqueo à interface do Coletor.
- [x] Configurar container Python 3.12 com `PORT`, health check em `/_app/health`, manifesto de rotas e suporte ao Preview Webdev.

## Descoberta pública SEI

- [x] A tela de links aceita páginas públicas SEI/IPHAN fornecidas, ignora linhas não URL HTTPS, remove duplicatas e divide mais de 50 URLs em tarefas separadas.
- [x] O worker aceita somente o endpoint público de processo SEI/IPHAN, registra processo/documentos descobertos e baixa apenas links públicos PDF/TXT verificados.
- [x] Linhas sem link público, login, CAPTCHA, redirecionamentos indevidos, restrições e erros permanecem como pendências individuais, sem tentativa de contorno.
- [x] A descoberta limita 1.000 documentos por página e 25.000 por tarefa; a quota existente de 100 MiB por tarefa e 20 MiB por arquivo permanece aplicada.
- [x] A demonstração sem senha permite somente a fila de descoberta pública durante a construção, com dados efêmeros; administração e alterações operacionais continuam bloqueadas.

## Entrega atual

- [x] Executar testes específicos de descoberta SEI, formatos documentais, formatos geográficos, análise de processos, sintaxe e regressão integral em banco temporário: **82 testes aprovados em 20/10/2026**.
- [x] Salvar o checkpoint atualizado no repositório canônico Manus sem incluir arquivos de rascunho não ativados.
- [ ] Publicar o checkpoint confirmado no ambiente Manus.

## Limites explícitos

- [ ] PostgreSQL/PostGIS em servidor real e integrações externas reais só poderão ser declarados quando instalados e homologados.
- [ ] Não há pesquisa de processo por número, autenticação externa, resolução de CAPTCHA ou acesso a documentos SEI sem link público.
- [ ] O container demonstrativo armazena dados efêmeros; não deve receber credenciais ou dados operacionais reais.
