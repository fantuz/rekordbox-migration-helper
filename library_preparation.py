"""Explicit preparation of retained metadata; audio scans remain a separate action."""
from contextlib import closing
import re
from threading import RLock

from flask import jsonify, request

from collection_sources import resolve
from research_capture import capture_private_database, capture_workspace, open_capture
from workbench_store import Store, now


def latest_snapshot(saved, scope):
    # Do not use Store.snapshots()'s most-recent-100 display limit for reuse.
    with saved.connection() as db:
        row = db.execute('SELECT id,label,created FROM snapshots WHERE scope_key=? ORDER BY created DESC,id DESC LIMIT 1',
                         (scope,)).fetchone()
    return dict(row) if row else None


def register(owner):
    app = owner.app
    guard = RLock()

    def store():
        return Store(owner.DATA / 'workbench-sidecar.sqlite3')

    def selection(values):
        source = values.get('source', '')
        if source == 'workspace':
            session = owner.current()
            if values.get('workspace') != session['id']:
                raise ValueError('This workspace is no longer loaded')
            return source, 'session:' + session['id'], session.get('name', 'Loaded XML + ZIP'), session
        if not isinstance(source, str) or not re.fullmatch(r'(?:capture|snapshot):[0-9a-f]{32}', source):
            raise ValueError('Choose a loaded workspace or saved collection snapshot')
        payload = resolve(owner, source)
        return source, payload['scope_key'], payload.get('label', 'Library snapshot'), payload

    @app.get('/api/library-preparation')
    def library_preparation_status():
        source, scope, label, _ = selection(request.args)
        saved = store()
        prepared = ({'id': source[9:], 'label': label} if source.startswith('snapshot:')
                    else latest_snapshot(saved, scope))
        scan_source = 'snapshot:' + prepared['id'] if prepared else source
        with saved.connection() as db:
            row = db.execute('SELECT total,done,checked_at,state FROM file_health_scans WHERE source=?',
                             (scan_source,)).fetchone()
        return jsonify(source=source, scope=scope, label=label, snapshot=prepared,
                       file_health=dict(row) if row else {'state': 'not_started', 'done': 0},
                       scan_source=scan_source, extra_rekordbox_exports=0)

    @app.post('/api/library-preparation')
    def prepare_library_metadata():
        values = request.get_json(silent=True)
        if not isinstance(values, dict):
            raise ValueError('Provide a JSON object')
        source, scope, label, frozen = selection(values)
        saved = store()
        data = str(owner.DATA.resolve())
        # Freeze the workspace object, not the mutable global active selection.
        # A delayed worker must never capture another tab's newly loaded library.
        def work(progress):
            with guard:
                if str(owner.DATA.resolve()) != data:
                    raise ValueError('The workspace storage changed')
                prepared = ({'id': source[9:], 'label': label} if source.startswith('snapshot:')
                            else latest_snapshot(saved, scope))
                if prepared:
                    return {**prepared, 'source': source, 'scope': scope, 'reused': True}
                progress(10, 'Preparing metadata from the loaded library')
                if source == 'workspace':
                    private = owner.TEMPORARY.path / frozen['id'] / 'master.db'
                    if private.is_file():
                        with closing(open_capture(private.resolve())) as db:
                            payload = capture_private_database(db, scope)
                    else:
                        payload = capture_workspace(frozen['catalog'], scope)
                    payload.update(source_kind='Loaded XML + ZIP', source_capture='session')
                else:
                    payload = frozen
                    payload.update(source_captured=payload.get('captured'),
                                   source_kind='Saved source-folder capture', source_capture=source[8:])
                payload.update(scope_key=scope, captured=now())
                progress(95, 'Saving local metadata for batch review')
                return {**saved.save_snapshot(payload, label), 'source': source, 'scope': scope, 'reused': False}
        with guard:
            for job in getattr(owner, 'tasks', {}).values():
                if (job.get('status') == 'running' and job.get('preparation_scope') == (data, scope)):
                    return jsonify(job=job['id'])
            job = owner.launch(work, 'Capturing an immutable Library lab snapshot')
            if job in getattr(owner, 'tasks', {}):
                owner.tasks[job]['preparation_scope'] = (data, scope)
        return jsonify(job=job)
