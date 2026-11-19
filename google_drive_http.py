"""Bounded read-only Google Drive HTTPS transport with fixed endpoints."""
import http.client
import json
import math
import re
import ssl
from urllib.parse import urlencode,quote

API_HOST='www.googleapis.com'
TOKEN_HOST='oauth2.googleapis.com'
JSON_LIMIT=4*1024*1024
ERROR_LIMIT=64*1024
MAX_DOWNLOAD=8*1024**3
FILE_FIELDS='id,name,mimeType,parents,driveId,size,modifiedTime,version,md5Checksum,sha256Checksum,trashed,capabilities(canDownload)'
ACCOUNT_FIELDS='user(permissionId,emailAddress,displayName)'


class GoogleDriveError(ValueError):
    """A safe failure: provider bodies and credentials never enter diagnostics."""
    def __init__(self,message='Google Drive could not complete this request. Try again.',*,status=0,tag='unavailable',retry_after=None):
        super().__init__(message);self.status=status;self.tag=tag;self.retry_after=retry_after


def file_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,300}',value):
        raise GoogleDriveError('Choose a verified Google Drive file or folder.',tag='invalid_argument')
    return value


def _provider_error(status,raw,headers):
    tags=[]
    try:
        value=json.loads(raw)
        if isinstance(value,dict):
            error=value.get('error')
            if isinstance(error,str):tags.append(error)
            elif isinstance(error,dict):
                for row in error.get('errors',[])[:20]:
                    if isinstance(row,dict):tags.append(row.get('reason'))
    except (ValueError,UnicodeError,TypeError,RecursionError):pass
    known={'invalid_grant','invalid_client','invalid_token','access_denied','insufficientPermissions',
           'insufficientFilePermissions','notFound','rateLimitExceeded','userRateLimitExceeded',
           'downloadQuotaExceeded','dailyLimitExceeded','fileNotDownloadable','cannotDownloadAbusiveFile'}
    tag=next((s for s in reversed(tags) if s in known),'unavailable')
    if status==401:tag='invalid_access_token'
    elif status==404:tag='not_found'
    elif status==412:tag='revision_changed'
    elif status==429:tag='rate_limit'
    retry=None
    try:
        retry=float(headers.get('Retry-After',''))
        if not math.isfinite(retry) or not 0<=retry<=86400:retry=None
    except (TypeError,ValueError):pass
    message={
        'invalid_grant':'Google authorization expired or was revoked. Connect again.',
        'invalid_client':'Google did not accept this desktop client configuration.',
        'invalid_access_token':'Reconnect Google Drive to authorize this request.',
        'invalid_token':'Reconnect Google Drive to authorize this request.',
        'access_denied':'Google sign-in was not approved. You can connect again.',
        'insufficientPermissions':'Google did not grant the required Drive permission. Connect again.',
        'insufficientFilePermissions':'This Google account cannot access the selected file or folder.',
        'not_found':'Google Drive could not find the selected file in this account.',
        'notFound':'Google Drive could not find the selected file in this account.',
        'rate_limit':'Google Drive is temporarily limiting requests. Wait before trying again.',
        'rateLimitExceeded':'Google Drive is temporarily limiting requests. Wait before trying again.',
        'userRateLimitExceeded':'Google Drive is temporarily limiting requests. Wait before trying again.',
        'downloadQuotaExceeded':'Google Drive cannot download this file until its download quota resets.',
        'fileNotDownloadable':'This Google Drive entry cannot be downloaded as an audio file.',
        'cannotDownloadAbusiveFile':'Google Drive has restricted downloading this file.',
        'revision_changed':'The Google Drive file changed. Confirm the current file again.',
    }.get(tag,'Google Drive could not complete this request. Try again.')
    return GoogleDriveError(message,status=status,tag=tag,retry_after=retry)


class DownloadResponse:
    def __init__(self,connection,response,metadata):
        self._connection=connection;self._response=response;self._read=0;self._closed=False
        self.metadata=dict(metadata)
        try:
            raw=response.getheader('Content-Length')
            self.length=int(raw) if raw is not None else None
            if self.length is not None and not 0<=self.length<=MAX_DOWNLOAD:raise ValueError()
        except (TypeError,ValueError):
            self.close();raise GoogleDriveError('Google Drive returned an invalid file size.',tag='invalid_response') from None
    def read(self,size=128*1024):
        if self._closed:return b''
        if type(size) is not int or not 1<=size<=1024*1024:raise ValueError('Read Google Drive downloads in bounded chunks.')
        try:chunk=self._response.read(size)
        except (OSError,http.client.HTTPException):
            self.close();raise GoogleDriveError('The Google Drive download was interrupted. Try this one track again.',tag='interrupted') from None
        self._read+=len(chunk)
        if self._read>MAX_DOWNLOAD or self.length is not None and self._read>self.length:
            self.close();raise GoogleDriveError('Google Drive returned an unexpected file size.',tag='invalid_response')
        if not chunk and self.length is not None and self._read!=self.length:
            self.close();raise GoogleDriveError('The Google Drive download was incomplete.',tag='interrupted')
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


class GoogleDriveTransport:
    def __init__(self,timeout=25):self.timeout=timeout
    def _request(self,host,path,method='GET',body=None,headers=None,metadata=None):
        if host not in (API_HOST,TOKEN_HOST):raise GoogleDriveError('This Google endpoint is not supported.',tag='invalid_argument')
        connection=http.client.HTTPSConnection(host,timeout=self.timeout,context=ssl.create_default_context())
        streaming=metadata is not None
        try:
            connection.request(method,path,body=body,headers={**(headers or {}),'User-Agent':'Library-Workbench-GoogleDrive/1'})
            response=connection.getresponse()
            if not 200<=response.status<300:
                raw=response.read(ERROR_LIMIT+1)
                failure=_provider_error(response.status,raw[:ERROR_LIMIT],response.headers)
                response.close();connection.close();raise failure
            if streaming:return DownloadResponse(connection,response,metadata)
            raw=response.read(JSON_LIMIT+1)
            if len(raw)>JSON_LIMIT:raise GoogleDriveError('Google Drive returned too much metadata. Choose a smaller folder.',tag='response_too_large')
            if not raw.strip():return {}
            try:value=json.loads(raw)
            except (ValueError,UnicodeError,RecursionError):raise GoogleDriveError('Google Drive returned invalid metadata.',tag='invalid_response') from None
            if not isinstance(value,dict):raise GoogleDriveError('Google Drive returned invalid metadata.',tag='invalid_response')
            return value
        except GoogleDriveError:
            connection.close();raise
        except (OSError,http.client.HTTPException,ValueError):
            connection.close();raise GoogleDriveError('Google Drive could not be reached securely. Check your connection and try again.',tag='network') from None
        finally:
            if not streaming:connection.close()
    def token(self,parameters):
        return self._request(TOKEN_HOST,'/token','POST',urlencode(parameters).encode('ascii'),{'Content-Type':'application/x-www-form-urlencoded'})
    def revoke(self,token):
        return self._request(TOKEN_HOST,'/revoke','POST',urlencode({'token':token}).encode('ascii'),{'Content-Type':'application/x-www-form-urlencoded'})
    def rpc(self,route,payload,access_token):
        if payload is not None and not isinstance(payload,dict):
            raise GoogleDriveError('Provide a Google Drive metadata request.',tag='invalid_argument')
        payload=dict(payload or {})
        if route=='about/get':
            allowed={'fields'};path='/drive/v3/about';payload.setdefault('fields',ACCOUNT_FIELDS)
        elif route=='files/get':
            identity=file_id(payload.pop('fileId',None));allowed={'fields','supportsAllDrives'}
            path='/drive/v3/files/'+quote(identity,safe='');payload.setdefault('fields',FILE_FIELDS)
        elif route=='files/list':
            allowed={'q','fields','pageSize','pageToken','spaces','corpora','driveId','includeItemsFromAllDrives','supportsAllDrives','orderBy'}
            path='/drive/v3/files';payload.setdefault('pageSize',1000)
        else:raise GoogleDriveError('This Google Drive operation is not supported.',tag='invalid_argument')
        if set(payload)-allowed:raise GoogleDriveError('This Google Drive metadata parameter is not supported.',tag='invalid_argument')
        for key,value in payload.items():
            if key=='pageSize':
                if type(value) is not int or not 1<=value<=1000:raise GoogleDriveError('Choose a bounded Google Drive metadata page.',tag='invalid_argument')
            elif key in ('includeItemsFromAllDrives','supportsAllDrives'):
                if type(value) is not bool:raise GoogleDriveError('Choose a valid Google Drive metadata request.',tag='invalid_argument')
            elif not isinstance(value,str) or len(value)>4096 or any(ord(c)<32 for c in value):
                raise GoogleDriveError('Choose a valid Google Drive metadata request.',tag='invalid_argument')
        query=urlencode({k:str(v).lower() if isinstance(v,bool) else v for k,v in payload.items()})
        return self._request(API_HOST,path+'?'+query,headers={'Authorization':'Bearer '+access_token})
    def download(self,identity,access_token,metadata):
        identity=file_id(identity)
        headers={'Authorization':'Bearer '+access_token}
        # A metadata representation's ETag need not identify the media
        # representation. The download helper pins version/checksums before
        # and after streaming instead of assuming these ETags are equivalent.
        path='/drive/v3/files/'+quote(identity,safe='')+'?alt=media&supportsAllDrives=true'
        return self._request(API_HOST,path,headers=headers,metadata=metadata)
