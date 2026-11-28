"""Collection-wide, lexical evidence about captured audio references."""
from collections import Counter
from pathlib import PureWindowsPath

import cloud_analysis
import metadata_sidecars
from cloud_file_status import lexical_path, PROVIDERS
from export_references import decoded_path

MODES = ('all', 'changed', 'missing_path', 'shared_path', 'missing_analysis', 'cross_platform')
GROUPS = ('none', 'folder', 'volume', 'format', 'cloud', 'platform')
FIELDS = ('id', 'title', 'artist', 'current_path', 'original_path', 'analysis_path', 'xml_location', 'size')


def recorded_path(value):
    path = lexical_path(value)
    if path is not None or not isinstance(value, str):
        return path
    if not (value.startswith(('//', '\\\\')) or value.casefold().startswith('file:')):
        return None
    # Analyse recorded UNC shares and their file URIs without accessing them.
    try:
        decoded = decoded_path(value)
    except ValueError:
        return None
    if decoded.startswith('//') and not decoded.startswith(('//?/', '//./')) and ':' not in decoded:
        share = PureWindowsPath(decoded)
        if share.is_absolute():
            return share
    return None


def has_text(value):
    return isinstance(value, str) and bool(value.strip())


def platform(path, value):
    if isinstance(path, PureWindowsPath):
        return 'network_share' if path.drive.startswith('\\\\') else 'windows_drive'
    if path is not None:
        return 'posix'
    return 'unrecognized' if has_text(value) else 'unknown'


def path_volume(path):
    if isinstance(path, PureWindowsPath):
        return path.anchor.replace('\\', '/')
    parts = path.parts
    # Conventional mount prefixes are labels from the reference. Their
    # presence in a path does not establish a mount on this computer.
    if len(parts) > 3 and parts[1] in ('Volumes', 'mnt'):
        return '/' + '/'.join(parts[1:3])
    if len(parts) > 5 and parts[1:3] == ('run', 'media'):
        return '/' + '/'.join(parts[1:5])
    if len(parts) > 4 and parts[1] == 'media':
        return '/' + '/'.join(parts[1:4])
    return path.anchor


def reference_flags(track, path, shared, analysis_captured):
    current, original = track.get('current_path'), track.get('original_path')
    old = recorded_path(original)
    flags = []
    if has_text(original) and (old != path if old is not None else original != current):
        flags.append('changed')
    if not has_text(current):
        flags.append('missing_path')
    if path is not None and shared[path] > 1:
        flags.append('shared_path')
    if analysis_captured and not has_text(track.get('analysis_path')):
        flags.append('missing_analysis')
    if path is not None and old is not None and type(path) is not type(old):
        flags.append('cross_platform')
    return flags


def reference_group(grouping, row, path, location):
    if grouping == 'platform':
        kind = platform(path, row['current_path'])
        return kind, kind, True
    if grouping == 'cloud':
        mask = location['providers']
        if not location['provider_checked']:
            kind = 'unknown'
        elif not mask:
            kind = 'other'
        else:
            kind = next((key for key, value in PROVIDERS.items() if value == mask), 'multiple')
        return kind, kind, True
    if path is None or (grouping == 'format' and not path.suffix):
        return '', '', False
    if grouping == 'format':
        value = path.suffix[1:].upper()
        return value, value, False
    value = path.parent.as_posix() if grouping == 'folder' else path_volume(path)
    key = value.casefold() if isinstance(path, PureWindowsPath) else value
    return key, value, False


def reference_rows(snapshot, matches, mode, grouping, provider, configuration, hide_sidecars):
    if mode not in MODES or grouping not in GROUPS:
        raise ValueError('Choose a reference filter or grouping')
    provider = cloud_analysis.checked_provider(provider)
    tracks = snapshot['tracks']
    shared = Counter(path for track in tracks if (path := recorded_path(track.get('current_path'))) is not None)
    analysis_captured = snapshot.get('capabilities', {}).get('analysis_references') is True
    matching, sidecars = metadata_sidecars.select((track for track in tracks if matches(track)), hide_sidecars)
    locations, selected_locations, rows = [], [], []
    counts = dict.fromkeys(MODES, 0)
    for track in matching:
        location = cloud_analysis.classify(track, configuration)
        locations.append(location)
        if not cloud_analysis.matches(location, provider):
            continue
        path = recorded_path(track.get('current_path'))
        flags = reference_flags(track, path, shared, analysis_captured)
        counts['all'] += 1
        for flag in flags:
            counts[flag] += 1
        if mode != 'all' and mode not in flags:
            continue
        selected_locations.append(location)
        row = {field: track.get(field) for field in FIELDS}
        row['flags'] = flags
        if grouping != 'none':
            key, label, translated = reference_group(grouping, row, path, location)
            row['group'] = {'key': key, 'label': label, 'translated': translated}
        rows.append(row)
    if not analysis_captured:
        counts['missing_analysis'] = None
    cloud = {'provider': provider, 'counts': cloud_analysis.counts(locations),
             'selected_counts': cloud_analysis.counts(selected_locations), 'note': cloud_analysis.NOTE}
    return rows, counts, sidecars, cloud


def group_references(rows, grouping):
    """Keep each group together across pages, retaining the requested row sort."""
    if grouping == 'none':
        return rows
    counts = Counter(row['group']['key'] for row in rows)
    labels = {}
    for row in rows:
        group = row['group']
        key = group['key']
        group['count'] = counts[key]
        group['label'] = labels.setdefault(key, group['label'])
    return sorted(rows, key=lambda row: (not row['group']['key'], row['group']['key'].casefold(), row['group']['key']))
