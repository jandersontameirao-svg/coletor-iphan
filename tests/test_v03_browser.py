"""E2E da interface no Chromium instalado; sem conexão externa."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from support import Fixture
import app

class BrowserTests(Fixture):
    @unittest.skipIf(getattr(app.app, 'version', '').startswith('0.7.'), 'Interface legada substituída pela ponte 0.7; E2E dedicado em scripts/browser_bridge.py')
    @unittest.skipUnless(shutil.which('chromium'),'Chromium não instalado; teste E2E pendente')
    def test_navigation_upload_worker_evidence_and_logout(self):
        try: from playwright.sync_api import sync_playwright, expect
        except ImportError: self.skipTest('Playwright não instalado; teste E2E pendente')
        name='operador-ui-'+app.uid()[:8];password='browser-password-123';user_id=app.uid()
        with app.db() as c: c.execute('INSERT INTO users(id,name,password,role) VALUES(?,?,?,?)',(user_id,name,app.password_hash(password),'admin'))
        with socket.socket() as sock: sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env={**os.environ,'COLLECTOR_DATA':str(app.ROOT)};logs=tempfile.TemporaryFile()
        server=subprocess.Popen([sys.executable,'-m','uvicorn','app:app','--host','127.0.0.1','--port',str(port)],env=env,stdout=logs,stderr=logs)
        worker=subprocess.Popen([sys.executable,'worker.py'],env=env,stdout=logs,stderr=logs)
        try:
            base=f'http://127.0.0.1:{port}';opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));ready=False
            for _ in range(100):
                try:
                    with opener.open(base+'/',timeout=.2) as r: ready=r.status==200
                    if ready: break
                except Exception: time.sleep(.05)
            self.assertTrue(ready)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(executable_path=shutil.which('chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
                page=browser.new_page(viewport={'width':1365,'height':900});errors=[];page.on('pageerror',lambda err:errors.append(str(err)))
                page.goto(base)
                page.locator('#login-form input[name=name]').fill(name);page.locator('#login-form input[name=password]').fill(password)
                page.locator('#login-form button').click();page.wait_for_selector('#application:not([hidden])')
                page.get_by_role('button',name='Processos',exact=True).click()
                page.locator('#content input[name=number]').fill(app.uid());page.locator('#content input[name=title]').fill('Processo do navegador')
                page.get_by_role('button',name='Cadastrar processo',exact=True).click()
                expect(page.locator('#process-context')).not_to_have_value('')
                page.get_by_role('button',name='Documentos',exact=True).click()
                page.locator('#content input[type=file]').set_input_files({'name':'browser.txt','mimeType':'text/plain','buffer':b'Fonte conferivel no navegador'})
                page.get_by_role('button',name='Importar original',exact=True).click()
                page.wait_for_selector('#document-detail h2')
                page.get_by_role('button',name='Extrair / reutilizar execução',exact=True).click()
                page.wait_for_selector('#job-detail')
                for _ in range(60):
                    if page.locator('#job-detail').get_by_role('button',name='Evidência texto',exact=True).count(): break
                    page.wait_for_timeout(200)
                    page.get_by_role('button',name='Atualizar tarefas',exact=True).click()
                    page.get_by_role('button',name='Resultados e pendências',exact=True).first.click()
                page.locator('#job-detail').get_by_role('button',name='Evidência texto',exact=True).click()
                page.wait_for_selector('#detail-dialog[open]')
                self.assertIn('Fonte conferivel no navegador',page.locator('#dialog-content').inner_text())
                page.get_by_role('button',name='Fechar',exact=True).click()
                for name_ in ('Entrada de links','Biblioteca','Integrações','Administração','Visão geral'):
                    page.get_by_role('button',name=name_,exact=True).click()
                    expect(page.locator('#content h1')).to_have_text(name_)
                    expect(page.locator('#content')).to_have_attribute('aria-busy','false')
                expect(page.locator('.metric')).to_have_count(7)
                expect(page.locator('.metric').filter(has_text='Estudos analisados')).to_contain_text('Capacidade planejada')
                expect(page.locator('.metric').filter(has_text='Conhecimento validado')).to_contain_text('Capacidade planejada')
                self.assertEqual(errors,[])
                screenshot=os.getenv('COLLECTOR_UI_SCREENSHOT')
                if screenshot: page.screenshot(path=screenshot,full_page=True)
                page.get_by_role('button',name='Sair',exact=True).click();page.wait_for_selector('#login-panel:not([hidden])')
                self.assertEqual(page.locator('#dialog-content').inner_text(),'')
                browser.close()
        finally:
            for proc in (worker,server):
                proc.terminate()
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired: proc.kill();proc.wait()
            logs.close()
