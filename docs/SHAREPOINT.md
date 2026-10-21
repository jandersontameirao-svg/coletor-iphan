# Configurar o destino do acervo

O destino inicial é o link da pasta no site ATENA fornecido por Janderson. Ele está em `sharepoint_store.DEFAULT_FOLDER`, pode ser trocado pela interface e não foi acessado nesta construção.

## Preparação única pelo administrador Microsoft 365

1. Registrar um aplicativo de locatário único no Microsoft Entra ID.
2. Habilitar o fluxo de cliente público (device code).
3. Adicionar Microsoft Graph, permissão **delegada Files.ReadWrite**, e conceder consentimento conforme a política da organização. O protocolo também solicita `offline_access` para renovação. Não é necessário criar segredo de cliente neste fluxo.
4. Configurar `MICROSOFT_TENANT_ID` e `MICROSOFT_CLIENT_ID` no ambiente da API e do worker. Esses são identificadores, não senhas. Usar uma conta profissional autorizada para a biblioteca.
5. Na aba Configurações, confirmar o link e selecionar **Conectar com Microsoft**. A tela apresenta um código e o endereço oficial `microsoft.com/devicelogin`. A senha/MFA são informados apenas à Microsoft.
6. Selecionar **Testar leitura e gravação**. Essa ação cria um TXT com nome único, baixa seus bytes para conferir integridade e remove somente esse arquivo de teste. Só depois o destino é liberado para a fila.

O link identifica o destino; não concede autenticação. A permissão delegada permite acesso dentro dos direitos da conta e não é uma permissão OAuth restrita exclusivamente à pasta. O Coletor limita operacionalmente seu destino à pasta configurada. Concessão/revogação efetiva do SharePoint deve ser administrada na Microsoft; a ACL do catálogo não altera automaticamente as permissões da biblioteca. Links diretos respeitam as permissões do SharePoint. Para isolamento entre equipes, alinhar ACLs e permissões Microsoft antes da homologação.

## Execução em segundo plano

API e worker usam cache de tokens criptografado pelo Fernet. O refresh token permite renovação sem login a cada arquivo, enquanto a política Microsoft permitir. Revogação, MFA, Acesso Condicional ou expiração podem exigir reconexão; não há promessa de acesso permanente. O cache é compartilhado no banco e não é enviado ao navegador. A chave é `COLLECTOR_TOKEN_KEY` ou o arquivo local `data/token.key` (gerado com permissão 0600 no POSIX). Proteja esse volume no servidor.

Não registrar tokens, códigos de dispositivo, URLs pré-autorizadas de download nem corpos de resposta OAuth em logs. O cliente Graph não segue redirects com Bearer. A verificação dos bytes usa a URL pré-autorizada retornada pela própria Microsoft, sem enviar Bearer e somente em HTTPS/SharePoint.

## Organização física

```
01422.000120-2011-70/
  Georreferenciados/
  Documentos/
    PAPIPA/
    RAPIPA/
    PAIPA/
    RAIPA/
    PGPA/
    RAIPI/
    Educacao patrimonial/
    Outros documentos/
    A classificar/
```

Pastas são criadas sob demanda, quando há arquivos na categoria. RAIPI é uma categoria própria e não é agrupada com RAIPA/RAIPI por aproximação. Somente sigla explícita ou título administrativo inequívoco gera sugestão inicial; siglas conflitantes ficam em A classificar. Revisor humano pode corrigir e o histórico é preservado. ZIP de Shapefile é identificado por inventário, mantendo todos os componentes e o compactado original intactos. RAR/7z são preservados e, se o nome não identifica o tipo, ficam em A classificar: o Coletor não executa ferramentas externas para abri-los.

O nome remoto combina número SEI/título e ID integral da revisão para evitar colisões e sobrescritas. O filename original do servidor permanece no catálogo/ocorrência. Revisões A→B→A têm IDs distintos e histórico; há deduplicação física no cache por SHA-256. Cada revisão remota é preservada separadamente, pois faz parte do histórico documental. Aplicativos consumidores reutilizam suas referências e não precisam criar cópias próprias.

Após reclassificar um arquivo já enviado, a movimentação pode ser solicitada pela API `POST /v1/bridge/documents/{id}/move`; o worker move o mesmo item, verifica seus bytes e atualiza seu caminho. Não apaga o histórico da categoria anterior.

## Estado real da entrega

OAuth, resolução do link, criação de pastas, upload, conferência SHA-256 por releitura, renovação, desconexão, fila, retomada e movimentação têm código implementado. Os testes usam respostas controladas; login/MFA, consentimento, acesso ao destino real e escrita real precisam ser homologados pela organização. Não há segredo de cliente, usuário Microsoft, token ou sessão real no pacote.

Referências oficiais consultadas: [Device code](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code), [resolver link](https://learn.microsoft.com/en-us/graph/api/shares-get?view=graph-rest-1.0), [upload](https://learn.microsoft.com/en-us/graph/api/driveitem-put-content?view=graph-rest-1.0).
