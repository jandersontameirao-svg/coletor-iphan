# Relatório da entrega 0.4 — escopo real do Coletor IPHAN

A versão 0.4 parte diretamente do pacote 0.3 e preserva a API, autenticação, ACL, fila, armazenamento por hash, worker, extração PDF/TXT e oito telas existentes. A versão 0.3 original permanece em outra cópia sem alterações.

## Implementado e testado

- Conhecimento rastreável com afirmação, tipo, confiança opcional, revisão humana, validação, rejeição, conflito e relações `supports`, `contradicts` e `derived_from`.
- Toda afirmação exige `evidence_id` autorizado e permanece vinculada à revisão/documento/processo de origem.
- Importação KML/KMZ com XML validado, Placemark, Point, LineString, Polygon, WGS84/EPSG:4326 e rejeição de coordenadas inválidas.
- Revisões espaciais versionadas sem duplicação automática de originais documentais.
- Consulta por latitude/longitude e entorno em metros usando distância geodésica; polígonos podem responder como área contendo o ponto.
- Contratos de capacidades para consumidores, mantendo homologação ATENA e Geoportal explicitamente falsa.
- Interface com marca local do Grupo Arqueo, telas reais para Conhecimento e Pesquisa espacial e tela de Integrações atualizada.
- Detecção explícita de OCR opcional. Quando o motor não está disponível, PDF sem texto permanece `needs_ocr` e não cria evidência fictícia.
- 68 testes passaram: 65 da base/regressão e 3 testes específicos 0.4.

## Não declarado como concluído

- PostgreSQL/PostGIS e testes em servidor PostgreSQL real: bloqueados pela ausência de servidor/adapter operacional neste ambiente.
- OCR efetivo: condicional à instalação de `tesseract` e idioma adequado; `pdftoppm` existe, `tesseract` não foi encontrado no host desta execução.
- Integração externa real com ATENA, Geoportal ou SEI/IPHAN: não homologada.
- Descoberta automática, login, CAPTCHA, paginação de processos e anexos: continuam fora do escopo por decisão de segurança e de entrada exclusivamente por links.
- Homologação positiva de documento IPHAN: não substituída por fixtures ou testes locais.

## Rotas adicionadas

`/v1/knowledge/assertions`, `/v1/knowledge/assertions/{id}`, `/v1/spatial-resources`, `/v1/spatial-resources/{id}`, `/v1/spatial-search`, `/v1/overview/advanced` e `/v1/integration/capabilities`.

## Segurança e proveniência

As novas rotas usam o mesmo `Authorization: Bearer`, ACL por processo e permissões `operate`, `read` e `review` da base. Eventos de criação, revisão e validação entram na auditoria/outbox existente. A interface não oferece geração automática de fatos nem acesso espacial fora das permissões do processo.
