"""Provider path evidence, not a remote inventory or an audio-content reader."""
from copy import deepcopy
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sys
from threading import RLock
import time
from urllib.parse import unquote, urlsplit

PROVIDERS = {'dropbox': 1, 'google_drive': 2}
PATH_FIELDS = ('current_path', 'xml_location', 'original_path')
_ROOTS = {}
_LOCK = RLock()


def provider_context():
    """Read bounded local provider configuration once per ten seconds."""
    key = (sys.platform, str(Path.home()), os.environ.get('APPDATA', ''), os.environ.get('LOCALAPPDATA', ''))
    now = time.monotonic()
    with _LOCK:
        cached = _ROOTS.get(key)
        if cached and 0 <= now - cached[0] < 10:
            return deepcopy(cached[1])
    from cloud_locations import provider_roots
    roots = provider_roots(include_unavailable=True)
    with _LOCK:
        _ROOTS.clear()
        _ROOTS[key] = (now, deepcopy(roots))
    return roots


def lexical_path(value):
    """Parse captured Windows/POSIX references on any host without filesystem IO."""
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        return None
    if value.casefold().startswith('file:'):
        try:
            parsed = urlsplit(value)
        except ValueError:
            return None
        if parsed.netloc.casefold() not in ('', 'localhost') or parsed.query or parsed.fragment:
            return None
        value = unquote(parsed.path)
        if re.match(r'^/[a-zA-Z]:[/\\]', value):
            value = value[1:]
    if any(ord(c) < 32 for c in value) or value.startswith(('//', '\\\\')):
        return None
    path = PureWindowsPath(value) if re.match(r'^[a-zA-Z]:[/\\]', value) else PurePosixPath(value)
    if not path.is_absolute() or '..' in path.parts:
        return None
    if isinstance(path, PureWindowsPath) and ':' in str(path)[2:]:
        return None
    return path


def path_providers(value, roots):
    """Return evidence labels; neither matching method verifies cloud membership."""
    path = lexical_path(str(value) if isinstance(value, Path) else value)
    if path is None:
        return {}
    matches = {}
    for root in roots:
        kind = root.get('kind')
        base = lexical_path(root.get('root'))
        if kind not in PROVIDERS or base is None or type(base) is not type(path):
            continue
        # PureWindowsPath compares components case-insensitively. POSIX does not.
        if path.is_relative_to(base):
            matches[kind] = 'detected_root' if root.get('provider_verified') else 'folder_hint'
    # Inspect directory components only: a song called "Dropbox.mp3" is no hint.
    for part in path.parts[:-1]:
        if re.search(r'(?:^|[\s_-])dropbox(?:$|[\s_(-])', part, re.I):
            matches.setdefault('dropbox', 'path_hint')
        if re.match(r'^google(?:\s*drive)(?:$|[\s_(-])', part, re.I):
            matches.setdefault('google_drive', 'path_hint')
    return matches


def track_providers(track, mappings, roots):
    from audio_paths import mapped_path, mapping_applies
    matches = {}
    for field in PATH_FIELDS:
        value = track.get(field)
        if not value:
            continue
        for kind, evidence in path_providers(value, roots).items():
            if kind not in matches or evidence == 'detected_root':
                matches[kind] = evidence
        if mapping_applies(value, mappings):
            mapped = mapped_path(value, mappings)
            if mapped:
                for kind, evidence in path_providers(mapped, roots).items():
                    if kind not in matches or evidence == 'detected_root':
                        matches[kind] = evidence
    return matches


def provider_mask(matches):
    return sum(PROVIDERS[kind] for kind in matches if kind in PROVIDERS)


def captured_filename(track):
    for field in PATH_FIELDS:
        path = lexical_path(track.get(field))
        if path:
            return path.name
    return ''
