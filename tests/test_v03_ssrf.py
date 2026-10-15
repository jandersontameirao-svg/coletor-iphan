import socket
import unittest
from unittest.mock import patch
import safe_fetch

GOOD='https://www.gov.br/iphan/example.pdf'

def record(ip): return (socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,443))

class SsrfTests(unittest.TestCase):
    def test_scheme_credentials_ports_and_unapproved_destinations(self):
        for url in ('http://www.gov.br/iphan','https://user:pass@www.gov.br/iphan','https://www.gov.br:8443/iphan','https://127.0.0.1/','https://169.254.169.254/latest','https://www.gov.br.evil.test/','https://www.gov.br/\r\nHost:evil','file:///etc/passwd'):
            with self.subTest(url=url),self.assertRaises(safe_fetch.FetchError): safe_fetch.validate_url(url)
    def test_mixed_dns_public_and_private_is_rejected_before_request(self):
        with patch('socket.getaddrinfo',return_value=[record('8.8.8.8'),record('10.0.0.1')]),patch('safe_fetch.request_once') as request:
            with self.assertRaises(safe_fetch.FetchError) as ctx: safe_fetch.fetch(GOOD)
            self.assertEqual(ctx.exception.code,'private_destination');request.assert_not_called()
    def test_redirect_to_private_or_unapproved_host_never_followed(self):
        with patch('safe_fetch.resolve_public',return_value=['8.8.8.8']),patch('safe_fetch.request_once',return_value=(302,{'location':'https://169.254.169.254/secret'},b'')) as request:
            with self.assertRaises(safe_fetch.FetchError): safe_fetch.fetch(GOOD)
            self.assertEqual(request.call_count,1)
    def test_allowed_redirect_is_resolved_again_and_private_dns_blocked(self):
        with patch('socket.getaddrinfo',side_effect=[[record('8.8.8.8')],[record('127.0.0.1')]]),patch('safe_fetch.request_once',return_value=(302,{'location':'https://sei.iphan.gov.br/document.pdf'},b'')) as request:
            with self.assertRaises(safe_fetch.FetchError): safe_fetch.fetch(GOOD)
            self.assertEqual(request.call_count,1)
    def test_pinned_transport_uses_validated_ip_and_original_tls_host(self):
        import os
        with patch.dict(os.environ,{'HTTPS_PROXY':'','https_proxy':''}),patch('socket.create_connection') as connect:
            conn=safe_fetch.PinnedTLS('www.gov.br','8.8.8.8')
            with patch.object(conn._context,'wrap_socket') as tls:
                conn.connect()
                connect.assert_called_once_with(('8.8.8.8',443),timeout=safe_fetch.TIMEOUT)
                self.assertEqual(tls.call_args.kwargs['server_hostname'],'www.gov.br')
    def test_login_and_html_are_not_saved_as_pdf(self):
        for body in (b'<html><input type="password"></html>',b'<!doctype html><p>Pagina comum</p>'):
            with patch('safe_fetch.resolve_public',return_value=['8.8.8.8']),patch('safe_fetch.request_once',return_value=(200,{'content-type':'text/html'},body)):
                with self.assertRaises(safe_fetch.FetchError) as ctx: safe_fetch.fetch(GOOD)
                self.assertIn(ctx.exception.code,('access_barrier','page_not_document'))
    def test_redirect_limit_and_http_429(self):
        for response in ((302,{'location':GOOD},b''),(429,{},b'')):
            with patch('safe_fetch.resolve_public',return_value=['8.8.8.8']),patch('safe_fetch.request_once',return_value=response):
                with self.assertRaises(safe_fetch.FetchError) as ctx: safe_fetch.fetch(GOOD)
                self.assertIn(ctx.exception.code,('redirect_limit','rate_limited'))
