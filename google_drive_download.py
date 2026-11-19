"""One approved Google Drive binary file over the shared no-clobber publisher.

Google's MD5 value is a provider content checksum, not an authentication or
signature primitive. SHA-256 is preferred whenever Drive supplies it. HTTPS,
the authorized account, immutable file identity and version checks establish
the source; neither filenames nor an unverified checksum do that by themselves.
"""
from contextlib import contextmanager
from datetime import datetime,timezone
from hashlib import md5,sha256
import re

from dropbox_download import MAX_FILE_BYTES,download_verified_file
from dropbox_download import prepare_target as _prepare_target

FILE_FIELDS=('id,name,mimeType,parents,size,modifiedTime,version,md5Checksum,'
             'sha256Checksum,trashed,driveId,capabilities(canDownload)')
_ID=re.compile(r'[A-Za-z0-9_-]{1,256}')


def prepare_target(local_path,local_root):
    """Inspect only destination directory attributes; never read a placeholder."""
    try:return _prepare_target(local_path,local_root)
    except ValueError as error:raise ValueError(str(error).replace('Dropbox','Google Drive')) from None


def _identity(value):
    if not isinstance(value,str) or not _ID.fullmatch(value):
        raise ValueError('Choose a valid Google Drive file identity')
    return value


def _algorithm(metadata):
    selected=None
    for algorithm,field,length in (('sha256','sha256Checksum',64),('md5','md5Checksum',32)):
        checksum=metadata.get(field)
        if checksum is not None:
            if not isinstance(checksum,str) or not re.fullmatch('[0-9a-f]{'+str(length)+'}',checksum):
                raise ValueError('Google Drive returned an invalid content checksum')
            if selected is None:selected=algorithm,checksum
    if selected is not None:return selected
    raise ValueError('Google Drive did not provide a verifiable content checksum for this file')


def _metadata(metadata):
    if not isinstance(metadata,dict):raise ValueError('Choose a downloadable Google Drive audio file')
    identity=_identity(metadata.get('id'))
    version=metadata.get('version');size=metadata.get('size');mime=metadata.get('mimeType')
    if type(version) is int:version=str(version)
    if isinstance(size,str) and re.fullmatch('[0-9]{1,20}',size):size=int(size)
    capabilities=metadata.get('capabilities')
    if (not isinstance(version,str) or not re.fullmatch('[0-9]{1,40}',version)
            or type(size) is not int or not 0<size<=MAX_FILE_BYTES
            or not isinstance(mime,str) or not 1<=len(mime)<=256
            or any(ord(char)<32 for char in mime)
            or mime.startswith('application/vnd.google-apps.')
            or metadata.get('trashed',False) is not False
            or not isinstance(capabilities,dict) or capabilities.get('canDownload') is not True):
        raise ValueError('Choose a nonempty downloadable Google Drive binary audio file no larger than 8 GiB')
    _,checksum=_algorithm(metadata)
    modified=metadata.get('modifiedTime');modified_ns=None
    if modified is not None:
        try:
            if not isinstance(modified,str):raise ValueError()
            stamp=datetime.fromisoformat(modified.replace('Z','+00:00'))
            if stamp.tzinfo is None:raise ValueError()
            delta=stamp.astimezone(timezone.utc)-datetime(1970,1,1,tzinfo=timezone.utc)
            modified_ns=(delta.days*86400+delta.seconds)*10**9+delta.microseconds*1000
        except (ValueError,OverflowError):
            raise ValueError('Google Drive returned an invalid modification time') from None
    return identity,version,size,checksum,modified_ns


def _fingerprint(metadata):
    details=_metadata(metadata)
    parents=metadata.get('parents',[])
    if (not isinstance(parents,list) or len(parents)>100
            or any(not isinstance(parent,str) or not _ID.fullmatch(parent) for parent in parents)
            or len(set(parents))!=len(parents)):
        raise ValueError('Google Drive returned an invalid file location')
    name=metadata.get('name')
    if name is not None and (not isinstance(name,str) or len(name)>4096 or any(ord(c)<32 for c in name)):
        raise ValueError('Google Drive returned an invalid filename')
    drive=metadata.get('driveId')
    if drive is not None:_identity(drive)
    # Pin metadata that determines which attached remote location this file
    # belongs to, in addition to the actual approved byte representation.
    return details+(metadata.get('mimeType'),name,tuple(sorted(parents)),drive,
                       metadata.get('sha256Checksum'),metadata.get('md5Checksum'))


def metadata_details(metadata):
    """Validated id, version, size, preferred checksum and optional timestamp."""
    return _metadata(metadata)


def metadata_fingerprint(metadata):
    """Immutable approved content and location fields for route consent binding."""
    return _fingerprint(metadata)


def download_file(connection,metadata,local_path,local_root,namespace=None,
                  progress=None,validate=None,expected_target=None,staging_dir=None,
                  managed_root=None,excluded_roots=None):
    """Check identity/version/hash before and after streaming exactly one file.

    Drive's file-content endpoint returns the current representation rather
    than an immutable revision URL. The post-stream metadata check is therefore
    required before the shared helper publishes the file in the local folder.
    ``namespace`` is accepted only for symmetry with the Dropbox route adapter.
    """
    approved=_fingerprint(metadata);algorithm,_=_algorithm(metadata)
    identity,version=approved[:2]
    def verify_remote():
        actual=connection.rpc('files/get',{'fileId':identity,'fields':FILE_FIELDS})
        if _fingerprint(actual)!=approved:
            raise ValueError('Google Drive file details changed. Confirm this track again')
    @contextmanager
    def stream(file_id,revision,_space):
        verify_remote()
        with connection.download(file_id,version=revision) as response:
            if _fingerprint(response.metadata)!=approved:
                raise ValueError('Google Drive file details changed. Confirm this track again')
            yield response
    # usedforsecurity=False makes the MD5 fallback explicit and usable on FIPS
    # systems: it compares the provider's checksum, never passwords or tokens.
    factory=sha256 if algorithm=='sha256' else lambda:md5(usedforsecurity=False)
    try:
        result=download_verified_file(connection,metadata,local_path,local_root,
            progress=progress,validate=validate,expected_target=expected_target,staging_dir=staging_dir,
            managed_root=managed_root,excluded_roots=excluded_roots,metadata_parser=_metadata,
            hash_factory=factory,open_stream=stream,verify_after_stream=verify_remote,provider='Google Drive')
    except ValueError as error:
        raise ValueError(str(error).replace('Dropbox','Google Drive')) from None
    return {**result,'file_id':identity,'version':version,'checksum_algorithm':algorithm}
