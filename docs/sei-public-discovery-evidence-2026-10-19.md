# Evidência de estrutura pública SEI/IPHAN — 19/10/2026

Uma página de processo fornecida pelo usuário em `sei.iphan.gov.br/sei/modulos/pesquisa/md_pesq_processo_exibir.php?...` retornou HTML público com cabeçalho de autuação, número do processo e tabela `tblDocumentos`. A página continha links por linha no padrão JavaScript `window.open('md_pesq_documento_consulta_externa.php?...')`. O parser implementado restringe a descoberta a esses dois endpoints e ao host `sei.iphan.gov.br`.

A mesma página trazia registros sem `window.open(...)`, sinalizados como acesso restrito. Eles serão registrados como pendência e não receberão nova requisição. A página exibiu CAPTCHA exclusivamente para a ação de gerar o PDF da página; o Coletor não aciona essa ação, não envia código de imagem e não contorna CAPTCHA.

Um teste de três URLs de documentos públicos extraídos da página retornou `200 application/pdf`, demonstrando que o endpoint de consulta externa pode expor arquivos PDF diretamente. O coletor ainda verifica tipo e bytes antes de guardar um original; uma resposta HTML, login, CAPTCHA, restrição, erro ou formato não suportado permanece individualmente pendente.

## Fontes

- Padrão da página pública de processo SEI/IPHAN fornecida pelo usuário: `https://sei.iphan.gov.br/sei/modulos/pesquisa/md_pesq_processo_exibir.php?<token-redigido>`.
- Serviço oficial SEI do IPHAN: https://www.gov.br/iphan/pt-br/servicos/sei
