"""Cria o primeiro administrador sem senha padrão; execução idempotente."""
import getpass
import os
from pathlib import Path
import app

def main():
    with app.db() as c:
        if c.execute("SELECT 1 FROM users WHERE role='admin' AND kind='human' AND active=1").fetchone():
            print('Administrador já configurado.');return
    name=os.getenv('COLLECTOR_ADMIN_NAME') or input('Nome do administrador: ').strip()
    secret_file=os.getenv('COLLECTOR_ADMIN_PASSWORD_FILE')
    password=Path(secret_file).read_text(encoding='utf-8').rstrip('\r\n') if secret_file else getpass.getpass('Senha inicial (mínimo 12 caracteres): ')
    if not name or len(password)<12: raise SystemExit('Nome obrigatório e senha com pelo menos 12 caracteres.')
    with app.db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute("SELECT 1 FROM users WHERE role='admin' AND kind='human' AND active=1").fetchone():
            c.execute('INSERT INTO users(id,name,password,role) VALUES(?,?,?,?)',(app.uid(),name,app.password_hash(password),'admin'))
            app.event(c,'bootstrap','administrator.created',name)
    print('Administrador configurado. Nenhuma senha foi gravada em log.')

if __name__=='__main__':main()
