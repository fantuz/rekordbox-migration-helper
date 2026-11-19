"""Google desktop OAuth with PKCE and optional OS-backed renewal credentials.

Google documents desktop apps as public clients and client_secret as optional:
https://developers.google.com/identity/protocols/oauth2/native-app
"""
import base64
from hashlib import sha256
import json
import math
import re
import secrets
from threading import RLock
import time
from urllib.parse import urlencode,urlsplit

from flask import has_request_context,request
from dropbox_auth import CredentialVault as DropboxVault
from dropbox_http import DropboxError
from google_drive_http import GoogleDriveError,GoogleDriveTransport,ACCOUNT_FIELDS,FILE_FIELDS,file_id
from workbench_store import Store

SCOPES=('https://www.googleapis.com/auth/drive.readonly',)
SETTING='google_drive_connection_v1'
RPC_ROUTES={'about/get','files/get','files/list'}


def _client_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{5,250}\.apps\.googleusercontent\.com',value):
        raise GoogleDriveError('Enter the Google Desktop app client ID from Google Cloud Console.',tag='configuration')
    return value


def _secret(value):
    return isinstance(value,str) and 1<=len(value)<=65536 and all(32<=ord(c)<127 for c in value)


def _origin(value):
    try:
        parsed=urlsplit(value)
        valid=(parsed.scheme=='http' and parsed.hostname=='127.0.0.1' and parsed.port is not None
               and 1<=parsed.port<=65535 and parsed.path in ('','/') and not parsed.username
               and not parsed.password and not parsed.query and not parsed.fragment)
    except (ValueError,TypeError):valid=False
    if not valid:raise GoogleDriveError('Use the local 127.0.0.1 Workbench callback address.',tag='configuration')
    return 'http://127.0.0.1:'+str(parsed.port)


class CredentialVault(DropboxVault):
    """Use the existing approved OS backend policy with a distinct service."""
    def __init__(self,profile):
        super().__init__(profile)
        self.service='LibraryWorkbench.GoogleDrive.'+sha256(str(profile).encode()).hexdigest()[:24]
    def _call(self,name,*args):
        try:return getattr(super(),name)(*args)
        except DropboxError as error:
            raise GoogleDriveError(str(error).replace('Dropbox','Google Drive'),tag=error.tag) from None
    def get(self,key):return self._call('get',key)
    def set(self,key,value):return self._call('set',key,value)
    def delete(self,key):return self._call('delete',key)


class GoogleDriveConnection:
    def __init__(self,owner,transport=None,vault=None):
        self.owner=owner;self._data=owner.DATA.resolve();self._lock=RLock()
        self.transport=transport or GoogleDriveTransport()
        self.vault=vault if vault is not None else CredentialVault(self._data)
        self._access=None;self._refresh=None;self._expires=0;self._pending=None;self._client_secret=None
        self._generation=secrets.token_urlsafe(24);self._needs_reconnect=False
        value=self._store().setting(SETTING,{})
        if not isinstance(value,dict):value={}
        try:self._key=_client_id(value.get('client_id'))
        except GoogleDriveError:self._key=''
        self._remember=value.get('remember') is True
        self._account=value.get('account') if self._remember and isinstance(value.get('account'),dict) else None
        self._scopes=[s for s in value.get('scopes',[]) if s in SCOPES] if isinstance(value.get('scopes'),list) else []
        self._saved=bool(self._remember and self._account and value.get('saved'))
        self._secret_saved=bool(self._saved and value.get('client_secret_saved'))
        self._cleanup=value.get('cleanup_key') if isinstance(value.get('cleanup_key'),str) else ''
    def _store(self):return Store(self._data/'workbench-sidecar.sqlite3')
    def _credential_key(self,account=None):
        account=account or self._account or {}
        return sha256((str(self._data)+'\0'+self._key+'\0'+str(account.get('account_id',''))).encode()).hexdigest()
    def _save(self):
        # Public configuration and account labels only, never OAuth/token secrets.
        self._store().set_setting(SETTING,{'client_id':self._key,'remember':self._remember,
            'account':self._account if self._saved else None,'saved':self._saved,
            'scopes':list(self._scopes) if self._saved else [],'cleanup_key':self._cleanup,
            'client_secret_saved':self._secret_saved if self._saved else False})
    def _clear_pending_cleanup(self):
        if not self._cleanup:return
        try:self.vault.delete(self._cleanup)
        except (GoogleDriveError,DropboxError):
            raise GoogleDriveError('Previous remembered Google authorization could not be removed. Retry Disconnect or choose a session-only connection.',tag='vault_unavailable') from None
        self._cleanup='';self._save()
    def _credential(self,account,refresh):
        value={'refresh_token':refresh,'account_id':account['account_id'],'client_id':self._key}
        if self._client_secret:value['client_secret']=self._client_secret
        return json.dumps(value,separators=(',',':'))
    def status(self):
        with self._lock:
            active=bool(self._access or self._refresh or self._saved and self.vault.available) and not self._needs_reconnect
            return {'configured':bool(self._key),'client_id':self._key,'remember':self._remember,
                'client_secret_configured':bool(self._client_secret or self._secret_saved),
                'connected':active,'state':'saved' if active and self._saved else 'session' if active else 'disconnected',
                'connection_id':self._generation,'account':dict(self._account) if self._account and active else None,
                'scopes':list(self._scopes),'vault_available':bool(self.vault.available),
                'secure_storage_available':bool(self.vault.available),'persistent':bool(self._saved),
                'vault_backend':getattr(self.vault,'backend_name','operating_system' if self.vault.available else 'unavailable'),
                'credential_cleanup_pending':bool(self._cleanup),'needs_reconnect':self._needs_reconnect}
    def configure(self,client_id,client_secret=None,remember=False):
        key=_client_id(client_id)
        if type(remember) is not bool:raise GoogleDriveError('Choose whether Google authorization is remembered.',tag='configuration')
        if client_secret is not None and (not isinstance(client_secret,str) or len(client_secret)>4096 or client_secret and not _secret(client_secret)):
            raise GoogleDriveError('Enter a valid optional desktop client secret or leave it empty.',tag='configuration')
        with self._lock:
            if remember and not self.vault.available:
                raise GoogleDriveError('A supported operating-system credential store is unavailable. Use this session only.',tag='vault_unavailable')
            secret_changed=(client_secret is not None and
                (client_secret!=(self._client_secret or '') or client_secret=='' and self._secret_saved))
            changed=bool(self._key and (key!=self._key or remember!=self._remember or secret_changed))
            old_secret=self._client_secret if key==self._key else None
            if changed:self.disconnect()
            if remember:self._clear_pending_cleanup()
            self._key=key;self._remember=remember;self._pending=None
            self._client_secret=(client_secret or None) if client_secret is not None else old_secret
            self._generation=secrets.token_urlsafe(24);self._save();return self.status()
    def begin(self,callback_origin):
        origin=_origin(callback_origin)
        with self._lock:
            if not self._key:raise GoogleDriveError('Configure the Google Desktop app client ID before connecting.',tag='configuration')
            if self._remember and not self.vault.available:
                raise GoogleDriveError('A supported operating-system credential store is unavailable. Use this session only.',tag='vault_unavailable')
            if self._remember:self._clear_pending_cleanup()
            if self._saved and self._secret_saved and not self._client_secret:
                # Beginning a new grant is an explicit action. Restore the
                # optional desktop credential here, never while showing status.
                self._load_credential()
            state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(64)
            redirect=origin+'/api/google-drive/callback'
            challenge=base64.urlsafe_b64encode(sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')
            self._pending={'state':state,'verifier':verifier,'created':time.monotonic(),'redirect':redirect,'origin':origin,'key':self._key}
            parameters={'client_id':self._key,'response_type':'code','redirect_uri':redirect,'state':state,
                'code_challenge_method':'S256','code_challenge':challenge,'access_type':'offline',
                'prompt':'consent','scope':' '.join(SCOPES)}
            url='https://accounts.google.com/o/oauth2/v2/auth?'+urlencode(parameters)
            return {'authorize_url':url,'authorization_url':url,'redirect_uri':redirect,'expires_in':600}
    def _account_info(self,value):
        user=value.get('user') if isinstance(value,dict) else None
        if not isinstance(user,dict) or not isinstance(user.get('permissionId'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}',user['permissionId']):
            raise GoogleDriveError('Google Drive did not return a valid account identity.',tag='invalid_response')
        return {'account_id':user['permissionId'],'permission_id':user['permissionId'],
                'name':str(user.get('displayName') or '')[:200],'display_name':str(user.get('displayName') or '')[:200],
                'email':str(user.get('emailAddress') or '')[:320]}
    def _token_values(self,value,*,refreshing=False):
        if not isinstance(value,dict) or not _secret(value.get('access_token')) or str(value.get('token_type','Bearer')).lower()!='bearer':
            raise GoogleDriveError('Google did not return valid authorization.',tag='invalid_response')
        try:
            if isinstance(value.get('expires_in'),bool):raise ValueError()
            expires=float(value.get('expires_in'))
            if not math.isfinite(expires) or not 0<expires<=31*86400:raise ValueError()
        except (ValueError,TypeError):raise GoogleDriveError('Google did not return a valid authorization expiry.',tag='invalid_response') from None
        refresh=value.get('refresh_token') or (self._refresh if refreshing else None)
        if not _secret(refresh):raise GoogleDriveError('Google did not return renewable authorization. Connect again.',tag='invalid_response')
        scope=value.get('scope')
        scopes=sorted({s for s in scope.split() if s in SCOPES}) if isinstance(scope,str) else list(self._scopes) if refreshing else []
        if not set(SCOPES)<=set(scopes):raise GoogleDriveError('Google did not grant read-only Drive access. Connect again.',tag='insufficient_scope')
        return value['access_token'],refresh,time.monotonic()+expires,scopes
    def _parameters(self,parameters):
        result={'client_id':self._key,**parameters}
        if self._client_secret:result['client_secret']=self._client_secret
        return result
    def callback(self,state,code,error=None,callback_origin=None):
        with self._lock:
            pending=self._pending
            if not isinstance(state,str) or not pending or not secrets.compare_digest(state,pending['state']):
                raise GoogleDriveError('Google sign-in state is invalid or expired. Start Connect again.',tag='oauth_state')
            self._pending=None
            if callback_origin is None and has_request_context():callback_origin=request.host_url.rstrip('/')
            if callback_origin is not None and _origin(callback_origin)!=pending['origin']:
                raise GoogleDriveError('Google sign-in returned to another local address. Start Connect again.',tag='oauth_state')
            if pending['key']!=self._key or not 0<=time.monotonic()-pending['created']<=600:
                raise GoogleDriveError('Google sign-in state is invalid or expired. Start Connect again.',tag='oauth_state')
            if error is not None:raise GoogleDriveError('Google sign-in was not approved. You can connect again.',tag='oauth_denied')
            if not _secret(code) or len(code)>4096:raise GoogleDriveError('Google did not return a valid authorization code.',tag='oauth_state')
            value=self.transport.token(self._parameters({'grant_type':'authorization_code','code':code,
                'redirect_uri':pending['redirect'],'code_verifier':pending['verifier']}))
            access,refresh,expires,scopes=self._token_values(value)
            account=self._account_info(self.transport.rpc('about/get',{'fields':ACCOUNT_FIELDS},access))
            if self._account and self._account['account_id']!=account['account_id']:
                raise GoogleDriveError('A different Google account signed in. Disconnect before switching accounts.',tag='account_mismatch')
            if self._remember:
                self._clear_pending_cleanup();self.vault.set(self._credential_key(account),self._credential(account,refresh))
            self._access=access;self._refresh=refresh;self._expires=expires;self._scopes=scopes;self._account=account
            self._saved=self._remember;self._secret_saved=bool(self._saved and self._client_secret)
            self._needs_reconnect=False;self._generation=secrets.token_urlsafe(24)
            self._save();return self.status()
    def _load_credential(self):
        raw=self.vault.get(self._credential_key())
        try:
            value=json.loads(raw or '{}')
            if value.get('client_id')!=self._key or value.get('account_id')!=(self._account or {}).get('account_id') or not _secret(value.get('refresh_token')):raise ValueError()
            if self._secret_saved and not _secret(value.get('client_secret')):raise ValueError()
            self._refresh=value['refresh_token']
            self._client_secret=value.get('client_secret') or None
        except (ValueError,TypeError,AttributeError):
            self._needs_reconnect=True;raise GoogleDriveError('Saved Google authorization is unavailable. Connect again.',tag='invalid_access_token') from None
    def _ensure_access(self):
        if self._needs_reconnect:raise GoogleDriveError('Reconnect Google Drive to authorize this request.',tag='invalid_access_token')
        if self._access and time.monotonic()<self._expires-30:return self._access
        if not self._refresh and self._saved:self._load_credential()
        if not self._refresh:raise GoogleDriveError('Connect Google Drive before checking remote files.',tag='not_connected')
        try:
            value=self.transport.token(self._parameters({'grant_type':'refresh_token','refresh_token':self._refresh}))
            access,refresh,expires,scopes=self._token_values(value,refreshing=True)
            account=self._account_info(self.transport.rpc('about/get',{'fields':ACCOUNT_FIELDS},access))
            if account['account_id']!=(self._account or {}).get('account_id'):
                raise GoogleDriveError('Google authorization belongs to another account. Connect again.',tag='account_mismatch')
            if self._remember and refresh!=self._refresh:self.vault.set(self._credential_key(account),self._credential(account,refresh))
            self._access=access;self._refresh=refresh;self._expires=expires;self._scopes=scopes;self._account=account
            self._save();return access
        except GoogleDriveError as error:
            if error.tag in ('invalid_grant','invalid_access_token','invalid_token','account_mismatch'):
                self._access=None;self._needs_reconnect=True
            raise
    def rpc(self,route,payload=None):
        if route not in RPC_ROUTES:raise GoogleDriveError('This Google Drive operation is not supported.',tag='invalid_argument')
        if payload is not None and not isinstance(payload,dict):raise GoogleDriveError('Provide a Google Drive metadata request.',tag='invalid_argument')
        with self._lock:
            access=self._ensure_access()
            try:return self.transport.rpc(route,payload or {},access)
            except GoogleDriveError as error:
                if error.status!=401:raise
                self._access=None;self._expires=0;access=self._ensure_access()
                try:return self.transport.rpc(route,payload or {},access)
                except GoogleDriveError as repeated:
                    if repeated.status==401:self._access=None;self._needs_reconnect=True
                    raise
    def download(self,identity,version=None,**_kwargs):
        identity=file_id(identity)
        if version is not None and (not isinstance(version,(str,int)) or isinstance(version,bool) or not re.fullmatch(r'[A-Za-z0-9._-]{1,200}',str(version))):
            raise GoogleDriveError('Choose a verified Google Drive file version.',tag='invalid_argument')
        with self._lock:
            metadata=self.rpc('files/get',{'fileId':identity,'fields':FILE_FIELDS,'supportsAllDrives':True})
            capabilities=metadata.get('capabilities') if isinstance(metadata,dict) else None
            if (not isinstance(metadata,dict) or capabilities is not None and not isinstance(capabilities,dict)
                    or metadata.get('id')!=identity or metadata.get('trashed') is True
                    or str(metadata.get('mimeType','')).startswith('application/vnd.google-apps.')
                    or (capabilities or {}).get('canDownload') is False
                    or version is not None and str(metadata.get('version'))!=str(version)):
                raise GoogleDriveError('Google Drive file details changed or downloading is unavailable. Check this track again.',tag='revision_changed')
            access=self._ensure_access()
            try:return self.transport.download(identity,access,metadata)
            except GoogleDriveError as error:
                if error.status!=401:raise
                self._access=None;self._expires=0;access=self._ensure_access()
                # Recheck the pinned metadata after account renewal as well.
                fresh=self.rpc('files/get',{'fileId':identity,'fields':FILE_FIELDS,'supportsAllDrives':True})
                if any(fresh.get(k)!=metadata.get(k) for k in ('id','version','size','md5Checksum','sha256Checksum',
                        'trashed','mimeType','name','parents','driveId','capabilities','modifiedTime')):
                    raise GoogleDriveError('The Google Drive file changed. Confirm this track again.',tag='revision_changed')
                try:return self.transport.download(identity,access,fresh)
                except GoogleDriveError as repeated:
                    if repeated.status==401:self._access=None;self._needs_reconnect=True
                    raise
    def disconnect(self):
        with self._lock:
            key=self._credential_key() if self._saved else '';revoked=False
            try:
                if not self._refresh and self._saved:self._load_credential()
                token=self._refresh or self._access
                if token:self.transport.revoke(token);revoked=True
            except (GoogleDriveError,DropboxError):pass
            self._access=None;self._refresh=None;self._client_secret=None;self._expires=0;self._pending=None
            self._saved=False;self._secret_saved=False;self._account=None;self._scopes=[];self._needs_reconnect=False
            self._generation=secrets.token_urlsafe(24);self._cleanup=key or self._cleanup;self._save()
            if self._cleanup:
                try:self.vault.delete(self._cleanup);self._cleanup='';self._save()
                except (GoogleDriveError,DropboxError):pass
            return {'disconnected':True,'remote_revoked':revoked,'vault_cleared':not bool(self._cleanup)}
