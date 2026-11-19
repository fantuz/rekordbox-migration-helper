"""OAuth state, secret-storage and fixed-host transport regressions; no account needed."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit

from dropbox_auth import DropboxConnection,CredentialVault,SCOPES,require_local_request
from dropbox_http import DropboxError,DropboxTransport,DownloadResponse,_provider_error
from workbench_store import Store


ACCOUNT={'account_id':'dbid:invented-account','name':{'display_name':'Invented user'},'email':'test@example.invalid',
         'root_info':{'.tag':'team','root_namespace_id':'root-123','home_namespace_id':'home-456'}}


class Vault:
    available=True;backend_name='test-secure-vault'
    def __init__(self):self.values={};self.calls=[]
    def get(self,key):self.calls.append(('get',key));return self.values.get(key)
    def set(self,key,value):self.calls.append(('set',key));self.values[key]=value
    def delete(self,key):self.calls.append(('delete',key));self.values.pop(key,None)


class Transport:
    def __init__(self):
        self.calls=[];self.account=deepcopy(ACCOUNT);self.failure=None;self.tokens=0
    def token(self,data):
        self.calls.append(('token',deepcopy(data)))
        if self.failure:raise self.failure
        self.tokens+=1
        value={'access_token':'PRIVATE_ACCESS_'+str(self.tokens),'expires_in':14400,'scope':' '.join(SCOPES),'account_id':self.account['account_id']}
        if data['grant_type']=='authorization_code':value['refresh_token']='PRIVATE_REFRESH'
        return value
    def rpc(self,route,payload,access_token,path_root=None):
        self.calls.append(('rpc',route,deepcopy(payload),access_token,path_root))
        if route=='users/get_current_account':return deepcopy(self.account)
        return {'id':'id:one','name':'Synthetic.mp3'}
    def download(self,path,rev,access_token,namespace=None):
        self.calls.append(('download',path,rev,access_token,namespace));return BytesIO(b'invented')


class DropboxOAuthTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.owner=SimpleNamespace(DATA=self.root,TOKEN='local-test-token');self.transport=Transport();self.vault=Vault()
        self.connection=DropboxConnection(self.owner,self.transport,self.vault)
    def connect(self,remember=False):
        self.connection.configure('PUBLIC_APP_KEY',remember)
        start=self.connection.begin('http://127.0.0.1:8765')
        state=parse_qs(urlsplit(start['authorize_url']).query)['state'][0]
        result=self.connection.callback(state,'PRIVATE_CODE',callback_origin='http://127.0.0.1:8765')
        return start,state,result

    def test_pkce_state_and_minimal_public_setup_are_bound_and_single_use(self):
        self.connection.configure('PUBLIC_APP_KEY')
        start=self.connection.begin('http://127.0.0.1:8765');parameters=parse_qs(urlsplit(start['authorize_url']).query)
        self.assertEqual(parameters['code_challenge_method'],['S256']);self.assertEqual(parameters['token_access_type'],['offline'])
        self.assertEqual(set(parameters['scope'][0].split()),set(SCOPES));self.assertNotIn('client_secret',parameters)
        self.assertEqual(start['redirect_uri'],'http://127.0.0.1:8765/api/dropbox/callback')
        state=parameters['state'][0]
        with self.assertRaises(DropboxError):self.connection.callback('wrong-state','PRIVATE_CODE')
        self.assertEqual(self.transport.calls,[])
        result=self.connection.callback(state,'PRIVATE_CODE',callback_origin='http://127.0.0.1:8765')
        self.assertTrue(result['connected']);self.assertEqual(result['state'],'session')
        from hashlib import sha256
        import base64
        sent=self.transport.calls[0][1]
        expected=base64.urlsafe_b64encode(sha256(sent['code_verifier'].encode()).digest()).rstrip(b'=').decode()
        self.assertEqual(parameters['code_challenge'],[expected])
        with self.assertRaises(DropboxError):self.connection.callback(state,'PRIVATE_CODE')

    def test_bad_callback_origins_expiry_and_denial_never_exchange_tokens(self):
        for origin in ['http://evil.example:8765','https://127.0.0.1:8765','http://127.0.0.1:8765/other','http://user@127.0.0.1:8765','http://127.0.0.1:8765?x=1','http://127.0.0.1:999999']:
            self.connection.configure('PUBLIC_APP_KEY')
            with self.assertRaises(DropboxError):self.connection.begin(origin)
        self.connection.configure('PUBLIC_APP_KEY');start=self.connection.begin('http://127.0.0.1:8765')
        state=parse_qs(urlsplit(start['authorize_url']).query)['state'][0]
        with self.assertRaises(DropboxError):self.connection.callback(state,'PRIVATE_CODE',callback_origin='http://127.0.0.1:9999')
        start=self.connection.begin('http://127.0.0.1:8765');state=parse_qs(urlsplit(start['authorize_url']).query)['state'][0]
        with patch('dropbox_auth.time.monotonic',return_value=1e20),self.assertRaises(DropboxError):self.connection.callback(state,'PRIVATE_CODE')
        start=self.connection.begin('http://127.0.0.1:8765');state=parse_qs(urlsplit(start['authorize_url']).query)['state'][0]
        with self.assertRaises(DropboxError):self.connection.callback(state,None,error='access_denied')
        self.assertEqual(self.transport.calls,[])

    def test_configuration_changes_and_new_begin_invalidate_old_flow(self):
        self.connection.configure('PUBLIC_APP_KEY');start=self.connection.begin('http://127.0.0.1:8765')
        old=parse_qs(urlsplit(start['authorize_url']).query)['state'][0]
        self.connection.begin('http://127.0.0.1:8765')
        with self.assertRaises(DropboxError):self.connection.callback(old,'PRIVATE_CODE')
        start=self.connection.begin('http://127.0.0.1:8765');state=parse_qs(urlsplit(start['authorize_url']).query)['state'][0]
        self.connection.configure('NEW_PUBLIC_KEY')
        with self.assertRaises(DropboxError):self.connection.callback(state,'PRIVATE_CODE')
        self.assertEqual(self.transport.calls,[])

    def test_tokens_never_enter_settings_status_or_auth_url(self):
        start,state,result=self.connect(remember=True)
        stored=Store(self.root/'workbench-sidecar.sqlite3').setting('dropbox_connection_v1')
        for public in [start,result,stored,self.connection.status()]:
            text=json.dumps(public)
            for secret in ['PRIVATE_ACCESS','PRIVATE_REFRESH','PRIVATE_CODE','code_verifier']:
                self.assertNotIn(secret,text)
        self.assertEqual(len(self.vault.values),1)
        self.assertIn('PRIVATE_REFRESH',next(iter(self.vault.values.values())))
        self.assertNotIn('PRIVATE_ACCESS',next(iter(self.vault.values.values())))

    def test_session_only_never_uses_vault_and_does_not_reconnect_after_restart(self):
        self.connect();self.assertEqual(self.vault.calls,[])
        other=DropboxConnection(self.owner,self.transport,self.vault)
        self.assertFalse(other.status()['connected'])
        with self.assertRaises(DropboxError):other.rpc('files/get_metadata',{'path':'/Synthetic.mp3'})
        self.assertEqual(self.vault.calls,[])

    def test_persistent_refresh_is_lazy_identity_checked_and_revocable(self):
        self.connect(remember=True);generation=self.connection.status()['connection_id']
        self.transport.calls.clear();self.vault.calls.clear()
        resumed=DropboxConnection(self.owner,self.transport,self.vault)
        self.assertTrue(resumed.status()['connected']);self.assertEqual(self.transport.calls,[]);self.assertEqual(self.vault.calls,[])
        resumed.rpc('files/get_metadata',{'path':'/one.mp3'},path_root='root-123')
        self.assertEqual(self.transport.calls[0][1]['grant_type'],'refresh_token')
        self.assertEqual(self.transport.calls[-1][1],'files/get_metadata')
        self.assertEqual(self.transport.calls[-1][-1],'root-123')
        result=resumed.disconnect();self.assertTrue(result['disconnected']);self.assertTrue(result['vault_cleared'])
        self.assertEqual(self.vault.values,{})
        self.assertFalse(resumed.status()['connected']);self.assertNotEqual(generation,resumed.status()['connection_id'])
        self.assertEqual(self.transport.calls[-1][1],'auth/token/revoke')
        self.assertFalse(DropboxConnection(self.owner,self.transport,self.vault).status()['connected'])

    def test_revoked_refresh_and_account_mismatch_require_reconnect(self):
        self.connect(remember=True);self.connection._access=None
        self.transport.failure=DropboxError('Revoked',status=400,tag='invalid_grant')
        with self.assertRaises(DropboxError):self.connection.rpc('files/get_metadata',{'path':'/one.mp3'})
        self.assertFalse(self.connection.status()['connected'])
        self.transport.failure=None
        self.connection=DropboxConnection(self.owner,self.transport,self.vault)
        self.transport.account['account_id']='dbid:another'
        with self.assertRaises(DropboxError):self.connection.rpc('files/get_metadata',{'path':'/one.mp3'})
        self.assertFalse(self.connection.status()['connected'])

    def test_second_account_cannot_silently_replace_connected_account(self):
        self.connect();self.transport.account['account_id']='dbid:another'
        start=self.connection.begin('http://127.0.0.1:8765');state=parse_qs(urlsplit(start['authorize_url']).query)['state'][0]
        with self.assertRaises(DropboxError):self.connection.callback(state,'PRIVATE_CODE')
        self.assertEqual(self.connection.status()['account']['account_id'],ACCOUNT['account_id'])

    def test_missing_or_unapproved_vault_is_explicit_session_only(self):
        self.vault.available=False
        with self.assertRaises(DropboxError):self.connection.configure('PUBLIC_APP_KEY',remember=True)
        self.connect(remember=False);self.assertTrue(self.connection.status()['connected'])
        class Plaintext:
            priority=100
        Plaintext.__module__='keyrings.alt.file'
        module=SimpleNamespace(get_keyring=lambda:Plaintext())
        with patch.dict('sys.modules',{'keyring':module}):self.assertFalse(CredentialVault(self.root).available)

    def test_secure_leaf_is_selected_without_plaintext_chainer_fallback(self):
        class Plaintext:
            priority=100
        Plaintext.__module__='keyrings.alt.file'
        class WinVaultKeyring:
            priority=5
        WinVaultKeyring.__module__='keyring.backends.Windows'
        secure=WinVaultKeyring()
        class ChainerBackend:
            backends=[Plaintext(),secure]
        ChainerBackend.__module__='keyring.backends.chainer'
        module=SimpleNamespace(get_keyring=lambda:ChainerBackend())
        with patch.dict('sys.modules',{'keyring':module}):
            vault=CredentialVault(self.root)
        self.assertTrue(vault.available);self.assertIs(vault.backend,secure)

    def test_vault_delete_failure_is_reported_until_credential_absence_is_known(self):
        class PasswordDeleteError(Exception):pass
        backend=SimpleNamespace(get_password=lambda *args:'PRIVATE_REFRESH',
                                delete_password=lambda *args:(_ for _ in ()).throw(PasswordDeleteError('PRIVATE_DETAIL')))
        vault=CredentialVault(self.root);vault.backend=backend
        with self.assertRaises(DropboxError) as failure:vault.delete('opaque-key')
        self.assertNotIn('PRIVATE',str(failure.exception))
        backend.get_password=lambda *args:None
        vault.delete('already-absent')

    def test_pending_vault_cleanup_blocks_remembered_auth_but_allows_explicit_session(self):
        self.connect(remember=True);old_key=next(iter(self.vault.values))
        failure=DropboxError('Locked operating-system store',tag='vault_unavailable')
        with patch.object(self.vault,'delete',side_effect=failure):
            disconnected=self.connection.disconnect()
            self.assertFalse(disconnected['vault_cleared'])
            self.assertTrue(self.connection.status()['credential_cleanup_pending'])
            with self.assertRaises(DropboxError):self.connection.begin('http://127.0.0.1:8765')
            with self.assertRaises(DropboxError):self.connection.configure('ANOTHER_PUBLIC_KEY',remember=True)
            self.connection.configure('ANOTHER_PUBLIC_KEY',remember=False)
            start=self.connection.begin('http://127.0.0.1:8765')
            state=parse_qs(urlsplit(start['authorize_url']).query)['state'][0]
            self.connection.callback(state,'PRIVATE_CODE',callback_origin='http://127.0.0.1:8765')
            self.assertEqual(self.connection.status()['state'],'session')
            self.assertTrue(self.connection.status()['credential_cleanup_pending'])
            self.assertFalse(self.connection.status()['persistent'])
            self.assertEqual(set(self.vault.values),{old_key})
            with self.assertRaises(DropboxError):self.connection.configure('ANOTHER_PUBLIC_KEY',remember=True)
            stored=Store(self.root/'workbench-sidecar.sqlite3').setting('dropbox_connection_v1')
            self.assertEqual(stored['cleanup_key'],old_key)
        self.connection.configure('ANOTHER_PUBLIC_KEY',remember=True)
        self.assertFalse(self.connection.status()['credential_cleanup_pending'])
        self.assertEqual(self.vault.values,{})

    def test_pending_cleanup_survives_restart_without_reactivating_saved_authorization(self):
        self.connect(remember=True);old_key=next(iter(self.vault.values))
        with patch.object(self.vault,'delete',side_effect=DropboxError('Locked store',tag='vault_unavailable')):
            self.connection.disconnect()
            restarted=DropboxConnection(self.owner,self.transport,self.vault)
            self.assertFalse(restarted.status()['connected'])
            self.assertTrue(restarted.status()['credential_cleanup_pending'])
            with self.assertRaises(DropboxError):restarted.begin('http://127.0.0.1:8765')
            self.assertEqual(restarted._cleanup,old_key)
        self.assertTrue(restarted.disconnect()['vault_cleared'])
        self.assertEqual(self.vault.values,{})

    def test_expired_download_access_refreshes_once_without_duplicate_content_transfer(self):
        self.connect();attempts=[]
        def download(path,rev,access,namespace=None):
            attempts.append(access)
            if len(attempts)==1:raise DropboxError('Expired',status=401,tag='expired_access_token')
            return BytesIO(b'invented')
        self.transport.download=download
        with self.connection.download('id:one') as stream:self.assertEqual(stream.read(),b'invented')
        self.assertEqual(len(attempts),2);self.assertNotEqual(attempts[0],attempts[1])

    def test_owner_data_changes_cannot_redirect_the_authenticated_store(self):
        self.connect(remember=True);new_root=self.root/'other-profile';new_root.mkdir();self.owner.DATA=new_root
        self.connection.configure('PUBLIC_APP_KEY',remember=True)
        self.assertFalse((new_root/'workbench-sidecar.sqlite3').exists())
        other=DropboxConnection(self.owner,self.transport,self.vault)
        self.assertFalse(other.status()['connected'])

    def test_metadata_route_allowlist_and_download_boundary(self):
        self.connect();self.transport.calls.clear()
        for route in ['files/download','files/delete_v2','files/upload','https://evil.example','../oauth2/token']:
            with self.assertRaises(DropboxError):self.connection.rpc(route,{})
        for path in ['https://evil.example/file.mp3','relative.mp3','/one.mp3\n']:
            with self.assertRaises(DropboxError):self.connection.download(path)
        self.assertEqual(self.transport.calls,[])
        self.connection.download('id:one',rev='abc123',namespace='root-123')
        self.assertEqual(self.transport.calls[0][0],'download')

    def test_explicit_namespace_header_is_preserved_and_cannot_inject_options(self):
        self.connect();self.transport.calls.clear()
        root={'.tag':'namespace_id','namespace_id':'12345'}
        self.connection.rpc('files/list_folder',{'path':''},path_root=root)
        self.assertEqual(self.transport.calls[-1][-1],root)
        for bad in [{'.tag':'namespace_id','namespace_id':'bad\nheader'},
                    {'.tag':'namespace_id','namespace_id':'12345','untrusted':'extra'},
                    {'.tag':'arbitrary','namespace_id':'12345'},[]]:
            with self.assertRaises(DropboxError):self.connection.rpc('files/list_folder',{'path':''},path_root=bad)

    def test_transport_download_uses_the_same_selected_namespace_as_listing(self):
        transport=DropboxTransport()
        with patch.object(transport,'_request',return_value=None) as invoke:
            transport.rpc('files/list_folder',{'path':''},'PRIVATE_ACCESS',{'.tag':'namespace_id','namespace_id':'12345'})
            listing=json.loads(invoke.call_args.args[3]['Dropbox-API-Path-Root'])
            transport.download('id:one','abc123','PRIVATE_ACCESS',namespace='12345')
            download=json.loads(invoke.call_args.args[3]['Dropbox-API-Path-Root'])
        self.assertEqual(listing,download)

    def test_request_guard_rejects_remote_origins_and_hosts(self):
        from flask import Flask
        app=Flask(__name__)
        for base,peer,origin in [('http://127.0.0.1:8765','192.0.2.1',None),('http://evil.example','127.0.0.1',None),('http://127.0.0.1:8765','127.0.0.1','https://evil.example')]:
            with app.test_request_context('/',base_url=base,environ_overrides={'REMOTE_ADDR':peer},headers={'Origin':origin} if origin else {}):
                with self.assertRaises(DropboxError):require_local_request(self.owner)
        with app.test_request_context('/',base_url='http://127.0.0.1:8765',environ_overrides={'REMOTE_ADDR':'127.0.0.1'},headers={'X-Workbench-Token':self.owner.TOKEN}):
            self.assertEqual(require_local_request(self.owner,token=True),'http://127.0.0.1:8765')


class DropboxTransportTests(unittest.TestCase):
    def test_provider_errors_hide_untrusted_bodies_and_classify_absence_and_retry(self):
        failure=_provider_error(409,json.dumps({'error_summary':'PRIVATE_ACCESS/path-secret','error':{'.tag':'path','path':{'.tag':'not_found'}}}).encode(),{})
        self.assertEqual(failure.tag,'not_found');self.assertNotIn('PRIVATE',str(failure));self.assertNotIn('path-secret',str(failure))
        self.assertEqual(_provider_error(429,b'PRIVATE_ACCESS',{'Retry-After':'30'}).retry_after,30)
        self.assertIsNone(_provider_error(429,b'',{'Retry-After':'nan'}).retry_after)

    def test_only_fixed_tls_hosts_and_no_credential_redirects(self):
        response=SimpleNamespace(status=302,headers={},read=lambda n:b'PRIVATE_ACCESS',close=lambda:None)
        with patch('dropbox_http.http.client.HTTPSConnection') as create:
            create.return_value.getresponse.return_value=response
            with self.assertRaises(DropboxError):DropboxTransport().rpc('files/get_metadata',{'path':'/one'},'PRIVATE_ACCESS')
            self.assertEqual(create.call_args.args[0],'api.dropboxapi.com');self.assertEqual(create.call_count,1)
            self.assertEqual(create.return_value.request.call_args.args[:2],('POST','/2/files/get_metadata'))

    def test_stream_is_bounded_and_incomplete_content_is_rejected(self):
        class Response(BytesIO):
            def getheader(self,key,default=None):return {'Dropbox-API-Result':'{"id":"id:one","name":"one.mp3"}','Content-Length':'10'}.get(key,default)
        connection=SimpleNamespace(close=lambda:None)
        with DownloadResponse(connection,Response(b'123')) as response:
            self.assertEqual(response.read(2),b'12');self.assertEqual(response.read(2),b'3')
            with self.assertRaises(DropboxError):response.read(2)
        with DownloadResponse(connection,Response(b'1234567890')) as response:
            with self.assertRaises(ValueError):response.read(-1)
            self.assertEqual(b''.join(response.iter_chunks(3)),b'1234567890')


class DropboxConnectorLifecycleTests(unittest.TestCase):
    def setUp(self):
        from flask import Flask,jsonify
        import dropbox_connector
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.profile=self.root/'profile-a';self.profile.mkdir()
        self.other=self.root/'profile-b';self.other.mkdir()
        app=Flask(__name__);app.config['TESTING']=True
        self.owner=SimpleNamespace(DATA=self.profile,TOKEN='test-local-token',app=app)
        @app.errorhandler(ValueError)
        def failure(error):return jsonify(error=str(error)),400
        dropbox_connector.register(self.owner)
        self.client=app.test_client();self.transport=Transport();self.vault=Vault()
        self.connection=DropboxConnection(self.owner,self.transport,self.vault)
        self.owner.dropbox_connection=self.connection;self.owner._dropbox_profile=self.profile.resolve()

    def test_callback_binds_the_actual_loopback_origin_and_never_caches_codes(self):
        self.connection.configure('PUBLIC_APP_KEY')
        start=self.connection.begin('http://127.0.0.1:8765')
        state=parse_qs(urlsplit(start['authorize_url']).query)['state'][0]
        result=self.client.get('/api/dropbox/callback',query_string={'state':state,'code':'PRIVATE_CODE'},base_url='http://127.0.0.1:9999')
        self.assertEqual(result.status_code,303);self.assertEqual(result.location,'/#dropbox')
        self.assertEqual(result.headers['Cache-Control'],'no-store')
        self.assertEqual(result.headers['Referrer-Policy'],'no-referrer')
        self.assertEqual(self.transport.calls,[]);self.assertFalse(self.connection.status()['connected'])

    def test_connection_registry_does_not_reuse_live_tokens_after_profile_change(self):
        from dropbox_connector import connection
        self.connection.configure('PUBLIC_APP_KEY');start=self.connection.begin('http://127.0.0.1:8765')
        state=parse_qs(urlsplit(start['authorize_url']).query)['state'][0]
        self.connection.callback(state,'PRIVATE_CODE',callback_origin='http://127.0.0.1:8765')
        self.owner.DATA=self.other
        other=connection(self.owner)
        self.assertIsNot(other,self.connection);self.assertFalse(other.status()['configured'])
        self.assertFalse(other.status()['connected']);self.assertIsNone(other.status()['account'])
        self.assertTrue(self.connection.status()['connected'])
        self.assertEqual(self.connection._data,self.profile.resolve())

    def test_callback_log_redacts_plain_and_encoded_callback_queries(self):
        import logging
        from dropbox_connector import _CallbackLogFilter
        redact=_CallbackLogFilter()
        for path in ['/api/dropbox/callback','/%61pi/dropbox/callback','/api/dropbox/%63allback']:
            record=logging.LogRecord('werkzeug',logging.INFO,__file__,1,'%s',
                ('GET '+path+'?code=PRIVATE_CODE&state=PRIVATE_STATE HTTP/1.1',),None)
            redact.filter(record)
            self.assertNotIn('PRIVATE_CODE',record.getMessage())
            self.assertNotIn('PRIVATE_STATE',record.getMessage())

    def test_metadata_worker_never_writes_into_a_later_profile(self):
        source_store=Store(self.profile/'workbench-sidecar.sqlite3')
        identity=source_store.save_snapshot({'scope_key':'synthetic:profile-isolation','tracks':[
            {'id':'one','title':'Invented','current_path':'/invented/dropbox/one.mp3'}],'playlists':[]},'Invented')['id']
        source_store.set_setting('dropbox_mapping',{'account_id':'dbid:invented'})
        def launch(work,_message,on_finished=None):
            def progress(amount,_text):
                if amount==98:self.owner.DATA=self.other
            try:work(progress)
            finally:
                if on_finished:on_finished('complete')
            return 'invented-job'
        self.owner.launch=launch
        with patch('dropbox_files.binding',return_value='invented-binding'),\
             patch('dropbox_files.inventory',return_value=({},True)),\
             patch('dropbox_files.target',return_value=None):
            self.client.post('/api/dropbox/check',json={'source':'snapshot:'+identity})
        database=self.other/'workbench-sidecar.sqlite3'
        if database.exists():
            with Store(database).connection() as db:
                table=db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dropbox_records'").fetchone()
                if table:self.assertEqual(db.execute('SELECT COUNT(*) FROM dropbox_records').fetchone()[0],0)
