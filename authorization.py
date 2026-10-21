"""Autorização de recurso. Administração da plataforma não ignora ACLs."""
import json
import time
from fastapi import HTTPException

PERMISSIONS={'read':{'read'},'operate':{'read','operate'},'review':{'read','review'},'admin':{'read','operate','review','admin'}}


def resolve(c,pid):
    row=c.execute('SELECT * FROM processes WHERE id=?',(pid,)).fetchone()
    if not row: raise HTTPException(404,'Processo não encontrado')
    if row['canonical_id']:
        row=c.execute('SELECT * FROM processes WHERE id=?',(row['canonical_id'],)).fetchone()
    return row


def allows_principal(c,pid,principal,permission):
    if not c.execute('SELECT id FROM users WHERE id=? AND active=1',(principal,)).fetchone(): return False
    rows=c.execute("SELECT role FROM resource_grants WHERE process_id=? AND active=1 AND ((subject_type='user' AND subject_id=?) OR (subject_type='group' AND subject_id IN (SELECT group_id FROM group_members WHERE user_id=? AND active=1)))",(pid,principal,principal)).fetchall()
    return any(permission in PERMISSIONS.get(r['role'],set()) for r in rows)


def delegation_valid(c,user,pid,permission):
    delegation=user.get('_delegation')
    if not delegation: return True
    row=c.execute('SELECT * FROM delegations WHERE id=? AND service_id=? AND user_id=? AND active=1 AND expires>?',(delegation,user['_actor_id'],user['id'],time.time())).fetchone()
    if not row or not c.execute('SELECT token FROM service_tokens WHERE user_id=? AND active=1 AND expires>? LIMIT 1',(user['_actor_id'],time.time())).fetchone(): return False
    scopes=json.loads(row['scopes'])
    return permission in scopes.get(pid,[]) and allows_principal(c,pid,user['_actor_id'],permission)


def process_access(c,pid,user,permission='read'):
    row=resolve(c,pid)
    if not allows_principal(c,row['id'],user['id'],permission) or not delegation_valid(c,user,row['id'],permission):
        # Esconde existência tanto para leitura quanto para operação.
        raise HTTPException(404,'Processo não encontrado ou sem permissão')
    return row


def job_authorized(c,job):
    row=c.execute('SELECT * FROM users WHERE id=? AND active=1',(job['owner'],)).fetchone()
    if not row: return False
    user=dict(row)
    if user['kind']=='service' and not c.execute('SELECT token FROM service_tokens WHERE user_id=? AND active=1 AND expires>? LIMIT 1',(user['id'],time.time())).fetchone(): return False
    if job.get('delegation_id'):
        user['_delegation']=job['delegation_id'];user['_actor_id']=job['actor_id']
    payload=json.loads(job['input'])
    try:
        if payload.get('operation')=='extract_revision':
            doc=c.execute('SELECT d.process_id FROM revisions r JOIN documents d ON d.id=r.document_id WHERE r.id=?',(payload['input']['revision_id'],)).fetchone()
            if not doc: return False
            process_access(c,doc['process_id'],user,'operate')
        else:
            pid=payload.get('input',{}).get('process_id')
            if pid: process_access(c,pid,user,'operate')
            elif user.get('_delegation'): return False
            for item in c.execute('SELECT DISTINCT process_id FROM link_items WHERE job_id=? AND process_id IS NOT NULL',(job['id'],)).fetchall():
                process_access(c,item['process_id'],user,'operate')
        return True
    except (HTTPException,KeyError): return False
