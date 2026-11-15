"""Bounded, persistent *advisory* evidence about local audio paths.

No source or media is modified. Entries contain path digests, not raw paths.
Statuses are intentionally not proof of decodable media or duplicate content.
"""
from hashlib import sha256
import json
import sys
import time

from workbench_store import Store
from track_playback import inspect_audio

SCHEMA = 'file-status-v1'
MAX_ENTRIES = 20000
TTL = {
    'playable': 3600,
    'missing': 90,
    'inaccessible': 90,
    'unverified': 300,
}
PATH_FIELDS = ('current_path', 'xml_location', 'original_path')


def fingerprint(track):
    # Both the current and alternate recorded paths affect the result.
    # Include the host OS: a Windows path is not a POSIX local file.
    paths = [str(track.get(field)) if track.get(field) is not None else None
             for field in PATH_FIELDS]
    payload = json.dumps([SCHEMA, sys.platform, paths], ensure_ascii=False,
                         separators=(',', ':'))
    return sha256(payload.encode('utf-8')).hexdigest()


def inspect(owner, tracks, refresh=False):
    """Return (status, cache-hit) maps for server-resolved track IDs.

    A separate explicit refresh bypasses the cache, e.g. after reconnecting
    a removable disk. A playback launch never trusts these entries.
    """
    statuses, hits, groups = {}, {}, {}
    for identity, track in tracks.items():
        if not isinstance(track, dict):
            statuses[identity] = 'unverified'
            hits[identity] = False
            continue
        groups.setdefault(fingerprint(track), {'track': track, 'ids': []})['ids'].append(identity)

    if not groups:
        return statuses, hits

    store = Store(owner.DATA / 'workbench-sidecar.sqlite3')
    now = time.time()
    keys = list(groups)
    placeholders = ','.join('?' for _ in keys)
    with store.connection() as db:
        old = {row['key']: row for row in db.execute(
            f'SELECT key,status,checked_at FROM file_status_cache WHERE key IN ({placeholders})', keys)}

    writes = []
    for key, group in groups.items():
        cached = old.get(key)
        valid = (not refresh and cached is not None
                 and cached['status'] in TTL
                 and 0 <= now - cached['checked_at'] < TTL[cached['status']])
        status = cached['status'] if valid else inspect_audio(group['track'])[0]
        if not valid:
            writes.append((key, status, now))
        for identity in group['ids']:
            statuses[identity] = status
            hits[identity] = bool(valid)

    if writes:
        with store.connection() as db:
            db.executemany(
                'INSERT OR REPLACE INTO file_status_cache (key,status,checked_at) VALUES (?,?,?)',
                writes)
            count = db.execute('SELECT COUNT(*) FROM file_status_cache').fetchone()[0]
            if count > MAX_ENTRIES:
                db.execute('DELETE FROM file_status_cache WHERE key IN '
                           '(SELECT key FROM file_status_cache ORDER BY checked_at ASC LIMIT ?)',
                           (count - MAX_ENTRIES,))
    return statuses, hits
