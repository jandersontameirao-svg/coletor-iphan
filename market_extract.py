"""Extração determinística e conservadora: campos explícitos, nunca instruções.

Papéis declarados são afirmações propostas. Coocorrência não comprova contrato.
"""
import re
import unicodedata

VERSION='explicit-fields-1.0'
ROLES={
 'empreendedor':('organization','empreendedor'), 'titular':('organization','titular'),
 'contratante':('organization','contratante_declarado'), 'cliente':('organization','cliente_declarado'),
 'cliente final':('organization','cliente_final_declarado'),
 'consultoria ambiental':('organization','consultoria_ambiental'),
 'consultoria arqueologica':('organization','consultoria_arqueologica'),
 'empresa executora':('organization','executora'), 'empresa responsavel':('organization','executora_declarada'),
 'empresa de consultoria':('organization','consultoria'), 'razao social':('organization','empresa_identificada'),
 'elaboracao':('unresolved','elaboracao_declarada'),
 'responsavel tecnico':('person','responsavel_tecnico'), 'responsavel tecnica':('person','responsavel_tecnico'),
 'coordenador':('person','coordenacao'), 'coordenadora':('person','coordenacao'),
 'coordenacao tecnica':('person','coordenacao_tecnica'), 'coordenador tecnico':('person','coordenacao_tecnica'),
 'arqueologo responsavel':('person','responsavel_arqueologia'),
 'representante legal':('person','representante_legal'), 'representante':('person','representante_declarado'),
 'autor':('person','autoria'), 'autora':('person','autoria'), 'autores':('person','autoria'),
 'equipe tecnica':('unresolved','equipe_declarada'),
}
CONTACTS={'email':'email','e-mail':'email','correio eletronico':'email','telefone':'phone','fone':'phone','tel':'phone','contato':'contact'}
def norm(text):
    return ' '.join(unicodedata.normalize('NFKD',text).encode('ascii','ignore').decode().lower().split())

def cnpj_digits(value):
    digits=re.sub(r'\D','',value)
    if len(digits)!=14 or len(set(digits))==1:return None
    def check(part,weights):
        r=sum(int(a)*b for a,b in zip(part,weights))%11
        return '0' if r<2 else str(11-r)
    a=check(digits[:12],[5,4,3,2,9,8,7,6,5,4,3,2])
    b=check(digits[:12]+a,[6,5,4,3,2,9,8,7,6,5,4,3,2])
    return digits if digits[-2:]==a+b else None

def family(name,category):
    if category in ('PAPIPA','RAPIPA','PAIPA','RAIPA','PGPA','RAIPI','Educacao patrimonial'):return 'technical'
    text=norm(name)
    if re.search(r'\b(papipa|rapipa|paipa|raipa|pgpa|raipi)\b',text.replace('_',' ')):return 'technical'
    if re.search(r'\b(fca|oficio|requerimento|despacho|parecer|portaria)\b',text.replace('_',' ')):return 'administrative'
    return 'unclassified'

def extract(pages):
    result=[];seen=set()
    for page,text in pages:
        lines=text.splitlines();subject=None;subject_line=-99
        for i,line in enumerate(lines):
            match=re.match(r'^\s*([\wÀ-ÿ .()/-]{2,65})\s*[:\u2013\u2014-]\s*(.*?)\s*$',line)
            if match:label,value=match.groups();key=norm(label).strip(' .')
            elif norm(line).strip(' .') in ROLES:label=line.strip();value='';key=norm(label).strip(' .')
            else:continue
            # Títulos de seção sem valor: aceitar somente a próxima linha não rotulada.
            end=i
            if not value and i+1<len(lines) and not re.match(r'^.{2,65}:',lines[i+1]):value=lines[i+1].strip();end=i+1
            if not value or len(value)>500:continue
            if key in ROLES:
                kind,role=ROLES[key]
                name=re.split(r'\s*(?:[;|]|\bCNPJ\s*:?)',value,flags=re.I)[0].strip(' -.,')
                if len(name)<3:continue
                nearby=lines[i:end+1]
                for following in lines[end+1:end+3]:
                    if re.match(r'^\s*(?:cnpj)\s*:',following,re.I):nearby.append(following)
                    else:break
                block='\n'.join(nearby)
                ids=re.findall(r'\b(?:\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|\d{14})\b',block)
                valid=next((cnpj_digits(x) for x in ids if cnpj_digits(x)),None) if kind=='organization' else None
                subject={'kind':kind,'name':name,'role':role,'cnpj':valid,'identifier_candidate':ids[0] if ids and not valid else None}
                subject_line=i
                fact={**subject,'field':'participation','value':name,'label':label,'page':page,'line_start':i+1,'line_end':max(end+1,i+len(nearby)),'quote': '\n'.join(lines[i:max(end+1,i+len(nearby))])[:2000],'association':'explicit_field'}
            elif key in CONTACTS:
                emails=re.findall(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',value)
                phones=re.findall(r'(?:\+55\s*)?(?:\(?\d{2}\)?[ .-]*)?\d{4,5}[ .-]?\d{4}\b',value)
                values=[('email',x) for x in emails]+[('phone',x) for x in phones]
                for field,contact in values:
                    linked=subject if subject and i-subject_line<=5 else None
                    fact={**(linked or {'kind':'unresolved','name':'Contato sem titular explicitamente identificado','role':'unassigned','cnpj':None,'identifier_candidate':None}),'field':field,'value':contact,'label':label,'page':page,'line_start':i+1,'line_end':i+1,'quote':'\n'.join(lines[max(0,subject_line if linked else i):i+1])[:2000],'association':'nearby_field_candidate' if linked else 'unassigned'}
                    token=(page,i,field,contact)
                    if token not in seen:seen.add(token);result.append(fact)
                continue
            else:
                # Outro campo titular impede herdar contatos através de blocos ambíguos.
                if key not in ('cnpj','endereco','cargo','crea','registro profissional'):subject=None
                continue
            token=(page,i,fact['role'],fact['value'])
            if token not in seen:seen.add(token);result.append(fact)
            if len(result)>=5000:raise ValueError('Limite de 5.000 identificações por documento')
    return result

def cross_reference(facts):
    groups={}
    for f in facts:
        if f['review_status']=='rejected' or not f['is_current']:continue
        if f['field']!='participation':continue
        key=('cnpj:'+f['cnpj']) if f['cnpj'] else f['kind']+':name:'+norm(f['name'])
        group=groups.setdefault(key,{'key':key,'identity_basis':'valid_cnpj' if f['cnpj'] else 'name_only_candidate','names':set(),'roles':set(),'families':set(),'documents':set(),'evidence_ids':[],'cnpj':f['cnpj']})
        group['names'].add(f['name']);group['roles'].add(f['role']);group['families'].add(f['family']);group['documents'].add(f['document_id']);group['evidence_ids'].append(f['id'])
    result=[]
    for g in groups.values():
        result.append({**g,'names':sorted(g['names']),'roles':sorted(g['roles']),'families':sorted(g['families']),'documents':sorted(g['documents']),'crosses_administrative_technical':{'administrative','technical'}<=g['families'],'relationship_status':'documented_participation_only','notice':'Coocorrência e papéis declarados não comprovam contrato nem cliente final.'})
    return result
