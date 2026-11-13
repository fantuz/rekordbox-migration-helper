"""Evidence summaries and resumable plans; no rekordbox source is opened here."""
from collections import Counter
from copy import deepcopy
from uuid import uuid4

from library_checks import metadata_consistency
from workbench_store import now


STEPS = (
    ('backup', 'Keep a separate backup', 'files'),
    ('capture', 'Capture the source library', 'analyzer'),
    ('availability', 'Check audio and cloud availability', 'inventory'),
    ('paths', 'Plan destination paths', 'reference'),
    ('cleanup', 'Review optional cleanup', 'review'),
    ('export', 'Create copy exports', 'exports'),
    ('restore', 'Restore on the destination', 'files'),
    ('compare', 'Capture and compare the destination', 'lab'),
)


def new_plan(kind, source=''):
    if kind not in ('migration', 'integrity'):
        raise ValueError('Choose a migration or integrity journey')
    if not isinstance(source, str) or len(source) > 128:
        raise ValueError('Choose a loaded workspace or saved collection snapshot')
    return {'id': uuid4().hex, 'kind': kind, 'created': now(), 'updated': now(),
            'source': source, 'before_snapshot': source[9:] if source.startswith('snapshot:') else '',
            'after_snapshot': '', 'destination_root': '', 'cloud_mode': 'unknown', 'notes': '',
            'steps': {}, 'report': None, 'comparison': None}


def update_plan(plan, changes, snapshot_exists):
    """Record user confirmations separately from machine-checked evidence."""
    result = deepcopy(plan)
    allowed = {'step', 'status', 'before_snapshot', 'after_snapshot', 'destination_root', 'cloud_mode', 'notes'}
    if set(changes) - allowed:
        raise ValueError('Unsupported journey field')
    if 'status' in changes and 'step' not in changes:
        raise ValueError('Choose a journey step for this confirmation')
    for field, limit in (('destination_root', 4096), ('notes', 4000)):
        if field in changes:
            value = changes[field]
            if not isinstance(value, str) or len(value) > limit or '\x00' in value:
                raise ValueError('Journey text is invalid or too long')
            result[field] = value.strip()
    for field in ('before_snapshot', 'after_snapshot'):
        if field in changes:
            identity = changes[field]
            if not isinstance(identity, str):
                raise ValueError('Choose a saved collection snapshot')
            if identity:
                snapshot_exists(identity)
            if identity != result.get(field):
                result['comparison'] = None
            result[field] = identity
    if 'cloud_mode' in changes:
        if changes['cloud_mode'] not in ('unknown', 'copy', 'move', 'no-cloud'):
            raise ValueError('Choose an available cloud mode')
        result['cloud_mode'] = changes['cloud_mode']
    if 'step' in changes:
        step = changes['step']
        status = changes.get('status', 'pending')
        if not isinstance(step, str) or step not in {row[0] for row in STEPS} or status not in ('pending', 'confirmed', 'skipped'):
            raise ValueError('Choose a journey step and confirmation status')
        if status == 'skipped' and step != 'cleanup':
            raise ValueError('Only optional cleanup can be skipped')
        result['steps'][step] = {'status': status, 'updated': now(), 'basis': 'user statement'}
    result['updated'] = now()
    return result


def context(snapshot, *, source='', overrides=0):
    tracks = snapshot.get('tracks', [])
    capabilities = snapshot.get('capabilities', {})
    return {'source': source, 'snapshot': snapshot.get('id'), 'label': snapshot.get('label', 'Loaded library'),
            'captured': snapshot.get('source_captured') or snapshot.get('captured'),
            'scope': snapshot.get('scope', 'all'), 'scope_key': snapshot.get('scope_key'),
            'source_kind': snapshot.get('source_kind'), 'tracks': len(tracks),
            'basis': 'captured', 'working_override_fields': overrides,
            'capabilities': {key: bool(capabilities.get(key)) for key in
                             ('cue_positions', 'playlist_order', 'analysis_references', 'history_details', 'history_order')},
            'cleanup_plan_applied': False}


def integrity(snapshot, source_report=None, inventory=None, asset_summary=None, depth='quick'):
    """Unknown and unchecked evidence never becomes an all-clear result."""
    if depth not in ('quick', 'deep'):
        raise ValueError('Choose quick or deep integrity scope')
    checks = []
    def add(key, label, status, detail, count=None):
        checks.append({'section': key, 'title': label, 'status': status,
                       'severity': 'warning' if status == 'issue' else 'review' if status == 'review' else 'info',
                       'detail': detail, 'count': count})
    report = source_report or {}
    database = report.get('database') or {}
    if 'integrity_ok' in database:
        add('database', 'Database integrity', 'clear' if database['integrity_ok'] else 'issue',
            'Saved private-copy SQLite integrity result; not a live-library check.')
    else:
        add('database', 'Database integrity', 'not_checked',
            'A saved native database integrity result is unavailable. XML alone cannot establish database integrity.')
    missing = database.get('missing_core_columns')
    if missing is not None:
        add('schema', 'Required database fields', 'issue' if missing else 'clear',
            ', '.join(missing) if missing else 'Required desktop track fields were present in the captured database.', len(missing))
    else:
        add('schema', 'Required database fields', 'not_checked', 'No native schema result is available.')
    health = database.get('health') or {}
    broken = health.get('broken_track_links')
    if broken is None:
        broken = (report.get('xml') or {}).get('counters', {}).get('unresolved_playlist_references')
    add('relationships', 'Broken record references', 'unknown' if broken is None else 'issue' if broken else 'clear',
        'Native relationship checks or unresolved XML playlist references, within the captured scope.', broken)
    repeated = health.get('duplicate_recorded_path_groups')
    add('duplicate_paths', 'Repeated recorded paths', 'not_checked' if repeated is None else 'review' if repeated else 'clear',
        'Repeated database paths are candidates; they do not prove duplicate audio bytes.', repeated)
    tags, rows = metadata_consistency(snapshot)
    findings = tags.get('tracks_with_missing_tags', 0) + tags.get('implausible_values', 0) + tags.get('variant_groups', 0)
    add('metadata', 'Metadata consistency', 'review' if findings else 'clear',
        'Missing fields, review thresholds and case/spacing/Unicode variants; these are not automatic corrections.', findings)
    if inventory is None:
        add('audio', 'Audio availability', 'not_checked', 'Run Media inventory on selected music roots. Cloud-only files must be downloaded before playback or byte verification.')
    else:
        counts = inventory.get('counts', {})
        missing = counts.get('not_found', 0)
        unknown = counts.get('unverified', 0) + counts.get('ambiguous', 0) + counts.get('cloud_only', 0)
        partial = bool(inventory.get('warnings')) or sum(counts.values()) < len(snapshot['tracks'])
        add('audio', 'Audio availability', 'unknown' if partial else 'review' if missing or unknown else 'clear',
            'Saved selected-root inventory only; not found in this scope does not prove a file was deleted.', missing + unknown)
    if depth == 'quick' or asset_summary is None:
        add('assets', 'Analysis assets', 'not_checked', 'Deep scope can inventory explicit analysis folders or backup ZIPs. No asset roots are scanned implicitly.')
    else:
        count = asset_summary.get('missing_in_scope', 0) + (asset_summary.get('unreferenced_folders') or 0) + asset_summary.get('duplicate_candidate_groups', 0)
        complete = asset_summary.get('inventory_complete') is True and asset_summary.get('ownership_complete') is True
        add('assets', 'Analysis assets', 'unknown' if not complete else 'review' if count else 'clear',
            'Selected-root audit. Missing here may exist elsewhere; unreferenced assets may belong to another library. No deletion is proposed.', count)
    add('cloud', 'Cloud copy or move setting', 'unknown', 'Paths and database rows cannot prove the chosen cloud Copy/Move setting. Record your choice in the migration journey.')
    counts = dict(Counter(row['status'] for row in checks))
    return {'depth': depth, 'tracks': len(snapshot['tracks']), 'checks': counts,
            'source_captured': snapshot.get('source_captured') or snapshot.get('captured'),
            'scope': snapshot.get('scope', 'all'), 'working_metadata_applied': 0,
            'asset_scope': asset_summary, 'metadata': tags, 'source_writes': False}, checks + rows
