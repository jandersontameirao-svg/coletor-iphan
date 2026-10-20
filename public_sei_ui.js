'use strict';

statuses.process_discovered='Processo lido';
const advancedIntegrationView=views.integrations;

function seiInputLines(value){
  const lines=String(value||'').split(/\r?\n/).map(line=>line.trim()).filter(Boolean);
  const urls=[];
  const ignored=[];
  for(const line of lines){
    if(/^https:\/\//i.test(line)) urls.push(line);else ignored.push(line);
  }
  return {urls:[...new Set(urls)],ignored};
}

function batches(values,size=50){
  const result=[];
  for(let index=0;index<values.length;index+=size) result.push(values.slice(index,index+size));
  return result;
}

function publicSeiMetadata(item){
  try{return JSON.parse(item.metadata||'{}')}catch{return {}}
}

views.links=async root=>{
  root.append(node('p','Informe links diretos PDF/TXT ou páginas públicas de processo do SEI/IPHAN, um por linha. Para páginas SEI fornecidas, o Coletor identifica somente os documentos que a própria página expõe publicamente.'));
  const panelLinks=panel('Links e páginas de processo fornecidos');
  const setup=form(panelLinks,'Receber e iniciar coleta',async data=>{
    const parsed=seiInputLines(data.get('urls'));
    if(!parsed.urls.length) throw Error('Informe ao menos uma URL HTTPS');
    if(parsed.urls.length>250) throw Error('Informe no máximo 250 URLs por envio; divida a lista para preservar os limites de coleta');
    const inputBase={};
    if(state.pid&&data.get('associate')){
      if(!can('operate')) throw Error('Você não possui operação no processo selecionado');
      inputBase.process_id=state.pid;
    }
    const jobIds=[];
    for(const group of batches(parsed.urls)){
      const result=await api('/v1/collection-jobs','POST',{source:'iphan',operation:'collect_links',input:{...inputBase,urls:group},request_context:{application:'collector-ui',mode:'public-sei-discovery'}},{'Idempotency-Key':crypto.randomUUID()});
      jobIds.push(result.job_id);
    }
    const ignored=parsed.ignored.length?` ${parsed.ignored.length} linha(s) que não eram URL HTTPS foram ignoradas.`:'';
    notify(`${parsed.urls.length} URL(s) recebidas em ${jobIds.length} tarefa(s).${ignored}`);
    state.tab='tasks';
    await navigate('tasks');
    await showJob(jobIds[0]);
  });
  const textarea=field(setup.f,'URLs · páginas públicas SEI ou documentos diretos','urls','textarea');
  textarea.placeholder='https://sei.iphan.gov.br/sei/modulos/pesquisa/md_pesq_processo_exibir.php?...\nhttps://…/documento.pdf\nLink do Processo\nnão foi encontrado';
  textarea.maxLength=200000;
  const label=node('label');
  const check=node('input');
  check.type='checkbox';
  check.name='associate';
  check.checked=false;
  label.append(check,document.createTextNode('Associar ao processo selecionado — somente para documentos diretos do mesmo processo'));
  setup.f.append(label);
  setup.finish();
  panelLinks.append(node('p','Listas maiores são separadas automaticamente em tarefas de até 50 URLs. Páginas SEI registram número, título e cada documento listado. Registros sem link público ficam pendentes; o Coletor não pesquisa processos por número, não faz login e não resolve CAPTCHA.'));
  root.append(panelLinks);
};

showJob=async function(jid){
  const job=await api('/v1/collection-jobs/'+jid);
  let host=$('job-detail');
  if(!host){await navigate('tasks');host=$('job-detail')}
  host.replaceChildren();
  const panelResult=panel('Resultados da tarefa');
  const actions=node('div',undefined,'actions');
  const input=JSON.parse(job.input).input||{};
  if(['queued','running','waiting_for_user','partial','paused'].includes(job.status)) actions.append(button('Cancelar',async()=>{await api('/v1/collection-jobs/'+jid+'/cancel','POST');await showJob(jid)},true,jobOperate(job)));
  if(['waiting_for_user','partial','cancelled','paused'].includes(job.status)&&!(job.status==='partial'&&JSON.parse(job.input).operation==='extract_revision')) actions.append(button('Retomar pendências',async()=>{const body={retry_pending:true};if(!input.process_id&&state.pid)body.process_id=state.pid;await api('/v1/collection-jobs/'+jid+'/resume','POST',body);notify('Retomada solicitada; resultados confirmados serão preservados');await showJob(jid)},false,jobOperate(job)));
  panelResult.append(badge(job.status),node('p',job.detail),actions);
  const checkpoint=JSON.parse(job.checkpoint);
  for(const evidence of checkpoint.result?.evidence||[]) panelResult.append(button('Evidência '+(evidence.page??'texto'),async()=>detail('Evidência',await api('/v1/evidence/'+evidence.id))));
  const items=await api('/v1/collection-jobs/'+jid+'/links');
  for(const item of items){
    const meta=publicSeiMetadata(item);
    const box=node('div',undefined,'item');
    const title=item.display_name||(item.kind==='sei_process_page'?'Página pública de processo SEI':item.url);
    box.append(node('h3',title),badge(item.status));
    if(item.kind==='sei_process_page'&&meta.number) box.append(node('small',`Processo declarado: ${meta.number}`,'subtle'));
    if(item.kind==='sei_document'){
      const details=[meta.date&&`data: ${meta.date}`,meta.unit&&`unidade: ${meta.unit}`,meta.access==='restricted'?'sem link público':'link público identificado'].filter(Boolean).join(' · ');
      if(details) box.append(node('small',details,'subtle'));
    }
    box.append(node('div',item.url,'url'),node('p',item.detail));
    if(item.revision_id){
      box.append(button('Baixar original',()=>download(item.revision_id,'documento')),button('Histórico de extração',async()=>detail('Extrações',await api('/v1/document-revisions/'+item.revision_id+'/extractions'))),button('Extrair via worker',async()=>{await startExtraction(item.revision_id);notify('Extração solicitada; acompanhe nas tarefas')},true,jobOperate(job)));
    }else if(['waiting_for_user','partial','cancelled'].includes(job.status)&&jobOperate(job)&&item.kind!=='sei_process_page'){
      if(item.kind!=='sei_document'||meta.access!=='restricted'){
        const correction=form(box,'Salvar correção do link',async data=>{await api(`/v1/collection-jobs/${jid}/links/${item.id}`,'PATCH',{url:data.get('url')});await showJob(jid)});
        field(correction.f,'Corrigir URL','url','url',item.url);
        correction.finish();
      }
      if(item.process_id){
        const manual=form(box,'Resolver por importação manual',async data=>{const file=data.get('file');await api(`/v1/collection-jobs/${jid}/links/${item.id}/import?name=${encodeURIComponent(file.name)}`,'POST',file);notify('Original importado com referência ao link');await showJob(jid)});
        field(manual.f,'Documento autorizado · PDF ou TXT','file','file').accept='.pdf,.txt';
        manual.finish();
      }
    }
    panelResult.append(box);
  }
  host.append(panelResult);
  host.scrollIntoView({behavior:'smooth',block:'start'});
};

views.integrations=async root=>{
  await advancedIntegrationView(root);
  const contract=panel('Descoberta pública SEI/IPHAN');
  contract.append(node('p','A interface e as contas de serviço usam a mesma API e fila. A identidade vem da autenticação; um ID no corpo não concede acesso.'));
  const pre=node('pre',JSON.stringify({source:'iphan',operation:'collect_links',input:{urls:['https://sei.iphan.gov.br/sei/modulos/pesquisa/md_pesq_processo_exibir.php?...'],process_id:'<opcional, somente se for o mesmo processo autorizado>'},request_context:{application:'atena-master'}},null,2));
  contract.append(pre,node('p','Envie Idempotency-Key. A resposta 202 não confirma obtenção. Cada página pública SEI fornecida é lida somente uma vez para identificar os documentos que ela já expõe; não há pesquisa por número, login ou CAPTCHA.'));
  const link=node('a','Abrir contrato OpenAPI');link.href='/openapi.json';link.target='_blank';link.rel='noopener';contract.append(link);root.append(contract);
  const capabilities=panel('Capacidades de descoberta pública');
  for(const name of ['Entrada por link/lista','Leitura de páginas públicas SEI fornecidas','Descoberta de links públicos de documentos SEI','Download direto de PDF/TXT público','Importação manual','Extração nativa isolada','Biblioteca por classificação revisada']) capabilities.append(node('p',name+' · disponível'));
  capabilities.append(node('p','Páginas e documentos restritos permanecem como pendência. Não há pesquisa por número, autenticação, resolução de CAPTCHA ou homologação institucional com IPHAN.'));
  root.append(capabilities);
};
