"""Bounded, persistent *advisory* evidence about local audio paths.

No source or media is modified. Entries contain path digests, not raw paths.
Statuses are intentionally not proof of decodable media or duplicate content.
"""
from hashlib import sha256
import json
import sys
import time

from workbench_store import Store
from track_playback import inspect_audio_details
from cloud_file_status import provider_context

SCHEMA = 'file-status-v4-location-evidence'
MAX_ENTRIES = 20000
TTL = {
    'playable': 3600,
    'missing': 90,
    'inaccessible': 90,
    'unverified': 300,
}
PATH_FIELDS = ('current_path', 'xml_location', 'original_path')


def fingerprint(track, mappings=None, roots=None):
    # Both the current and alternate recorded paths affect the result.
    # Include the host OS: a Windows path is not a POSIX local file.
    paths = [str(track.get(field)) if track.get(field) is not None else None
             for field in PATH_FIELDS]
    context=[(r.get('kind'),r.get('root'),r.get('provider_verified')) for r in (roots or [])]
    payload = json.dumps([SCHEMA, sys.platform, paths, mappings or [],context], ensure_ascii=False,
                         separators=(',', ':'))
    return sha256(payload.encode('utf-8')).hexdigest()


def inspect(owner, tracks, refresh=False, mappings=None, details=False, roots=None):
    """Return (status, cache-hit) maps for server-resolved track IDs.

    A separate explicit refresh bypasses the cache, e.g. after reconnecting
    a removable disk. A playback launch never trusts these entries.
    """
    statuses, hits, groups, evidence = {}, {}, {}, {}
    roots=provider_context() if roots is None else roots
    for identity, track in tracks.items():
        if not isinstance(track, dict):
            statuses[identity] = 'unverified'
            hits[identity] = False
            evidence[identity] = {}
            continue
        groups.setdefault(fingerprint(track,mappings,roots), {'track': track, 'ids': []})['ids'].append(identity)

    if not groups:
        return (statuses,hits,evidence) if details else (statuses,hits)

    store = Store(owner.DATA / 'workbench-sidecar.sqlite3')
    now = time.time()
    keys = list(groups)
    placeholders = ','.join('?' for _ in keys)
    with store.connection() as db:
        old = {row['key']: row for row in db.execute(
            f'SELECT key,status,checked_at,evidence FROM file_status_cache WHERE key IN ({placeholders})', keys)}

    writes = []
    for key, group in groups.items():
        cached = old.get(key)
        valid = (not refresh and cached is not None
                 and cached['status'] in TTL
                 and 0 <= now - cached['checked_at'] < TTL[cached['status']])
        info=None
        if valid:
            try:info=json.loads(cached['evidence'])
            except (TypeError,ValueError):valid=False
            if not isinstance(info,dict):valid=False
        if not valid:
            probed=inspect_audio_details(group['track'],mappings,roots)
            info={k:v for k,v in probed.items() if k not in ('path','open_candidate')}
        status = cached['status'] if valid else probed['status']
        if not valid:
            # Persistent cache keys are path digests. Do not store names/paths.
            cached_evidence={k:v for k,v in info.items() if k!='filename'}
            writes.append((key, status, now,json.dumps(cached_evidence,separators=(',',':'))))
        for identity in group['ids']:
            statuses[identity] = status
            hits[identity] = bool(valid)
            evidence[identity] = dict(info)

    if writes:
        with store.connection() as db:
            db.executemany(
                'INSERT OR REPLACE INTO file_status_cache (key,status,checked_at,evidence) VALUES (?,?,?,?)',
                writes)
            count = db.execute('SELECT COUNT(*) FROM file_status_cache').fetchone()[0]
            if count > MAX_ENTRIES:
                db.execute('DELETE FROM file_status_cache WHERE key IN '
                           '(SELECT key FROM file_status_cache ORDER BY checked_at ASC LIMIT ?)',
                           (count - MAX_ENTRIES,))
    return (statuses,hits,evidence) if details else (statuses,hits)
