"""Collection storage totals from saved sizes and explicit File health scans."""
from collections import defaultdict

from audio_paths import signature as mapping_signature
from cloud_file_status import PATH_FIELDS
from reference_views import recorded_path
from result_cache import signature as source_signature
from stems_eligibility import provider as track_provider
from storage_sizes import byte_count
from workbench_store import Store, encoded


OBSERVED_LOCATIONS = ('current', 'alternate', 'mapped', 'placeholder')
STREAMING = {'apple_music', 'spotify', 'other_streaming'}


def captured_size(track):
    # A saved zero cannot establish an expected recording size.
    return byte_count(track.get('size', track.get('size_bytes')), minimum=1)


def measure(values):
    known = [size for size in values if size is not None]
    return {'bytes': sum(known) if known or not values else None,
            'known': len(known), 'total': len(values)}


def recorded_storage(selected):
    recorded, cloud, streaming = [], [], []
    paths = defaultdict(set)
    for track, evidence in selected:
        size = captured_size(track)
        recorded.append(size)
        value = next((track[field] for field in PATH_FIELDS if track.get(field)), None)
        path = recorded_path(value)
        if path is not None:
            sizes = paths[path]
            if size is not None:
                sizes.add(size)
        if evidence['providers']:
            cloud.append(size)
        source_details = track.get('source_evidence')
        if not isinstance(source_details, dict) and (source_details is not None or track.get('service_id') is not None):
            track = {**track, 'source_evidence': {'service_id': track.get('service_id')}}
        if track_provider(track, {})[0] in STREAMING:
            streaming.append(size)
    unique = measure([next(iter(sizes)) if len(sizes) == 1 else None for sizes in paths.values()])
    unique['conflicts'] = sum(len(sizes) > 1 for sizes in paths.values())
    return {'recorded': measure(recorded), 'unique_paths': unique,
            'cloud': measure(cloud), 'streaming': measure(streaming)}


def capture_revision(owner, source):
    return encoded(source_signature(owner, source))


def scan_row(db, source):
    return db.execute(
        'SELECT state, checked_at, mapping_revision, source_revision, evidence_revision '
        'FROM file_health_scans WHERE source=?', (source,)).fetchone()


def observation_signature(owner, source):
    saved = Store(owner.DATA / 'workbench-sidecar.sqlite3')
    with saved.connection() as db:
        row = scan_row(db, source)
        return tuple(row) if row is not None else None


def observed_storage(owner, source, tracks, mappings):
    unavailable = {'state': 'workspace' if source == 'workspace' else 'not_started'}
    if not owner or not source or source == 'workspace':
        return unavailable
    saved = Store(owner.DATA / 'workbench-sidecar.sqlite3')
    recorded = {str(track['id']): captured_size(track) for track in tracks}
    revision = capture_revision(owner, source)
    with saved.connection() as db:
        # Read one committed scan revision and its observations, even while a
        # new batch is being written by the explicit File health worker.
        db.execute('BEGIN')
        scan = scan_row(db, source)
        if scan is None:
            return unavailable
        if scan['source_revision'] is None or scan['mapping_revision'] is None:
            return {'state': 'legacy'}
        if scan['mapping_revision'] != mapping_signature(mappings):
            return {'state': 'mapping_changed'}
        if scan['source_revision'] != revision:
            return {'state': 'legacy'}

        results = {kind: {'bytes': None, 'recorded_bytes': None, 'entries': 0,
                          'paired': 0, 'paired_bytes': None, 'mismatches': 0}
                   for kind in OBSERVED_LOCATIONS}
        checked = 0
        for row in db.execute(
            'SELECT track_id, logical_size, observed_location, cloud_state '
            'FROM file_health_records WHERE source=?', (source,)
        ):
            if row['track_id'] not in recorded:
                continue
            checked += 1
            actual = byte_count(row['logical_size'])
            kind = 'placeholder' if row['cloud_state'] == 'online_only' else row['observed_location']
            if actual is None or kind not in results:
                continue
            result = results[kind]
            result['entries'] += 1
            result['bytes'] = (result['bytes'] or 0) + actual
            expected = recorded[row['track_id']]
            if expected is not None:
                result['paired'] += 1
                result['recorded_bytes'] = (result['recorded_bytes'] or 0) + expected
                result['paired_bytes'] = (result['paired_bytes'] or 0) + actual
                result['mismatches'] += actual != expected
    return {'state': scan['state'], 'checked_at': scan['checked_at'],
            'checked': checked, 'total': len(tracks), 'locations': results}
