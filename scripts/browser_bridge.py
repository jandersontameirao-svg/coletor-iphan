"""E2E isolado da ponte; nenhum serviço externo ou credencial real."""
import json,os,pathlib,socket,subprocess,sys,tempfile,time,urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1];os.chdir(ROOT);sys.path.insert(0,str(ROOT))
temporary=tempfile.TemporaryDirectory(prefix='collector-browser-');os.environ['COLLECTOR_DATA']=temporary.name
import app
from playwright.sync_api import sync_playwright,expect
name='browser-fixture';password='synthetic-browser-1234'
with app.db() as c:c.execute('INSERT INTO users(id,name,password,role) VALUES(?,?,?,?)',(app.uid(),name,app.password_hash(password),'admin'))
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
log=tempfile.TemporaryFile();server=subprocess.Popen([sys.executable,'-m','uvicorn','app:app','--host','127.0.0.1','--port',str(port)],stdout=log,stderr=log)
try:
    url=f'http://127.0.0.1:{port}'
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(150):
        try:
            opener.open(url+'/_app/health',timeout=.3).close();break
        except Exception:time.sleep(.1)
    candidates=[os.getenv('CHROMIUM_PATH',''),'C:/Program Files/Google/Chrome/Application/chrome.exe','C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','/usr/bin/chromium','/usr/bin/chromium-browser']
    executable=next((x for x in candidates if x and pathlib.Path(x).is_file()),None)
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=executable)
        page=browser.new_page(viewport={'width':1440,'height':1050});page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(url);page.get_by_label('Usuário',exact=True).fill(name);page.get_by_label('Senha',exact=True).fill(password);page.get_by_role('button',name='Entrar',exact=True).click()
        expect(page.locator('#nav button')).to_have_count(4)
        page.get_by_label('Número do processo').fill('01422.000120/2011-70');page.get_by_label('Título',exact=True).fill('Acervo de demonstração · teste local');page.get_by_role('button',name='Cadastrar processo',exact=True).click()
        expect(page.locator('#notice')).to_contain_text('Processo cadastrado')
        page.get_by_label('Arquivo',exact=True).set_input_files({'name':'1234567_RAIPI.txt','mimeType':'text/plain','buffer':'Contratante: Energia Exemplo Ltda\nCNPJ: 11.444.777/0001-61\nResponsável técnico: Ana Teste\n'.encode()})
        page.get_by_role('button',name='Preservar e enviar',exact=True).click();expect(page.locator('#notice')).to_contain_text('Original preservado')
        page.get_by_role('button',name='Biblioteca',exact=True).click();expect(page.get_by_role('heading',name='1234567_RAIPI.txt')).to_be_visible()
        expect(page.locator('#content')).to_contain_text('01422.000120-2011-70/Documentos/RAIPI')
        with page.expect_download() as info:page.get_by_role('button',name='Baixar original').click()
        assert pathlib.Path(info.value.path()).read_bytes()=='Contratante: Energia Exemplo Ltda\nCNPJ: 11.444.777/0001-61\nResponsável técnico: Ana Teste\n'.encode()
        pid=page.evaluate('state.processes[0].id');token=page.evaluate('state.token')
        response=page.request.post(url+'/v1/processes/'+pid+'/documents?name=7654321_FCA.txt',headers={'Authorization':'Bearer '+token},data='Empreendedor: Energia Exemplo Ltda\nCNPJ: 11.444.777/0001-61\n')
        assert response.status==201
        assert app.market_domain.run_once(app);assert app.market_domain.run_once(app)
        page.get_by_role('button',name='Empresas e responsáveis',exact=True).click()
        expect(page.get_by_role('dialog')).to_contain_text('Ana Teste')
        expect(page.get_by_role('dialog')).to_contain_text('Presente em documentos administrativos e técnicos')
        screenshots=ROOT/'docs'/'screenshots-0.7';screenshots.mkdir(exist_ok=True)
        page.screenshot(path=str(screenshots/'participantes.png'),full_page=True)
        page.get_by_role('button',name='Fechar',exact=True).click()

        page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(screenshots/'biblioteca.png'),full_page=True)
        page.get_by_role('button',name='Acompanhamento',exact=True).click();expect(page.locator('#content')).to_contain_text('1234567_RAIPI.txt')
        page.get_by_role('button',name='Configurações',exact=True).click();expect(page.get_by_label('Link da pasta')).to_have_value(app.sharepoint_store.DEFAULT_FOLDER)
        page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(screenshots/'configuracoes.png'),full_page=True)
        page.get_by_role('button',name='Coleta',exact=True).click();page.screenshot(path=str(screenshots/'coleta.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(screenshots/'coleta-mobile.png'),full_page=True)
        page.get_by_role('button',name='Sair',exact=True).click();expect(page.locator('#login')).to_be_visible()
        browser.close()
    assert not errors,errors
    print(json.dumps({'status':'passed','checks':['login','4 tabs','process','manual import','RAIPI folder','library','download bytes','transfers','settings','mobile','logout','participants with sources','administrative technical crossing'],'javascript_errors':errors},ensure_ascii=True))
finally:
    server.terminate();server.wait(timeout=10);log.close();temporary.cleanup()
