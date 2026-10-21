"""Fetch limitado de links explícitos. DNS fixado por conexão; redirects revalidados."""
import http.client
import ipaddress
import os
import socket
import ssl
import time
import threading
import queue
from email.message import Message
from pathlib import PurePosixPath
from urllib.parse import urlsplit, urljoin, unquote, quote

MAX_BYTES=128*1024*1024
TIMEOUT=15
MAX_REDIRECTS=5
DEFAULT_HOSTS=('www.gov.br','portal.iphan.gov.br','sei.iphan.gov.br')

class FetchError(Exception):
    def __init__(self,code,action): self.code=code;self.action=action;super().__init__(code)


def allowed_hosts():
    return set(x.strip().lower() for x in os.getenv('COLLECTOR_ALLOWED_HOSTS',','.join(DEFAULT_HOSTS)).split(',') if x.strip())


def validate_url(url):
    if not isinstance(url,str) or len(url)>4096 or any(ord(ch)<33 or ord(ch)==127 for ch in url) or '\\' in url:
        raise FetchError('invalid_url','Corrija o link informado')
    try:
        parsed=urlsplit(url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.port not in (None,443) or parsed.username or parsed.password or parsed.fragment:
            raise ValueError()
        host=parsed.hostname.lower()
        if host not in allowed_hosts() or '%' in parsed.netloc:
            raise FetchError('destination_not_allowed','Destino fora da allowlist; revise configuração autorizada ou importe manualmente')
        return parsed
    except ValueError: raise FetchError('invalid_url','Use HTTPS, sem credenciais, fragmento ou porta alternativa')


def resolve_public(host):
    results=queue.Queue(maxsize=1)
    def lookup():
        try: results.put(socket.getaddrinfo(host,443,type=socket.SOCK_STREAM))
        except OSError: results.put(None)
    threading.Thread(target=lookup,daemon=True).start()
    try: records=results.get(timeout=5)
    except queue.Empty: raise FetchError('dns_timeout','Resolução da origem excedeu 5 segundos; tente depois ou importe manualmente')
    if records is None: raise FetchError('dns_unavailable','Origem não resolvida; tente depois ou importe manualmente')
    ips=[]
    for record in records:
        ip=record[4][0]
        address=ipaddress.ip_address(ip.split('%')[0])
        if not address.is_global or address.is_multicast or address.is_reserved or getattr(address,'sixtofour',None) or getattr(address,'teredo',None) or (address.version==6 and address in ipaddress.ip_network('64:ff9b::/96')) or (getattr(address,'ipv4_mapped',None) and not address.ipv4_mapped.is_global):
            raise FetchError('private_destination','Destino privado/reservado bloqueado; importe manualmente')
        if ip not in ips: ips.append(ip)
    if not ips: raise FetchError('dns_unavailable','Origem não resolvida')
    return ips


class PinnedTLS(http.client.HTTPSConnection):
    def __init__(self,host,ip):
        super().__init__(host,443,timeout=TIMEOUT,context=ssl.create_default_context())
        self.ip=ip
    def connect(self):
        # A resolução do destino não é repetida pela biblioteca; SNI e certificado usam host.
        proxy=os.getenv('HTTPS_PROXY') or os.getenv('https_proxy')
        if proxy:
            p=urlsplit(proxy)
            if p.scheme!='http' or not p.hostname or p.username or p.password:
                raise FetchError('proxy_unsupported','Proxy não suportado; mantenha a política de rede e importe manualmente')
            tunnel=http.client.HTTPConnection(p.hostname,p.port or 80,timeout=TIMEOUT)
            tunnel.set_tunnel(self.ip,443)
            try:
                tunnel.connect();sock=tunnel.sock;tunnel.sock=None
            except OSError: raise FetchError('proxy_connection_failed','Proxy recusou ou não alcançou destino validado; importe manualmente')
        else:
            sock=socket.create_connection((self.ip,443),timeout=TIMEOUT)
        try: self.sock=self._context.wrap_socket(sock,server_hostname=self.host)
        except Exception:
            sock.close();raise


def request_once(url,ip,guard):
    parsed=validate_url(url);conn=PinnedTLS(parsed.hostname,ip)
    try:
        guard()
        path=quote(parsed.path or '/',safe="/%:@!$&'()*+,;=-._~")
        if parsed.query: path+='?'+quote(parsed.query,safe="/%?:@!$&'()*+,;=-._~")
        conn.request('GET',path,headers={'Host':parsed.hostname,'Accept':'application/pdf,text/plain;q=0.9,text/html;q=0.5','Accept-Encoding':'identity','User-Agent':'Coletor-IPHAN/0.3 (explicit user links)'})
        response=conn.getresponse();headers={k.lower():v for k,v in response.getheaders()}
        if response.status in (301,302,303,307,308): return response.status,headers,b''
        length=headers.get('content-length')
        if length:
            try:
                if int(length)>MAX_BYTES: raise FetchError('file_too_large','Limite de download de 128 MiB; importe versão reduzida')
            except ValueError: raise FetchError('invalid_response','Resposta da origem inválida')
        if headers.get('content-encoding','identity') not in ('identity',''): raise FetchError('unsupported_encoding','Resposta comprimida não suportada; importe manualmente')
        body=bytearray();deadline=time.monotonic()+30
        while True:
            guard()
            if time.monotonic()>deadline: raise FetchError('timeout','Origem excedeu limite de leitura; tente depois ou importe manualmente')
            chunk=response.read(65536)
            if not chunk: break
            body.extend(chunk)
            if len(body)>MAX_BYTES: raise FetchError('file_too_large','Limite de download de 128 MiB')
        return response.status,headers,bytes(body)
    except FetchError: raise
    except (OSError,http.client.HTTPException): raise FetchError('network_unavailable','Falha de conexão à origem; tente depois ou importe manualmente')
    finally: conn.close()


def fetch(url,guard=lambda:None):
    current=url
    for hop in range(MAX_REDIRECTS+1):
        parsed=validate_url(current);guard()
        ips=resolve_public(parsed.hostname)
        status,headers,body=request_once(current,ips[0],guard)
        if status in (301,302,303,307,308):
            if hop==MAX_REDIRECTS or not headers.get('location'): raise FetchError('redirect_limit','Redirecionamento inválido/excessivo')
            current=urljoin(current,headers['location'])
            # Validar imediatamente; a resolução pública é verificada antes do próximo GET.
            validate_url(current)
            continue
        if status in (401,403): raise FetchError('access_barrier','Login ou autorização necessários; importe manualmente um documento autorizado')
        if status==429: raise FetchError('rate_limited','Origem limitou solicitações; aguarde e retome')
        if status==404: raise FetchError('not_found','Link não encontrado; corrija ou importe manualmente')
        if status!=200: raise FetchError('origin_unavailable','Origem indisponível; tente depois ou importe manualmente')
        content_type=headers.get('content-type','').split(';')[0].lower()
        import archive_policy
        lower=body[:65536].lower()
        message=Message();message['Content-Disposition']=headers.get('content-disposition','')
        original_name=str(message.get_filename() or unquote(parsed.path.rsplit('/',1)[-1]) or 'document')[:300]
        name=''.join(ch for ch in original_name.replace('/','_').replace('\\','_') if ord(ch)>=32 and ord(ch)!=127)[:270] or 'document'
        native_html=parsed.hostname=='sei.iphan.gov.br' and parsed.path=='/sei/modulos/pesquisa/md_pesq_documento_consulta_externa.php'
        if content_type=='text/html' or lower.lstrip().startswith((b'<!doctype html',b'<html')):
            if any(word in lower for word in (b'captcha',b'type="password"',b"type='password'")):
                raise FetchError('access_barrier','Página de login/CAPTCHA; importe manualmente sem contornar controles')
            if not native_html: raise FetchError('page_not_document','Página não documental; informe link direto')
            if not name.lower().endswith(('.html','.htm')): name+='.html'
        if PurePosixPath(name).suffix.lower() in ('.php','') and content_type in ('text/plain','text/csv'): name+='.csv' if content_type=='text/csv' else '.txt'
        try: mime=archive_policy.detect(body,name,allow_html=native_html)
        except ValueError: raise FetchError('unsupported_document','Formato inválido ou não suportado para preservação')
        extension=next((ext for ext,value in archive_policy.MIMES.items() if value==mime),'.bin')
        if archive_policy.MIMES.get(PurePosixPath(name).suffix.lower())!=mime: name+=extension
        return {'data':body,'mime':mime,'name':name,'original_name':original_name,'final_url':current,'source_url':url}
    raise FetchError('redirect_limit','Limite de redirecionamentos')
