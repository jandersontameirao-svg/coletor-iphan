# Fila, confirmação e recuperação — 0.3

API/worker compartilham SQLite e filesystem local (`COLLECTOR_DATA`). `python worker.py` faz polling com espera de um segundo; `--once` executa no máximo uma tarefa. `BEGIN IMMEDIATE` serializa aquisição; cada tentativa tem token e lease de 120 segundos. Heartbeat renova a cada até 20 segundos enquanto status, token, prazo e autorização continuam válidos. Falha ao comprovar validade interrompe a confirmação. Não há lock de processamento mantido durante rede/parser.

Antes de cada commit, o worker verifica o token atual e a autorização vigente, incluindo permissões de grupo, conta ativa e delegação/serviço quando aplicáveis. Dados/evidências, checkpoint, estado final e outbox são transacionais. Cancelamento invalida token; o supervisor interrompe o parser, e o downloader verifica validade entre operações/chunks. Uma chamada de socket já bloqueada pode aguardar seu timeout antes de observar cancelamento.

Lease expirado volta à fila quando outro worker tenta adquirir trabalho; tentativa antiga vira interrupted. No máximo três aquisições, incluindo recuperações/retomadas. Falhas internas agendam backoff de 2^tentativa segundos (máximo 60); esgotamento vira failed. Pendências externas não geram retries silenciosos ilimitados: requerem resolução/retomada explícita. Desativação/revogação cancela tarefas sem autorização.

Extrações são identificadas pela revisão/ferramenta/versão. Por padrão, pedidos assíncronos compartilham o job canônico, com mapeamento separado de cada Idempotency-Key. Execução concluída pode ser reutilizada sem duplicar evidências; reprocessamento explícito mantém novos runs. Recuperação usa novo token **e novo ExtractionRun**, deixando o anterior interrupted. O worker antigo não cancela o run do substituto. Runs de extração síncrona também usam reserva exclusiva e prazo, com parser isolado.

A extração interrompida reinicia sua unidade; não existe checkpoint dentro da página. Para links, cada documento/ocorrência/captura é confirmado com o item. Retomada pula itens downloaded/already_exists/manual_imported/duplicate. Links repetidos reutilizam o primeiro resultado sem nova requisição e não consomem novamente a quota. HTTP redirects são parte do mesmo link, não descoberta de novos processos.

`waiting_for_user` explica a ação necessária; itens podem ser corrigidos, associados a processo ou resolvidos por importação. Última importação manual pode concluir a tarefa sem novo acesso. Retomada de parcial de links repete somente itens solicitados. Parcial de extração por OCR indisponível não oferece retomada que simule OCR; o texto nativo já confirmado permanece acessível.

O SIGTERM/SIGINT do worker pede parada do loop; uma tarefa já iniciada pode terminar antes da saída. Confirme a saída de todos os processos antes de backup. Não há isolamento por containers, RPO/RTO medidos nem adapter PostgreSQL nesta entrega.

Eventos da outbox: collection.queued/started/recovered/retry_scheduled/completed/partial/failed/cancelled/resumed/waiting_for_user; collection.item.obtained/manual_imported/waiting_for_user/corrected; extraction.started/completed/needs_ocr; eventos de classificação e autorização. Outbox não possui transportador/consumidor/webhook operacional. Se houver futura entrega, deverá ser ao menos uma vez com consumidores idempotentes; não há promessa de exatamente uma vez.
