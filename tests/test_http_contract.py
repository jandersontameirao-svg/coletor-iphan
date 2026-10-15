"""Ciclo HTTP real: API + worker + cliente de referência em processos separados."""
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
os.environ['COLLECTOR_DATA']=tempfile.mkdtemp(prefix='iphan-http-tests-')
import app

class HttpContractTests(unittest.TestCase):
    def test_reference_client_with_real_server_and_worker(self):
        name=app.uid();password='http-test-password-123'
        with app.db() as c: c.execute('INSERT INTO users(id,name,password,role) VALUES(?,?,?,?)',(app.uid(),name,app.password_hash(password),'operator'))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env={**os.environ,'COLLECTOR_DATA':str(app.ROOT)}
        logs=tempfile.TemporaryFile()
        server=subprocess.Popen([sys.executable,'-m','uvicorn','app:app','--host','127.0.0.1','--port',str(port)],env=env,stdout=logs,stderr=logs)
        worker=None
        try:
            base=f'http://127.0.0.1:{port}'
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            ready=False
            for _ in range(100):
                try:
                    with opener.open(base+'/',timeout=.2) as response: ready=response.status==200
                    if ready: break
                except Exception: time.sleep(.05)
            self.assertTrue(ready,'Servidor HTTP não iniciou')
            def request(path,body,token=None,binary=False):
                headers={'Content-Type':'application/octet-stream' if binary else 'application/json'}
                if token: headers['Authorization']='Bearer '+token
                req=urllib.request.Request(base+path,data=body if binary else json.dumps(body).encode(),headers=headers)
                with opener.open(req,timeout=5) as response: return json.load(response)
            token=request('/v1/sessions',{'name':name,'password':password})['access_token']
            pid=request('/v1/processes',{'number':app.uid(),'title':'Contrato ATENA'},token)['id']
            revision=request('/v1/processes/'+pid+'/documents?name=contract.txt',b'HTTP reference evidence',token,True)['revision_id']
            worker=subprocess.Popen([sys.executable,'worker.py'],env=env,stdout=logs,stderr=logs)
            result=subprocess.run([sys.executable,'reference_client.py','--base-url',base,'--revision-id',revision,'--timeout','10'],env={**env,'COLLECTOR_TOKEN':token,'NO_PROXY':'127.0.0.1,localhost'},capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            outputs=[json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(outputs[2]['status'],'completed')
            self.assertEqual(outputs[3]['revision_id'],revision)
            self.assertEqual(outputs[3]['text'],'HTTP reference evidence')
            self.assertNotIn(token,result.stdout+result.stderr)
        finally:
            for proc in (worker,server):
                if proc:
                    proc.terminate()
                    try: proc.wait(timeout=5)
                    except subprocess.TimeoutExpired: proc.kill();proc.wait()
            logs.close()

if __name__=='__main__':unittest.main()
