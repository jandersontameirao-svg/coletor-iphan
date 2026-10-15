"""API de concessões, grupos, serviços, delegação e revisão de duplicatas."""
import hashlib
import json
import secrets
import time
from typing import Literal
from pydantic import BaseModel, Field
from fastapi import Depends, HTTPException
import authorization
import repository_migration

class Grant(BaseModel):
    subject_type: Literal['user','group']
    subject_id: str
    role: Literal['read','operate','review','admin']
class Named(BaseModel):
    name: str = Field(min_length=1,max_length=150)
class Member(BaseModel):
    user_id: str
    active: bool = True
class Delegation(BaseModel):
    service_id: str
    scopes: dict[str,list[Literal['read','operate','review','admin']]]
    lifetime_seconds: int = Field(default=3600,ge=60,le=28800)
class Merge(BaseModel):
    canonical_id: str
    source_ids: list[str] = Field(min_length=1,max_length=100)
    acknowledge_permission_union: Literal[True]


def register(app,db,event,identity,platform_admin,uid,password_hash):
    def invalidate(c,actor):
        for row in c.execute("SELECT * FROM jobs WHERE status IN ('queued','running','waiting_for_user','paused')").fetchall():
            if not authorization.job_authorized(c,dict(row)):
                c.execute("UPDATE jobs SET status='cancelled',lease_token=NULL,lease_until=NULL,detail='Autorização revogada' WHERE id=?",(row['id'],))
                c.execute("UPDATE job_attempts SET status='cancelled',finished=? WHERE job_id=? AND status='running'",(time.time(),row['id']))
                c.execute("UPDATE extraction_runs SET state='cancelled',finished=? WHERE job_id=? AND state='running'",(time.time(),row['id']))
                event(c,actor,'collection.authorization_revoked',row['id'])

    @app.get('/v1/processes/{pid}/permissions')
    def grants(pid: str,user=Depends(identity)):
        with db() as c:
            pid=authorization.process_access(c,pid,user,'admin')['id']
            return [dict(r) for r in c.execute('SELECT * FROM resource_grants WHERE process_id=?',(pid,))]

    @app.post('/v1/processes/{pid}/permissions',status_code=201)
    def grant(pid: str,body: Grant,user=Depends(identity)):
        with db() as c:
            c.execute('BEGIN IMMEDIATE');pid=authorization.process_access(c,pid,user,'admin')['id']
            table='users' if body.subject_type=='user' else 'groups'
            if not c.execute(f'SELECT id FROM {table} WHERE id=?',(body.subject_id,)).fetchone(): raise HTTPException(404,'Sujeito não encontrado')
            old=c.execute('SELECT id FROM resource_grants WHERE process_id=? AND subject_type=? AND subject_id=? AND role=?',(pid,body.subject_type,body.subject_id,body.role)).fetchone()
            gid=old['id'] if old else uid()
            if old: c.execute('UPDATE resource_grants SET active=1 WHERE id=?',(gid,))
            else: c.execute('INSERT INTO resource_grants VALUES(?,?,?,?,?,?,?)',(gid,pid,body.subject_type,body.subject_id,body.role,1,time.time()))
            event(c,user.get('_actor_id',user['id']),'permission.granted',gid)
            return {'id':gid}

    @app.delete('/v1/processes/{pid}/permissions/{grant_id}',status_code=204)
    def revoke(pid: str,grant_id: str,user=Depends(identity)):
        with db() as c:
            c.execute('BEGIN IMMEDIATE');pid=authorization.process_access(c,pid,user,'admin')['id']
            row=c.execute('SELECT * FROM resource_grants WHERE id=? AND process_id=?',(grant_id,pid)).fetchone()
            if not row: raise HTTPException(404)
            if row['subject_type']=='user' and row['subject_id']==user['id'] and row['role']=='admin': raise HTTPException(409,'Não revogue sua própria administração')
            c.execute('UPDATE resource_grants SET active=0 WHERE id=?',(grant_id,));event(c,user.get('_actor_id',user['id']),'permission.revoked',grant_id)
            invalidate(c,user['id'])

    @app.get('/v1/groups')
    def groups(user=Depends(identity)):
        platform_admin(user)
        with db() as c: return [dict(r) for r in c.execute('SELECT * FROM groups')]

    @app.post('/v1/groups',status_code=201)
    def group(body: Named,user=Depends(identity)):
        platform_admin(user);gid=uid()
        with db() as c:
            try: c.execute('INSERT INTO groups VALUES(?,?)',(gid,body.name))
            except Exception: raise HTTPException(409,'Grupo já existente')
            event(c,user['id'],'group.created',gid)
        return {'id':gid}

    @app.put('/v1/groups/{gid}/members')
    def member(gid: str,body: Member,user=Depends(identity)):
        platform_admin(user)
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT id FROM groups WHERE id=?',(gid,)).fetchone() or not c.execute('SELECT id FROM users WHERE id=?',(body.user_id,)).fetchone(): raise HTTPException(404)
            c.execute('INSERT INTO group_members VALUES(?,?,?) ON CONFLICT(group_id,user_id) DO UPDATE SET active=excluded.active',(gid,body.user_id,int(body.active)))
            event(c,user['id'],'group.member.granted' if body.active else 'group.member.revoked',gid+':'+body.user_id)
            invalidate(c,user['id'])
        return {'active':body.active}

    @app.get('/v1/service-accounts')
    def services(user=Depends(identity)):
        platform_admin(user)
        with db() as c: return [dict(r) for r in c.execute("SELECT id,name,active FROM users WHERE kind='service'")]

    @app.post('/v1/service-accounts',status_code=201)
    def service(body: Named,user=Depends(identity)):
        platform_admin(user);sid=uid();token=secrets.token_urlsafe(40)
        with db() as c:
            try: c.execute("INSERT INTO users(id,name,password,role,kind) VALUES(?,?,?,'operator','service')",(sid,body.name,''))
            except Exception: raise HTTPException(409,'Nome já existente')
            c.execute('INSERT INTO service_tokens VALUES(?,?,?,1)',(hashlib.sha256(token.encode()).hexdigest(),sid,time.time()+86400*30))
            event(c,user['id'],'service.created',sid)
        return {'id':sid,'access_token':token,'expires_in':86400*30,'notice':'Token exibido somente nesta resposta; armazene em cofre'}

    @app.post('/v1/service-accounts/{sid}/revoke',status_code=204)
    def revoke_service(sid: str,user=Depends(identity)):
        platform_admin(user)
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute("SELECT id FROM users WHERE id=? AND kind='service'",(sid,)).fetchone(): raise HTTPException(404)
            c.execute('UPDATE service_tokens SET active=0 WHERE user_id=?',(sid,))
            c.execute('UPDATE users SET active=0 WHERE id=?',(sid,))
            c.execute('UPDATE delegations SET active=0 WHERE service_id=?',(sid,))
            event(c,user['id'],'service.revoked',sid);invalidate(c,user['id'])

    @app.post('/v1/delegations',status_code=201)
    def delegate(body: Delegation,user=Depends(identity)):
        if user.get('kind','human')!='human' or user.get('_delegation'): raise HTTPException(403,'Delegação deve ser emitida pelo usuário humano')
        if not body.scopes or len(body.scopes)>100: raise HTTPException(422,'Escopo entre 1 e 100 processos')
        did=uid();scopes={}
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute("SELECT id FROM users WHERE id=? AND kind='service' AND active=1",(body.service_id,)).fetchone(): raise HTTPException(404)
            for pid,permissions in body.scopes.items():
                pid=authorization.process_access(c,pid,user)['id']
                if not permissions: raise HTTPException(422,'Escopo vazio')
                for permission in permissions:
                    authorization.process_access(c,pid,user,permission)
                    if not authorization.allows_principal(c,pid,body.service_id,permission): raise HTTPException(403,'Serviço não possui o escopo solicitado')
                scopes[pid]=sorted(set(permissions))
            c.execute('INSERT INTO delegations VALUES(?,?,?,?,?,?,?)',(did,body.service_id,user['id'],json.dumps(scopes),time.time()+body.lifetime_seconds,1,time.time()))
            event(c,user['id'],'delegation.granted',did)
        return {'id':did,'header':'X-Delegation-Id','scopes':scopes,'expires_in':body.lifetime_seconds}

    @app.delete('/v1/delegations/{did}',status_code=204)
    def revoke_delegation(did: str,user=Depends(identity)):
        if user.get('_delegation') or user.get('kind','human')!='human': raise HTTPException(403)
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT id FROM delegations WHERE id=? AND user_id=?',(did,user['id'])).fetchone(): raise HTTPException(404)
            c.execute('UPDATE delegations SET active=0 WHERE id=?',(did,));event(c,user['id'],'delegation.revoked',did);invalidate(c,user['id'])

    @app.get('/v1/migrations/duplicates')
    def duplicates(user=Depends(identity)):
        platform_admin(user)
        with db() as c: return repository_migration.duplicate_plan(c)

    @app.post('/v1/migrations/merge')
    def merge(body: Merge,user=Depends(identity)):
        platform_admin(user)
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            try: return repository_migration.merge(c,event,user['id'],body.canonical_id,body.source_ids)
            except ValueError as exc: raise HTTPException(409,str(exc))
