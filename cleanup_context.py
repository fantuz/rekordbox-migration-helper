"""Source-scoped Workbench evidence that can hold a reference during collection cleanup."""
from collections import defaultdict
from hashlib import sha256
import json

from audio_paths import FIELDS, mapping_applies
from cloud_analysis import classify
from cloud_file_status import lexical_path
from cleanup_paths import _path_text
from collection_views import DUPLICATE_BASES, duplicate_groups, duplicate_review_keys


def _setting(db, name, default):
    row = db.execute('SELECT value FROM settings WHERE name=?', (name,)).fetchone()
    return json.loads(row[0]) if row else default


def _source_keys(snapshot):
    """A saved snapshot can also carry evidence recorded against its originating capture."""
    keys = []
    if snapshot.get('id'):
        keys.append('snapshot:' + snapshot['id'])
    scope = snapshot.get('scope_key', '')
    if scope.startswith('capture:'):
        keys.append(scope)
    return keys


def workspace_stamp(owner, snapshot):
    """A successful session save or a new load invalidates its outstanding reviews."""
    scope = snapshot.get('scope_key') or ''
    if not scope.startswith('session:'):
        return ''
    identity = scope.removeprefix('session:')
    with owner.lock:
        session = owner.sessions.get(identity)
        if owner.active != identity or not session or session.get('id') != identity:
            return 'unavailable'
        values = [identity, session.get('_workspace_generation'), session.get('_state_commit')]
        return sha256(json.dumps(values).encode()).hexdigest()


def _hold_separate(snapshot, separate, hold):
    if separate:
        for basis in DUPLICATE_BASES:
            for group in duplicate_groups(snapshot, basis):
                if group['id'] in separate:
                    for track in group['tracks']:
                        hold(track['id'], 'keep_separate')


def _reference_key(path):
    text, valid = _path_text(path)
    return text if valid else None


def _session_evidence(owner, db, scope, tracks, hold):
    if not scope.startswith('session:'):
        return
    identity = scope.removeprefix('session:')
    session = owner.sessions.get(identity)
    if owner.active != identity or not session or session.get('id') != identity:
        for track in tracks:
            hold(track['id'], 'workspace_unavailable')
        return
    catalog = session['catalog']
    # An old unscoped "keep separate" can only add a hold for a matching group.
    # An explicit later review in this session supersedes that legacy entry.
    reviews = {}
    for name in duplicate_review_keys('workspace', scope):
        reviews.update(_setting(db, name, {}))
    separate = {key for key, value in reviews.items() if value == 'keep_separate'}
    if separate:
        members = [{'id':identity, 'current_path':item.get('current_path'),
                    'artist':item.get('artist'), 'title':item.get('title'), 'isrc':item.get('isrc')}
                   for identity, item in catalog.tracks.items()]
        _hold_separate({'tracks':members}, separate, hold)
    inventory = (session.get('inventory') or {}).get('matches', {})
    for track in tracks:
        track_id = track['id']
        joined = catalog.tracks.get(track_id)
        if joined is None:
            hold(track_id, 'workspace_unavailable')
            continue
        # A native snapshot of an XML + ZIP workspace can omit the alternate
        # XML location and XML-only cue / tempo preparation present in its catalog.
        if joined.get('xml_marks'):
            hold(track_id, 'cues')
        if joined.get('xml_tempo_entries') or joined.get('grid_sha256') or joined.get('preview_sha256'):
            hold(track_id, 'analysis')
        if joined.get('playlist_ids'):
            hold(track_id, 'playlist')
        match = inventory.get(track_id, {})
        candidates = match.get('candidates', [])
        alternatives = {joined[field] for field in FIELDS if joined.get(field)}
        alternatives.update(row['path'] for row in candidates)
        alternatives.difference_update(track.get(field) for field in FIELDS)
        if len(candidates) < match.get('candidate_count', 0):
            hold(track_id, 'alternate_reference')
        elif alternatives:
            # Match the eligibility inspector's strict file-URI parser. Windows
            # can use per-directory case sensitivity, so preserve spelling here.
            known = {_reference_key(track.get(field)) for field in FIELDS} - {None}
            if any(_reference_key(path) not in known for path in alternatives):
                hold(track_id, 'alternate_reference')
        if match.get('status') == 'cloud_only' or any(row.get('cloud_only') for row in candidates):
            hold(track_id, 'cloud_reference')
    for track_id in session.get('relocations', {}):
        hold(track_id, 'workspace_relocation')
    pairs = set(session.get('decisions', {}))
    pairs.update(session.get('held_pairs', {}), session.get('media_verifications', {}))
    # Undo can restore previously held pairs or explicit keeper decisions.
    for batch in session.get('batches', []):
        if isinstance(batch, dict):
            pairs.update(batch.get('previous_decisions', {}), batch.get('previous_held', {}))
    for pair_id in pairs:
        pair = catalog.pairs.get(pair_id)
        if not pair:
            raise ValueError('A staged duplicate decision cannot be resolved in the linked workspace.')
        for track_id in (pair['a'], pair['b']):
            hold(track_id, 'workspace_decision')


def _cloud_evidence(db, sources):
    # A stale binding may only *protect* a reference. It cannot grant cloud access,
    # prove current presence, or prove deletion. No account, token or remote path is returned.
    providers = ('dropbox_records', 'google_drive_records')
    tables = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_schema WHERE type='table' AND name IN (?,?)", providers)}
    cloud = set()
    for source in sources:
        cloud.update(row[0] for row in db.execute(
            """SELECT track_id FROM file_health_records WHERE source=?
               AND (providers!=0 OR cloud_state IN ('online_only','not_local'))""", (source,)))
        for table in providers:
            if table in tables:
                # A provider scan writes an 'unmapped' row for every track outside its mapping.
                # Mapped absence and partial listings are still managed paths.
                cloud.update(row[0] for row in db.execute(
                    f"""SELECT DISTINCT track_id FROM {table} WHERE source=?
                        AND CASE WHEN json_valid(payload) THEN
                            COALESCE(json_extract(payload,'$.status'),'unknown')!='unmapped'
                            ELSE 1 END""", (source,)))
    return cloud


def _enrichment(db, snapshot_id, hold):
    if not snapshot_id:
        return
    # The sample is saved before the first lookup. Include queued as well as reviewed tracks.
    for row in db.execute(
            """SELECT DISTINCT json_extract(sample.value,'$.id')
               FROM mb_batches, json_each(mb_batches.sample) AS sample WHERE snapshot_id=?""", (snapshot_id,)):
        hold(row[0], 'enrichment_review')
    for row in db.execute(
            """SELECT DISTINCT json_extract(track.value,'$.track_id')
               FROM settings, json_each(settings.value, '$.tracks') AS track
               WHERE settings.name GLOB 'onetagger:*' AND json_extract(settings.value,'$.snapshot')=?""",
            (snapshot_id,)):
        hold(row[0], 'enrichment_review')


def build_context(owner, store, snapshot, *, db=None):
    """Purely local exclusion evidence. Supply the publishing transaction's db for a recheck.

    The writer holds owner.lock before its SQLite writer transaction, which keeps both
    active-workspace decisions and private sidecar edits stable through publication.
    """
    if db is None:
        with owner.lock, store.connection() as connection:
            connection.execute('BEGIN')
            return build_context(owner, store, snapshot, db=connection)
    scope = snapshot.get('scope_key') or ''
    sources = _source_keys(snapshot)
    tracks = snapshot['tracks']
    track_ids = {track['id'] for track in tracks}
    protected = defaultdict(set)

    def hold(track_id, reason):
        if track_id in track_ids:
            protected[track_id].add(reason)

    if snapshot.get('cleanup_lineage') or scope.startswith('cleanup:'):
        for track_id in track_ids:
            hold(track_id, 'derived_snapshot')
    _session_evidence(owner, db, scope, tracks, hold)
    for table, reason in (('overrides', 'metadata_edit'), ('override_history', 'edit_history')):
        for row in db.execute(f'SELECT DISTINCT track_id FROM {table} WHERE scope_key=?', (scope,)):
            hold(row[0], reason)
    _enrichment(db, snapshot.get('id'), hold)

    separate = set()
    for source in sources:
        reviews = _setting(db, 'duplicate_reviews:' + source, {})
        separate.update(key for key, value in reviews.items() if value == 'keep_separate')
    _hold_separate(snapshot, separate, hold)

    roots = []
    for provider in ('dropbox', 'google_drive'):
        mapping = _setting(db, provider + '_mapping', None)
        if not mapping:
            continue
        if not isinstance(mapping, dict):
            raise ValueError('The saved cloud folder mapping cannot be verified.')
        if (mapping.get('source') and mapping['source'] not in sources
                or mapping.get('scope_key') and mapping['scope_key'] != scope):
            continue
        for field in ('local_root', 'managed_root', 'recorded_root'):
            path = mapping.get(field)
            if lexical_path(path) is not None:
                roots.append({'kind': provider, 'root': path})
    mappings = _setting(db, 'audio_paths:' + scope, [])
    if not isinstance(mappings, list) or any(not isinstance(m, dict)
            or lexical_path(m.get('recorded_root')) is None or lexical_path(m.get('local_root')) is None
            for m in mappings):
        raise ValueError('The saved audio path mappings cannot be verified.')
    cloud = _cloud_evidence(db, sources) & track_ids
    # Avoid invoking the playback mapper: its existence/case checks can contact mounted volumes.
    if mappings:
        for track in tracks:
            if any(mapping_applies(track.get(field), mappings) for field in FIELDS):
                hold(track['id'], 'mapped_path')
                if classify(track, {'roots': roots, 'mappings': mappings})['providers']:
                    cloud.add(track['id'])
    return {'protected_ids': dict(protected), 'cloud_ids': cloud,
            'extra_cloud_roots': tuple(dict.fromkeys(row['root'] for row in roots))}
