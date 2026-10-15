# TODO — Publicação demonstrativa do Coletor IPHAN 0.4

- [ ] Publicar uma cópia isolada da versão 0.4 validada, sem alterar a versão 0.3 nem a prévia local existente.
- [x] Expor a interface FastAPI em container Python 3.12, atendendo `PORT` e `/_app/health` sem autenticação.
- [x] Oferecer acesso público de demonstração somente para leitura, com dados sintéticos de processo, documento, evidência, conhecimento e geografia.
- [x] Não incluir dados reais, banco local, blobs reais, contas operacionais, tokens ou senhas no checkpoint ou na imagem.
- [ ] Preservar as limitações reais: SQLite efêmero, ausência de worker, OCR/integrações externas não homologados e sem uso operacional de coleta externa.
- [x] Validar preview, health check, login demonstrativo, consulta de conhecimento, consulta espacial e bloqueio de escrita antes da publicação.
- [ ] Registrar checkpoint no repositório Manus e publicar a versão confirmada.
