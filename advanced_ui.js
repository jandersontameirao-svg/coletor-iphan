'use strict';
/* Extensão 0.4: usa os mesmos helpers, sessão e ACL da interface 0.3. */
const advancedTitles={knowledge:'Conhecimento',spatial:'Pesquisa espacial'};
titles.knowledge=advancedTitles.knowledge;
titles.spatial=advancedTitles.spatial;

function advancedSelect(formEl,label,name,choices){return select(formEl,label,name,choices)}

views.knowledge=async root=>{
  root.append(node('p','Afirmações somente entram no conhecimento quando estão vinculadas a uma revisão e a uma evidência autorizada. Nenhum fato é criado automaticamente.'));
  if(!state.pid){root.append(node('p','Selecione um processo para consultar e registrar afirmações.','empty'));return}
  const list=panel('Afirmações do processo');
  const data=await api('/v1/knowledge/assertions?process_id='+encodeURIComponent(state.pid));
  if(!data.length) list.append(node('p','Nenhuma afirmação registrada para este processo.','empty'));
  for(const item of data){
    const box=node('div',undefined,'item');
    box.append(node('h3',item.statement),badge(item.status),node('small',`${item.kind} · evidência ${item.evidence_id}`,'subtle'));
    if(item.rationale) box.append(node('p',item.rationale));
    const actions=node('div',undefined,'actions');
    actions.append(button('Abrir evidência',async()=>detail('Evidência vinculada',await api('/v1/evidence/'+item.evidence_id))));
    if(can('review')) for(const [status,label] of [['validated','Validar'],['rejected','Rejeitar'],['conflict','Marcar conflito']]) actions.append(button(label,async()=>{await api('/v1/knowledge/assertions/'+item.id,'PATCH',{status,rationale:'Revisão humana registrada na interface'});await navigate('knowledge')}));
    box.append(actions);list.append(box);
  }
  root.append(list);
  const create=panel('Registrar afirmação rastreável');
  const f=form(create,'Registrar como proposta',async data=>{await api('/v1/knowledge/assertions','POST',{process_id:state.pid,...Object.fromEntries(data)});notify('Afirmação proposta com evidência vinculada');await navigate('knowledge')});
  field(f.f,'ID da evidência','evidence_id');
  field(f.f,'Afirmação','statement','textarea');
  advancedSelect(f.f,'Tipo','kind',[['fact','Fato transcrito'],['interpretation','Interpretação'],['transcription','Transcrição'],['inference','Inferência pendente'],['bibliography','Referência bibliográfica']]);
  field(f.f,'Confiança opcional · 0 a 1','confidence','number','',false).step='0.01';
  f.finish();root.append(create);
};

views.spatial=async root=>{
  root.append(node('p','Importe KML/KMZ, Shapefile ZIP, GeoJSON/JSON ou GPX para criar uma revisão geográfica versionada. As consultas usam WGS84 e distância geodésica em metros; graus nunca são tratados como metros. PDF continua sendo importado como documento do processo.'));
  if(!state.pid){root.append(node('p','Selecione um processo para importar e consultar recursos espaciais.','empty'));return}
  const resources=await api('/v1/spatial-resources?process_id='+encodeURIComponent(state.pid));
  const list=panel('Recursos espaciais');
  if(!resources.length) list.append(node('p','Nenhum recurso geográfico registrado.','empty'));
  for(const r of resources){const row=node('div',undefined,'item');row.append(node('h3',r.name),node('small',`${r.source_filename} · ${r.feature_count} feições · versão ${r.version}`,'subtle'),button('Abrir recurso',async()=>detail('Recurso espacial',await api('/v1/spatial-resources/'+r.id))));list.append(row)}
  root.append(list);
  if(can('operate')){
    const imp=panel('Importar recurso geográfico');
    const f=form(imp,'Importar recurso',async data=>{const file=data.get('file');await api(`/v1/spatial-resources?process_id=${encodeURIComponent(state.pid)}&name=${encodeURIComponent(data.get('name')||file.name)}&filename=${encodeURIComponent(file.name)}`,'POST',file);notify('Recurso espacial importado como revisão 1');await navigate('spatial')});
    field(f.f,'Nome do recurso','name');field(f.f,'Arquivo KML, KMZ, Shapefile ZIP, GeoJSON, JSON ou GPX','file','file').accept='.kml,.kmz,.zip,.shp,.geojson,.json,.gpx';f.finish();root.append(imp);
  }
  const query=panel('Consultar por ponto e entorno');
  const q=form(query,'Pesquisar feições',async data=>{const result=await api('/v1/spatial-search','POST',{process_id:state.pid,latitude:Number(data.get('latitude')),longitude:Number(data.get('longitude')),radius_m:Number(data.get('radius_m')||0)});detail('Resultados espaciais',result)});
  field(q.f,'Latitude','latitude','number');field(q.f,'Longitude','longitude','number');field(q.f,'Entorno em metros','radius_m','number','0');q.finish();root.append(query);
};

views.integrations=async root=>{
  const data=await api('/v1/integration/capabilities');
  const contract=panel('Contratos do Coletor IPHAN');
  contract.append(node('p','A API recebe links explícitos de documentos e páginas públicas SEI fornecidas, preservando autenticação, Idempotency-Key, ACL e fila persistente. Consumidores devem reutilizar IDs de processo, revisão, evidência e recurso espacial.'));
  contract.append(node('p',`Versão do contrato: ${data.version} · cliente externo homologado: não · Geoportal real homologado: não.`));
  const link=node('a','Abrir contrato OpenAPI');link.href='/openapi.json';link.target='_blank';link.rel='noopener';contract.append(link);
  root.append(contract);
  const available=panel('Capacidades do escopo 0.7');
  for(const text of ['Afirmações vinculadas a evidência: disponível','Validação humana e conflitos: disponível','Importação KML/KMZ, Shapefile, GeoJSON/JSON e GPX em WGS84: disponível','Importação de PDF, TXT, CSV, DOCX e XLSX: disponível','OCR de PDF digitalizado: condicional ao motor instalado','Consulta por entorno em metros: disponível','Descoberta em páginas públicas SEI fornecidas: disponível','Pesquisa por número, login e CAPTCHA: não disponível','Homologação externa IPHAN/ATENA/Geoportal: pendente']) available.append(node('p',text));
  root.append(available);
};

const legacyOverviewV04=views.overview;
views.overview=async root=>{
  await legacyOverviewV04(root);
  try{
    const data=await api('/v1/overview/advanced');
    const p=panel('Capacidades implementadas no escopo 0.7');
    p.append(node('p',`${data.knowledge_assertions} afirmações rastreáveis · ${data.spatial_resources} recursos espaciais · ${data.spatial_revisions} revisões geográficas.`));
    p.append(button('Conhecimento',()=>navigate('knowledge'),false),button('Pesquisa espacial',()=>navigate('spatial')));
    root.append(p);
  }catch(_){/* compatibilidade com uma base antiga durante migração */}
};
