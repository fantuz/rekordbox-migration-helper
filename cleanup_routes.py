"""Review collection references and publish an explicitly confirmed Workbench copy."""
import json
import re
from hashlib import sha256

from flask import abort, jsonify, request

from cleanup_context import build_context, workspace_stamp
from cleanup_operation import apply_cleanup, preview_cleanup
from cleanup_paths import PathInspector
from cleanup_review import build_report
from collection_sources import resolve
from file_health import local_request, selected_source
from workbench_store import Store, encoded


KIND = 'collection cleanup'
MAX_TRACKS = 250_000
ID = re.compile(r'[a-f0-9]{32}')


def _identity(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError('Choose a saved collection cleanup report.')
    return value


def _body():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValueError('Provide a collection cleanup request.')
    return value


def _read_snapshot(store, identity):
    with store.connection() as db:
        record = db.execute('SELECT payload,digest FROM snapshots WHERE id=?', (identity,)).fetchone()
    if not record or sha256(record['payload'].encode()).hexdigest() != record['digest']:
        raise ValueError('This snapshot is unavailable or has changed. Select the source again.')
    return json.loads(record['payload']), record['digest']


def _report_page(store, identity, source_key, args):
    try:
        offset, limit = int(args.get('offset', 0)), int(args.get('limit', 50))
    except ValueError:
        raise ValueError('Choose a valid cleanup report page.') from None
    if not 0 <= offset <= MAX_TRACKS or not 1 <= limit <= 100:
        raise ValueError('Choose a valid cleanup report page.')
    section = args.get('candidate', '')
    if section not in ('', 'eligible', 'protected', 'missing', 'duplicate'):
        raise ValueError('Choose a supported cleanup filter.')
    clauses = ['report_id=?']
    params = [identity]
    if section == 'eligible':
        clauses.append("json_extract(payload,'$.candidate') IS NOT NULL")
    elif section == 'protected':
        clauses.append("json_extract(payload,'$.protected')=1")
    elif section:
        clauses.append("json_extract(payload,'$.candidate')=?")
        params.append(section)
    for field in ('status', 'volume', 'os', 'q'):
        value = args.get(field, '')
        if len(value) > 512:
            raise ValueError('Choose a shorter cleanup filter.')
        if value:
            if field == 'q':
                clauses.append('instr(search_text,?)>0')
                params.append(value.casefold())
            else:
                clauses.append('json_extract(payload,?)=?')
                params.extend(('$.' + field, value))
    with store.connection() as db:
        db.execute('BEGIN')
        record = db.execute('SELECT summary,created FROM reports WHERE id=? AND kind=? AND sources=?',
                            (identity, KIND, encoded([source_key]))).fetchone()
        if not record:
            abort(404, 'Cleanup report not found for this source.')
        where = ' AND '.join(clauses)
        count = db.execute('SELECT count(*) FROM report_rows WHERE ' + where, params).fetchone()[0]
        page = db.execute('SELECT payload FROM report_rows WHERE ' + where + ' ORDER BY ordinal LIMIT ? OFFSET ?',
                          (*params, limit, offset))
        return dict(id=identity, created=record['created'], summary=json.loads(record['summary']),
                    rows=[json.loads(row[0]) for row in page], total=count, offset=offset, limit=limit)


def register(owner):
    app = owner.app

    def store():
        return Store(owner.DATA / 'workbench-sidecar.sqlite3')

    def source_key(source):
        if source == 'workspace':
            return 'session:' + owner.current()['id']
        selected_source(source)
        return source[9:] if source.startswith('snapshot:') else source

    def local():
        if not local_request():
            abort(403, 'Open collection cleanup on the computer running Library Workbench.')

    def launch(work, label):
        return jsonify(job=owner.launch(work, label, local_only=True))

    @app.get('/api/collection-cleanup')
    def collection_cleanup_info():
        local()
        source = request.args.get('source', '')
        inspector = PathInspector.current()
        reports = []
        if source:
            key = source_key(source)
            with store().connection() as db:
                records = db.execute('SELECT id,created,summary FROM reports WHERE kind=? AND sources=? '
                                     'ORDER BY created DESC LIMIT 20', (KIND, encoded([key])))
                reports = [dict(id=r['id'], created=r['created'], summary=json.loads(r['summary'])) for r in records]
        return jsonify(source=source, host=inspector.host, can_apply=inspector.can_apply, reports=reports)

    @app.get('/api/collection-cleanup/<identity>')
    def cleanup_page(identity):
        local()
        source = request.args.get('source')
        page = _report_page(store(), _identity(identity), source_key(source), request.args)
        return jsonify(source=source, **page)

    @app.post('/api/collection-cleanup/scan')
    def cleanup_scan():
        local()
        body = _body()
        source = body.get('source')
        key = source_key(source)
        saved_source = source.startswith('snapshot:')
        compare = body.get('compare_bytes', False)
        if not isinstance(compare, bool) or compare and (body.get('local_only') is not True or not saved_source):
            raise ValueError('Confirm an always-local Music folder and select a saved snapshot to compare audio.')
        if compare and not PathInspector.current().can_apply:
            raise ValueError('Audio comparison requires the original Windows or macOS computer.')
        session = owner.current() if source == 'workspace' else None

        def work(progress):
            saved = store()
            progress(1, 'Reading the selected collection')
            if saved_source:
                snapshot, digest = _read_snapshot(saved, key)
            elif session is not None:
                with owner.lock:
                    if owner.sessions.get(owner.active) is not session:
                        raise ValueError('Workspace changed. Scan the current collection again.')
                    snapshot = resolve(owner, source)
                digest = None
            else:
                snapshot, digest = resolve(owner, source), None
            if len(snapshot['tracks']) > MAX_TRACKS:
                raise ValueError('This collection exceeds the cleanup review limit of 250,000 tracks.')
            context = build_context(owner, saved, snapshot)
            report = build_report(snapshot, compare_bytes=compare, review_only=not saved_source,
                                  progress=progress, **context)
            rows = report.pop('rows')
            for row in rows:
                row['track_id'] = row['id']
                row['section'] = row['candidate'] or ('protected' if row['protected'] else 'retained')
            report.update(source=source, source_digest=digest, source_label=snapshot.get('label', ''),
                          compare_bytes=compare)
            progress(99, 'Saving the collection cleanup report')
            result = saved.save_report(KIND, [key], report, rows)
            return {'id': result['id']}

        return launch(work, 'Reviewing collection references')

    @app.post('/api/collection-cleanup/preview')
    @app.post('/api/collection-cleanup/apply')
    def cleanup_selection():
        local()
        body = _body()
        source = selected_source(body.get('source'))
        if not source.startswith('snapshot:'):
            raise ValueError('Save a snapshot and review it before creating a cleaned copy.')
        if not PathInspector.current().can_apply:
            abort(403, 'Collection cleanup is review-only on this host.')
        report_id = _identity(body.get('report_id'))
        applying = request.path.endswith('/apply')

        def work(progress):
            saved = store()
            cloud_roots = ()

            def recheck(snapshot, compare_bytes, ids, db=None, context_only=False, locations=None):
                nonlocal cloud_roots
                with owner.lock:
                    stamp = workspace_stamp(owner, snapshot) or 'independent-snapshot'
                    if context_only:
                        from cleanup_review import location_evidence
                        inspector = PathInspector.current(extra_cloud_roots=cloud_roots)
                        return {'context_stamp': stamp, 'locations': {
                            identity: location_evidence(inspector.inspect(path))
                            for identity, path in locations.items()}}
                    context = build_context(owner, saved, snapshot, db=db)
                    cloud_roots = context['extra_cloud_roots']
                result = build_report(snapshot, compare_bytes=compare_bytes, scope_ids=ids,
                                      progress=progress, **context)
                result['context_stamp'] = stamp
                return result

            args = (saved, source[9:], report_id, body.get('selected_ids'))
            if applying:
                return apply_cleanup(*args, body.get('token'), body.get('confirmation'),
                                     body.get('original_computer'), body.get('local_only'), recheck,
                                     publication_lock=owner.lock,
                                     checkpoint=lambda: progress(99, 'Verifying the cleaned snapshot'))
            return preview_cleanup(*args, recheck, publication_lock=owner.lock,
                                   checkpoint=lambda: progress(99, 'Saving the selection preview'))

        return launch(work, 'Creating a cleaned Workbench snapshot' if applying else 'Checking selected references')
