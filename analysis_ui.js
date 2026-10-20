'use strict';
const analysisStatus={not_started:'Não iniciado',pending:'Pendente',in_progress:'Em análise',analyzed:'Analisado'};
titles.analysis='Processos analisados';
views.analysis=async root=>{
  root.append(node('p','Painel operacional que diferencia documentos coletados, extração concluída, classificação validada e conhecimento pendente. Nenhum processo é marcado como analisado por contador fictício.'));
  const data=await api('/v1/analysis/processes');
  const totals=data.totals||{};
  const metrics=node('div',undefined,'metrics');
  for(const [key,label] of [['processes','Processos acessíveis'],['analyzed','Analisados'],['in_progress','Em análise'],['pending','Pendentes'],['ocr_required','OCR necessário'],['knowledge_pending_review','Revisões pendentes']]){
    const box=node('div',undefined,'metric');box.append(node('strong',String(totals[key]??0)),node('span',label));metrics.append(box);
  }
  root.append(metrics);
  const filter=panel('Lista de processos');
  const selectFilter=select(filter,'Filtrar status','analysis-status',[['','Todos'],['analyzed','Analisados'],['in_progress','Em análise'],['pending','Pendentes'],['not_started','Não iniciados']]);
  const list=node('div');filter.append(list);
  const renderList=()=>{
    list.replaceChildren();
    const items=data.items.filter(item=>!selectFilter.value || item.status===selectFilter.value);
    if(!items.length){list.append(node('p','Nenhum processo corresponde ao filtro.','empty'));return}
    for(const item of items){
      const box=node('div',undefined,'item');
      const title=node('h3',item.folder||item.title);box.append(title,badge(analysisStatus[item.status]||item.status),node('small',`${item.number} · ${item.progress_percent}% do fluxo concluído`,'subtle'));
      box.append(node('p',`${item.documents} documento(s) · ${item.extracted_documents} extraído(s) · ${item.classified_documents} classificação(ões) validada(s) · ${item.evidence} evidência(s) · ${item.knowledge_validated} conhecimento validado(s).`));
      const pending=[];
      if(item.ocr_required) pending.push(`${item.ocr_required} aguardando OCR`);
      if(item.pending_classification) pending.push(`${item.pending_classification} aguardando classificação`);
      if(item.knowledge_pending_review) pending.push(`${item.knowledge_pending_review} aguardando revisão de conhecimento`);
      if(pending.length) box.append(node('p','Pendências: '+pending.join(' · '),'subtle'));
      box.append(button('Abrir documentos',async()=>{state.pid=item.process_id;state.document=null;await loadProcesses();await navigate('documents')},false),button('Abrir conhecimento',async()=>{state.pid=item.process_id;await loadProcesses();await navigate('knowledge')}));
      list.append(box);
    }
  };
  selectFilter.onchange=renderList;renderList();root.append(filter);
};
