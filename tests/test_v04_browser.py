"""E2E das telas novas 0.4 usando o Chromium do host."""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from support import app


class V04BrowserTests(unittest.TestCase):
    @unittest.skipIf(getattr(app.app, 'version', '').startswith('0.7.'), 'Interface 0.4 substituída pela ponte 0.7; E2E dedicado em scripts/browser_bridge.py')
    @unittest.skipUnless(shutil.which('chromium'), 'Chromium não instalado; E2E 0.4 pendente')
    def test_advanced_navigation_loads_without_page_errors(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest('Playwright não instalado; E2E 0.4 pendente')
        name = 'v04-ui-' + app.uid()[:8]
        password = 'v04-browser-password-123'
        with app.db() as c:
            c.execute('INSERT INTO users(id,name,password,role) VALUES(?,?,?,?)', (app.uid(), name, app.password_hash(password), 'admin'))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        env = {**os.environ, 'COLLECTOR_DATA': str(app.ROOT)}
        logs = tempfile.TemporaryFile()
        server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', str(port)], env=env, stdout=logs, stderr=logs)
        try:
            base = f'http://127.0.0.1:{port}'
            import urllib.request
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for _ in range(100):
                try:
                    with opener.open(base + '/', timeout=.2): break
                except Exception: time.sleep(.05)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=shutil.which('chromium'), headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
                page = browser.new_page(viewport={'width': 1365, 'height': 900})
                errors = []; page.on('pageerror', lambda err: errors.append(str(err)))
                page.goto(base)
                page.locator('#login-form input[name=name]').fill(name)
                page.locator('#login-form input[name=password]').fill(password)
                page.locator('#login-form button').click()
                page.wait_for_selector('#application:not([hidden])')
                for label in ('Conhecimento', 'Pesquisa espacial', 'Integrações'):
                    page.locator('#navigation').get_by_role('button', name=label, exact=True).click()
                    self.assertEqual(page.locator('#content h1').inner_text(), label)
                self.assertEqual(errors, [])
                browser.close()
        finally:
            server.terminate()
            try: server.wait(timeout=5)
            except subprocess.TimeoutExpired: server.kill(); server.wait()
            logs.close()


if __name__ == '__main__':
    unittest.main()
