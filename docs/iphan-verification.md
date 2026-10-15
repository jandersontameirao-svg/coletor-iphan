# Verificação externa real — 15/10/2026

Acesso real é registrado separadamente dos testes de transporte mockado. Não foi feita busca automática, submissão de formulário de pesquisa, login nem contorno de CAPTCHA. O link verificado é o endereço institucional de pesquisa pública identificado no histórico 0.2.

| Tentativa | Resultado |
|---|---|
| 2026-10-15 00:32:52 UTC, https://sei.iphan.gov.br/pesquisapublica | Fetch protegido recebeu página HTML com indicadores classificados como access_barrier. Nenhum documento obtido. |
| 2026-10-15 00:43:21 UTC, mesmo link | Resolução DNS excedeu o novo prazo de 5 segundos; dns_timeout. Nenhum documento obtido. |

A classificação de barreira é heurística; a página poderia conter indicadores de login/CAPTCHA e também partes públicas. Não se conclui que todo SEI seja restrito ou que não exista mecanismo de consulta. O timeout posterior também não demonstra indisponibilidade para outros ambientes. Os resultados variaram por tentativa; não substituem homologação de um processo e seus anexos.

Dados JSON em `external-verification-history-v0.3.json`; última tentativa em `external-verification-v0.3.json`. Em 14/10, os registros 0.2 mostravam portal e página institucional SEI HTTP 200, HTTPS da pesquisa 503 pelo proxy e HTTP em timeout. Essa evidência histórica não foi transformada em resultado atual.

**Caminho implementado:** links explícitos de PDF/texto UTF-8 direto, com proteção de destino/redirect e armazenamento autorizado. **Homologação IPHAN positiva:** pendente. Faltam um link autorizado de documento/processo efetivamente acessível e demonstração real de obtenção/versão/origem. Links para páginas recebem pendência e alternativa manual, sem inventar descoberta automática de anexos. ATENA OS real não foi acessada.

Reprodução: `python scripts/verify_external.py --url <link autorizado>`. O script não persiste acervo e não pesquisa o portal. Não trocar bloqueio por fixture e chamar isso de homologação.
