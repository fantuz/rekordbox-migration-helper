"""One explicitly approved Dropbox file, published without replacing local data.

Filesystem attributes and directory handles authorize the destination. Existing
files, cloud placeholders and redirected parents are never opened for writing.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import sys
import tempfile

from media import cloud_placeholder
from track_playback import AUDIO_EXTENSIONS

MAX_FILE_BYTES = 8 * 1024**3
CHUNK_BYTES = 1024**2
HASH_BLOCK_BYTES = 4 * 1024**2
_USE_DIR_FD = (os.name == 'posix' and hasattr(os, 'O_NOFOLLOW')
               and os.open in os.supports_dir_fd and os.stat in os.supports_dir_fd
               and os.link in os.supports_dir_fd and os.unlink in os.supports_dir_fd)


def _identity(info):
    return [info.st_dev, info.st_ino]


def _ordinary_directory(path, info):
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or getattr(info, 'st_file_attributes', 0) & 0x400
            or cloud_placeholder(info)):
        raise ValueError('Choose locally available ordinary Dropbox folders, without links or placeholders')


def _windows_parts(parts):
    reserved = {'CON', 'PRN', 'AUX', 'NUL', 'CLOCK$', 'CONIN$', 'CONOUT$'}
    reserved.update(prefix + digit for prefix in ('COM', 'LPT') for digit in '123456789¹²³')
    for part in parts:
        if (part.endswith((' ', '.')) or any(char in part for char in '<>:"|?*')
                or part.split('.')[0].upper() in reserved):
            raise ValueError('Choose a Windows audio path without reserved or ambiguous names')


def _paths(local_path, local_root):
    try:
        raw_path, raw_root = os.fspath(local_path), os.fspath(local_root)
    except TypeError:
        raise ValueError('Choose an absolute Dropbox audio location') from None
    if (not isinstance(raw_path, str) or not isinstance(raw_root, str)
            or any(ord(c) < 32 for c in raw_path + raw_root)
            or raw_path.startswith(('//', '\\\\')) or raw_root.startswith(('//', '\\\\'))):
        raise ValueError('Choose an absolute Dropbox audio location')
    target, root = Path(raw_path), Path(raw_root)
    if (not target.is_absolute() or not root.is_absolute() or '..' in target.parts or '..' in root.parts
            or root == Path(root.anchor) or target == root or not target.is_relative_to(root)
            or target.suffix.lower() not in AUDIO_EXTENSIONS):
        raise ValueError('Choose an audio file inside the verified Dropbox folder')
    if os.name == 'nt':
        _windows_parts(target.parts[1:])
        _windows_parts(root.parts[1:])
    return target, root


def _missing(path, parent_fd=None):
    try:
        if parent_fd is None:
            info = path.lstat()
        else:
            info = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if cloud_placeholder(info):
        raise ValueError('This track has a cloud placeholder. Use its individual Play action to download it')
    raise ValueError('The local destination already exists; it will not be replaced')


def _snapshot(target, root):
    chain = list(reversed(target.parent.parents)) + [target.parent]
    directories = []
    for path in chain:
        info = path.lstat()
        _ordinary_directory(path, info)
        directories.append({'path': str(path), 'identity': _identity(info)})
    _missing(target)
    return {'local_path': str(target), 'local_root': str(root), 'directories': directories}


def prepare_target(local_path, local_root):
    """Return metadata-only destination identity suitable for consent binding.

    No directories are created and no existing file is opened. A missing parent
    requires the user to make that individual destination folder available first.
    """
    target, root = _paths(local_path, local_root)
    try:
        return _snapshot(target, root)
    except (OSError, RuntimeError) as error:
        raise ValueError('The Dropbox destination folder is unavailable or changed') from error


def resident_file_identity(local_path, local_root, expected_target=None):
    """Inspect an ordinary published file and its parents without audio reads.

    This stamp supports a subsequent, explicitly approved local Play action.
    It is freshness evidence, not another content-hash or decoding check.
    """
    target,root=_paths(local_path,local_root)
    if expected_target is not None and _snapshot_after_publish(target,root)!=expected_target:
        raise ValueError('The downloaded track folder changed. Choose Play again')
    info=target.lstat()
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or getattr(info,'st_file_attributes',0)&0x400 or cloud_placeholder(info)
            or info.st_size<=0 or not os.access(target,os.R_OK)):
        raise ValueError('The downloaded track is no longer an ordinary locally available file')
    def stamp(value):
        return [value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns,
                getattr(value,'st_file_attributes',0),getattr(value,'st_flags',0)]
    result=stamp(info)
    return result


def verify_downloaded_content(local_path,local_root,expected_target,expected_identity,
                              expected_size,expected_hash,checkpoint=None):
    """Recheck only the already approved download before its approved Play.

    Metadata clocks can coalesce writes, including writes that restore mtime.
    A matching stamp is only freshness evidence; verify the selected resident
    file's bytes against the remote revision already approved and downloaded.
    Never call this helper from inventory, browsing or download-only actions.
    """
    target,root=_paths(local_path,local_root)
    if (type(expected_size) is not int or not 0<expected_size<=MAX_FILE_BYTES
            or not isinstance(expected_hash,str) or not re.fullmatch('[0-9a-f]{64}',expected_hash)
            or not isinstance(expected_identity,list) or len(expected_identity)!=7):
        raise ValueError('The approved download cannot be verified for playback')
    def check():
        if checkpoint is not None:checkpoint()
    def unchanged(info):
        # Windows fd/path stat APIs differ in timestamp precision and ctime
        # semantics. Their shared identity is device/inode/size, not timestamps.
        # Full path stamps are still checked before/after reading on every OS;
        # the final byte hash detects changes hidden by timestamp granularity.
        if (not stat.S_ISREG(info.st_mode) or cloud_placeholder(info)
                or [info.st_dev,info.st_ino,info.st_size]!=expected_identity[:3]):return False
        return sys.platform=='win32' or [info.st_mtime_ns,info.st_ctime_ns]==expected_identity[3:5]
    check()
    if resident_file_identity(target,root,expected_target)!=expected_identity:
        raise ValueError('The downloaded track changed before content verification')
    flags=(os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOINHERIT',0)
           |getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
    fd=os.open(target,flags)
    try:
        if not unchanged(os.fstat(fd)) or resident_file_identity(target,root,expected_target)!=expected_identity:
            raise ValueError('The downloaded track changed before content verification')
        digest=_DropboxHash();consumed=0
        while True:
            check()
            chunk=os.read(fd,min(CHUNK_BYTES,expected_size-consumed+1))
            if not chunk:break
            consumed+=len(chunk)
            if consumed>expected_size:raise ValueError('The downloaded track size changed before playback')
            digest.update(chunk)
        check()
        if consumed!=expected_size or digest.hexdigest()!=expected_hash:
            raise ValueError('The downloaded track content changed before playback')
        if not unchanged(os.fstat(fd)) or resident_file_identity(target,root,expected_target)!=expected_identity:
            raise ValueError('The downloaded track changed during content verification')
    finally:os.close(fd)


@contextmanager
def _parent_handle(target, snapshot):
    handles = []
    try:
        if _USE_DIR_FD:
            for row in snapshot['directories']:
                path = Path(row['path'])
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                fd = os.open(str(path) if not handles else path.name, flags,
                             **({'dir_fd': handles[-1]} if handles else {}))
                handles.append(fd)
                info = os.fstat(fd)
                _ordinary_directory(path, info)
                if _identity(info) != row['identity']:
                    raise ValueError('The Dropbox destination folder changed. Choose Download again')
        yield handles[-1] if handles else None
    finally:
        for fd in reversed(handles):
            os.close(fd)


def _metadata(metadata):
    if not isinstance(metadata, dict) or metadata.get('.tag', 'file') != 'file':
        raise ValueError('Choose a downloadable Dropbox file')
    identity, revision, size = (metadata.get(key) for key in ('id', 'rev', 'size'))
    if (not isinstance(identity, str) or not identity.startswith('id:') or len(identity) > 1024
            or not isinstance(revision, str) or not revision or len(revision) > 256
            or any(ord(c) < 32 for c in identity + revision)
            or isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_FILE_BYTES
            or metadata.get('is_downloadable') is False):
        raise ValueError('Choose a nonempty downloadable Dropbox audio file no larger than 8 GiB')
    content_hash = metadata.get('content_hash')
    if not isinstance(content_hash, str) or not re.fullmatch('[0-9a-f]{64}', content_hash):
        raise ValueError('Dropbox returned an invalid content hash')
    modified = metadata.get('server_modified')
    modified_ns = None
    if modified is not None:
        try:
            if not isinstance(modified, str):raise ValueError()
            stamp = datetime.fromisoformat(modified.replace('Z', '+00:00'))
            if stamp.tzinfo is None:raise ValueError()
            delta = stamp.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
            modified_ns = (delta.days * 86400 + delta.seconds) * 10**9 + delta.microseconds * 1000
        except (ValueError, OverflowError):
            raise ValueError('Dropbox returned an invalid modification time') from None
    return identity, revision, size, content_hash, modified_ns


class _DropboxHash:
    def __init__(self):
        self.outer, self.block, self.used = sha256(), sha256(), 0

    def update(self, chunk):
        view = memoryview(chunk)
        while view:
            count = min(HASH_BLOCK_BYTES - self.used, len(view))
            self.block.update(view[:count]);self.used += count;view = view[count:]
            if self.used == HASH_BLOCK_BYTES:
                self.outer.update(self.block.digest());self.block = sha256();self.used = 0

    def hexdigest(self):
        outer = self.outer.copy()
        if self.used:outer.update(self.block.digest())
        return outer.hexdigest()


def _connection_id(connection, provider='Dropbox'):
    status = connection.status()
    if not status.get('connected') or not status.get('connection_id'):
        raise ValueError('Reconnect '+provider+' before downloading this track')
    return status['connection_id']


@contextmanager
def _staging_directory(staging_dir, root, managed_root, excluded_roots=None, provider='Dropbox'):
    """Stage outside the sync tree so no partial recording reaches the client."""
    automatic = staging_dir is None
    base = Path(tempfile.gettempdir()).resolve() if automatic else Path(staging_dir).parent
    boundary = Path(managed_root) if managed_root is not None else root
    if (not boundary.is_absolute() or '..' in boundary.parts
            or not root.is_relative_to(boundary)):
        raise ValueError('Choose a verified '+provider+' root')
    candidate = base if automatic else Path(staging_dir)
    if (not candidate.is_absolute() or '..' in candidate.parts
            or candidate == boundary or candidate.is_relative_to(boundary)
            or candidate == root or candidate.is_relative_to(root)):
        raise ValueError('Download staging must be outside '+provider)
    # A selected-file cache can live outside its own provider's desktop tree.
    # Do not let private staging accidentally live inside another account's or
    # provider's sync tree either. Discovery reads bounded local configuration,
    # never music contents or a provider API.
    from cloud_locations import provider_roots
    boundaries=list(excluded_roots or [])
    boundaries.extend(row['root'] for row in provider_roots(include_unavailable=True))
    if len(boundaries)>256:raise ValueError('Too many configured cloud folders to verify download staging')
    for value in boundaries:
        if isinstance(value,dict):value=value.get('root')
        if not isinstance(value,(str,Path)):raise ValueError('Verify the configured cloud folders before downloading')
        raw=os.fspath(value)
        if (len(raw)>4096 or any(ord(c)<32 for c in raw)
                or raw.startswith(('//','\\\\'))):
            raise ValueError('Verify the configured cloud folders before downloading')
        other=Path(value)
        if not other.is_absolute() or '..' in other.parts:
            raise ValueError('Verify the configured cloud folders before downloading')
        try:canonical=other.resolve(strict=False)
        except OSError:raise ValueError('A configured cloud folder could not be verified') from None
        if any(candidate==item or candidate.is_relative_to(item) for item in (other,canonical)):
            raise ValueError('Private download staging must be outside every configured cloud folder')
    for folder in list(reversed(base.parents)) + [base]:
        _ordinary_directory(folder, folder.lstat())
    created = False
    if automatic:
        path = Path(tempfile.mkdtemp(prefix='workbench-dropbox-', dir=base))
        created = True
    else:
        path = candidate
        try:path.mkdir(mode=0o700);created = True
        except FileExistsError:pass
    try:
        info = path.lstat();_ordinary_directory(path, info)
        if os.name == 'posix' and info.st_mode & 0o077:
            raise ValueError('Choose a private download staging folder')
        yield path
    finally:
        if automatic and created:
            try:path.rmdir()
            except OSError:pass


def download_file(connection, metadata, local_path, local_root, namespace,
                  progress=None, validate=None, expected_target=None, staging_dir=None, managed_root=None,
                  excluded_roots=None):
    """Preserve Dropbox's public download contract over the shared safe stream."""
    return download_verified_file(connection,metadata,local_path,local_root,namespace,
        progress=progress,validate=validate,expected_target=expected_target,staging_dir=staging_dir,
        managed_root=managed_root,excluded_roots=excluded_roots,metadata_parser=_metadata,
        hash_factory=_DropboxHash,open_stream=lambda identity,revision,space:
        connection.download(identity,rev=revision,namespace=space),provider='Dropbox')


def download_verified_file(connection, metadata, local_path, local_root, namespace=None,
                           progress=None, validate=None, expected_target=None, staging_dir=None,
                           managed_root=None, excluded_roots=None, *, metadata_parser,
                           hash_factory, open_stream, verify_after_stream=None, provider):
    """Stream exactly one approved revision and publish it without overwrite.

    ``validate`` rechecks the caller's mapping/source binding. It may raise to
    cancel. ``expected_target`` is the result of prepare_target at confirmation
    time. A post-publication progress callback cannot undo a completed transfer.
    """
    identity, revision, size, expected_hash, modified_ns = metadata_parser(metadata)
    target, root = _paths(local_path, local_root)
    snapshot = prepare_target(target, root)
    if expected_target is not None and snapshot != expected_target:
        raise ValueError('The Dropbox destination changed. Choose Download again')
    connection_id = _connection_id(connection,provider)
    def checkpoint(amount=0):
        if _connection_id(connection,provider) != connection_id:
            raise ValueError(provider+' authorization changed. Choose Download again')
        if validate is not None:validate()
        if prepare_target(target, root) != snapshot:
            raise ValueError('The Dropbox destination changed. Choose Download again')
        if progress is not None:progress(amount, 'Downloading one approved '+provider+' track')
    checkpoint()
    temporary = '.library-workbench-dropbox-' + secrets.token_hex(16) + '.tmp'
    published = False
    fd = None
    with _staging_directory(staging_dir, root, managed_root,excluded_roots,provider) as staging:
        temporary_path = staging / temporary
        stage_snapshot = _snapshot_after_publish(temporary_path, staging)
        with _parent_handle(target, snapshot) as parent_fd, _parent_handle(temporary_path, stage_snapshot) as stage_fd:
            if stage_snapshot['directories'][-1]['identity'][0] != snapshot['directories'][-1]['identity'][0]:
                raise ValueError('Private download staging is on another volume. Use Dropbox to make this track available')
            if shutil.disk_usage(staging).free < size:
                raise ValueError('There is not enough free space to download this track')
            kwargs = {'dir_fd': stage_fd} if stage_fd is not None else {}
            try:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOINHERIT', 0)
                if stage_fd is not None:flags |= os.O_NOFOLLOW
                fd = os.open(temporary if stage_fd is not None else temporary_path, flags, 0o600, **kwargs)
                output_identity = _identity(os.fstat(fd))
                if not stat.S_ISREG(os.fstat(fd).st_mode):raise ValueError('Unable to create an ordinary temporary audio file')
                consumed, digest = 0, hash_factory()
                with open_stream(identity,revision,namespace) as response:
                    actual = metadata_parser(response.metadata)
                    if actual[:3] != (identity, revision, size) or actual[3] != expected_hash:
                        raise ValueError(provider+' file details changed. Check this track again')
                    while True:
                        checkpoint(min(98, 98 * consumed / size))
                        chunk = response.read(CHUNK_BYTES)
                        if not isinstance(chunk, bytes):raise ValueError(provider+' returned invalid file content')
                        if not chunk:break
                        consumed += len(chunk)
                        if consumed > size:raise ValueError(provider+' returned more bytes than the approved file size')
                        digest.update(chunk)
                        remaining = memoryview(chunk)
                        while remaining:
                            written = os.write(fd, remaining)
                            if written <= 0:raise OSError('Incomplete file write')
                            remaining = remaining[written:]
                if consumed != size:raise ValueError(provider+' returned an incomplete file')
                actual_hash = digest.hexdigest()
                if actual_hash != expected_hash:
                    raise ValueError('Downloaded content does not match '+provider+' metadata')
                if verify_after_stream is not None:verify_after_stream()
                if modified_ns is not None:
                    if os.utime in os.supports_fd:
                        os.utime(fd, ns=(modified_ns, modified_ns))
                    else:
                        if _identity(temporary_path.lstat()) != output_identity:raise ValueError('Temporary download changed')
                        os.utime(temporary_path, ns=(modified_ns, modified_ns))
                os.fsync(fd)
                # Windows can deny creation of another link while the write handle
                # is open. The private staging path is checked again after closing.
                if os.name == 'nt':
                    os.close(fd)
                    fd = None
                checkpoint(99)
                _missing(target, parent_fd)
                if _snapshot_after_publish(temporary_path, staging) != stage_snapshot:
                    raise ValueError('Private download staging changed')
                # link() is atomic and fails if the target exists. replace/rename
                # would be unsafe here because another client may create the song.
                try:
                    if parent_fd is not None and stage_fd is not None:
                        os.link(temporary, target.name, src_dir_fd=stage_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
                    else:
                        if _identity(temporary_path.lstat()) != output_identity:raise ValueError('Temporary download changed')
                        os.link(temporary_path, target, follow_symlinks=False)
                except FileExistsError:
                    raise ValueError('The local destination appeared during download; it will not be replaced') from None
                except OSError as error:
                    raise ValueError('This filesystem cannot safely publish the download. Use Dropbox to make the track available') from error
                published = True
                # Detect parent replacement during publication. Remove only our own
                # inode through its original handle, never an unrelated replacement.
                current = _snapshot_after_publish(target, root)
                if current != snapshot:
                    raise ValueError('The Dropbox destination changed during publication')
                if parent_fd is not None:
                    result_info = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
                else:result_info = target.lstat()
                if _identity(result_info) != output_identity:raise ValueError('The published download changed')
            except Exception:
                if published:
                    _remove_ours(target, parent_fd, output_identity)
                raise
            finally:
                if fd is not None:os.close(fd)
                if 'output_identity' in locals():_remove_ours(temporary_path, stage_fd, output_identity)
    # Capture identity after removing the staging hardlink: that removal can
    # itself update ctime. A provider may evict/replace the file at any time;
    # the caller must recheck this stamp before an approved playback launch.
    published_identity=None
    try:
        info=resident_file_identity(target,root,snapshot)
        if info[:2]==output_identity and info[2]==size:published_identity=info
    except (OSError,ValueError,RuntimeError):pass
    if progress is not None:
        try:progress(100, 'The selected '+provider+' track is available locally')
        except Exception:pass  # Late cancellation cannot roll back publication.
    return {'downloaded': True, 'local_path': str(target), 'bytes': consumed,
            'content_hash': actual_hash,'file_identity':published_identity}


def _snapshot_after_publish(target, root):
    result = {'local_path': str(target), 'local_root': str(root), 'directories': []}
    for path in list(reversed(target.parent.parents)) + [target.parent]:
        info = path.lstat();_ordinary_directory(path, info)
        result['directories'].append({'path': str(path), 'identity': _identity(info)})
    return result


def _remove_ours(target, parent_fd, identity):
    try:
        info = target.lstat() if parent_fd is None else os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
        if _identity(info) == identity:
            if parent_fd is None:target.unlink()
            else:os.unlink(target.name, dir_fd=parent_fd)
    except FileNotFoundError:pass
