"""Reversible cleanup of app-owned investigations; never delete source libraries."""
from contextlib import ExitStack
from hashlib import sha256
import json
import re
import shutil
from result_cache import clear as clear_results,connection as cache_connection
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
    def inventory(allow_active=False):
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
                    if kind == 'snapshots' and str(row.get('scope_key')).startswith('cleanup:'):
                        lineage = json.loads(row['payload']).get('cleanup_lineage', {})
                        refs = ['snapshot:' + lineage.get('parent_snapshot_id',''), 'reports:' + lineage.get('report_id','')]
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
                            ('workspaces', owner.DATA.glob('*/state.json')),
                            ('discovery', (owner.DATA / 'discovery').glob('*.json')),
                            ('storage', (owner.DATA / 'storage').glob('*/summary.json'))]:
            for path in paths:
                identity = path.stem if kind == 'discovery' else path.parent.name
                if not ID.fullmatch(identity) or path.is_symlink() or path.parent.is_symlink() or path.parent.is_junction() or not path.resolve().is_relative_to(owner.DATA.resolve()):
                    continue
                try:
                    raw = path.read_bytes()
                    row = json.loads(raw)
                    result.append({'key': kind + ':' + identity, 'kind': kind, 'id': identity,
                                   'label': row.get('name') or row.get('format') or kind,
                                   'created': row.get('created'), 'bytes': len(raw),
                                   'stamp': sha256(raw).hexdigest(), 'refs': ['capture:'+row['source_report']] if kind=='storage' and row.get('source_report') else [],
                                   'blocked': 'Unload or switch this workspace first' if kind == 'workspaces' and identity == owner.active and not allow_active else ''})
                except (OSError, ValueError):
                    continue
        for folder in (owner.DATA/'analyzers').glob('*'):
            if not ID.fullmatch(folder.name) or not folder.is_dir() or folder.is_symlink() or folder.is_junction() or not folder.resolve().is_relative_to(owner.DATA.resolve()) or (folder/'report.json').exists():continue
            stamps=[(p.name,p.stat().st_size,p.stat().st_mtime_ns) for p in folder.iterdir() if p.is_file() and not p.is_symlink()]
            result.append({'key':'captures:'+folder.name,'kind':'captures','id':folder.name,'label':'Incomplete source analysis',
                           'created':None,'bytes':sum(r[1] for r in stamps),'stamp':sha256(encoded(sorted(stamps)).encode()).hexdigest(),'refs':[],'blocked':''})
        return sorted(result, key=lambda r: (str(r.get('created') or ''), r['key']), reverse=True)
    def plan(keys,fresh=False):
        if not isinstance(keys, list) or (not keys and not fresh) or len(keys) > 10000 or any(not isinstance(k, str) for k in keys):
            raise ValueError('Select saved investigations to archive')
        selected = set(keys)
        items = inventory(allow_active=fresh)
        if fresh:selected={r['key'] for r in items}
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
        with store().connection() as db:
            edits=[dict(r) for table in ('overrides','override_history') for r in db.execute('SELECT * FROM '+table)] if fresh else []
        fingerprint = sha256(encoded({'items': chosen, 'blockers': blockers,'fresh':fresh,'edits':edits,'active':owner.active if fresh else None}).encode()).hexdigest()
        return chosen, blockers, fingerprint
    def body():
        b = request.get_json(silent=True)
        if not isinstance(b, dict):
            raise ValueError('Supply a JSON object')
        return b
    def ordinary_path(path):
        root=owner.DATA.resolve()
        if not path.resolve().is_relative_to(root):raise ValueError('Investigation path is outside the data folder')
        for candidate in (path,*path.parents):
            if candidate==owner.DATA:break
            if candidate.is_symlink() or candidate.is_junction():raise ValueError('Investigation folders must not be linked')

    def file_location(kind, identity):
        if not ID.fullmatch(identity) or kind not in ('captures', 'workspaces','discovery','storage'):
            raise ValueError('Invalid archived investigation')
        if kind=='discovery':return owner.DATA/'discovery'/(identity+'.json')
        if kind=='storage':return owner.DATA/'storage'/identity
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
            b=body();fresh=b.get('fresh') is True
            chosen, blockers, token = plan(b.get('keys',[]),fresh)
            return jsonify(items=[{k: r[k] for k in ('key', 'label', 'kind')} for r in chosen], blockers=blockers, token=token,
                           fresh=fresh,note=('Start fresh: archive all current investigations, clear staged metadata edits and detach loaded workspaces. Appearance settings are kept. ' if fresh else '')+'Move selected saved work out of active menus. Restore is available here. Original libraries, music, uploaded inputs and export files are preserved. Archiving does not reclaim disk space.')

    @app.post('/api/investigations/archive')
    def archive():
        with gate, owner.lock:
            idle()
            b = body()
            fresh=b.get('fresh') is True
            chosen, blockers, token = plan(b.get('keys',[]),fresh)
            if blockers or b.get('token') != token:
                raise ValueError('Preview changed or has dependent items; review the selection again')
            identity = uuid4().hex
            folder = owner.DATA / 'archived-investigations' / identity
            ordinary_path(folder)
            folder.mkdir(parents=True)
            payload = {'items': chosen, 'tables': {}, 'plans': {}, 'files': [], 'settings': {}}
            saved = store()
            with ExitStack() as rollback:
                for r in chosen:
                    if r['kind'] in ('captures', 'workspaces','discovery','storage'):
                        src = file_location(r['kind'], r['id'])
                        ordinary_path(src)
                        dst = folder / r['kind'] / r['id']
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        src.rename(dst)
                        rollback.callback(dst.rename, src)
                        payload['files'].append([r['kind'], r['id']])
                with saved.connection() as db:
                    cleanup_previews = db.execute("SELECT 1 FROM sqlite_schema WHERE name='collection_cleanup_previews'").fetchone()
                    if fresh:
                        for table in ('overrides','override_history'):
                            payload['tables'][table]=[dict(row) for row in db.execute('SELECT * FROM '+table)]
                            db.execute('DELETE FROM '+table)
                    plans = saved.setting('journey_plans', {})
                    for r in chosen:
                        kind, item = r['kind'], r['id']
                        if cleanup_previews and kind in ('reports','snapshots'):
                            db.execute('DELETE FROM collection_cleanup_previews WHERE parent=? OR report=? OR result_id=?', (item,item,item))
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
            if fresh:
                owner.active=None;owner.sessions.clear();saved.set_setting('collection_context','')
            clear_results(owner,providers=fresh)
            return jsonify(archived=len(chosen), id=identity, fresh=fresh,source_writes=False)

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
                    ordinary_path(src);ordinary_path(dst)
                    if dst.exists():
                        raise ValueError('An investigation already exists at the restore destination')
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    src.rename(dst)
                    rollback.callback(dst.rename, src)
                for table, rows in payload['tables'].items():
                    allowed = {'overrides','override_history'} | {t for t, _ in TABLES.values()} | {t for entries in RELATED.values() for t, _ in entries}
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
            clear_results(owner)
            return jsonify(restored=len(payload['items']), source_writes=False)


    def purge_plan(identities):
        if not isinstance(identities,list) or not identities or len(identities)>10000 or any(not isinstance(v,str) or not ID.fullmatch(v) for v in identities):
            raise ValueError('Choose archived investigations to delete')
        records=[]
        with store().connection() as db:
            for identity in sorted(set(identities)):
                row=db.execute('SELECT * FROM investigation_archives WHERE id=?',(identity,)).fetchone()
                if row is None:raise ValueError('Archive selection changed; refresh the preview')
                payload=json.loads(row['payload'])
                records.append({'id':identity,'created':row['created'],'items':len(payload['items']),'digest':sha256(row['payload'].encode()).hexdigest()})
        return records,sha256(encoded(records).encode()).hexdigest()

    @app.post('/api/investigations/purge-preview')
    def purge_preview():
        with gate:
            idle();records,token=purge_plan(body().get('ids'))
            return jsonify(archives=[{k:v for k,v in row.items() if k!='digest'} for row in records],token=token)

    @app.post('/api/investigations/purge')
    def purge():
        with gate,owner.lock:
            idle();b=body();records,token=purge_plan(b.get('ids'))
            if b.get('token')!=token or b.get('confirmed') is not True:raise ValueError('Review and confirm permanent archive deletion')
            base=owner.DATA/'archived-investigations'
            ordinary_path(base)
            if base.is_symlink() or base.is_junction():raise ValueError('The archive folder must not be linked')
            for row in records:
                folder=base/row['id']
                if folder.is_symlink() or folder.is_junction():raise ValueError('An archive folder must not be linked')
            for row in records:
                folder=base/row['id']
                # Only this app-owned archive is removed; no source paths from its payload are followed.
                if folder.exists():shutil.rmtree(folder)
                with store().connection() as db:db.execute('DELETE FROM investigation_archives WHERE id=?',(row['id'],))
            clear_results(owner)
            return jsonify(deleted=len(records),source_writes=False)

    @app.get('/api/investigations/cache')
    def cache_info():
        with cache_connection(owner) as db:
            results=db.execute('SELECT count(*),coalesce(sum(length(CAST(payload AS BLOB))),0) FROM result_cache').fetchone()
            provider=db.execute('SELECT count(*) FROM mb_cache').fetchone()[0]
        return jsonify(results=results[0],bytes=results[1],provider_entries=provider)

    @app.post('/api/investigations/cache/clear')
    def cache_clear():
        with gate,owner.lock:
            idle();clear_results(owner,providers=True)
            return jsonify(cleared=True,source_writes=False)
