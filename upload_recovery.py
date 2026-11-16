"""Retryable, serialized uploads in the owned temporary workspace only."""
from contextlib import contextmanager
import errno
import json
import os
import shutil
from threading import Lock
from werkzeug.exceptions import Conflict

_guard = Lock()
_active = set()
RESERVE_BYTES = 16 * 1024 * 1024


@contextmanager
def slot(key):
    with _guard:
        if key in _active:
            raise Conflict('This file is still uploading. Wait or cancel it before retrying.')
        _active.add(key)
    try:
        yield
    finally:
        with _guard:
            _active.discard(key)


def receive(runtime, sid, kind, source, length=None, cancelled=lambda: False):
    folder = runtime.path / sid
    info_path = folder / 'upload.json'
    if folder.is_symlink() or folder.is_junction() or not info_path.is_file() or info_path.is_symlink():
        raise ValueError('This upload session is unavailable. Start a new import.')
    key = (str(runtime.path), sid, kind)
    with slot(key), runtime.operation():
        info = json.loads(info_path.read_text(encoding='utf-8'))
        name = info.get(kind)
        if not isinstance(name, str) or not name or '/' in name or '\\' in name:
            raise ValueError('Invalid upload session. Start a new import.')
        final = folder / name
        temp = folder / (kind + '.part')
        if final.exists():
            raise ValueError('File has already been uploaded')
        done = 0
        try:
            # The slot proves no live writer owns a leftover partial file.
            temp.unlink(missing_ok=True)
            if length is not None and length + RESERVE_BYTES > shutil.disk_usage(folder).free:
                raise ValueError('Not enough free space for this upload. Free space or use existing files without copying.')
            with temp.open('xb') as stream:
                while chunk := source.read(2 * 1024 * 1024):
                    if cancelled():
                        raise ValueError('Upload cancelled. You can retry this file.')
                    stream.write(chunk)
                    done += len(chunk)
            if not done:
                raise ValueError('File is empty')
            if length is not None and done != length:
                raise ValueError('Upload was interrupted. Retry this file.')
            if cancelled():
                raise ValueError('Upload cancelled. You can retry this file.')
            os.replace(temp, final)
            return done
        except OSError as error:
            if error.errno == errno.ENOSPC:
                raise ValueError('Storage filled during upload. Free space and retry this file.') from error
            if error.errno in (errno.EACCES, errno.EPERM):
                raise ValueError('The temporary folder is not writable. Check permissions and retry.') from error
            raise ValueError('The upload could not be saved. Check storage and retry this file.') from error
        finally:
            try:temp.unlink(missing_ok=True)
            except OSError:pass  # Retry removes abandoned partials after permissions are repaired.
