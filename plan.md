# Plano técnico — Coletor IPHAN 0.7

## Objetivo

Publicar o Coletor IPHAN como ponte rastreável entre links fornecidos, catálogo documental autorizado, Biblioteca e SharePoint, preservando originais, revisões, hashes, evidências, ACLs e histórico. O módulo de participantes é determinístico e baseado em fontes documentais; não é um módulo financeiro, comercial ou de prospecção.

## Escopo entregue

A versão 0.7 mantém a fundação de processos canônicos, ACL por processo, grupos, contas de serviço, delegação, auditoria, fila persistente, extração isolada, conhecimento rastreável e geografia em WGS84. A interface operacional possui quatro abas: Coleta, Acompanhamento, Biblioteca e Configurações.

A coleta aceita links HTTPS explícitos, páginas públicas SEI/IPHAN fornecidas e importação manual. A página SEI só pode revelar documentos que ela própria apresenta publicamente; login, CAPTCHA, pesquisa automática por número e contorno de restrições continuam proibidos. Original, ocorrência, revisão, hash e proveniência são preservados antes de qualquer transferência.

A ponte SharePoint implementa configuração de destino, autenticação Microsoft por device code sem senha Microsoft dentro do Coletor, cache criptografado de tokens, validação do link, criação de pastas sob demanda, upload, releitura com conferência SHA-256, fila, retry, retomada, movimentação de categoria e preservação local até confirmação. Credenciais e consentimento reais permanecem responsabilidade da organização.

A organização física usa uma pasta por processo, com `Georreferenciados` e `Documentos`. As categorias documentais incluem PAPIPA, RAPIPA, PAIPA, RAIPA, PGPA, RAIPI, Educação patrimonial, Outros documentos e A classificar. Ambiguidade não é inventada; a classificação humana mantém histórico e o reenvio não duplica o item remoto.

O módulo Empresas e responsáveis identifica somente papéis, CNPJ, contatos e trechos explicitamente encontrados em documentos. Fatos começam como `proposed`, exigem revisão humana e preservam evidências, revisão, página real ou unidade textual, hash e origem. Nomes iguais sem CNPJ são apenas candidatos; o sistema não infere cliente final, contrato ou vínculo empregatício.

## Arquitetura

- `app.py`: API, autenticação, catálogo, health check, assets e bootstrap de módulos.
- `bridge_routes.py`, `sharepoint_store.py`, `archive_policy.py`: ponte, destino, categorias e transferências.
- `market_routes.py`, `market_domain.py`, `market_extract.py`: participantes, evidências, revisão e exportação JSON.
- `task_queue.py`, `worker.py`, `safe_fetch.py`, `extraction.py`, `extraction_child.py`: fila, obtenção segura e extração.
- `repository_migration.py`, `sei_domain.py`, `knowledge_domain.py`, `geo_domain.py`: migrações e domínios documentais, SEI, conhecimento e geografia.
- `bridge.html`, `bridge_ui.js`, `bridge.css`: interface 0.7 de quatro abas.
- `tests/`: regressão histórica, ponte SharePoint, participantes, formatos, geografia, SEI, ACL e fila.

## Publicação e limites

O container usa Python 3.12, instala Poppler/Tesseract para OCR condicional, respeita `PORT` e responde em `/_app/health`. O banco SQLite/cache local precisa de volume persistente em implantação operacional. O SharePoint real requer `MICROSOFT_TENANT_ID`, `MICROSOFT_CLIENT_ID`, consentimento delegado `Files.ReadWrite`, conta autorizada e validação do destino.

A entrega não declara homologação real do SharePoint, IPHAN, ATENA ou Geoportal. Não inclui tokens, senha, segredo de cliente, banco operacional ou acervo real.
