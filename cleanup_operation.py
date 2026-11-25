"""Publish a reviewed subset as an independent Workbench snapshot in the same sidecar."""
from contextlib import nullcontext
from hashlib import sha256
import json
import re
import sys
import time
from uuid import uuid4

from werkzeug.exceptions import Conflict

from metadata_concurrency import revision
from workbench_store import encoded, insert_snapshot, snapshot_record


MAX_SELECTION = 25
PREVIEW_SECONDS = 30 * 60
PLAN_SCHEMA = '''CREATE TABLE IF NOT EXISTS collection_cleanup_previews(
    token TEXT PRIMARY KEY, parent TEXT NOT NULL, report TEXT NOT NULL, selection TEXT NOT NULL,
    binding TEXT NOT NULL, expires INTEGER NOT NULL, result_id TEXT)'''
ID = re.compile(r'[a-f0-9]{32}')


def _inputs(parent, report, selected):
    if sys.platform not in ('darwin', 'win32'):
        raise ValueError('Cleanup is report-only on this computer. Open the original Windows or macOS Music folder to create a copy.')
    if any(not isinstance(value, str) or not ID.fullmatch(value) for value in (parent, report)):
        raise ValueError('Choose a saved snapshot and its cleanup report')
    if (not isinstance(selected, list) or not 1 <= len(selected) <= MAX_SELECTION
            or any(not isinstance(i, str) or not i or len(i) > 512 for i in selected)
            or len(set(selected)) != len(selected)):
        raise ValueError('Choose between 1 and 25 distinct track references from this report')
    return sorted(selected)


def _source(db, parent):
    record = db.execute('SELECT digest,payload FROM snapshots WHERE id=?', (parent,)).fetchone()
    if not record or sha256(record['payload'].encode()).hexdigest() != record['digest']:
        raise Conflict('The original recovery snapshot is unavailable or failed its integrity check')
    source = json.loads(record['payload'])
    if source.get('id') != parent or not isinstance(source.get('scope_key'), str) or not source['scope_key']:
        raise ValueError('This source has insufficient snapshot identity evidence')
    if source.get('cleanup_lineage') or source['scope_key'].startswith('cleanup:'):
        raise ValueError('Review the original snapshot to prepare a cleanup copy')
    return source, record['digest']


def _report(db, parent, report, digest):
    row = db.execute('SELECT kind,sources,summary FROM reports WHERE id=?', (report,)).fetchone()
    if not row or row['kind'] != 'collection cleanup' or json.loads(row['sources']) != [parent]:
        raise Conflict('Choose a cleanup report made from this exact saved snapshot')
    summary = json.loads(row['summary'])
    if summary.get('source_digest') != digest or summary.get('can_apply') is not True:
        raise Conflict('This report cannot authorize a cleanup copy. Scan the original snapshot on its import computer.')
    return summary


def _rows(db, report, ids):
    if not ids:
        return {}
    marks = ','.join('?' for _ in ids)
    result = {}
    for stored_id, raw in db.execute(f'SELECT track_id,payload FROM report_rows WHERE report_id=? AND track_id IN ({marks})',
                                     (report, *ids)):
        row = json.loads(raw)
        if row.get('id') != stored_id or stored_id in result:
            raise Conflict('Track identity is ambiguous in the saved cleanup report')
        result[stored_id] = row
    if set(result) != set(ids):
        raise Conflict('A selected track or its keeper is absent from the saved report')
    return result


def _evidence(rows, selected):
    proof = {}
    for identity, row in rows.items():
        if not row.get('evidence') or not row.get('location_evidence') or not row.get('path'):
            raise Conflict('A selected path or its evidence is unavailable')
        if identity in selected:
            if row.get('protected') is not False or row.get('reasons'):
                raise Conflict('A selected reference has a protection reason')
            candidate = row.get('candidate')
            if candidate == 'duplicate':
                keeper = row.get('keeper_id')
                kept = rows.get(keeper, {})
                if (row.get('status') != 'present' or keeper in selected or kept.get('status') != 'present' or kept.get('candidate')
                        or not kept.get('path') or row.get('keeper_path') != kept['path']
                        or row.get('proof') not in ('same_file', 'sha256')):
                    raise Conflict('A verified duplicate keeper must remain in the copy')
            elif candidate != 'missing' or row.get('status') != 'missing' or row.get('proof') != 'absent':
                raise Conflict('The selection contains a protected or ineligible reference')
        proof[identity] = [row.get(key) for key in ('evidence','location_evidence','path','status','candidate','proof','keeper_id','keeper_path')]
    return proof


def _check_references(source, selected):
    tracks = source['tracks']
    identities = {row.get('id') for row in tracks}
    if len(identities) != len(tracks) or not selected <= identities or len(selected) == len(tracks):
        raise ValueError('Choose unique track references and leave at least one track in the copy')
    for playlist in source.get('playlists', []):
        if selected.intersection(playlist.get('tracks', [])):
            raise Conflict('A selected reference belongs to a retained playlist')
    for history in source.get('histories', []):
        if any(item.get('track_id') in selected for item in history.get('entries', [])):
            raise Conflict('A selected reference belongs to a retained play history')


def _preview_record(db, token, parent, report, selected):
    if not isinstance(token, str) or not ID.fullmatch(token):
        raise ValueError('Preview the exact selection before confirming it')
    plan = db.execute('SELECT * FROM collection_cleanup_previews WHERE token=?', (token,)).fetchone()
    if not plan or (plan['parent'], plan['report'], plan['selection']) != (parent, report, encoded(selected)):
        raise Conflict('The confirmation does not belong to this selection and source')
    if not plan['result_id'] and time.time() >= plan['expires']:
        raise Conflict('The cleanup preview expired. Preview your selection again.')
    return plan


def _result(db, result_id, parent):
    row = db.execute('''SELECT id,label,digest,created,json_array_length(payload,'$.tracks') AS tracks
                        FROM snapshots WHERE id=?''', (result_id,)).fetchone()
    if not row:
        raise Conflict('This cleanup copy has already been archived. Find it in Saved investigations.')
    return {'snapshot': dict(row), 'snapshot_id': result_id, 'parent_snapshot_id': parent,
            'remaining_count': row['tracks'], 'source_writes': False}


def preview_cleanup(store, snapshot_id, report_id, selected_ids, recheck, *, publication_lock=None, checkpoint=None):
    selected = _inputs(snapshot_id, report_id, selected_ids)
    return _run(store, snapshot_id, report_id, selected, recheck, None, publication_lock, checkpoint)


def apply_cleanup(store, snapshot_id, report_id, selected_ids, token, confirmation, original_computer,
                  local_only, recheck, *, publication_lock=None, checkpoint=None):
    selected = _inputs(snapshot_id, report_id, selected_ids)
    if original_computer is not True or local_only is not True or confirmation != f'COPY {len(selected)}':
        raise ValueError('Confirm the original import computer, the always-local Music folder, and the exact COPY count')
    if not isinstance(token, str) or not ID.fullmatch(token):
        raise ValueError('Preview the exact selection before confirming it')
    return _run(store, snapshot_id, report_id, selected, recheck, token, publication_lock, checkpoint)


def _run(store, parent, report, selected, recheck, token, publication_lock, checkpoint):
    chosen = set(selected)
    with store.connection() as db:
        db.execute(PLAN_SCHEMA)
        # Read one coherent sidecar state. Media reads and serialization hold no writer lock.
        db.execute('BEGIN')
        data_version = db.execute('PRAGMA data_version').fetchone()[0]
        if token:
            plan = _preview_record(db, token, parent, report, selected)
            if plan['result_id']:
                return _result(db, plan['result_id'], parent)
        source, digest = _source(db, parent)
        summary = _report(db, parent, report, digest)
        rows = _rows(db, report, selected)
        keepers = {row['keeper_id'] for row in rows.values() if row.get('keeper_id')} - chosen
        rows.update(_rows(db, report, sorted(keepers)))
        proof = _evidence(rows, chosen)
        _check_references(source, chosen)
        scope = source['scope_key']
        edits = store.overrides(scope, db=db)
        if chosen.intersection(edits):
            raise Conflict('A selected track has staged metadata edits')
        stamp = revision(db, scope)
        compare = summary.get('compare_bytes') is True
        before = len(source['tracks'])
        if token:
            result_id = uuid4().hex
            # The immutable tracks can be shared while encoding an unedited source.
            # Only working metadata edits need a separate deep copy of the collection.
            effective = store.effective(source, edits) if edits else dict(source, metadata_overrides_applied=0)
            effective.pop('source_capture', None)
            effective.update(tracks=[track for track in effective['tracks'] if track['id'] not in chosen],
                             source_kind='Workbench cleanup copy',scope_key='cleanup:' + result_id,
                             cleanup_lineage={'parent_snapshot_id': parent, 'parent_digest': digest,
                                              'report_id': report, 'removed_ids': selected, 'edit_revision': stamp})
            record = snapshot_record(effective, 'Cleanup copy · ' + source['label'], result_id)
        inspected = set(rows)
        fresh = recheck(source, compare, inspected, db=db)
        observed = {row['id']: row for row in fresh['rows'] if row['id'] in inspected}
        if (fresh.get('can_apply') is not True or len(observed) != len(inspected)
                or not fresh.get('context_stamp') or _evidence(observed, chosen) != proof):
            raise Conflict('A file, keeper or protection changed. Scan the snapshot again.')
        binding = sha256(encoded([digest, report, selected, stamp, compare, sorted(proof.items()),
                                  fresh['context_stamp']]).encode()).hexdigest()
        db.commit()
        # Pause/cancel before taking the application lock; publication is one short atomic step.
        if checkpoint:
            checkpoint()
        with publication_lock if publication_lock is not None else nullcontext():
            db.execute('BEGIN IMMEDIATE')
            if token:
                plan = _preview_record(db, token, parent, report, selected)
                if plan['result_id']:
                    return _result(db, plan['result_id'], parent)
                if binding != plan['binding']:
                    raise Conflict('The preview is stale. Review the files and staged edits again.')
            if db.execute('PRAGMA data_version').fetchone()[0] != data_version:
                raise Conflict('Workspace evidence changed during this operation. Preview the selection again.')
            paths = {i: row['path'] for i, row in rows.items()}
            current = recheck(source, compare, inspected, db=db, context_only=True, locations=paths)
            if current.get('context_stamp') != fresh['context_stamp']:
                raise Conflict('Cloud evidence or workspace decisions changed during review')
            if current.get('locations') != {i: row['location_evidence'] for i, row in rows.items()}:
                raise Conflict('A file or its local folder changed during review')
            if token:
                insert_snapshot(db, record)
                db.execute('UPDATE collection_cleanup_previews SET result_id=? WHERE token=?', (result_id, token))
                answer = _result(db, result_id, parent)
            else:
                now = time.time()
                db.execute('DELETE FROM collection_cleanup_previews WHERE result_id IS NULL AND expires<=?', (now,))
                token = uuid4().hex
                expires = int(now) + PREVIEW_SECONDS
                db.execute('INSERT INTO collection_cleanup_previews VALUES (?,?,?,?,?,?,NULL)',
                           (token,parent,report,encoded(selected),binding,expires))
                keys = ('id','title','path','candidate','proof','keeper_id','keeper_path')
                answer = {'token': token, 'selected': [{k:rows[i].get(k) for k in keys} for i in selected],
                          'selected_count': len(selected), 'before_count': before, 'after_count': before-len(selected),
                          'confirmation': f'COPY {len(selected)}', 'expires_at': expires,
                          'parent_snapshot_id': parent, 'source_writes': False}
            db.commit()
            return answer
