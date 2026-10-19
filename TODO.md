# TODO — Coletor IPHAN 0.4

## Recursos entregues

- [x] Manter processos canônicos, documentos, revisões, evidências, origem, download protegido, extração assíncrona, fila persistente e armazenamento por SHA-256.
- [x] Manter ACL por processo com permissões de leitura, operação, revisão e administração, incluindo grupos, contas de serviço, delegação, revogação e auditoria.
- [x] Aceitar apenas links explícitos e importação manual autorizada; não realizar busca automática de processos ou anexos no IPHAN.
- [x] Registrar afirmações de conhecimento somente quando vinculadas a evidência autorizada, com revisão humana, validação, rejeição, conflito e relações rastreáveis.
- [x] Importar e versionar KML/KMZ WGS84/EPSG:4326 e realizar pesquisa espacial por ponto e entorno em metros.
- [x] Informar OCR como condicional e manter PDF sem texto como `needs_ocr`, sem criar evidências fictícias.
- [x] Manter contratos de integração sem declarar homologação real com IPHAN, ATENA ou Geoportal.
- [x] Aplicar a marca local e o padrão visual do Grupo Arqueo à interface do Coletor.
- [x] Disponibilizar demonstração sintética somente de leitura para processos, documentos, evidências, conhecimento e geografia.
- [x] Configurar container Python 3.12 com `PORT`, health check em `/_app/health`, manifesto de rotas e suporte ao Preview Webdev.

## Entrega atual

- [x] Executar a regressão final da versão 0.4 com banco temporário e verificar health check e fluxo da demonstração. Evidência: 69 testes aprovados em 19/10/2026.
- [ ] Salvar o checkpoint atualizado no repositório canônico Manus sem incluir arquivos de rascunho não ativados.
- [ ] Publicar o checkpoint confirmado no ambiente Manus.

## Limites explícitos

- [ ] PostgreSQL/PostGIS em servidor real, OCR efetivo e integrações externas reais só poderão ser declarados quando instalados e homologados.
- [ ] O container demonstrativo continuará sem dados reais, sem worker e com SQLite efêmero.
