"""Fila SQLite persistente, leases com fencing e entrega ao menos uma vez."""
import json
import time
import uuid
import authorization

MAX_ATTEMPTS = 3
LEASE_SECONDS = 120


def migrate(db):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        columns={r['name'] for r in c.execute('PRAGMA table_info(jobs)')}
        for name,kind in [('lease_token','TEXT'),('lease_until','REAL'),('attempt_count','INTEGER NOT NULL DEFAULT 0'),('available_at','REAL NOT NULL DEFAULT 0')]:
            if name not in columns: c.execute(f'ALTER TABLE jobs ADD COLUMN {name} {kind}')
        c.execute('CREATE TABLE IF NOT EXISTS job_attempts(id TEXT PRIMARY KEY,job_id TEXT REFERENCES jobs(id),number INTEGER,worker TEXT,started REAL,finished REAL,status TEXT,error TEXT,UNIQUE(job_id,number))')
        c.execute('CREATE INDEX IF NOT EXISTS jobs_ready ON jobs(status,available_at,lease_until)')
        c.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,applied REAL)')
        c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(2,?)',(time.time(),))


def claim(db,event,worker,now=None):
    now=time.time() if now is None else now
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        stale=c.execute("SELECT * FROM jobs WHERE status='running' AND lease_until<=?",(now,)).fetchall()
        for row in stale:
            exhausted=row['attempt_count']>=MAX_ATTEMPTS
            state='failed' if exhausted else 'queued'
            c.execute('UPDATE jobs SET status=?,lease_token=NULL,lease_until=NULL,detail=? WHERE id=?',(state,'Lease expirado; limite de tentativas atingido' if exhausted else 'Worker interrompido; tarefa recuperada',row['id']))
            c.execute("UPDATE job_attempts SET status='interrupted',finished=?,error='Lease expirado' WHERE job_id=? AND status='running'",(now,row['id']))
            event(c,row['owner'],'collection.'+('failed' if exhausted else 'recovered'),row['id'])
        for pending in c.execute("SELECT * FROM jobs WHERE status='queued'").fetchall():
            if not authorization.job_authorized(c,dict(pending)):
                c.execute("UPDATE jobs SET status='cancelled',detail='Autorização revogada' WHERE id=?",(pending['id'],))
                event(c,pending['owner'],'collection.authorization_revoked',pending['id'])
        row=c.execute("SELECT j.* FROM jobs j JOIN users u ON u.id=j.owner WHERE j.status='queued' AND j.available_at<=? AND u.active=1 ORDER BY j.created,j.rowid LIMIT 1",(now,)).fetchone()
        if not row: return None
        token=str(uuid.uuid4());number=row['attempt_count']+1
        c.execute("UPDATE jobs SET status='running',lease_token=?,lease_until=?,attempt_count=?,detail='Execução iniciada' WHERE id=?",(token,now+LEASE_SECONDS,number,row['id']))
        c.execute('INSERT INTO job_attempts VALUES(?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),row['id'],number,worker,now,None,'running',None))
        event(c,row['owner'],'collection.started',row['id'])
        return {**dict(row),'lease_token':token,'attempt_count':number}


def held(c,job,now=None):
    now=time.time() if now is None else now
    row=c.execute("SELECT * FROM jobs WHERE id=? AND status='running' AND lease_token=? AND lease_until>?",(job['id'],job['lease_token'],now)).fetchone()
    return row is not None and authorization.job_authorized(c,dict(row))


def renew(db,job,now=None):
    now=time.time() if now is None else now
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not held(c,job,now): return False
        c.execute('UPDATE jobs SET lease_until=? WHERE id=? AND lease_token=?',(now+LEASE_SECONDS,job['id'],job['lease_token']))
        c.execute("UPDATE extraction_runs SET lease_until=? WHERE job_id=? AND state='running'",(now+LEASE_SECONDS,job['id']))
        return True


def finish(c,event,job,status,detail,checkpoint=None):
    """Chamar na mesma transação dos resultados, após held()."""
    c.execute('UPDATE jobs SET status=?,detail=?,checkpoint=?,lease_token=NULL,lease_until=NULL WHERE id=?',(status,detail,json.dumps(checkpoint or {}),job['id']))
    c.execute('UPDATE job_attempts SET status=?,finished=? WHERE job_id=? AND number=?',(status,time.time(),job['id'],job['attempt_count']))
    event(c,job['owner'],'collection.'+status,job['id'])


def fail(db,event,job):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not held(c,job): return
        final=job['attempt_count']>=MAX_ATTEMPTS
        state='failed' if final else 'queued'
        delay=min(60,2**job['attempt_count'])
        c.execute('UPDATE jobs SET status=?,detail=?,available_at=?,lease_token=NULL,lease_until=NULL WHERE id=?',(state,'Falha de execução; consulte tentativa registrada',time.time()+delay,job['id']))
        c.execute("UPDATE job_attempts SET status='failed',finished=?,error='execution_error' WHERE job_id=? AND number=?",(time.time(),job['id'],job['attempt_count']))
        event(c,job['owner'],'collection.'+('failed' if final else 'retry_scheduled'),job['id'])
