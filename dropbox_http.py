"""Bounded Dropbox HTTPS transport. No redirects, logging, or arbitrary hosts."""
import http.client
import json
import math
import ssl

API_HOST='api.dropboxapi.com'
CONTENT_HOST='content.dropboxapi.com'
JSON_LIMIT=4*1024*1024
ERROR_LIMIT=64*1024
MAX_DOWNLOAD=64*1024**3


class DropboxError(ValueError):
    """Safe public failure; never include provider bodies or authorization values."""
    def __init__(self,message='Dropbox could not complete this request. Try again.',*,status=0,tag='unavailable',retry_after=None):
        super().__init__(message);self.status=status;self.tag=tag;self.retry_after=retry_after


_TAGS={'not_found','not_file','not_folder','malformed_path','restricted_content','disallowed_name',
       'invalid_access_token','expired_access_token','invalid_grant','insufficient_scope','missing_scope',
       'access_denied','rate_limit','too_many_requests','too_many_write_operations','user_suspended',
       'no_permission','invalid_root','unsupported_content_type','invalid_argument'}


def _provider_error(status,body,headers):
    tags=[]
    try:
        value=json.loads(body)
        def visit(node,depth=0):
            if depth>5:return
            if isinstance(node,dict):
                tag=node.get('.tag')
                if tag in _TAGS:tags.append(tag)
                if isinstance(node.get('error'),str) and node['error'] in _TAGS:tags.append(node['error'])
                for key,item in node.items():
                    if key in ('error','path','reason','lookup_failed','invalid_root'):visit(item,depth+1)
        visit(value)
    except (ValueError,TypeError,RecursionError):pass
    tag=tags[-1] if tags else 'unavailable'
    if status==401 and tag=='unavailable':tag='invalid_access_token'
    if status==429:tag='rate_limit'
    retry=None
    try:
        retry=float(headers.get('Retry-After',''))
        if not math.isfinite(retry) or not 0<=retry<=86400:retry=None
    except (TypeError,ValueError):pass
    message={
        'invalid_access_token':'Reconnect Dropbox to authorize this request.',
        'expired_access_token':'Reconnect Dropbox to authorize this request.',
        'invalid_grant':'Dropbox authorization expired or was revoked. Connect again.',
        'insufficient_scope':'Dropbox did not grant the permission required for this action. Connect again.',
        'missing_scope':'Dropbox did not grant the permission required for this action. Connect again.',
        'not_found':'Dropbox could not find this path in the selected account and folder.',
        'invalid_root':'The selected Dropbox namespace is no longer available. Reconnect the account.',
        'rate_limit':'Dropbox is temporarily limiting requests. Wait before trying again.',
        'no_permission':'This Dropbox account cannot access the selected file or folder.',
    }.get(tag,'Dropbox could not complete this request. Try again.')
    return DropboxError(message,status=status,tag=tag,retry_after=retry)


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
