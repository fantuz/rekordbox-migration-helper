"""Journey orchestration over existing captures, inventories and sidecar reports."""
from copy import deepcopy
import json
import re
from threading import RLock

from flask import jsonify, request

from analysis_audit import audit_assets
from journeys import STEPS, context, integrity, new_plan, update_plan
from library_checks import compare_snapshots
from research_capture import capture_workspace
from workbench_store import Store, now


def register(owner):
    app = owner.app
    mutation_lock = RLock()
    def store():
        return Store(owner.DATA / 'workbench-sidecar.sqlite3')
    def plans():
        return store().setting('journey_plans', {})
    def save(plan):
        with mutation_lock:
            values = plans()
            values[plan['id']] = plan
            store().set_setting('journey_plans', values)
        return plan
    def plan(identity):
        result = plans().get(identity)
        if result is None:
            raise ValueError('Journey not found')
        return result
    def resolve(source):
        if source == 'workspace':
            session = owner.current()
            result = capture_workspace(session['catalog'], 'session:' + session['id'])
            result.update(label=session['name'], captured=None)
            return result
        if isinstance(source, str) and source.startswith('snapshot:'):
            return store().snapshot(source[9:])
        if isinstance(source, str) and source.startswith('capture:') and re.fullmatch('[a-f0-9]{32}', source[8:]):
            folder = owner.DATA / 'analyzers' / source[8:]
            path = folder / 'comparison.json'
            if not path.is_file():
                path = folder / 'metadata.json'
            report_path = folder / 'report.json'
            if path.is_file() and report_path.is_file():
                result = json.loads(path.read_text(encoding='utf-8'))
                report = json.loads(report_path.read_text(encoding='utf-8'))
                result.update(scope_key=source, source_capture=source[8:], captured=report.get('created'),
                              label=report.get('format', 'Saved source capture'))
                return result
        raise ValueError('Choose a loaded workspace or saved collection snapshot')
    def describe(source):
        if source == 'workspace':
            # The global header must not rebuild every cue/track row per refresh.
            session = owner.current()
            snapshot = {'tracks': session['catalog'].tracks, 'scope_key': 'session:' + session['id'],
                        'label': session['name'], 'scope': 'all', 'source_kind': 'Loaded XML + ZIP',
                        'capabilities': {'cue_positions': True}}
        else:
            snapshot = resolve(source)
        edits = store().overrides(snapshot['scope_key'])
        return context(snapshot, source=source, overrides=sum(len(v) for v in edits.values()))
    def evidence(snapshot):
        capture = str(snapshot.get('source_capture') or '')
        scope = snapshot.get('scope_key', '')
        if scope.startswith('capture:'):
            capture = scope[8:]
        if re.fullmatch('[a-f0-9]{32}', capture):
            path = owner.DATA / 'analyzers' / capture / 'report.json'
            if path.is_file():
                return json.loads(path.read_text(encoding='utf-8'))
        return None
    def body():
        result = request.get_json(silent=True)
        if not isinstance(result, dict):
            raise ValueError('Supply a JSON object')
        return result

    @app.get('/api/journeys')
    def journey_info():
        sources = [{**row, 'id': 'snapshot:' + row['id']} for row in store().snapshots()]
        captures = []
        for path in (owner.DATA / 'analyzers').glob('*/report.json'):
            if not re.fullmatch('[a-f0-9]{32}', path.parent.name) or not (path.parent / 'metadata.json').is_file():
                continue
            try:
                r = json.loads(path.read_text(encoding='utf-8'))
                captures.append({'id': 'capture:' + path.parent.name, 'label': r.get('format', 'Saved source capture'),
                                 'created': r.get('created'), 'source_kind': 'Source analyzer capture'})
            except (OSError, ValueError):
                continue
        sources.extend(sorted(captures, key=lambda row: str(row.get('created') or ''), reverse=True)[:20])
        if owner.active in owner.sessions:
            session = owner.sessions[owner.active]
            sources.insert(0, {'id': 'workspace', 'label': session['name'], 'source_kind': 'Loaded XML + ZIP', 'created': None})
        selected = store().setting('collection_context', '')
        referenced = {selected} if isinstance(selected, str) else set()
        for saved_plan in plans().values():
            referenced.update('snapshot:' + saved_plan[field] for field in ('before_snapshot', 'after_snapshot') if saved_plan.get(field))
            if isinstance(saved_plan.get('source'), str):
                referenced.add(saved_plan['source'])
        present = {row['id'] for row in sources}
        for reference in sorted(referenced - present):
            if not reference.startswith('snapshot:'):
                continue
            try:
                saved = store().snapshot(reference[9:])
                sources.append({'id': reference, 'label': saved.get('label', 'Library snapshot'),
                                'created': saved.get('captured'), 'source_kind': saved.get('source_kind')})
            except ValueError:
                pass
        if selected not in {row['id'] for row in sources}:
            selected = sources[0]['id'] if sources else ''
        return jsonify(sources=sources, selected=selected, context=describe(selected) if selected else None,
                       plans=sorted(plans().values(), key=lambda row: row['updated'], reverse=True),
                       steps=[{'id': key, 'title': title, 'view': view} for key, title, view in STEPS])

    @app.post('/api/journeys/context')
    def select_context():
        source = body().get('source', '')
        result = describe(source)
        store().set_setting('collection_context', source)
        return jsonify(result)

    @app.post('/api/journeys')
    def create_journey():
        b = body()
        source = b.get('source', '')
        if source:
            resolve(source)
        return jsonify(save(new_plan(b.get('kind'), source)))

    @app.post('/api/journeys/<identity>')
    def change_journey(identity):
        with mutation_lock:
            return jsonify(save(update_plan(plan(identity), body(), store().snapshot)))

    @app.post('/api/journeys/<identity>/check')
    def check_journey(identity):
        p = deepcopy(plan(identity))
        b = body()
        source = b.get('source') or p['source']
        snapshot = resolve(source)
        source_report = evidence(snapshot)
        paths = b.get('asset_paths') or []
        if not isinstance(paths, list) or len(paths) > 20 or any(not isinstance(path, str) for path in paths):
            raise ValueError('Choose up to twenty analysis folders or backup ZIPs')
        depth = b.get('depth', 'quick')
        if depth not in ('quick', 'deep'):
            raise ValueError('Choose quick or deep integrity scope')
        if depth == 'quick' and paths:
            raise ValueError('Choose deep scope to inventory selected asset locations')
        scope = snapshot.get('scope_key')
        session = owner.sessions.get(owner.active)
        inventory = deepcopy(session.get('inventory')) if session and scope == 'session:' + session['id'] else None
        def work(progress):
            progress(5, 'Checking captured library evidence')
            assets = audit_assets(snapshot, paths, progress, b.get('verify_assets') is True)[0] if depth == 'deep' and paths else None
            summary, rows = integrity(snapshot, source_report, inventory, assets, depth)
            sources = [snapshot['id']] if snapshot.get('id') else [scope]
            report = store().save_report('integrity journey', sources, summary, rows)
            with mutation_lock:
                latest = plan(identity)
                latest.update(report=report, source=source, updated=now())
                save(latest)
            progress(100, 'Integrity report saved')
            return report
        return jsonify(job=owner.launch(work, 'Checking captured library evidence'))

    @app.post('/api/journeys/<identity>/compare')
    def compare_destination(identity):
        p = deepcopy(plan(identity))
        if not p.get('before_snapshot') or not p.get('after_snapshot') or p['before_snapshot'] == p['after_snapshot']:
            raise ValueError('Choose two different saved source and destination snapshots')
        before, after = store().snapshot(p['before_snapshot']), store().snapshot(p['after_snapshot'])
        def work(progress):
            progress(10, 'Comparing captured source and destination metadata')
            summary, rows = compare_snapshots(before, after)
            report = store().save_report('migration comparison', [before['id'], after['id']], summary, rows)
            with mutation_lock:
                latest = plan(identity)
                if (latest['before_snapshot'], latest['after_snapshot']) == (before['id'], after['id']):
                    latest.update(comparison=report, updated=now())
                    save(latest)
            progress(100, 'Destination comparison saved; review unmatched and changed items')
            return report
        return jsonify(job=owner.launch(work, 'Comparing source and destination snapshots'))
