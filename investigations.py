"""Reversible cleanup of app-owned investigations; never delete source libraries."""
from contextlib import ExitStack
from hashlib import sha256
import json
import re
from threading import RLock
from uuid import uuid4

from flask import jsonify, request
from workbench_store import Store, encoded, now

ID = re.compile(r'^[a-f0-9]{32}$')
TABLES = {'snapshots': ('snapshots', 'id'), 'reports': ('reports', 'id'), 'batches': ('mb_batches', 'id')}
RELATED = {'reports': [('report_rows', 'report_id')], 'batches': [('mb_results', 'batch_id')]}


def register(owner):
    app = owner.app
    gate = RLock()
    def store():
        result = Store(owner.DATA / 'workbench-sidecar.sqlite3')
        with result.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS investigation_archives(id TEXT PRIMARY KEY,created TEXT,payload TEXT)')
        return result
    def idle():
        if any(t.get('status') in ('running', 'paused', 'queued') for t in owner.tasks.values()):
            raise ValueError('Wait for background work to finish before managing investigations')
        if getattr(owner, 'lab_jobs_active', lambda: False)():
            raise ValueError('Wait for MusicBrainz lookups to finish or stop them first')
    def inventory():
        result = []
        saved = store()
        with saved.connection() as db:
            for kind, (table, _) in TABLES.items():
                for r in db.execute('SELECT * FROM ' + table):
                    row = dict(r)
                    identity = row['id']
                    refs = []
                    if kind == 'reports':
                        refs = [str(s) for s in json.loads(row['sources'])]
                    if kind == 'batches':
                        refs = ['snapshot:' + row['snapshot_id']]
                    result.append({'key': kind + ':' + identity, 'kind': kind, 'id': identity,
                                   'label': row.get('label') or row.get('kind') or 'MusicBrainz batch',
                                   'created': row['created'], 'bytes': len(encoded(row).encode()),
                                   'stamp': sha256(encoded(row).encode()).hexdigest(), 'refs': refs,
                                   'blocked': 'Lookup is active' if row.get('status') in ('queued', 'running') else ''})
        for identity, p in saved.setting('journey_plans', {}).items():
            result.append({'key': 'journeys:' + identity, 'kind': 'journeys', 'id': identity,
                           'label': p['kind'] + ' journey', 'created': p.get('updated'), 'bytes': len(encoded(p).encode()),
                           'stamp': sha256(encoded(p).encode()).hexdigest(),
                           'refs': [p.get('source', '')] + ['snapshot:' + p[f] for f in ('before_snapshot', 'after_snapshot') if p.get(f)] +
                                   ['reports:' + p[f]['id'] for f in ('report', 'comparison') if p.get(f)], 'blocked': ''})
        for kind, paths in [('captures', (owner.DATA / 'analyzers').glob('*/report.json')),
                            ('workspaces', owner.DATA.glob('*/state.json'))]:
            for path in paths:
                identity = path.parent.name
                if not ID.fullmatch(identity) or path.is_symlink() or path.parent.is_symlink():
                    continue
                try:
                    raw = path.read_bytes()
                    row = json.loads(raw)
                    result.append({'key': kind + ':' + identity, 'kind': kind, 'id': identity,
                                   'label': row.get('name') or row.get('format') or kind,
                                   'created': row.get('created'), 'bytes': len(raw),
                                   'stamp': sha256(raw).hexdigest(), 'refs': [],
                                   'blocked': 'Unload or switch this workspace first' if kind == 'workspaces' and identity == owner.active else ''})
                except (OSError, ValueError):
                    continue
        return sorted(result, key=lambda r: (str(r.get('created') or ''), r['key']), reverse=True)
    def plan(keys):
        if not isinstance(keys, list) or not keys or len(keys) > 10000 or any(not isinstance(k, str) for k in keys):
            raise ValueError('Select saved investigations to archive')
        selected = set(keys)
        items = inventory()
        if selected - {r['key'] for r in items}:
            raise ValueError('Selection changed; refresh the saved investigations')
        chosen = [r for r in items if r['key'] in selected]
        references = set()
        for r in chosen:
            references.add(r['key'])
            if r['kind'] == 'snapshots':
                references.update(('snapshot:' + r['id'], r['id']))
            elif r['kind'] == 'captures':
                references.add('capture:' + r['id'])
            elif r['kind'] == 'workspaces':
                references.add('session:' + r['id'])
        blockers = [{'key': r['key'], 'reason': r['blocked']} for r in chosen if r['blocked']]
        blockers += [{'key': r['key'], 'reason': 'This retained item references a selected investigation; select it too or keep its source'}
                     for r in items if r['key'] not in selected and references.intersection(r['refs'])]
        # Native snapshots are self-contained and do not depend on their analyzer folder.
        fingerprint = sha256(encoded({'items': chosen, 'blockers': blockers}).encode()).hexdigest()
        return chosen, blockers, fingerprint
    def body():
        b = request.get_json(silent=True)
        if not isinstance(b, dict):
            raise ValueError('Supply a JSON object')
        return b
    def file_location(kind, identity):
        if not ID.fullmatch(identity) or kind not in ('captures', 'workspaces'):
            raise ValueError('Invalid archived investigation')
        return owner.DATA / 'analyzers' / identity if kind == 'captures' else owner.DATA / identity / 'state.json'

    @app.get('/api/investigations')
    def info():
        with gate:
            items = inventory()
            with store().connection() as db:
                archives = [{'id': r['id'], 'created': r['created'], 'items': len(json.loads(r['payload'])['items'])}
                            for r in db.execute('SELECT * FROM investigation_archives ORDER BY created DESC')]
            return jsonify(items=[{k: v for k, v in r.items() if k not in ('stamp', 'refs')} for r in items], archives=archives)

    @app.post('/api/investigations/preview')
    def preview():
        with gate:
            idle()
            chosen, blockers, token = plan(body().get('keys'))
            return jsonify(items=[{k: r[k] for k in ('key', 'label', 'kind')} for r in chosen], blockers=blockers, token=token,
                           note='Move selected saved work out of active menus. Restore is available here. Original libraries, music, uploaded inputs and export files are preserved. Archiving does not reclaim disk space.')

    @app.post('/api/investigations/archive')
    def archive():
        with gate, owner.lock:
            idle()
            b = body()
            chosen, blockers, token = plan(b.get('keys'))
            if blockers or b.get('token') != token:
                raise ValueError('Preview changed or has dependent items; review the selection again')
            identity = uuid4().hex
            folder = owner.DATA / 'archived-investigations' / identity
            folder.mkdir(parents=True)
            payload = {'items': chosen, 'tables': {}, 'plans': {}, 'files': [], 'settings': {}}
            saved = store()
            with ExitStack() as rollback:
                for r in chosen:
                    if r['kind'] in ('captures', 'workspaces'):
                        src = file_location(r['kind'], r['id'])
                        dst = folder / r['kind'] / r['id']
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        src.rename(dst)
                        rollback.callback(dst.rename, src)
                        payload['files'].append([r['kind'], r['id']])
                with saved.connection() as db:
                    plans = saved.setting('journey_plans', {})
                    for r in chosen:
                        kind, item = r['kind'], r['id']
                        if kind in TABLES:
                            for table, field in [TABLES[kind], *RELATED.get(kind, [])]:
                                rows = [dict(v) for v in db.execute('SELECT * FROM ' + table + ' WHERE ' + field + '=?', (item,))]
                                payload['tables'].setdefault(table, []).extend(rows)
                                db.execute('DELETE FROM ' + table + ' WHERE ' + field + '=?', (item,))
                        if kind == 'journeys':
                            payload['plans'][item] = plans.pop(item)
                        if kind in ('captures', 'snapshots'):
                            name = 'duplicate_reviews:' + ('capture:' if kind == 'captures' else 'snapshot:') + item
                            old = db.execute('SELECT value FROM settings WHERE name=?', (name,)).fetchone()
                            if old:
                                payload['settings'][name] = old[0]
                                db.execute('DELETE FROM settings WHERE name=?', (name,))
                    db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('journey_plans', encoded(plans)))
                    context = saved.setting('collection_context', '')
                    if any(context == ('capture:' if r['kind'] == 'captures' else 'snapshot:') + r['id'] for r in chosen if r['kind'] in ('captures', 'snapshots')):
                        db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('collection_context', encoded('')))
                    db.execute('INSERT INTO investigation_archives VALUES (?,?,?)', (identity, now(), encoded(payload)))
                rollback.pop_all()
            for r in chosen:
                if r['kind'] == 'workspaces':
                    owner.sessions.pop(r['id'], None)
            return jsonify(archived=len(chosen), id=identity, source_writes=False)

    @app.post('/api/investigations/<identity>/restore')
    def restore(identity):
        if not ID.fullmatch(identity):
            raise ValueError('Choose a saved cleanup')
        with gate, owner.lock:
            idle()
            saved = store()
            with saved.connection() as db, ExitStack() as rollback:
                row = db.execute('SELECT payload FROM investigation_archives WHERE id=?', (identity,)).fetchone()
                if not row:
                    raise ValueError('Cleanup not found')
                payload = json.loads(row[0])
                plans = saved.setting('journey_plans', {})
                if set(plans).intersection(payload['plans']):
                    raise ValueError('A journey with this identity already exists')
                for kind, item in payload['files']:
                    dst = file_location(kind, item)
                    src = owner.DATA / 'archived-investigations' / identity / kind / item
                    if dst.exists() or src.is_symlink() or dst.parent.is_symlink():
                        raise ValueError('An investigation already exists at the restore destination')
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    src.rename(dst)
                    rollback.callback(dst.rename, src)
                for table, rows in payload['tables'].items():
                    allowed = {t for t, _ in TABLES.values()} | {t for entries in RELATED.values() for t, _ in entries}
                    if table not in allowed:
                        raise ValueError('Invalid archived table')
                    for r in rows:
                        columns = [v[1] for v in db.execute('PRAGMA table_info(' + table + ')')]
                        if set(r) != set(columns):
                            raise ValueError('Archived schema differs; restore with the matching application version')
                        primary = [v[1] for v in db.execute('PRAGMA table_info(' + table + ')') if v[5]]
                        if primary and db.execute('SELECT 1 FROM ' + table + ' WHERE ' + ' AND '.join(c + '=?' for c in primary), [r[c] for c in primary]).fetchone():
                            raise ValueError('An investigation with this identity already exists; nothing was restored')
                        db.execute('INSERT INTO ' + table + ' (' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')', [r[c] for c in columns])
                for name, value in payload['settings'].items():
                    db.execute('INSERT INTO settings VALUES (?,?)', (name, value))
                plans.update(payload['plans'])
                db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('journey_plans', encoded(plans)))
                db.execute('DELETE FROM investigation_archives WHERE id=?', (identity,))
                # Commit before removing rollback callbacks, including file moves.
                db.commit()
                rollback.pop_all()
            return jsonify(restored=len(payload['items']), source_writes=False)
