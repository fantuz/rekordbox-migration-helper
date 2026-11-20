"""Lexical cloud-location lenses over captured paths, never file-access checks.

Only bounded provider configuration and saved folder mappings are read. No media
path is stat'ed, opened, listed or hydrated by classification or filtering.
"""
from hashlib import sha256
import json

from cloud_file_status import PATH_FIELDS, PROVIDERS, lexical_path, path_providers, provider_context
from workbench_store import Store

OPTIONS = ('all', 'dropbox', 'google_drive', 'other', 'unknown')
NOTE = 'Recorded or mapped paths; not cloud presence or local availability.'


def checked_provider(value='all'):
    value = value or 'all'
    if value not in OPTIONS:
        raise ValueError('Choose a supported cloud location filter')
    return value


def context(owner, source, snapshot=None, saved=None):
    """Return source-bound lexical hints; a disconnected mapping stays a hint."""
    saved = saved or Store(owner.DATA / 'workbench-sidecar.sqlite3')
    if snapshot is None:
        scope = source
        if source.startswith('snapshot:'):
            with saved.connection() as db:
                row = db.execute('SELECT scope_key FROM snapshots WHERE id=?', (source[9:],)).fetchone()
            scope = row['scope_key'] if row else ''
        elif source == 'workspace':
            scope = 'session:' + owner.current()['id']
    else:
        scope = str(snapshot.get('scope_key') or source)
    roots = [{key: row.get(key) for key in ('kind', 'root', 'provider_verified')}
             for row in provider_context()]
    for provider, setting in (('dropbox', 'dropbox_mapping'), ('google_drive', 'google_drive_mapping')):
        mapping = saved.setting(setting, None)
        if (not isinstance(mapping, dict) or mapping.get('source') not in (None, '', source)
                or mapping.get('scope_key') not in (None, '', scope)):
            continue
        # Attached roots provide location evidence only. Account access and the
        # current filesystem identity are deliberately not revalidated here.
        for field in ('local_root', 'recorded_root'):
            root = mapping.get(field)
            if lexical_path(root) is not None:
                roots.append({'kind': provider, 'root': root, 'provider_verified': False})
    audio = saved.setting('audio_paths:' + scope, [])
    return {'roots': roots, 'mappings': audio if isinstance(audio, list) else []}


def signature(value):
    return sha256(json.dumps(['cloud-location-v1', value], sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _mapped(value, mappings):
    """Translate the longest saved prefix lexically, without mapped_path IO."""
    path = lexical_path(value)
    if path is None:
        return None
    candidates = []
    for row in mappings:
        if not isinstance(row, dict):
            continue
        prefix, root = lexical_path(row.get('recorded_root')), lexical_path(row.get('local_root'))
        if prefix is None or root is None or type(prefix) is not type(path) or not path.is_relative_to(prefix):
            continue
        candidates.append((len(prefix.parts), root, path.relative_to(prefix).parts))
    if not candidates:
        return None
    _, root, parts = max(candidates, key=lambda row: row[0])
    return str(root.joinpath(*parts))


def classify(track, configuration=None):
    configuration = configuration or {}
    roots, mappings = configuration.get('roots', []), configuration.get('mappings', [])
    matches, known = {}, False
    for field in PATH_FIELDS:
        value = track.get(field)
        if lexical_path(value) is None:
            continue
        known = True
        for candidate in (value, _mapped(value, mappings)):
            if candidate is not None:
                matches.update(path_providers(candidate, roots))
    return {'providers': sum(PROVIDERS[kind] for kind in matches), 'provider_checked': known}


def matches(record, provider):
    provider = checked_provider(provider)
    if provider == 'all':
        return True
    if provider == 'unknown':
        return not record.get('provider_checked')
    if not record.get('provider_checked'):
        return False
    mask = record.get('providers', 0)
    return not mask if provider == 'other' else bool(mask & PROVIDERS[provider])


def counts(records):
    result = dict.fromkeys(OPTIONS, 0)
    for record in records:
        result['all'] += 1
        if not record.get('provider_checked'):
            result['unknown'] += 1
        elif not record.get('providers'):
            result['other'] += 1
        else:
            for provider, mask in PROVIDERS.items():
                result[provider] += bool(record['providers'] & mask)
    return result


def select(tracks, provider='all', configuration=None):
    """Return original track objects and scope counts without mutating tracks."""
    provider = checked_provider(provider)
    pairs = [(track, classify(track, configuration)) for track in tracks]
    selected = [(track, record) for track, record in pairs if matches(record, provider)]
    return [track for track, _ in selected], {
        'provider': provider, 'counts': counts(record for _, record in pairs),
        'selected_counts': counts(record for _, record in selected), 'note': NOTE,
    }
