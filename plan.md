# Plano de entrega — Coletor IPHAN 0.4

## Objetivo

Entregar e publicar a versão 0.4 do Coletor IPHAN como repositório técnico rastreável para processos, documentos, evidências, conhecimento e geografia. O produto não possui módulos financeiros, comerciais, de empresas, contratos, fluxo de caixa, DRE ou EBITDA. Esses temas não fazem parte desta entrega e não serão adicionados ao aplicativo.

## Escopo implementado

A fundação do Coletor mantém cadastro de processos canônicos, permissões por processo, grupos, contas de serviço, delegações e auditoria. Documentos PDF/TXT são preservados por hash SHA-256, com revisões, ocorrências, origem, download protegido e extração assíncrona. A entrada externa é feita somente por links explícitos ou importação manual autorizada; o sistema não busca processos, anexos ou páginas automaticamente no IPHAN.

A versão 0.4 acrescenta uma camada de conhecimento rastreável. Cada afirmação exige uma evidência existente e autorizada e pode receber tipo, confiança, revisão humana, validação, rejeição, conflito e relações com outras afirmações. O sistema não gera fatos automaticamente.

A mesma versão adiciona recursos espaciais em KML/KMZ. Os recursos são validados em WGS84/EPSG:4326, recebem revisões e podem ser consultados por latitude, longitude e entorno em metros usando distância geodésica. O vínculo espacial não substitui nem duplica os documentos do acervo.

O OCR é condicional: quando o motor não existe, um PDF digitalizado é indicado como `needs_ocr`, sem criação de evidência vazia ou fictícia. As integrações com IPHAN, ATENA e Geoportal não são declaradas homologadas. Login, CAPTCHA, descoberta automática e coleta de anexos permanecem fora do escopo por segurança e proveniência.

## Interface e identidade visual

A interface é uma aplicação FastAPI servida pelo próprio backend, com telas para Visão geral, Entrada de links, Tarefas, Processos, Documentos, Biblioteca, Integrações, Administração, Conhecimento e Pesquisa espacial. Ela usa a marca local do Grupo Arqueo e uma linguagem técnica, objetiva e transparente. O cabeçalho, as cores institucionais e os avisos de capacidade foram mantidos como referência visual do Grupo Arqueo, sem transformar o Coletor em outro produto.

## Demonstração e publicação

O modo demonstrativo usa somente registros sintéticos: processo, documento, evidência, afirmação e área espacial. A sessão pública é estritamente de leitura. Escrita, importação, coleta, edição de permissões, criação de usuários e administração são bloqueadas. O container responde em `/_app/health`, atende a porta `PORT` e permite Preview incorporado quando habilitado apenas para o runtime Webdev.

A publicação é feita no ambiente Manus por Dockerfile Python 3.12. O banco SQLite do container é efêmero e o worker não é iniciado na demonstração; portanto, a publicação é adequada para avaliação funcional e visual, não para operação com acervo real.

## Estrutura

- `app.py`: API FastAPI, inicialização, autenticação, recursos de acervo, demonstração e assets.
- `catalog_routes.py` e `access_routes.py`: catálogo, documentos, permissões, grupos, contas de serviço e delegação.
- `advanced_routes.py`: conhecimento rastreável, KML/KMZ, pesquisa espacial e contrato de capacidades.
- `knowledge_domain.py` e `geo_domain.py`: migrações e regras dos domínios 0.4.
- `task_queue.py`, `worker.py`, `extraction.py` e `safe_fetch.py`: fila durável, extração isolada e coleta limitada a links explícitos.
- `index.html`, `ui.js`, `advanced_ui.js` e `styles.css`: interface do Coletor.
- `demo_mode.py`: dados sintéticos e sessão pública somente de leitura.
- `Dockerfile`: execução do container de demonstração.
- `tests/`: regressão da base e cobertura da extensão 0.4.
