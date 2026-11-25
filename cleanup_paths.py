"""Evidence for collection cleanup. Only the native, always-local Music tree can prove absence."""
import errno
import hashlib
import os
from pathlib import Path, PureWindowsPath
import re
from functools import lru_cache
import stat
import sys
import unicodedata
from urllib.parse import urlsplit, unquote

from cloud_locations import small_json
from media import cloud_placeholder
from metadata_sidecars import is_name_sidecar
from track_playback import AUDIO_EXTENSIONS


_OS = {'win32': 'Windows', 'darwin': 'macOS', 'linux': 'Linux'}
_CLOUD = {'http', 'https', 'spotify', 'tidal', 'soundcloud', 'beatport', 'beatsource', 'dropbox', 'googledrive', 'icloud'}
_NETWORK = {'smb', 'afp', 'nfs'}
_DRIVE = re.compile(r'^[A-Za-z]:')
_BAD_WIN = re.compile(r'[<>:"|?*]|~[0-9]|[. ]$|^(?:CON(?:IN\$|OUT\$)?|AUX|NUL|PRN|(?:COM|LPT)[0-9¹²³])(?:\.|$)', re.I)
_BLOCK_SIZE = 256 * 1024
# Bidirectional overrides can make a selected path display differently from its stored spelling.
_UNSAFE_TEXT = re.compile(r'[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069\ud800-\udfff]')


def _path_text(value):
    """Accept ordinary local file URLs, preserving suspicious spellings for rejection."""
    if not isinstance(value, str) or len(value) > 8192 or _UNSAFE_TEXT.search(value):
        return '', False
    if value[:5].casefold() == 'file:':
        try:
            uri = urlsplit(value)
            if (uri.query or uri.fragment or re.search(r'%(?:2f|5c)|%(?![a-f0-9]{2})', uri.path, re.I)
                    or not uri.path.startswith('/')):
                return '', False
            value = unquote(uri.path, errors='strict')
            if _UNSAFE_TEXT.search(value):
                return '', False
            if uri.netloc and uri.netloc.casefold() != 'localhost':
                return '//' + uri.netloc + value, True
            if re.match(r'^/[a-z]:/', value, re.I):
                value = value[1:]
        except (ValueError, UnicodeError):
            return '', False
    if _DRIVE.match(value) or value.startswith('\\\\'):
        value = value.replace('\\', '/')
    return value, True


def _origin(value):
    if value.startswith('//'):
        parts = value[2:].split('/')
        if parts[0] in ('?', '.'):
            return 'Windows', 'Device namespace', 'unclassified'
        volume = '//' + '/'.join(parts[:2]).casefold() if len(parts) >= 2 and all(parts[:2]) else 'Network share'
        return 'Windows', volume, 'external'
    if _DRIVE.match(value):
        return 'Windows', value[:2].upper(), None if value[2:].startswith('/') else 'unclassified'
    if value == '/Volumes' or value.startswith('/Volumes/'):
        return 'macOS', '/'.join(value.split('/')[:3]), 'external'
    if value.startswith('/Network/'):
        return 'macOS', '/Network', 'external'
    if value.startswith(('/Users/', '/System/', '/Library/', '/Applications/')):
        return 'macOS', '/', None
    match = re.match(r'^([a-z][a-z\d.+-]*):', value, re.I)
    if match:
        scheme = match[1].lower()
        status = 'cloud' if scheme in _CLOUD else 'external' if scheme in _NETWORK else 'unclassified'
        return 'Unclassified', scheme + ':', status
    return 'Unclassified', 'Unclassified', 'unclassified'


def _cloud_key(value):
    if _DRIVE.match(value) or value.startswith('\\\\'):
        value = value.replace('\\', '/')
    return unicodedata.normalize('NFKD', value).casefold().rstrip('/')


def _cloud_component(value):
    name = value.casefold()
    return (any(term in name for term in ('dropbox', 'onedrive', 'icloud', 'google drive', 'googledrive'))
            or name in ('cloudstorage', 'mobile documents', 'my drive', 'shared drives', 'box sync', 'box drive')
            or name.startswith('contents_'))


def _ordinary(info):
    return (not stat.S_ISLNK(info.st_mode) and not cloud_placeholder(info)
            and not getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _os_path(path):
    value = Path(path).as_posix()
    return value[4:] if re.match(r'^//\?/\w:/', value) else value


def _windows_volume():
    from ctypes import create_unicode_buffer, windll
    buffer = create_unicode_buffer(32768)
    count = windll.kernel32.GetSystemWindowsDirectoryW(buffer, len(buffer))
    if 0 < count < len(buffer):
        root = PureWindowsPath(buffer.value).anchor
        if _DRIVE.match(root) and windll.kernel32.GetDriveTypeW(root) == 3:
            return root[:2].upper()
    return ''


def _windows_music():
    # Ask for the configured location without verifying or opening a redirected share.
    import ctypes
    from ctypes import wintypes
    from uuid import UUID
    music_id = (ctypes.c_ubyte * 16).from_buffer_copy(UUID('4bd8d571-6d19-48d3-be97-422220080e43').bytes_le)
    shell = ctypes.WinDLL('shell32').SHGetKnownFolderPath
    shell.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
    shell.restype = ctypes.c_long
    pointer = ctypes.c_void_p()
    try:
        if shell(ctypes.byref(music_id), 0x4000, None, ctypes.byref(pointer)) != 0 or not pointer:
            raise ValueError('The configured Music folder could not be verified')
        return ctypes.wstring_at(pointer)
    finally:
        if pointer:
            ctypes.windll.ole32.CoTaskMemFree(pointer)


def _registered_roots():
    """Every Windows File Provider registration, including custom-named sync folders."""
    import winreg
    result = []
    branch = r'Software\Microsoft\Windows\CurrentVersion\Explorer\SyncRootManager'
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            manager = winreg.OpenKey(hive, branch)
        except FileNotFoundError:
            continue
        with manager:
            count = winreg.QueryInfoKey(manager)[0]
            if count > 256:
                raise ValueError('Incomplete sync-root list')
            for index in range(count):
                name = winreg.EnumKey(manager, index)
                try:
                    roots = winreg.OpenKey(manager, name + r'\UserSyncRoots')
                except FileNotFoundError:
                    continue
                with roots:
                    values = winreg.QueryInfoKey(roots)[1]
                    if values > 64:
                        raise ValueError('Incomplete sync-root registration')
                    for position in range(values):
                        _, path, kind = winreg.EnumValue(roots, position)
                        if kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                            raise ValueError('Unreadable sync-root registration')
                        result.append(winreg.ExpandEnvironmentStrings(path) if kind == winreg.REG_EXPAND_SZ else path)
    return result


def _open_for_hash(path):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        import msvcrt
        create = ctypes.WinDLL('kernel32', use_last_error=True).CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                           wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        # OPEN_REPARSE_POINT | OPEN_NO_RECALL. The caller checks the opened handle before reading.
        handle = create(str(path), 0x80000000, 7, None, 3, 0x00200000 | 0x00100000, None)
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except OSError:
            ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(handle))
            raise
    # Pin every directory while opening its child, including the leaf's immediate parent.
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, flags, dir_fd=parent)
            os.close(parent)
            parent = child
        return os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
    finally:
        os.close(parent)


@lru_cache(maxsize=1)
def _darwin_getxattr():
    # Darwin's getxattr takes six arguments; os.getxattr is Linux-specific.
    import ctypes
    get = ctypes.CDLL(None, use_errno=True).getxattr
    get.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t,
                    ctypes.c_uint32, ctypes.c_int]
    get.restype = ctypes.c_ssize_t
    return get


def _finder_alias(path):
    import ctypes
    buffer = ctypes.create_string_buffer(32)
    size = _darwin_getxattr()(os.fsencode(path), b'com.apple.FinderInfo', buffer, len(buffer), 0, 1)
    if size < 0:
        code = ctypes.get_errno()
        if code == getattr(errno, 'ENOATTR', 93):
            return False
        raise OSError(code, os.strerror(code))
    return size < 10 or bool(int.from_bytes(buffer.raw[8:10], 'big') & 0x8000)


def _stamp(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


class _CloudParent(OSError):
    pass


class PathInspector:
    def __init__(self, host, music='', startup_drive='', devices=(), cloud_roots=(), roots_known=True):
        self.host = host
        self.music = music.rstrip('/')
        self.startup_drive = startup_drive
        self.devices = frozenset(devices)
        self.cloud_roots = tuple(_cloud_key(path) for path in cloud_roots if path)
        self.roots_known = roots_known

    @property
    def can_apply(self):
        return self.host in ('Windows', 'macOS') and self.roots_known and bool(self.music and self.devices)

    @classmethod
    def current(cls, extra_cloud_roots=()):
        host = _OS.get(sys.platform, 'Unclassified')
        if host not in ('Windows', 'macOS'):
            return cls(host, cloud_roots=extra_cloud_roots)
        inspector = cls(host)
        roots = []
        try:
            home = Path.home()
            inspector.music = _os_path(home / 'Music')
            if host == 'Windows':
                inspector.startup_drive = _windows_volume()
                if _os_path(_windows_music()).casefold() != inspector.music.casefold():
                    raise ValueError('The configured Music folder is redirected')
                if not inspector.startup_drive or _origin(inspector.music)[1] != inspector.startup_drive:
                    raise ValueError('Profile is outside the startup drive')
                inspector.devices = {Path(inspector.startup_drive + '/').stat().st_dev}
                configs = [Path(os.environ[key]) / 'Dropbox/info.json' for key in ('APPDATA', 'LOCALAPPDATA')]
                roots.extend(os.environ[key] for key in ('OneDrive', 'OneDriveConsumer', 'OneDriveCommercial') if os.environ.get(key))
                roots.extend(_registered_roots())
            else:
                devices = {Path('/').stat().st_dev}
                try:
                    devices.add(Path('/System/Volumes/Data').stat().st_dev)
                except FileNotFoundError:
                    pass
                inspector.devices = devices
                configs = [home / '.dropbox/info.json', home / 'Library/Application Support/Dropbox/info.json']
            for config in configs:
                if not config.is_absolute() or (host == 'Windows' and config.drive.upper() != inspector.startup_drive):
                    raise ValueError('Unverified Dropbox config location')
                try:
                    if inspector._parents(config) is None:
                        raise ValueError('Redirected Dropbox profile')
                    info = config.lstat()
                except FileNotFoundError:
                    continue
                if not _ordinary(info) or not stat.S_ISREG(info.st_mode):
                    raise ValueError('Unreadable Dropbox configuration')
                config_data = small_json(config)
                if not isinstance(config_data, dict) or len(config_data) > 32:
                    raise ValueError('Incomplete Dropbox configuration')
                for account in config_data.values():
                    if not isinstance(account, dict) or not isinstance(account.get('path'), str) or not account['path']:
                        raise ValueError('Incomplete Dropbox folder')
                    roots.append(account['path'])
            if len(roots) > 512 or any(not Path(root).is_absolute() or '..' in Path(root).parts for root in roots):
                raise ValueError('Unverified provider root')
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            inspector.roots_known = False
        inspector.cloud_roots = tuple(_cloud_key(_os_path(root)) for root in roots if isinstance(root, (str, Path)) and root)
        inspector.cloud_roots += tuple(_cloud_key(root) for root in extra_cloud_roots if isinstance(root, str) and root)
        return inspector

    def _cloud(self, value):
        key = _cloud_key(value)
        return (any(_cloud_component(part) for part in value.split('/')[:-1])
                or any(key == root or key.startswith(root + '/') for root in self.cloud_roots))

    def _parents(self, path):
        """Return the leaf parent's metadata only if its entire ancestry is ordinary."""
        info = None
        for folder in reversed(path.parents):
            info = folder.lstat()
            if cloud_placeholder(info):
                raise _CloudParent
            if not stat.S_ISDIR(info.st_mode) or not _ordinary(info) or info.st_dev not in self.devices:
                return None
        return info

    def inspect(self, raw, *, cloud_hint=False):
        value, parsed = _path_text(raw)
        os_name, volume, status = _origin(value)
        result = dict(os=os_name, volume=volume, status='unclassified', size=None, identity=None, stamp=None)
        if cloud_hint or self._cloud(value):
            status = 'cloud'
        elif is_name_sidecar(value):
            status = 'sidecar'
        elif not parsed or status:
            pass
        elif os_name != self.host:
            status = 'foreign'
        elif self.host == 'Windows' and volume != self.startup_drive:
            status = 'external' if self.startup_drive else 'unavailable'
        else:
            comparable, music = (value.lower(), self.music.lower()) if self.host == 'Windows' else (value, self.music)
            if not self.music or not comparable.startswith(music + '/'):
                status = 'outside'
            elif not self.can_apply:
                status = 'unavailable'
            else:
                parts = value[len(self.music) + 1:].split('/')
                if (not all(parts) or any(p.startswith('.') for p in parts) or '\\' in value
                        or (self.host == 'Windows' and any(_BAD_WIN.search(p) for p in parts))
                        or Path(parts[-1]).suffix.casefold() not in AUDIO_EXTENSIONS):
                    status = 'unclassified'
                else:
                    self._probe(Path(value), result)
                    return result
        result['status'] = status or 'unclassified'
        return result

    def _probe(self, path, result):
        result['status'] = 'unavailable'
        try:
            before = self._parents(path)
            if before is None or not before.st_ino:
                return
            canonical_parent = path.parent.resolve(strict=True)
            canonical_music = Path(self.music).resolve(strict=True)
            # Preserve native case-sensitive subtree boundaries, including NTFS per-directory mode.
            if canonical_parent.parts[:len(canonical_music.parts)] != canonical_music.parts:
                return
            if self._cloud(_os_path(canonical_parent / path.name)):
                result['status'] = 'cloud'
                return
            try:
                info = path.lstat()
            except FileNotFoundError:
                if self.host == 'macOS':
                    try:
                        path.with_name('.' + path.name + '.icloud').lstat()
                    except FileNotFoundError:
                        pass
                    else:
                        result['status'] = 'cloud'
                        return
                after = self._parents(path)
                if after is not None and _stamp(after) == _stamp(before):
                    result.update(status='missing', stamp=_stamp(after))
                return
            if cloud_placeholder(info):
                result['status'] = 'cloud'
            elif (_ordinary(info) and stat.S_ISREG(info.st_mode) and info.st_dev in self.devices
                  and info.st_ino and info.st_size > 0):
                if sys.platform == 'darwin' and _finder_alias(path):
                    return
                result.update(status='present', stamp=_stamp(info), identity=[info.st_dev, info.st_ino], size=info.st_size)
        except _CloudParent:
            result['status'] = 'cloud'
        except (OSError, RuntimeError, ValueError):
            pass

    def digest(self, raw, evidence, remaining, progress=None):
        """Hash a verified local file under explicit consent, charging even interrupted reads."""
        count = 0
        if (not self.can_apply or evidence.get('status') != 'present' or not evidence.get('size')
                or evidence['size'] > remaining or self.inspect(raw) != evidence):
            return None, count
        value, _ = _path_text(raw)
        try:
            with os.fdopen(_open_for_hash(Path(value)), 'rb', buffering=0) as stream:
                info = os.fstat(stream.fileno())
                if (not _ordinary(info) or not stat.S_ISREG(info.st_mode) or _stamp(info) != evidence['stamp']
                        or self.inspect(raw) != evidence):
                    return None, count
                digest = hashlib.sha256()
                while count < evidence['size']:
                    chunk = stream.read(min(_BLOCK_SIZE, evidence['size'] - count))
                    if not chunk:
                        return None, count
                    count += len(chunk)
                    digest.update(chunk)
                    if progress and (count % (8 * 1024 ** 2) < len(chunk) or count == evidence['size']):
                        progress(count)
                if _stamp(os.fstat(stream.fileno())) == evidence['stamp'] and self.inspect(raw) == evidence:
                    return digest.hexdigest(), count
        except InterruptedError:
            raise
        except (OSError, RuntimeError, ValueError):
            pass
        return None, count
