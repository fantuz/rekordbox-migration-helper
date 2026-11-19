"""Google desktop OAuth and bounded HTTP checks using invented credentials."""
import base64
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit

from google_drive_auth import GoogleDriveConnection,CredentialVault,SCOPES,SETTING
from google_drive_http import GoogleDriveError,GoogleDriveTransport,DownloadResponse,JSON_LIMIT
from workbench_store import Store

CLIENT='123456-inventeddesktopclient.apps.googleusercontent.com'
ORIGIN='http://127.0.0.1:8765'


class Vault:
    available=True;backend_name='invented operating-system vault'
    def __init__(self):self.values={};self.reads=0;self.fail_delete=False
    def get(self,key):self.reads+=1;return self.values.get(key)
    def set(self,key,value):self.values[key]=value
    def delete(self,key):
        if self.fail_delete:raise GoogleDriveError('Invented locked vault',tag='vault_unavailable')
        self.values.pop(key,None)


class Transport:
    def __init__(self):
        self.tokens=[];self.calls=[];self.downloads=[];self.revoked=[];self.account='permission-invented'
        self.token_response={'access_token':'invented-access-private','refresh_token':'invented-refresh-private',
                             'expires_in':3600,'token_type':'Bearer','scope':' '.join(SCOPES)}
        self.file={'id':'invented-file','name':'Invented.mp3','mimeType':'audio/mpeg','size':'12','version':'7',
                   'md5Checksum':'a'*32,'sha256Checksum':'b'*64,'capabilities':{'canDownload':True},'trashed':False}
        self.fail_rpc=[];self.fail_download=[]
    def token(self,parameters):self.tokens.append(dict(parameters));return deepcopy(self.token_response)
    def rpc(self,route,payload,access):
        self.calls.append((route,deepcopy(payload),access))
        if route=='about/get':return {'user':{'permissionId':self.account,'emailAddress':'invented@example.invalid','displayName':'Invented account'}}
        if self.fail_rpc:raise self.fail_rpc.pop(0)
        return deepcopy(self.file) if route=='files/get' else {'files':[]}
    def download(self,identity,access,metadata):
        self.downloads.append((identity,access,deepcopy(metadata)))
        if self.fail_download:raise self.fail_download.pop(0)
        stream=BytesIO(b'invented file');stream.metadata=deepcopy(metadata);stream.length=13
        return stream
    def revoke(self,token):self.revoked.append(token);return {}


class GoogleDriveAuthTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve();self.owner=SimpleNamespace(DATA=self.root)
        self.vault=Vault();self.transport=Transport()
        self.connection=GoogleDriveConnection(self.owner,self.transport,self.vault)
    def login(self,remember=False,secret=None):
        self.connection.configure(CLIENT,secret,remember=remember)
        result=self.connection.begin(ORIGIN);state=parse_qs(urlsplit(result['authorize_url']).query)['state'][0]
        return self.connection.callback(state,'invented-code-private',callback_origin=ORIGIN)

    def test_pkce_uses_public_desktop_id_and_single_readonly_scope(self):
        self.connection.configure(CLIENT)
        result=self.connection.begin(ORIGIN);url=urlsplit(result['authorize_url']);query=parse_qs(url.query)
        self.assertEqual(url.scheme+'://'+url.netloc+url.path,'https://accounts.google.com/o/oauth2/v2/auth')
        self.assertEqual(query['scope'],list(SCOPES));self.assertEqual(query['code_challenge_method'],['S256'])
        self.assertEqual(query['access_type'],['offline']);self.assertEqual(query['redirect_uri'],[ORIGIN+'/api/google-drive/callback'])
        self.connection.callback(query['state'][0],'invented-code-private',callback_origin=ORIGIN)
        sent=self.transport.tokens[-1]
        digest=base64.urlsafe_b64encode(sha256(sent['code_verifier'].encode()).digest()).rstrip(b'=').decode()
        self.assertEqual(query['code_challenge'],[digest]);self.assertNotIn('client_secret',sent)
        self.assertEqual(self.transport.calls[0][0],'about/get')
        self.assertEqual(self.connection.status()['account']['account_id'],'permission-invented')

    def test_status_reads_no_network_or_vault_and_contains_no_tokens(self):
        self.login(remember=True,secret='invented-client-secret-private')
        before=(len(self.transport.calls),len(self.transport.tokens),self.vault.reads)
        status=self.connection.status()
        self.assertEqual(before,(len(self.transport.calls),len(self.transport.tokens),self.vault.reads))
        encoded=json.dumps(status)
        for secret in ('invented-client-secret-private','invented-access-private','invented-refresh-private','invented-code-private'):
            self.assertNotIn(secret,encoded)
            self.assertNotIn(secret,Store(self.root/'workbench-sidecar.sqlite3').setting(SETTING).__str__())

    def test_optional_client_secret_is_ram_only_for_session(self):
        self.login(secret='invented-client-secret-private')
        self.assertEqual(self.transport.tokens[-1]['client_secret'],'invented-client-secret-private')
        self.assertTrue(self.connection.status()['client_secret_configured'])
        self.assertEqual(self.vault.values,{})
        restarted=GoogleDriveConnection(self.owner,self.transport,self.vault)
        self.assertFalse(restarted.status()['connected']);self.assertFalse(restarted.status()['client_secret_configured'])
        self.assertEqual(restarted.status()['client_id'],CLIENT)

    def test_remembered_authorization_renews_with_secret_only_from_os_vault(self):
        self.login(remember=True,secret='invented-client-secret-private')
        raw=next(iter(self.vault.values.values()));self.assertIn('invented-refresh-private',raw)
        restarted=GoogleDriveConnection(self.owner,self.transport,self.vault)
        self.assertEqual(self.vault.reads,0);self.assertTrue(restarted.status()['connected'])
        restarted.rpc('files/list',{'q':'trashed=false'})
        self.assertEqual(self.vault.reads,1)
        self.assertEqual(self.transport.tokens[-1]['grant_type'],'refresh_token')
        self.assertEqual(self.transport.tokens[-1]['client_secret'],'invented-client-secret-private')
        self.assertEqual(self.transport.calls[-2][0],'about/get')

    def test_explicit_reconnect_restores_optional_secret_from_vault(self):
        self.login(remember=True,secret='invented-client-secret-private')
        restarted=GoogleDriveConnection(self.owner,self.transport,self.vault)
        restarted.configure(CLIENT,remember=True)
        result=restarted.begin(ORIGIN);state=parse_qs(urlsplit(result['authorize_url']).query)['state'][0]
        restarted.callback(state,'invented-new-code',callback_origin=ORIGIN)
        self.assertEqual(self.transport.tokens[-1]['client_secret'],'invented-client-secret-private')

    def test_state_is_one_use_origin_bound_and_expires(self):
        self.connection.configure(CLIENT)
        result=self.connection.begin(ORIGIN);state=parse_qs(urlsplit(result['authorize_url']).query)['state'][0]
        with self.assertRaises(GoogleDriveError):self.connection.callback('incorrect', 'invented-code',callback_origin=ORIGIN)
        self.assertEqual(self.transport.tokens,[])
        with self.assertRaises(GoogleDriveError):self.connection.callback(state,'invented-code',callback_origin='http://127.0.0.1:8766')
        with self.assertRaises(GoogleDriveError):self.connection.callback(state,'invented-code',callback_origin=ORIGIN)
        result=self.connection.begin(ORIGIN);state=parse_qs(urlsplit(result['authorize_url']).query)['state'][0]
        self.connection._pending['created']-=601
        with self.assertRaises(GoogleDriveError):self.connection.callback(state,'invented-code',callback_origin=ORIGIN)
        self.assertEqual(self.transport.tokens,[])

    def test_denied_consent_and_missing_scope_never_connect(self):
        self.connection.configure(CLIENT)
        result=self.connection.begin(ORIGIN);state=parse_qs(urlsplit(result['authorize_url']).query)['state'][0]
        with self.assertRaises(GoogleDriveError):self.connection.callback(state,None,error='access_denied',callback_origin=ORIGIN)
        self.assertFalse(self.connection.status()['connected'])
        self.transport.token_response['scope']='https://www.googleapis.com/auth/drive.file'
        with self.assertRaises(GoogleDriveError):self.login(remember=True)
        self.assertFalse(self.connection.status()['connected']);self.assertEqual(self.vault.values,{})

    def test_invalid_identity_and_expiry_do_not_persist_credentials(self):
        for expires in (True,float('nan'),0,-1,32*86400):
            with self.subTest(expires=expires):
                self.transport.token_response['expires_in']=expires
                with self.assertRaises(GoogleDriveError):self.login(remember=True)
                self.assertEqual(self.vault.values,{})

    def test_refresh_rejects_another_google_account(self):
        self.login(remember=True)
        restarted=GoogleDriveConnection(self.owner,self.transport,self.vault);self.transport.account='other-permission'
        with self.assertRaises(GoogleDriveError):restarted.rpc('files/list',{})
        self.assertFalse(restarted.status()['connected']);self.assertTrue(restarted.status()['needs_reconnect'])
        self.assertNotEqual(self.transport.calls[-1][0],'files/list')

    def test_one_401_retries_after_refresh_and_second_401_requires_reconnect(self):
        self.login()
        self.transport.fail_rpc=[GoogleDriveError('expired',status=401),GoogleDriveError('expired',status=401)]
        with self.assertRaises(GoogleDriveError):self.connection.rpc('files/list',{})
        self.assertEqual(len(self.transport.tokens),2)
        self.assertTrue(self.connection.status()['needs_reconnect'])

    def test_download_rechecks_version_and_blocks_native_docs_or_restricted_files(self):
        self.login()
        with self.assertRaises(GoogleDriveError):self.connection.download('invented-file',version='6')
        self.assertEqual(self.transport.downloads,[])
        self.transport.file['mimeType']='application/vnd.google-apps.document'
        with self.assertRaises(GoogleDriveError):self.connection.download('invented-file',version='7')
        self.transport.file['mimeType']='audio/mpeg';self.transport.file['capabilities']['canDownload']=False
        with self.assertRaises(GoogleDriveError):self.connection.download('invented-file',version='7')
        self.assertEqual(self.transport.downloads,[])
        self.transport.file['capabilities']['canDownload']=True
        with self.connection.download('invented-file',version='7') as response:
            self.assertEqual(response.metadata['version'],'7');self.assertEqual(response.read(),b'invented file')

    def test_download_401_is_renewed_and_fresh_metadata_checked(self):
        self.login();self.transport.fail_download=[GoogleDriveError('expired',status=401)]
        with self.connection.download('invented-file',version='7') as response:self.assertEqual(response.metadata['id'],'invented-file')
        self.assertEqual(len(self.transport.tokens),2);self.assertEqual(len(self.transport.downloads),2)

    def test_no_mutating_or_arbitrary_routes_and_invalid_ids(self):
        self.login();calls=len(self.transport.calls)
        for route in ('files/delete','files/create','https://evil.invalid/','files/export'):
            with self.subTest(route=route),self.assertRaises(GoogleDriveError):self.connection.rpc(route,{})
        for value in ('https://evil.invalid/', '../secret','id\r\nAuthorization: x',None):
            with self.subTest(value=value),self.assertRaises(GoogleDriveError):self.connection.download(value)
        self.assertEqual(len(self.transport.calls),calls)

    def test_disconnect_revokes_refresh_and_removes_vault(self):
        self.login(remember=True,secret='invented-client-secret-private');old=self.connection.status()['connection_id']
        result=self.connection.disconnect()
        self.assertTrue(result['remote_revoked']);self.assertTrue(result['vault_cleared']);self.assertEqual(self.vault.values,{})
        self.assertEqual(self.transport.revoked,['invented-refresh-private'])
        self.assertFalse(self.connection.status()['connected']);self.assertNotEqual(self.connection.status()['connection_id'],old)

    def test_pending_cleanup_cannot_be_overwritten_by_another_remembered_account(self):
        self.login(remember=True);self.vault.fail_delete=True;self.connection.disconnect()
        original=Store(self.root/'workbench-sidecar.sqlite3').setting(SETTING)['cleanup_key']
        self.assertTrue(self.connection.status()['credential_cleanup_pending'])
        with self.assertRaises(GoogleDriveError):self.connection.configure(CLIENT,remember=True)
        self.connection.configure(CLIENT,remember=False);self.transport.account='other-account'
        self.login();self.connection.disconnect()
        self.assertEqual(Store(self.root/'workbench-sidecar.sqlite3').setting(SETTING)['cleanup_key'],original)
        self.vault.fail_delete=False;self.connection.disconnect();self.assertFalse(self.connection.status()['credential_cleanup_pending'])

    def test_credentials_remain_bound_to_original_profile(self):
        other=self.root/'Other profile';self.owner.DATA=other
        self.connection.configure(CLIENT)
        self.assertFalse((other/'workbench-sidecar.sqlite3').exists())
        self.assertEqual(Store(self.root/'workbench-sidecar.sqlite3').setting(SETTING)['client_id'],CLIENT)

    def test_invalid_client_configuration_and_callback_addresses(self):
        for value in ('private-key',None,'https://evil.invalid/',CLIENT+'\n'):
            with self.subTest(value=value),self.assertRaises(GoogleDriveError):self.connection.configure(value)
        self.connection.configure(CLIENT)
        for origin in ('https://127.0.0.1:8765','http://localhost:8765','http://evil.invalid:8765','http://127.0.0.1:8765/path'):
            with self.subTest(origin=origin),self.assertRaises(GoogleDriveError):self.connection.begin(origin)
        self.vault.available=False
        with self.assertRaises(GoogleDriveError):self.connection.configure(CLIENT,remember=True)

    def test_google_vault_service_is_provider_specific(self):
        def initial(base,profile):base.backend=None
        with patch('dropbox_auth.CredentialVault.__init__',initial):vault=CredentialVault(self.root)
        self.assertTrue(vault.service.startswith('LibraryWorkbench.GoogleDrive.'))


class Response:
    def __init__(self,payload=b'{}',status=200,headers=None):
        self.body=BytesIO(payload);self.status=status;self.headers=headers or {};self.closed=False
    def getheader(self,key,default=None):return self.headers.get(key,default)
    def read(self,size=-1):return self.body.read(size)
    def close(self):self.closed=True;self.body.close()


class GoogleDriveHTTPTests(unittest.TestCase):
    def setUp(self):
        self.responses=[];self.connections=[]
        tests=self
        class HTTPS:
            def __init__(self,host,**kwargs):self.host=host;self.closed=False;tests.connections.append(self)
            def request(self,method,path,body=None,headers=None):self.request_data=(method,path,body,headers)
            def getresponse(self):return tests.responses.pop(0)
            def close(self):self.closed=True
        patched=patch('google_drive_http.http.client.HTTPSConnection',HTTPS);patched.start();self.addCleanup(patched.stop)
        self.transport=GoogleDriveTransport()
    def test_token_and_refresh_use_only_google_token_endpoint(self):
        self.responses.append(Response(b'{"access_token":"invented"}'))
        self.transport.token({'client_id':CLIENT,'code_verifier':'verifier','client_secret':'private optional'})
        connection=self.connections[-1];method,path,body,headers=connection.request_data
        self.assertEqual(connection.host,'oauth2.googleapis.com');self.assertEqual((method,path),('POST','/token'))
        self.assertEqual(parse_qs(body.decode())['client_secret'],['private optional']);self.assertTrue(connection.closed)
    def test_drive_metadata_is_get_with_encoded_query_and_no_content_permission(self):
        self.responses.append(Response(b'{"files":[]}'))
        self.transport.rpc('files/list',{'q':"'parent' in parents and name='a & b'",'supportsAllDrives':True},'access private')
        connection=self.connections[-1];method,path,body,headers=connection.request_data
        self.assertEqual(connection.host,'www.googleapis.com');self.assertEqual(method,'GET');self.assertIsNone(body)
        self.assertEqual(parse_qs(urlsplit(path).query)['supportsAllDrives'],['true'])
        self.assertIn('a & b',parse_qs(urlsplit(path).query)['q'][0])
        with self.assertRaises(GoogleDriveError):self.transport.rpc('files/get',{'fileId':'file','alt':'media'},'access')
        with self.assertRaises(GoogleDriveError):self.transport.rpc('files/delete',{},'access')
    def test_redirects_are_not_followed_and_errors_redact_provider_messages(self):
        self.responses.append(Response(b'PRIVATE_ACCESS_TOKEN',302,{'Location':'https://evil.invalid/PRIVATE_REFRESH_TOKEN'}))
        with self.assertRaises(GoogleDriveError) as caught:self.transport.rpc('files/list',{},'PRIVATE_ACCESS_TOKEN')
        self.assertNotIn('PRIVATE',str(caught.exception));self.assertEqual(len(self.connections),1)
        self.responses.append(Response(b'{"error":{"message":"PRIVATE","errors":[{"reason":"notFound"}]}}',404))
        with self.assertRaises(GoogleDriveError) as caught:self.transport.rpc('files/get',{'fileId':'file'},'access')
        self.assertEqual(caught.exception.tag,'not_found');self.assertNotIn('PRIVATE',str(caught.exception))
    def test_oversized_metadata_and_non_objects_are_rejected(self):
        for raw in (b'x'*(JSON_LIMIT+1),b'[]',b'invalid'):
            with self.subTest(size=len(raw)):
                self.responses.append(Response(raw))
                with self.assertRaises(GoogleDriveError):self.transport.rpc('files/list',{},'access')
                self.assertTrue(self.connections[-1].closed)
    def test_download_is_bounded_without_confusing_metadata_etag_with_media(self):
        self.responses.append(Response(b'abc',headers={'Content-Length':'3'}))
        with self.transport.download('file','access',{'id':'file','_http_etag':'"invented-version"'}) as response:
            self.assertEqual(response.read(2),b'ab');self.assertEqual(response.read(2),b'c');self.assertEqual(response.read(2),b'')
        method,path,body,headers=self.connections[-1].request_data
        self.assertNotIn('If-Match',headers);self.assertIn('alt=media',path);self.assertEqual(method,'GET')
        self.assertTrue(self.connections[-1].closed)
    def test_truncated_stream_raises_and_closes(self):
        self.responses.append(Response(b'a',headers={'Content-Length':'2'}))
        with self.transport.download('file','access',{'id':'file'}) as response:
            self.assertEqual(response.read(),b'a')
            with self.assertRaises(GoogleDriveError):response.read()
        self.assertTrue(self.connections[-1].closed)
    def test_retry_after_is_bounded_and_revision_error_is_clear(self):
        self.responses.append(Response(b'{}',429,{'Retry-After':'12'}))
        with self.assertRaises(GoogleDriveError) as caught:self.transport.rpc('files/list',{},'access')
        self.assertEqual(caught.exception.retry_after,12);self.assertEqual(caught.exception.tag,'rate_limit')
        self.responses.append(Response(b'{}',412))
        with self.assertRaises(GoogleDriveError) as caught:self.transport.download('file','access',{'id':'file'})
        self.assertEqual(caught.exception.tag,'revision_changed')


if __name__=='__main__':unittest.main()
