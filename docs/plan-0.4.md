# Plano técnico — Coletor IPHAN 0.4 no escopo real

## Objetivo

Evoluir a cópia isolada da versão 0.3 somente com capacidades previstas na especificação do Coletor IPHAN, preservando API, autenticação, ACL, fila, armazenamento por hash, worker, parser e interface existentes. A versão 0.3 original permanecerá intocada.

## Implementação prevista

1. **Conhecimento rastreável:** afirmações vinculadas a evidências, revisão humana, conflitos e trilha de auditoria; sem geração automática de fatos.
2. **Recursos geográficos:** importação/versionamento de KML/KMZ, validação XML/geometria, papéis de localização e consulta por interseção/entorno com cálculo em metros quando tecnicamente possível.
3. **Formatos e extração:** preservar PDF/TXT, incluir inventário seguro de imagens e formatos adicionais somente quando houver parser verificável; OCR fica opcional e explicitamente identificado quando não houver motor instalado.
4. **Contratos de integração:** ampliar capacidades e endpoints consumíveis pela ATENA/Geoportal sem declarar integração externa homologada.
5. **Operação e evidência:** relatórios técnicos de implementação, testes novos e classificação clara de implementado, testado, bloqueado e não homologado.

## Não será inventado

- Não será criada busca automática de processos ou anexos SEI.
- Não será contornado login, CAPTCHA, allowlist, TLS ou restrição de origem.
- Não será declarada homologação IPHAN/ATENA/Geoportal sem acesso autorizado e evidência conferível.
- PostgreSQL não será apresentado como operacional sem servidor e testes reais; se preparado, ficará como adaptador/documentação explícita.

## Estrutura

- `knowledge_domain.py`: migração, parser de afirmações e consultas de conhecimento.
- `geo_domain.py`: KML/KMZ, geometria e métricas geográficas.
- `advanced_routes.py`: rotas autenticadas para conhecimento, geografia, capacidades e integração.
- `advanced_ui.js`: telas reais adicionais conectadas à API.
- `tests/test_v04_scope.py`: testes determinísticos das novas capacidades.
