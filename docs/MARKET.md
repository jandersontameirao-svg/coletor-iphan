# Empresas, responsáveis e fontes — versão 0.7

O novo módulo complementa a ponte documental: os originais e os envios ao SharePoint continuam independentes. Cada original confirmado entra numa fila persistente de extração local; o worker a executa quando termina os trabalhos de coleta/envio disponíveis. Acervos anteriores podem ser processados pela Biblioteca ou por POST /v1/market/processes/{id}/extract. Não foi adicionado um painel comercial nem outra aba.

## O que identifica

Campos explícitos de empreendedor, titular, contratante, cliente declarado, cliente final declarado, consultoria ambiental/arqueológica, empresa executora, autoria, coordenação, representação e responsabilidade técnica. Também lê CNPJ numérico, e-mail e telefone em campos rotulados. Reconhece separadores, acentos e alguns campos em linhas consecutivas. É um extrator determinístico conservador, sem provedor de IA, sem credenciais externas adicionais e sem interpretação irrestrita de texto narrativo. Não garante detectar todos os participantes de qualquer diagramação.

PDF usa texto nativo e tenta OCR quando os binários estão presentes. PDF sem texto permanece needs_ocr ou partial_needs_ocr. HTML do SEI é convertido em texto sem executar scripts; TXT/CSV/DOCX/XLSX também são processados pelo parser isolado. Formatos preservados mas não interpretados, como RAR/7z, recebem not_supported; documentos acima de 20 MiB recebem size_limit. Os originais continuam preservados e disponíveis. O original não é substituído pelo texto.

## Evidência

Cada identificação tem ID, papel, tipo de pessoa/organização, campo, valor, rótulo, trecho literal, página real do PDF quando disponível, intervalo de linhas da unidade textual, documento, revisão, SHA-256, origem, metadados SEI quando disponíveis, método/versão e instante de extração. DOCX/HTML/TXT não recebem páginas fictícias. As linhas referem-se ao texto extraído, não às linhas visuais do arquivo. A nova execução não sobrescreve os resultados antigos.

## Cruzamento

As participações são agrupadas por processo. Um mesmo CNPJ numérico com dígitos verificadores válidos pode unir denominações distintas; isso é validação do formato, não consulta ao cadastro oficial. Nomes iguais sem CNPJ são somente candidatos de identidade. Pessoas não são identificadas por CPF. O agrupamento mostra os papéis e as fontes administrativas/técnicas: a mesma empresa pode aparecer como empreendedor na FCA e contratante em um RAIPI. Pessoas citadas em diferentes documentos não são automaticamente declaradas empregadas de uma consultoria.

Proximidade entre campo de contato e nome gera associação candidata, indicada expressamente. Contato sem titular claro permanece sem associação. Papéis incompatíveis ou divergentes permanecem lado a lado com suas evidências: o sistema não escolhe um vencedor nem infere contrato, cliente final ou vínculo empregatício a partir de mera coocorrência. Datas dos documentos SEI, quando disponíveis, são exportadas nos metadados de origem; ausência de data permanece desconhecida. Contatos não são apresentados como necessariamente atuais.

## Revisão e acesso

Todos os achados começam proposed. Revisor autorizado registra validação/rejeição e justificativa; cada decisão é um novo registro, preservando o histórico. Achados rejeitados ficam visíveis como histórico, mas não compõem os cruzamentos. Revisões documentais antigas e execuções substituídas não alimentam o cruzamento atual. Uma execução nova sem correspondências substitui resultados anteriores na visão atual; falha de execução mantém o último resultado bem-sucedido disponível com seu histórico de runs.

As permissões são as mesmas dos documentos: read consulta/exporta, operate solicita extração, review valida/rejeita. O worker revalida permissões/delegação e usa lease antes de gravar achados. Revogação durante processamento impede o commit. Não há envio de contatos, mensagens comerciais, coleta de redes sociais ou consulta a cadastros externos.

## Uso na interface

Na Biblioteca, abrir **Empresas e responsáveis** em um documento para visualizar o conjunto do processo. Filtrar por processo também exibe o botão de cruzamento. O diálogo mostra processamento, agrupamentos, fontes e formulários de revisão; o usuário pode atualizar, solicitar reprocessamento e exportar JSON com evidências para o futuro aplicativo de inteligência de mercado.

## Contrato de consumo

- GET /v1/market/processes/{id}: execuções, fatos atuais e cruzamentos.
- GET /v1/market/processes/{id}?history=true: inclui fatos e revisões históricas.
- GET /v1/market/processes/{id}/export: JSON versionado, com fontes e IDs.
- GET /v1/market/facts/{id}: evidência e revisão de uma identificação.
- POST /v1/market/processes/{id}/extract, corpo {"reprocess":false}: enfileira/reutiliza.
- POST .../extract, corpo {"reprocess":true}: cria novo histórico, sem duplicar execução ativa.
- PATCH /v1/market/facts/{id}, corpo {"status":"validated","rationale":"Conferido na fonte"}: revisão auditável.

Autenticação Bearer e delegação seguem o contrato existente. O futuro aplicativo consome a API; o catálogo SQLite e seus backups incluem as novas tabelas market_jobs, market_facts e market_reviews. O JSON não é publicado automaticamente em uma pasta compartilhada. Não há IA generativa nem treinamento automático nesta implementação.

## Homologação

Testes com fontes sintéticas cobrem FCA + RAIPI, papéis distintos, CNPJ, contatos, HTML, página PDF, revisão humana, exportação, reprocessamento, histórico e revogação. A cobertura em documentos reais e a qualidade do OCR precisam ser verificadas com amostras representativas antes de uso comercial. A extração conservadora não é apresentada como leitura completa de todo conteúdo livre. SharePoint real, implantação e consumidores externos permanecem sujeitos à homologação da organização.
