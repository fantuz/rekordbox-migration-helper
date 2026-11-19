"""Dropbox public-client OAuth with PKCE; credentials never enter the sidecar."""
import base64
from hashlib import sha256
import ipaddress
import json
import math
import re
import secrets
from threading import RLock
import time
from urllib.parse import urlencode,urlsplit

from flask import has_request_context,request
from dropbox_http import DropboxError,DropboxTransport
from workbench_store import Store

SCOPES=('account_info.read','files.metadata.read','files.content.read')
SETTING='dropbox_connection_v1'
RPC_ROUTES={'users/get_current_account','files/get_metadata','files/list_folder','files/list_folder/continue'}
SECURE_BACKENDS={'keyring.backends.Windows.WinVaultKeyring','keyring.backends.macOS.Keyring',
                 'keyring.backends.SecretService.Keyring','keyring.backends.libsecret.Keyring',
                 'keyring.backends.kwallet.DBusKeyring','keyring.backends.kwallet.DBusKeyringKWallet4'}


def require_local_request(owner=None,*,token=False):
    """Use on every connector route; callbacks additionally validate their OAuth state."""
    try:
        peer=ipaddress.ip_address(request.remote_addr or '')
        parsed=urlsplit(request.host_url)
        host=parsed.hostname
        local_host=host=='localhost' or ipaddress.ip_address(host).is_loopback
    except (ValueError,TypeError):peer=None;local_host=False
    if not peer or not peer.is_loopback or not local_host:
        raise DropboxError('Dropbox connections are available only on the local computer.',tag='local_only')
    if token and (owner is None or request.headers.get('X-Workbench-Token')!=owner.TOKEN):
        raise DropboxError('Reload the local page to authorize this action.',tag='local_only')
    origin=request.headers.get('Origin')
    if origin and origin.rstrip('/')!=request.host_url.rstrip('/'):
        raise DropboxError('Open Dropbox settings from this local Workbench page.',tag='local_only')
    return request.host_url.rstrip('/')


def _public_key(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{5,200}',value):
        raise DropboxError('Enter the public Dropbox app key from the developer console.',tag='configuration')
    return value


def _origin(value):
    try:
        parsed=urlsplit(value)
        valid=(parsed.scheme=='http' and parsed.hostname=='127.0.0.1' and parsed.port is not None
               and 1<=parsed.port<=65535 and parsed.path in ('','/') and not parsed.username
               and not parsed.password and not parsed.query and not parsed.fragment)
    except (ValueError,TypeError):valid=False
    if not valid:raise DropboxError('Use the registered 127.0.0.1 Workbench callback address.',tag='configuration')
    return 'http://127.0.0.1:'+str(parsed.port)


def _secret(value):
    return isinstance(value,str) and 1<=len(value)<=65536 and all(32<=ord(c)<127 for c in value)


def _namespace(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,200}',value):
        raise DropboxError('Choose a verified Dropbox namespace.',tag='invalid_argument')
    return value


def _path_root(value):
    if isinstance(value,str):return _namespace(value)
    if isinstance(value,dict):
        tag=value.get('.tag')
        field='root' if tag=='root' else 'namespace_id' if tag=='namespace_id' else None
        if field and set(value)=={'.tag',field}:
            return {'.tag':tag,field:_namespace(value[field])}
        if value=={'.tag':'home'}:return {'.tag':'home'}
    raise DropboxError('Choose a verified Dropbox namespace.',tag='invalid_argument')


class CredentialVault:
    """Select one approved OS store; never invoke plaintext or chainer fallbacks."""
    def __init__(self,profile):
        self.service='LibraryWorkbench.Dropbox.'+sha256(str(profile).encode()).hexdigest()[:24]
        self.backend=None;self.backend_name='unavailable'
        try:
            import keyring
            candidate=keyring.get_keyring()
            name=type(candidate).__module__+'.'+type(candidate).__name__
            # Chainer is keyring's usual default when multiple stores exist.
            # Select a known secure leaf directly so it can never fall back to
            # another installed backend after an operating-system store error.
            candidates=candidate.backends if name=='keyring.backends.chainer.ChainerBackend' else [candidate]
            for candidate in candidates:
                name=type(candidate).__module__+'.'+type(candidate).__name__
                if name in SECURE_BACKENDS and candidate.priority>0:
                    self.backend=candidate;self.backend_name=name;break
        except Exception:pass
    @property
    def available(self):return self.backend is not None
    def get(self,key):
        if not self.available:raise DropboxError('A supported operating-system credential store is unavailable. Use this session only.',tag='vault_unavailable')
        try:return self.backend.get_password(self.service,key)
        except Exception:raise DropboxError('The operating-system credential store could not be opened.',tag='vault_unavailable') from None
    def set(self,key,value):
        if not self.available:raise DropboxError('A supported operating-system credential store is unavailable. Use this session only.',tag='vault_unavailable')
        try:self.backend.set_password(self.service,key,value)
        except Exception:raise DropboxError('The operating-system credential store could not save Dropbox authorization.',tag='vault_unavailable') from None
    def delete(self,key):
        if not self.available:raise DropboxError('The operating-system credential store could not remove Dropbox authorization.',tag='vault_unavailable')
        try:
            # PasswordDeleteError can mean a locked/broken store as well as a
            # missing entry. Verify absence instead of assuming deletion worked.
            if self.backend.get_password(self.service,key) is not None:
                self.backend.delete_password(self.service,key)
        except Exception:
            raise DropboxError('The operating-system credential store could not remove Dropbox authorization.',tag='vault_unavailable') from None


class DropboxConnection:
    def __init__(self,owner,transport=None,vault=None):
        self.owner=owner;self._data=owner.DATA.resolve();self._lock=RLock();self.transport=transport or DropboxTransport()
        self.vault=vault if vault is not None else CredentialVault(self._data)
        self._access=None;self._refresh=None;self._expires=0;self._pending=None
        self._generation=secrets.token_urlsafe(24);self._needs_reconnect=False
        value=self._store().setting(SETTING,{})
        if not isinstance(value,dict):value={}
        self._key=value.get('app_key','')
        if not isinstance(self._key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{5,200}',self._key):self._key=''
        self._remember=value.get('remember') is True
        self._account=value.get('account') if self._remember and isinstance(value.get('account'),dict) else None
        self._scopes=[s for s in value.get('scopes',[]) if s in SCOPES] if isinstance(value.get('scopes'),list) else []
        self._saved=bool(self._remember and self._account and value.get('saved'))
        self._cleanup=value.get('cleanup_key') if isinstance(value.get('cleanup_key'),str) else ''
    def _store(self):return Store(self._data/'workbench-sidecar.sqlite3')
    def _credential_key(self,account=None):
        account=account or self._account or {}
        return sha256((str(self._data)+'\0'+self._key+'\0'+str(account.get('account_id',''))).encode()).hexdigest()
    def _save(self):
        # Explicit allowlist: no OAuth codes, verifier, access or refresh tokens.
        self._store().set_setting(SETTING,{'app_key':self._key,'remember':self._remember,
            'account':self._account if self._saved else None,'saved':self._saved,
            'scopes':list(self._scopes) if self._saved else [],'cleanup_key':self._cleanup})
    def _clear_pending_cleanup(self):
        if not self._cleanup:return
        try:self.vault.delete(self._cleanup)
        except DropboxError:
            raise DropboxError('Previous remembered Dropbox authorization could not be removed. Retry Disconnect or choose a session-only connection.',tag='vault_unavailable') from None
        self._cleanup='';self._save()
    def status(self):
        with self._lock:
            active=bool(self._access or self._refresh or self._saved and self.vault.available) and not self._needs_reconnect
            return {'configured':bool(self._key),'app_key':self._key,'remember':self._remember,
                'connected':active,'state':'saved' if active and self._saved else 'session' if active else 'disconnected',
                'connection_id':self._generation,'account':dict(self._account) if self._account and active else None,
                'scopes':list(self._scopes),'vault_available':bool(self.vault.available),
                'secure_storage_available':bool(self.vault.available),'persistent':bool(self._saved),
                'vault_backend':getattr(self.vault,'backend_name','operating_system' if self.vault.available else 'unavailable'),
                'credential_cleanup_pending':bool(self._cleanup),'needs_reconnect':self._needs_reconnect}
    def configure(self,app_key,remember=False):
        key=_public_key(app_key)
        if not isinstance(remember,bool):raise DropboxError('Choose whether Dropbox authorization is remembered.',tag='configuration')
        with self._lock:
            if remember and not self.vault.available:
                raise DropboxError('A supported operating-system credential store is unavailable. Use this session only.',tag='vault_unavailable')
            if self._key and (key!=self._key or remember!=self._remember):self.disconnect()
            # Keep the previous vault entry retryable instead of overwriting its
            # cleanup key with a second remembered account's credential later.
            if remember:self._clear_pending_cleanup()
            self._key=key;self._remember=remember;self._pending=None
            self._generation=secrets.token_urlsafe(24);self._save();return self.status()
    def begin(self,callback_origin):
        origin=_origin(callback_origin)
        with self._lock:
            if not self._key:raise DropboxError('Configure the public Dropbox app key before connecting.',tag='configuration')
            if self._remember and not self.vault.available:
                raise DropboxError('A supported operating-system credential store is unavailable. Use this session only.',tag='vault_unavailable')
            if self._remember:self._clear_pending_cleanup()
            state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(64)
            redirect=origin+'/api/dropbox/callback'
            challenge=base64.urlsafe_b64encode(sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')
            self._pending={'state':state,'verifier':verifier,'created':time.monotonic(),'redirect':redirect,'origin':origin,'key':self._key}
            parameters={'client_id':self._key,'response_type':'code','redirect_uri':redirect,'state':state,
                'code_challenge_method':'S256','code_challenge':challenge,'token_access_type':'offline',
                'scope':' '.join(SCOPES)}
            url='https://www.dropbox.com/oauth2/authorize?'+urlencode(parameters)
            return {'authorize_url':url,'authorization_url':url,
                    'redirect_uri':redirect,'expires_in':600}
    def _account_info(self,value):
        if not isinstance(value,dict) or not isinstance(value.get('account_id'),str) or not value['account_id'].startswith('dbid:') or len(value['account_id'])>200:
            raise DropboxError('Dropbox did not return a valid account identity.',tag='invalid_response')
        roots=value.get('root_info') or {}
        if not isinstance(roots,dict) or not isinstance(value.get('name') or {},dict):
            raise DropboxError('Dropbox did not return a valid account identity.',tag='invalid_response')
        return {'account_id':value['account_id'],'display_name':str((value.get('name') or {}).get('display_name') or '')[:200],
                'email':str(value.get('email') or '')[:320],
                'root_namespace_id':_namespace(roots.get('root_namespace_id')),
                'home_namespace_id':_namespace(roots.get('home_namespace_id'))}
    def _token_values(self,value,*,refreshing=False):
        if not isinstance(value,dict) or not _secret(value.get('access_token')):
            raise DropboxError('Dropbox did not return valid authorization.',tag='invalid_response')
        try:
            expires=float(value.get('expires_in'))
            if not math.isfinite(expires) or not 0<expires<=31*86400:raise ValueError()
        except (ValueError,TypeError):raise DropboxError('Dropbox did not return a valid authorization expiry.',tag='invalid_response') from None
        refresh=value.get('refresh_token') or (self._refresh if refreshing else None)
        if not _secret(refresh):raise DropboxError('Dropbox did not return renewable authorization. Connect again.',tag='invalid_response')
        scope=value.get('scope')
        scopes=sorted({s for s in scope.split() if s in SCOPES}) if isinstance(scope,str) else list(self._scopes) if refreshing else []
        return value['access_token'],refresh,time.monotonic()+expires,scopes
    def callback(self,state,code,error=None,callback_origin=None):
        with self._lock:
            pending=self._pending
            if not isinstance(state,str) or not pending or not secrets.compare_digest(state,pending['state']):
                raise DropboxError('Dropbox sign-in state is invalid or expired. Start Connect again.',tag='oauth_state')
            self._pending=None  # A matched callback is consumed even when consent is declined.
            if callback_origin is None and has_request_context():callback_origin=request.host_url.rstrip('/')
            if callback_origin is not None and _origin(callback_origin)!=pending['origin']:
                raise DropboxError('Dropbox sign-in returned to another local address. Start Connect again.',tag='oauth_state')
            if pending['key']!=self._key or not 0<=time.monotonic()-pending['created']<=600:
                raise DropboxError('Dropbox sign-in state is invalid or expired. Start Connect again.',tag='oauth_state')
            if error is not None:raise DropboxError('Dropbox sign-in was not approved. You can connect again.',tag='oauth_denied')
            if not _secret(code) or len(code)>4096:raise DropboxError('Dropbox did not return a valid authorization code.',tag='oauth_state')
            value=self.transport.token({'grant_type':'authorization_code','client_id':self._key,'code':code,
                'redirect_uri':pending['redirect'],'code_verifier':pending['verifier']})
            access,refresh,expires,scopes=self._token_values(value)
            account=self._account_info(self.transport.rpc('users/get_current_account',None,access))
            if value.get('account_id') and value['account_id']!=account['account_id']:
                raise DropboxError('Dropbox returned inconsistent account identities. Connect again.',tag='account_mismatch')
            if self._account and self._account['account_id']!=account['account_id']:
                raise DropboxError('A different Dropbox account signed in. Disconnect before switching accounts.',tag='account_mismatch')
            if self._remember:
                self._clear_pending_cleanup()
                self.vault.set(self._credential_key(account),json.dumps({'refresh_token':refresh,'account_id':account['account_id'],'app_key':self._key},separators=(',',':')))
            self._access=access;self._refresh=refresh;self._expires=expires;self._scopes=scopes;self._account=account
            self._saved=self._remember;self._needs_reconnect=False;self._generation=secrets.token_urlsafe(24)
            self._save();return self.status()
    def _ensure_access(self):
        if self._needs_reconnect:raise DropboxError('Reconnect Dropbox to authorize this request.',tag='invalid_access_token')
        if self._access and time.monotonic()<self._expires-30:return self._access
        if not self._refresh and self._saved:
            raw=self.vault.get(self._credential_key())
            try:
                value=json.loads(raw or '{}')
                if value.get('app_key')!=self._key or value.get('account_id')!=(self._account or {}).get('account_id') or not _secret(value.get('refresh_token')):raise ValueError()
                self._refresh=value['refresh_token']
            except (ValueError,TypeError,AttributeError):
                self._needs_reconnect=True;raise DropboxError('Saved Dropbox authorization is unavailable. Connect again.',tag='invalid_access_token') from None
        if not self._refresh:raise DropboxError('Connect Dropbox before checking remote files.',tag='not_connected')
        try:
            value=self.transport.token({'grant_type':'refresh_token','client_id':self._key,'refresh_token':self._refresh})
            access,refresh,expires,scopes=self._token_values(value,refreshing=True)
            account=self._account_info(self.transport.rpc('users/get_current_account',None,access))
            if account['account_id']!=(self._account or {}).get('account_id') or value.get('account_id') and value['account_id']!=account['account_id']:
                raise DropboxError('Dropbox authorization belongs to another account. Connect again.',tag='account_mismatch')
            if self._remember and refresh!=self._refresh:
                self.vault.set(self._credential_key(account),json.dumps({'refresh_token':refresh,'account_id':account['account_id'],'app_key':self._key},separators=(',',':')))
            self._access=access;self._refresh=refresh;self._expires=expires;self._scopes=scopes;self._account=account
            self._save();return access
        except DropboxError as error:
            if error.tag in ('invalid_grant','invalid_access_token','expired_access_token','account_mismatch'):
                self._access=None;self._needs_reconnect=True
            raise
    def rpc(self,route,payload,path_root=None):
        if route not in RPC_ROUTES:raise DropboxError('This Dropbox operation is not supported.',tag='invalid_argument')
        if path_root is not None:path_root=_path_root(path_root)
        if payload is not None and not isinstance(payload,dict):raise DropboxError('Provide a Dropbox metadata request.',tag='invalid_argument')
        with self._lock:
            access=self._ensure_access()
            try:return self.transport.rpc(route,payload,access,path_root)
            except DropboxError as error:
                if error.status!=401:raise
                self._access=None;self._expires=0
                access=self._ensure_access()
                try:return self.transport.rpc(route,payload,access,path_root)
                except DropboxError as repeated:
                    if repeated.status==401:self._access=None;self._needs_reconnect=True
                    raise
    def download(self,path_or_id,rev=None,namespace=None):
        if not isinstance(path_or_id,str) or not 1<=len(path_or_id)<=4096 or not (path_or_id.startswith('/') or path_or_id.startswith('id:')) or any(ord(c)<32 for c in path_or_id):
            raise DropboxError('Choose a verified Dropbox file.',tag='invalid_argument')
        if rev is not None and (not isinstance(rev,str) or not re.fullmatch(r'[A-Za-z0-9]{1,200}',rev)):
            raise DropboxError('Choose a verified Dropbox file revision.',tag='invalid_argument')
        if namespace is not None:namespace=_namespace(namespace)
        with self._lock:
            access=self._ensure_access()
            try:return self.transport.download(path_or_id,rev,access,namespace)
            except DropboxError as error:
                if error.status!=401:raise
                self._access=None;self._expires=0
                access=self._ensure_access()
                try:return self.transport.download(path_or_id,rev,access,namespace)
                except DropboxError as repeated:
                    if repeated.status==401:self._access=None;self._needs_reconnect=True
                    raise
    def disconnect(self):
        with self._lock:
            key=self._credential_key() if self._saved else ''
            revoked=False
            try:
                if self._access or self._refresh or self._saved:
                    self.transport.rpc('auth/token/revoke',None,self._ensure_access());revoked=True
            except DropboxError:pass
            self._access=None;self._refresh=None;self._expires=0;self._pending=None;self._saved=False
            self._account=None;self._scopes=[];self._needs_reconnect=False;self._generation=secrets.token_urlsafe(24)
            self._cleanup=key or self._cleanup;self._save()
            if self._cleanup:
                try:self.vault.delete(self._cleanup);self._cleanup='';self._save()
                except DropboxError:pass
            return {'disconnected':True,'remote_revoked':revoked,'vault_cleared':not bool(self._cleanup)}
