"""Bounded Dropbox HTTPS transport. No redirects, logging, or arbitrary hosts."""
import http.client
import json
import math
import re
import ssl

API_HOST='api.dropboxapi.com'
CONTENT_HOST='content.dropboxapi.com'
JSON_LIMIT=4*1024*1024
ERROR_LIMIT=64*1024
MAX_DOWNLOAD=64*1024**3


class DropboxError(ValueError):
    """Safe public failure; never include provider bodies or authorization values."""
    def __init__(self,message='Dropbox could not complete this request. Try again.',*,status=0,tag='unavailable',retry_after=None,request_id=None):
        super().__init__(message)
        self.status=status if isinstance(status,int) and not isinstance(status,bool) and 100<=status<=599 else 0
        self.tag=tag if isinstance(tag,str) and re.fullmatch(r'[a-z][a-z0-9_]{0,63}',tag) else 'unavailable'
        self.retry_after=retry_after if isinstance(retry_after,(int,float)) and not isinstance(retry_after,bool) and 0<=retry_after<=86400 and math.isfinite(retry_after) else None
        self.request_id=_request_id(request_id)

    def public_fields(self):
        """Allowlisted diagnostics for JSON responses; never return the HTTP body."""
        fields={'provider':'dropbox','tag':self.tag}
        if self.status:fields['http_status']=self.status
        if self.request_id:fields['request_id']=self.request_id
        if self.retry_after is not None:fields['retry_after']=self.retry_after
        return fields


_TAGS={'not_found','not_file','not_folder','malformed_path','restricted_content','disallowed_name',
       'invalid_access_token','expired_access_token','invalid_grant','insufficient_scope','insufficient_scopes','missing_scope',
       'access_denied','rate_limit','too_many_requests','too_many_write_operations','user_suspended',
       'no_permission','invalid_root','unsupported_content_type','invalid_argument','route_access_denied',
       'restricted_by_team','team_policy_disallows_member_policy'}
_SCOPE_GUIDANCE='In the Dropbox App Console, enable account_info.read, files.metadata.read and files.content.read, save, then disconnect and connect again to grant them.'


def _request_id(value):
    # Dropbox's support identifier is opaque, not a URL, body excerpt or header
    # dump. Reject whitespace, control characters, Unicode and excessive sizes.
    return value if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}',value) else None


def _header(headers,name):
    # HTTPMessage is case insensitive; this also handles plain mocked mappings.
    for key,value in headers.items():
        if isinstance(key,str) and key.lower()==name.lower():return value
    return None


def _plaintext_tag(body):
    """Recognize explicit request rejections without publishing provider text.

    HTTP 400 is also used for malformed input, so neither its status nor a Path
    Root mention alone proves an App Folder or team policy restriction.
    """
    if not isinstance(body,(str,bytes)):return None
    text=body.decode('utf-8',errors='replace') if isinstance(body,bytes) else body
    text=' '.join(text[:ERROR_LIMIT].lower().split())
    denied=re.search(r'\b(?:not permitted|not allowed|cannot|can\x27t|does not support|not supported|unsupported|requires?)\b',text)
    app_folder=re.search(r'\bapp[ -]folder (?:apps?|access|permission)\b',text)
    if denied and ((app_folder and 'dropbox-api-path-root' in text)
                   or re.search(r'\brequires? (?:an? app with )?full dropbox access\b',text)):
        return 'app_folder_access'
    if (re.search(r'\b(?:not configured with (?:the )?required|missing (?:the )?required|does not have (?:the )?required) scope\b',text)
            or re.search(r'\binsufficient scope\b',text)):
        return 'missing_scope'
    if re.search(r'\b(?:invalid|bad|malformed|unsupported) (?:http )?[\x27\"]?dropbox-api-path-root[\x27\"]? header\b',text):
        return 'invalid_path_root'
    return None


def _provider_error(status,body,headers):
    tags=[]
    parsed=False
    try:
        value=json.loads(body[:ERROR_LIMIT])
        parsed=True
        def visit(node,depth=0):
            if depth>5:return
            if isinstance(node,dict):
                tag=node.get('.tag')
                if isinstance(tag,str) and tag in _TAGS:tags.append(tag)
                if isinstance(node.get('error'),str) and node['error'] in _TAGS:tags.append(node['error'])
                for key,item in node.items():
                    if key in ('error','path','reason','lookup_failed','invalid_root'):visit(item,depth+1)
        visit(value)
        # Dropbox documents a stable error_summary prefix, with arbitrary detail
        # following it. Only recognize known enum tokens, never echo the suffix.
        if not tags and isinstance(value,dict) and isinstance(value.get('error_summary'),str):
            for part in value['error_summary'].split('/')[:6]:
                if part in _TAGS:tags.append(part)
                elif part not in ('path','path_lookup','lookup_failed','reason','auth','access_error'):break
    except (ValueError,TypeError,RecursionError,UnicodeError):pass
    tag=tags[-1] if tags else 'unavailable'
    if status==400 and not parsed:tag=_plaintext_tag(body) or tag
    if status==401 and tag=='unavailable':tag='invalid_access_token'
    if status==429:tag='rate_limit'
    retry=None
    try:
        retry=float(_header(headers,'Retry-After'))
        if not math.isfinite(retry) or not 0<=retry<=86400:retry=None
    except (TypeError,ValueError):pass
    request_id=_request_id(_header(headers,'X-Dropbox-Request-Id'))
    message={
        'invalid_access_token':'Reconnect Dropbox to authorize this request.',
        'expired_access_token':'Reconnect Dropbox to authorize this request.',
        'invalid_grant':'Dropbox authorization expired or was revoked. Connect again.',
        'insufficient_scope':_SCOPE_GUIDANCE,
        'insufficient_scopes':_SCOPE_GUIDANCE,
        'missing_scope':_SCOPE_GUIDANCE,
        'not_found':'Dropbox could not find this path in the selected account and folder.',
        'invalid_root':'The selected Dropbox root namespace has changed. Reconnect, choose the matching Member home or Team root namespace, and verify the folder again.',
        'invalid_path_root':'Dropbox rejected the folder namespace header. Choose the matching Member home or Team root namespace and verify the folder again.',
        'app_folder_access':'Dropbox rejected access outside this app folder. Register a Full Dropbox app to inspect an existing Rekordbox library, then connect again and select only the required music folder.',
        'rate_limit':'Dropbox is temporarily limiting requests. Wait before trying again.',
        'no_permission':'This Dropbox account cannot access the selected file, folder or namespace. Choose the matching Member home or Team root namespace and verify access.',
        'access_denied':'Dropbox denied this operation. Confirm that the connected account can access the selected folder.',
        'route_access_denied':'Dropbox does not allow this API operation for the connected app. Check the app configuration and account access.',
        'user_suspended':'Dropbox reports that this user is suspended. Ask the team administrator to restore account access.',
        'restricted_by_team':'Dropbox reports that team policy blocks this operation. Ask the team administrator to review the app and folder permissions.',
        'team_policy_disallows_member_policy':'Dropbox reports that team policy blocks this operation. Ask the team administrator to review the app and folder permissions.',
    }.get(tag)
    if message is None:
        if status==400:message='Dropbox rejected this request. Check the folder namespace and app API permissions before trying again.'
        elif status==403:message='Dropbox denied access to this operation. Check account access and, for a team account, ask its administrator to confirm this app is allowed.'
        elif isinstance(status,int) and 500<=status<=599:message='Dropbox is temporarily unable to complete this request. Try again later.'
        else:message='Dropbox could not complete this request. Check the selected account and folder before trying again.'
    failure=DropboxError(message,status=status,tag=tag,retry_after=retry,request_id=request_id)
    details=[]
    if failure.status:details.append('HTTP '+str(failure.status))
    details.append('code: '+failure.tag)
    if failure.request_id:details.append('request ID: '+failure.request_id)
    failure.args=(message+' ('+'; '.join(details)+')',)
    return failure


class DownloadResponse:
    def __init__(self,connection,response):
        self._connection=connection;self._response=response;self._read=0;self._closed=False
        raw=response.getheader('Dropbox-API-Result','')
        try:
            if len(raw)>ERROR_LIMIT:raise ValueError()
            self.metadata=json.loads(raw)
            if not isinstance(self.metadata,dict):raise ValueError()
            length=response.getheader('Content-Length')
            self.length=int(length) if length is not None else None
            if self.length is not None and not 0<=self.length<=MAX_DOWNLOAD:raise ValueError()
        except (ValueError,TypeError):
            self.close();raise DropboxError('Dropbox returned invalid file metadata.',tag='invalid_response') from None
    def read(self,size=128*1024):
        if self._closed:return b''
        if not isinstance(size,int) or isinstance(size,bool) or not 1<=size<=1024*1024:
            raise ValueError('Read Dropbox downloads in bounded chunks.')
        try:chunk=self._response.read(size)
        except (OSError,http.client.HTTPException):
            self.close();raise DropboxError('The Dropbox download was interrupted. Try this one track again.',tag='interrupted') from None
        self._read+=len(chunk)
        if self._read>MAX_DOWNLOAD or self.length is not None and self._read>self.length:
            self.close();raise DropboxError('Dropbox returned an unexpected file size.',tag='invalid_response')
        if not chunk and self.length is not None and self._read!=self.length:
            self.close();raise DropboxError('The Dropbox download was incomplete.',tag='interrupted')
        return chunk
    def iter_chunks(self,size=128*1024):
        while chunk:=self.read(size):yield chunk
    def close(self):
        if not self._closed:
            self._closed=True
            try:self._response.close()
            finally:self._connection.close()
    def __enter__(self):return self
    def __exit__(self,*_):self.close()


class DropboxTransport:
    def __init__(self,timeout=25):self.timeout=timeout
    def _request(self,host,path,body,headers,download=False):
        connection=http.client.HTTPSConnection(host,timeout=self.timeout,context=ssl.create_default_context())
        try:
            connection.request('POST',path,body=body,headers={**headers,'User-Agent':'Library-Workbench-Dropbox/1'})
            response=connection.getresponse()
            if not 200<=response.status<300:
                content=response.read(ERROR_LIMIT+1)
                failure=_provider_error(response.status,content[:ERROR_LIMIT],response.headers)
                response.close();connection.close();raise failure
            if download:return DownloadResponse(connection,response)
            raw=response.read(JSON_LIMIT+1)
            if len(raw)>JSON_LIMIT:raise DropboxError('Dropbox returned too much metadata. Choose a smaller folder.',tag='response_too_large')
            if not raw.strip():return {}
            try:value=json.loads(raw)
            except (ValueError,UnicodeError):raise DropboxError('Dropbox returned invalid metadata.',tag='invalid_response') from None
            if value is not None and not isinstance(value,dict):raise DropboxError('Dropbox returned invalid metadata.',tag='invalid_response')
            return value or {}
        except DropboxError:
            connection.close();raise
        except (OSError,http.client.HTTPException,ValueError):
            connection.close();raise DropboxError('Dropbox could not be reached securely. Check your connection and try again.',tag='network') from None
        finally:
            if not download:connection.close()
    def token(self,parameters):
        from urllib.parse import urlencode
        return self._request(API_HOST,'/oauth2/token',urlencode(parameters).encode('ascii'),{'Content-Type':'application/x-www-form-urlencoded'})
    def rpc(self,route,payload,access_token,path_root=None):
        headers={'Authorization':'Bearer '+access_token,'Content-Type':'application/json'}
        if path_root:
            root=path_root if isinstance(path_root,dict) else {'.tag':'root','root':path_root}
            headers['Dropbox-API-Path-Root']=json.dumps(root,separators=(',',':'))
        return self._request(API_HOST,'/2/'+route,json.dumps(payload,separators=(',',':')).encode('utf-8'),headers)
    def download(self,path,rev,access_token,namespace=None):
        argument={'path':path}
        if rev is not None:argument['rev']=rev
        headers={'Authorization':'Bearer '+access_token,'Dropbox-API-Arg':json.dumps(argument,ensure_ascii=True,separators=(',',':'))}
        if namespace:headers['Dropbox-API-Path-Root']=json.dumps({'.tag':'namespace_id','namespace_id':namespace},separators=(',',':'))
        return self._request(CONTENT_HOST,'/2/files/download',b'',headers,download=True)
