"""Logical destination references, independent of the helper's operating system.

Local audio mappings are access aliases only. No filesystem probe belongs here.
"""
from collections import Counter
import re
import posixpath
from urllib.parse import unquote, urlsplit

TARGETS = ('auto', 'windows', 'macos')
FIELDS = ('current_path', 'xml_location')
LINUX_ROOTS = ('/home', '/media', '/mnt', '/run', '/tmp', '/var/tmp', '/workspace', '/proc', '/sys', '/dev')


def decoded_path(value, require_uri=False):
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise ValueError('Provide an absolute exported file reference.')
    if value.lower().startswith('file:'):
        try:
            parsed = urlsplit(value)
            if parsed.query or parsed.fragment or re.search(r'%(?![0-9a-fA-F]{2})', value):
                raise ValueError()
            path = unquote(parsed.path, errors='strict')
            if parsed.netloc.lower() not in ('', 'localhost'):
                if not re.fullmatch(r'[\w.-]+', parsed.netloc):raise ValueError()
                path = '//' + parsed.netloc + path
        except (ValueError, UnicodeError):
            raise ValueError('Use a valid file URI; encode spaces and special characters in the destination.') from None
    elif require_uri:
        raise ValueError('Use a file URI for the exported reference.')
    else:
        path = value
    path = path.replace('\\', '/')
    if re.match(r'^/[A-Za-z]:/', path):path = path[1:]
    if any(ord(c) < 32 for c in path) or '..' in path.split('/') or not (path.startswith('/') or re.match(r'^[A-Za-z]:/', path)):
        raise ValueError('Use an absolute destination without parent-directory traversal.')
    return path


def platform(value):
    try:path = decoded_path(value)
    except ValueError:return None
    if re.match(r'^[A-Za-z]:/', path) or path.startswith('//'):return 'windows'
    if any(path == p or path.startswith(p + '/') for p in ('/Users', '/Volumes', '/Library')):
        return 'macos'
    return None


def source_profile(catalog):
    cached = getattr(catalog, '_export_reference_profile', None)
    if cached is not None:return cached
    counts = Counter()
    for track in getattr(catalog, 'tracks', {}).values():
        values = [track.get(k) for k in FIELDS if track.get(k)]
        if not values and track.get('original_path'):values = [track['original_path']]
        kinds = {platform(value) or 'unknown' for value in values}
        counts.update(kinds or {'missing'})
    known = [p for p in ('windows', 'macos') if counts[p]]
    detected = known[0] if len(known) == 1 and not counts['unknown'] else None
    result = {'detected': detected, 'evidence': dict(counts),
              'basis': 'Recorded current/XML references; never the helper OS or mount location'}
    catalog._export_reference_profile = result
    return result


def target_info(catalog, requested='auto'):
    if requested not in TARGETS:raise ValueError('Choose Windows, macOS or the detected source target.')
    evidence = source_profile(catalog)
    return {**evidence, 'requested': requested,
            'target': evidence['detected'] if requested == 'auto' else requested}


def target_for(catalog):
    result = target_info(catalog, catalog.metadata.get('export_target', 'auto'))
    if not result['target']:
        raise ValueError('Choose Windows or macOS in Prepare export: the recorded source paths are mixed or unknown.')
    return result['target']


def at_root(path, root):
    path, root = posixpath.normpath(path), posixpath.normpath(root)
    if re.match(r'^[A-Za-z]:/', root) or root.startswith('//'):
        path, root = path.casefold(), root.casefold()
    return path == root.rstrip('/') or path.startswith(root.rstrip('/') + '/')


def validate_reference(uri, target, audio_mappings=()):
    path = decoded_path(uri, require_uri=True)
    if any(at_root(path, root) for root in LINUX_ROOTS):
        raise ValueError('A Linux access path cannot be an exported reference. Enter the Windows or macOS destination.')
    for mapping in audio_mappings:
        local = str(mapping.get('local_root', '')).replace('\\', '/')
        recorded = mapping.get('recorded_root', '')
        if local and local != recorded and at_root(path, local):
            raise ValueError('This is a local playback mapping. Enter the recorded destination path for export.')
    kind = platform(uri)
    if target == 'windows':
        if kind != 'windows':raise ValueError('The Windows export target requires a drive-letter or UNC file reference.')
        tail = path[3:] if re.match(r'^[A-Za-z]:/', path) else path[2:]
        if not tail or any(not p or re.search(r'[<>:"|?*]', p) or p.endswith((' ', '.')) for p in tail.split('/')):
            raise ValueError('The exported reference contains an invalid Windows path component.')
    elif target == 'macos':
        if not path.startswith('/') or path.startswith('//') or kind == 'windows':
            raise ValueError('The macOS export target requires an absolute macOS file reference.')
    else:
        raise ValueError('Choose the Windows or macOS export target first.')
    return uri  # Preserve the exact reviewed spelling and URI encoding.


def validate_relocations(catalog, relocations, audio_mappings=None):
    target = target_for(catalog)
    aliases = catalog.metadata.get('_audio_access_mappings', ()) if audio_mappings is None else audio_mappings
    for identity, uri in relocations.items():
        if identity not in catalog.tracks:raise ValueError('Unknown track in the exported reference edits.')
        validate_reference(uri, target, aliases)
    return target


def validate_export(catalog, relocations, kind='pair', retired=()):
    target = validate_relocations(catalog, relocations)
    # A deliberate platform change needs destination references for the other
    # platform's surviving tracks. Selecting a target is not path conversion.
    fields = ('xml_location',) if kind == 'xml' else ('current_path',) if kind == 'zip' else FIELDS
    for identity, track in catalog.tracks.items():
        if identity in relocations or identity in retired:continue
        if kind == 'xml' and not track.get('october_xml', True):continue
        for field in fields:
            value = track.get(field) or track.get('current_path') or track.get('original_path')
            if not value:continue
            detected = platform(value)
            if detected and detected != target:
                raise ValueError('Some recorded references still use the other platform. Review destination references before exporting.')
            try:path = decoded_path(value)
            except ValueError:continue  # Preserve historical unknown references without inventing a replacement.
            if any(at_root(path, root) for root in LINUX_ROOTS):
                raise ValueError('A recorded reference uses a Linux access path. Review it in File references before export.')
    return target


def restore_note(target):
    name = {'windows': 'Windows', 'macos': 'macOS'}.get(target, 'target-platform')
    return 'Verify in an isolated ' + name + ' rekordbox library with Cloud Library Sync paused before replacing your working library.'
