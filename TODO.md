# TODO — Coletor IPHAN 0.7

## Entregue

- [x] Manter processos canônicos, documentos, revisões, evidências, proveniência, ACL, grupos, contas de serviço, delegação, auditoria e fila persistente.
- [x] Aceitar links HTTPS explícitos, páginas públicas SEI/IPHAN fornecidas e importação manual, sem pesquisa automática por número, login externo ou CAPTCHA.
- [x] Preservar originais no cache local por SHA-256 e disponibilizar revisão, download autorizado e histórico.
- [x] Importar PDF, HTML documental SEI, TXT/CSV, DOCX/XLSX, imagens, ZIP/RAR/7z e formatos geográficos conforme a política de arquivo.
- [x] Versionar KML/KMZ, Shapefile ZIP, GeoJSON/JSON e GPX em WGS84/EPSG:4326; manter componentes geográficos juntos e consultar entorno em metros.
- [x] Manter conhecimento rastreável e processos analisados com evidências, revisão humana, conflitos e status explícitos.
- [x] Organizar a interface operacional em Coleta, Acompanhamento, Biblioteca e Configurações.
- [x] Classificar conservadoramente por processo em Georreferenciados, PAPIPA, RAPIPA, PAIPA, RAIPA, PGPA, RAIPI, Educação patrimonial, Outros documentos e A classificar.
- [x] Implementar ponte SharePoint com destino configurável, device code Microsoft, tokens criptografados, validação, pastas sob demanda, upload verificado, retry, retomada, movimentação e preservação local.
- [x] Implementar Empresas e responsáveis com papéis explícitos, CNPJ/contatos rotulados, evidências por documento/revisão/página ou unidade, revisão humana e exportação JSON.
- [x] Manter o módulo de participantes como análise documental conservadora, sem inferência de cliente final, contrato, vínculo empregatício, prospecção ou finanças.
- [x] Executar a suíte 0.7: 110 testes, 108 aprovados e 2 E2E históricos pulados quando Playwright não está instalado; o E2E dedicado da ponte SharePoint passou com Chromium e zero erros JavaScript.
- [x] Validar o manifesto SHA-256 do ZIP recebido, com 132 arquivos e zero divergências.
- [x] Adaptar o Dockerfile para respeitar `PORT` no runtime Manus.

## Checkpoint e publicação

- [ ] Criar checkpoint Manus da versão 0.7 integrada.
- [ ] Publicar o checkpoint confirmado no ambiente Manus.
- [ ] Verificar health check e abertura da URL publicada após o deploy.

## Homologações externas pendentes

- [ ] Configurar `MICROSOFT_TENANT_ID` e `MICROSOFT_CLIENT_ID` no ambiente seguro.
- [ ] Obter consentimento organizacional Microsoft Graph `Files.ReadWrite` e conectar uma conta autorizada.
- [ ] Validar o link real da pasta SharePoint, criar/conferir/remover arquivo de teste e confirmar uma transferência real.
- [ ] Medir implantação Linux/Compose, volume persistente, backup/restauração, RPO/RTO e concorrência com acervo real.
- [ ] Homologar fontes reais IPHAN e consumidores ATENA/Geoportal, sem declarar resultado antecipadamente.

## Restrições preservadas

- [ ] Não usar a publicação demonstrativa para credenciais, tokens, acervo real ou produção.
- [ ] Não acessar SharePoint real antes da autenticação e consentimento autorizados.
- [ ] Não apagar histórico de categorias, revisões, ocorrências, transferências ou evidências.
