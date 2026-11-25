"""Local Library lab endpoints; all mutable state lives in a separate sidecar."""
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from contextlib import closing
from copy import deepcopy
import json
import os
from threading import Event,RLock

from flask import abort,jsonify,request
from file_health import local_request
from engine import open_master
from workbench_store import Store,encoded,now
from research_capture import capture_private_database,capture_workspace,open_capture
from library_checks import compare_snapshots,metadata_consistency,collection_coverage
from analysis_audit import audit_assets
from backup_manifest import backup_manifest
from migration_readiness import export_readiness,tempo_key_review
from source_insights import source_insights
from stems_report import stems_report
from stems_eligibility import context as stems_context
from stems_formats import REPORT_FILTERS
from result_order import ordered,page_result,scan_statuses,with_status,TRACK_FIELDS
from history_browser import list_history,history_session
from metadata_overrides import FIELDS,FREE_FIELDS,comparable,baseline,validate
from track_tags import editable_colour,snapshot_colour_support
from musicbrainz_pilot import MusicBrainzClient,RateGate,SPEEDS,create_batch,batch_record,run_batch,target_options


def workspace_overrides(data,session,edits=None):
    """Freeze edits only when they still agree with the original workspace."""
    if edits is None:edits=Store(data/'workbench-sidecar.sqlite3').overrides('session:'+session['id'])
    tracks={t['id']:t for t in __import__('metadata_export').capture_catalog(session['catalog'])['tracks']}
    result={}
    for identity,fields in edits.items():
        if identity not in tracks:raise ValueError('An edited track no longer belongs to this workspace')
        for field,edit in fields.items():
            if comparable(field,baseline(field,tracks[identity]))!=comparable(field,edit['baseline']):
                raise ValueError('Metadata baseline changed for '+identity+' / '+field+'. Capture again and review the edit.')
            result.setdefault(identity,{})[field]=edit['value']
    return result


def register(owner):
    app=owner.app
    edit_unlocked=set();network_pool=ThreadPoolExecutor(max_workers=1)
    # Multiple jobs wait in one serial provider queue; do not exceed the provider's rate limit.
    MAX_MUSICBRAINZ_JOBS=8
    gate=RateGate();cancellations={};network_lock=RLock()
    target_cache=OrderedDict();target_lock=RLock()
    def store():return Store(owner.DATA/'workbench-sidecar.sqlite3')
    def enabled():return os.environ.get('LIBRARY_WORKBENCH_MUSICBRAINZ','1')!='0' and store().setting('musicbrainz_enabled',False) is True
    def cancel_all():
        with network_lock:
            for event in cancellations.values():event.set()
    owner.cancel_lab_jobs=cancel_all
    owner.lab_jobs_active=lambda: bool(cancellations)
    def snapshot(body):return store().snapshot(body.get('snapshot',''))
    def unlocked(s):
        if s['scope_key'] not in edit_unlocked:raise ValueError('Metadata is read-only. Unlock edits for this snapshot first.')
    def body():
        value=request.get_json(silent=True)
        if not isinstance(value,dict):raise ValueError('Provide a JSON object')
        return value

    def recover_batches(saved):
        # The lock also protects the gap between queueing and starting the worker.
        with saved.connection() as db:
            rows=db.execute("SELECT id,summary FROM mb_batches WHERE status IN ('running','queued')").fetchall()
            for row in rows:
                if row['id'] in cancellations:continue
                summary=json.loads(row['summary'])
                summary['message']='Application stopped before completion. Review and resume the remaining lookups.'
                db.execute('UPDATE mb_batches SET status=?,summary=? WHERE id=?',('interrupted',encoded(summary),row['id']))
    def download(payload,name):
        return app.response_class(json.dumps(payload,ensure_ascii=False,indent=2),mimetype='application/json',headers={'Content-Disposition':'attachment; filename="'+name+'"'})

    @app.get('/api/lab')
    def lab_info():
        sources=[]
        for p in (owner.DATA/'analyzers').glob('*/report.json'):
            if not (p.parent/'comparison.json').is_file() and not (p.parent/'snapshot/master.db').is_file():continue
            try:
                r=json.loads(p.read_text(encoding='utf-8'));sources.append({'id':r['id'],'created':r['created'],'label':str(r.get('source','Source capture'))})
            except (OSError,ValueError,KeyError):continue
        current=owner.sessions.get(owner.active)
        saved=store();snapshots=saved.snapshots()
        selected=saved.setting('collection_context','')
        if isinstance(selected,str) and selected.startswith('snapshot:') and not any(s['id']==selected[9:] for s in snapshots):
            with saved.connection() as db:
                row=db.execute('SELECT id,label,created,source_kind,scope_key,digest FROM snapshots WHERE id=?',(selected[9:],)).fetchone()
            if row:snapshots.append(dict(row))
        return jsonify(snapshots=snapshots,reports=saved.reports(exclude_kind=None if local_request() else 'collection cleanup'),sources=sources,
                       workspace=current['id'] if current else None,musicbrainz_enabled=enabled(),
                       musicbrainz_forced_off=os.environ.get('LIBRARY_WORKBENCH_MUSICBRAINZ')=='0',speeds=SPEEDS,fields=[f for f in FIELDS if f not in FREE_FIELDS])

    @app.post('/api/lab/snapshots')
    def lab_capture():
        b=body();source=b.get('source','session');label=b.get('label','Library snapshot')
        if source=='session':
            session=owner.current();scope='session:'+session['id'];private=owner.TEMPORARY.path/session['id']/'master.db'
        elif source=='orphans':
            session=owner.current();inventory=deepcopy(session.get('inventory'))
            if not inventory or 'orphans' not in inventory:raise ValueError('Scan Media inventory again to capture unreferenced file tags')
            def work(progress):
                from orphan_metadata import capture_orphans
                return store().save_snapshot(capture_orphans(inventory,progress),label)
            return jsonify(job=owner.launch(work,'Reading tags from selected local inventory files'))
        else:
            if not isinstance(source,str) or not owner.re_uuid(source):raise ValueError('Choose a saved source capture')
            private=owner.DATA/'analyzers'/source/'snapshot/master.db';scope='capture:'+source
            comparison=owner.DATA/'analyzers'/source/'comparison.json'
            metadata=owner.DATA/'analyzers'/source/'metadata.json'
            if not private.is_file() and not comparison.is_file() and not metadata.is_file():raise ValueError('Capture this source folder with Source analyzer first')
        def work(progress):
            progress(10,'Reading the already detached private database copy')
            if source!='session' and comparison.is_file():s=json.loads(comparison.read_text(encoding='utf-8'))
            elif private.is_file():
                with closing(open_capture(private.resolve())) as db:s=capture_private_database(db,scope)
            elif source!='session':
                from collection_sources import resolve
                s=resolve(owner,scope)
            else:s=capture_workspace(session['catalog'],scope)
            s.update(captured=now(),source_kind='Loaded XML + ZIP' if source=='session' else 'Saved source-folder capture',source_capture=source)
            if source!='session':s['source_captured']=json.loads((owner.DATA/'analyzers'/source/'report.json').read_text(encoding='utf-8')).get('created')
            return store().save_snapshot(s,label)
        return jsonify(job=owner.launch(work,'Capturing an immutable Library lab snapshot'))

    @app.post('/api/lab/compare')
    def lab_compare():
        b=body();left=store().snapshot(b.get('before',''));right=store().snapshot(b.get('after',''))
        def work(progress):
            summary,rows=compare_snapshots(left,right,b.get('tolerance_ms',0))
            return store().save_report('snapshot comparison',[left['id'],right['id']],summary,rows)
        return jsonify(job=owner.launch(work,'Comparing cue positions, stars and playlists'))

    @app.post('/api/lab/check')
    def lab_check():
        b=body();s=snapshot(b);kind=b.get('kind');state=store().edit_state(s['scope_key'])
        working=store().effective(s,state['overrides']) if b.get('working') is True else s
        edit_revision=state['edit_revision']
        if kind=='stems':stems_context(b.get('profile'))
        def work(progress):
            if kind=='consistency':summary,rows=metadata_consistency(working)
            elif kind=='coverage':summary,rows=collection_coverage(working,b.get('min_cues',1),b.get('min_manual',0),b.get('require_analysis',True) is True)
            elif kind=='assets':summary,rows=audit_assets(s,b.get('paths') or b.get('path',''),progress,b.get('verify') is True)
            elif kind=='formats':summary,rows=audit_assets(s,b.get('paths') or b.get('path',''),progress,b.get('verify') is True,inspect=True)
            elif kind=='stems':summary,rows=stems_report(s,b.get('paths') or b.get('path',''),b.get('profile'),progress,b.get('verify') is True)
            elif kind=='source_insights':summary,rows=source_insights(s,progress)
            elif kind=='backup':summary,rows=backup_manifest(s,b.get('path',''),progress,b.get('verify') is True)
            elif kind=='readiness':summary,rows=export_readiness(working,b.get('profile','generic'),b.get('filesystem','not_checked'))
            elif kind=='tempo':summary,rows=tempo_key_review(working)
            else:raise ValueError('Choose a Library lab check')
            summary['working_metadata_applied']=working.get('metadata_overrides_applied',0)
            summary['edit_revision']=edit_revision
            return store().save_report(kind,[s['id']],summary,rows)
        return jsonify(job=owner.launch(work,'Checking '+str(kind)))

    @app.get('/api/lab/reports/<identity>')
    @app.get('/api/lab/reports/<identity>/download')
    def lab_report(identity):
        saved=store()
        if not local_request():
            with saved.connection() as db:
                if db.execute('SELECT 1 FROM reports WHERE id=? AND kind=?',(identity,'collection cleanup')).fetchone():
                    abort(403,'Open this cleanup report on the computer running Library Workbench.')
        result=saved.report(identity,request.args.get('offset',0),request.args.get('section',''),request.args.get('q',''),True,
                              severity=request.args.get('severity',''),validation=request.args.get('validation',''),
                              **{field:request.args.get(field,'') for field in REPORT_FILTERS})
        result=page_result(result,request.args,('section','severity','validation','title','artist','detail','track_id',*REPORT_FILTERS),full=request.path.endswith('/download'))
        if request.path.endswith('/download'):return download(result,'library-lab-report.json')
        return jsonify(result)

    @app.get('/api/lab/tracks')
    def lab_tracks():
        s=store().snapshot(request.args.get('snapshot',''));state=store().edit_state(s['scope_key']);edits=state['overrides'];query=request.args.get('q','').casefold()
        tracks=[t for t in s['tracks'] if not query or query in (' '.join(str(t.get(f) or '') for f in ('id','title','artist','album','genre'))).casefold()]
        statuses=scan_statuses(store(),s)
        effective=[{**t,**{f:v['value'] for f,v in edits.get(t['id'],{}).items()},'file_status':statuses.get(t['id'])} for t in tracks]
        order=ordered(effective,request.args.get('sort',''),request.args.get('direction','asc'),TRACK_FIELDS)
        by_id={t['id']:t for t in tracks};tracks=[by_id[t['id']] for t in order]
        offset=max(0,int(request.args.get('offset',0)))
        return jsonify(sort_scope='collection',edit_revision=state['edit_revision'],rows=[{'edit_revision':state['edit_revision'],'file_status':statuses.get(t['id']),'original':{f:t.get(f) for f in ('id',*FIELDS)},'overrides':edits.get(t['id'],{})} for t in tracks[offset:offset+30]],
                       total=len(tracks),offset=offset,unlocked=s['scope_key'] in edit_unlocked,scope=s['scope_key'],override_fields=sum(len(v) for v in edits.values()))

    @app.get('/api/lab/history')
    def lab_history():
        from collection_sources import history_source
        s=history_source(owner, request.args)
        return jsonify(page_result(list_history(s,request.args.get('q',''),request.args.get('year',''),all_rows=True),
                                   request.args,('name','date','tracks'),page_size=30))

    @app.get('/api/lab/history/<identity>')
    @app.get('/api/lab/history/<identity>/download')
    def lab_history_session(identity):
        from collection_sources import history_source
        s=history_source(owner, request.args);full=request.path.endswith('/download')
        result=page_result(history_session(s,identity,request.args.get('q',''),all_rows=True),
                           request.args,('position',*TRACK_FIELDS),statuses=scan_statuses(store(),s),full=full)
        if full:return download(result,'saved-play-history.json')
        return jsonify(result)

    @app.post('/api/lab/unlock')
    def lab_unlock():
        b=body();s=snapshot(b)
        if b.get('unlocked') is True:edit_unlocked.add(s['scope_key'])
        else:edit_unlocked.discard(s['scope_key'])
        return jsonify(unlocked=s['scope_key'] in edit_unlocked)

    @app.route('/api/lab/overrides',methods=['POST','DELETE'])
    def lab_override():
        b=body();s=snapshot(b);identity=str(b.get('track_id',''));field=b.get('field')
        t=next((t for t in s['tracks'] if t['id']==identity),None)
        if t is None or field not in FIELDS:raise ValueError('Choose a track and editable field in this snapshot')
        if field not in FREE_FIELDS:unlocked(s)
        if request.method=='DELETE':
            state=store().clear_override(s['scope_key'],identity,field,expected_revision=b.get('edit_revision'))
            return jsonify(reset=True,edit_revision=state['edit_revision'],overrides=state['overrides'].get(identity,{}))
        if field=='colour':
            proposed=validate(field,b.get('value'))
            entry=next((p for p in snapshot_colour_support(s)['palette'] if p['value']==proposed),None)
            if not entry or not entry['supported']:raise ValueError(entry['reason'] if entry else 'This colour cannot be represented by the source library')
        state=store().save_override(s['scope_key'],identity,field,b.get('value'),baseline(field,t),expected_revision=b.get('edit_revision'))
        return jsonify(value=state['value'],edit_revision=state['edit_revision'],overrides=state['overrides'].get(identity,{}))

    @app.get('/api/lab/track')
    def lab_track_detail():
        s=store().snapshot(request.args.get('snapshot',''));identity=request.args.get('track_id','')
        t=next((t for t in s['tracks'] if t['id']==identity),None)
        if t is None:raise ValueError('Choose a track in this snapshot')
        fields=('id',*FIELDS,'bpm','duration','tonality','color_name','color_hex','color_status','color_basis','play_count','manual_cues','auto_cues','analysed')
        support=snapshot_colour_support(s);original={f:t.get(f) for f in fields};original['colour']=editable_colour(t)
        state=store().edit_state(s['scope_key'])
        return jsonify(original=original,native_evidence=t.get('native_evidence'),edit_revision=state['edit_revision'],overrides=state['overrides'].get(identity,{}),
                       editable_fields=[f for f in FIELDS if f not in FREE_FIELDS],unlocked=s['scope_key'] in edit_unlocked,
                       scope=s['scope_key'],comment_captured=t.get('comment') is not None,
                       snapshot_label=s.get('label','Library snapshot'),colour_palette=support['palette'],
                       colour_editable=any(p['supported'] for p in support['palette']),
                       colour_edit_reason='' if any(p['supported'] for p in support['palette']) else support['palette'][0]['reason'],
                       export_scope='matching loaded workspace XML/ZIP' if s['scope_key'].startswith('session:') else 'snapshot sidecar only; not linked to a loaded XML/ZIP workspace')

    @app.post('/api/lab/normalize')
    def lab_normalize():
        b=body();s=snapshot(b);unlocked(s)
        if b.get('field')=='colour':
            proposed=validate('colour',b.get('value'))
            entry=next((p for p in snapshot_colour_support(s)['palette'] if p['value']==proposed),None)
            if not entry or not entry['supported']:raise ValueError(entry['reason'] if entry else 'This colour cannot be represented by the source library')
        return jsonify(store().save_bulk(s,b.get('track_ids',[]),b.get('field'),b.get('value'),expected_revision=b.get('edit_revision')))

    @app.post('/api/lab/features')
    def lab_feature():
        requested=body().get('musicbrainz_enabled') is True
        if requested and os.environ.get('LIBRARY_WORKBENCH_MUSICBRAINZ')=='0':raise ValueError('MusicBrainz is disabled by the application environment')
        store().set_setting('musicbrainz_enabled',requested)
        if not requested:
            cancel_all()
        return jsonify(musicbrainz_enabled=enabled())

    @app.get('/api/lab/musicbrainz/targets')
    def lab_pilot_targets():
        snapshot_id=request.args.get('snapshot','')
        # Target lists stay local and contain only bounded, saved tag values.
        saved=store()
        with saved.connection() as db:
            row=db.execute('SELECT digest FROM snapshots WHERE id=?',(snapshot_id,)).fetchone()
        if not row:raise ValueError('Choose a saved Library lab snapshot')
        key=(str(owner.DATA),snapshot_id,row['digest'])
        # Snapshots are immutable. Cache only the small option lists, and share
        # the first build between overlapping requests for the same snapshot.
        with target_lock:
            if key not in target_cache:
                target_cache[key]=target_options(saved.snapshot(snapshot_id))
                if len(target_cache)>8:target_cache.popitem(last=False)
            else:target_cache.move_to_end(key)
            return jsonify(target_cache[key])

    @app.get('/api/lab/musicbrainz/context')
    def lab_pilot_context():
        from enrichment_context import context
        return jsonify(context(owner,store()))

    @app.post('/api/lab/musicbrainz/prepare')
    def lab_pilot_prepare():
        from enrichment_context import prepare,source_details
        from file_health import local_request
        if not local_request():raise ValueError('Preparing library metadata requires the local application')
        source=body().get('source','')
        if not isinstance(source,str):raise ValueError('Choose a current library')
        source_details(owner,source)
        return jsonify(job=owner.launch(lambda progress:prepare(owner,store(),source,progress),
                                        'Preparing the current library for enrichment'))

    @app.post('/api/lab/musicbrainz/preview')
    def lab_pilot_preview():
        b=body();s=store().effective(snapshot(b));speed=b.get('speed','balanced')
        from enrichment_context import require_snapshot,playable_collection
        require_snapshot(owner,s)
        if speed not in SPEEDS:raise ValueError('Choose gentle, balanced or fast lookup pacing')
        include=b.get('include_unavailable',False)
        if not isinstance(include,bool):raise ValueError('Choose whether to include unavailable audio')
        def work(progress):
            require_snapshot(owner,s)
            from musicbrainz_pilot import target_selection
            target=b.get('target','balanced');value=b.get('target_value','')
            selected={**s,'tracks':target_selection(s,target,value)}
            from audio_paths import mappings_for,signature
            mappings=mappings_for(store(),s)
            eligible,excluded=playable_collection(selected,include,progress,mappings)
            eligible['audio_mapping_revision']=signature(mappings)
            progress(95,'Preparing the local batch preview')
            return create_batch(store(),eligible,b.get('top_genres',5),b.get('seed','preview'),
                                SPEEDS[speed],b.get('sample_size'),target,value,
                                playable_only=not include,excluded_unplayable=excluded)
        return jsonify(job=owner.launch(work,'Checking local audio before batch preview'))

    @app.get('/api/lab/musicbrainz/batches')
    def lab_pilot_batches():
        with network_lock:
            saved=store();recover_batches(saved)
            with saved.connection() as db:
                rows=db.execute("SELECT b.id,b.snapshot_id,b.created,b.status,b.summary,s.label FROM mb_batches b LEFT JOIN snapshots s ON s.id=b.snapshot_id ORDER BY CASE WHEN b.status IN ('running','queued') THEN 0 ELSE 1 END,b.created DESC LIMIT 100").fetchall()
            positions={identity:n+1 for n,identity in enumerate(cancellations)}
            batches=[{**dict(r),'summary':json.loads(r['summary']),
                      'queue_position':positions.get(r['id'])} for r in rows]
            batches.sort(key=lambda r:positions.get(r['id'],MAX_MUSICBRAINZ_JOBS+1))
            return jsonify(batches=batches)

    @app.get('/api/lab/musicbrainz/<identity>')
    def lab_pilot_record(identity):
        with network_lock:
            saved=store();recover_batches(saved)
            return jsonify(batch_record(saved,identity,request.args.get('offset',0),request.args.get('sort','sample'),request.args.get('direction','asc')))

    @app.post('/api/lab/musicbrainz/<identity>/start')
    def lab_pilot_start(identity):
        b=body()
        if not enabled():raise ValueError('Enable the experimental MusicBrainz feature first')
        if b.get('query_consent') is not True:raise ValueError('Review and confirm sending selected public tags/identifiers to MusicBrainz')
        with network_lock:
            saved=store();recover_batches(saved);record=batch_record(saved,identity)
            from enrichment_context import require_snapshot
            require_snapshot(owner,saved.snapshot(record['snapshot_id']))
            from audio_paths import mappings_for,signature
            if record['summary'].get('audio_mapping_revision') and record['summary']['audio_mapping_revision']!=signature(mappings_for(saved,saved.snapshot(record['snapshot_id']))):
                raise ValueError('Audio folder mappings changed. Preview a new batch before starting.')
            if 'playable_only' not in record['summary']:
                raise ValueError('Preview a new batch to choose whether unavailable audio is included')
            if record['status']=='complete':raise ValueError('This batch is complete. Preview a new sample to run another batch.')
            if not record['total']:raise ValueError('This sample has no tracks to look up')
            if identity in cancellations or record['status'] in ('running','queued'):raise ValueError('This batch is already running or queued')
            if len(cancellations)>=MAX_MUSICBRAINZ_JOBS:raise ValueError('MusicBrainz queue is full (8 batches). Finish or cancel a batch before adding another.')
            event=Event();cancellations[identity]=event
            with saved.connection() as db:db.execute('UPDATE mb_batches SET status=? WHERE id=?',('queued',identity))
            def finished(task_status):
                # launch() can stop at its own checkpoint before work() runs.
                # In that case work's finally never executes; release the queue
                # reservation here and preserve an explicit resumable status.
                with network_lock:
                    if cancellations.get(identity) is not event:return
                    status='cancelled' if task_status=='cancelled' or event.is_set() else 'interrupted'
                    with saved.connection() as db:
                        db.execute("UPDATE mb_batches SET status=? WHERE id=? AND status IN ('queued','running')",(status,identity))
                    event.set();cancellations.pop(identity,None)
            def work(progress):
                try:
                    client=MusicBrainzClient(saved,gate,enabled,record['summary']['seconds_per_request'],event)
                    return run_batch(saved,identity,client,progress)
                except Exception:
                    with saved.connection() as db:db.execute('UPDATE mb_batches SET status=? WHERE id=?',('interrupted',identity))
                    raise
                finally:
                    event.set()
                    with network_lock:cancellations.pop(identity,None)
            try:job=owner.launch(work,'Looking up selected public metadata with MusicBrainz',pool=network_pool,on_finished=finished)
            except Exception:
                event.set();cancellations.pop(identity,None)
                with saved.connection() as db:db.execute('UPDATE mb_batches SET status=? WHERE id=?',('interrupted',identity))
                raise
        return jsonify(job=job,batch_id=identity,background=True,queue_depth=len(cancellations))

    @app.post('/api/lab/musicbrainz/<identity>/cancel')
    def lab_pilot_cancel(identity):
        with network_lock:
            if identity in cancellations:cancellations[identity].set()
        return jsonify(cancel_requested=True)

    from musicbrainz_review import register as register_review
    from onetagger_bridge import register as register_onetagger
    register_onetagger(owner,unlocked)
    register_review(owner,store,enabled,unlocked,gate,network_pool,cancellations,network_lock,
                    lambda *args:MusicBrainzClient(*args))

    @app.post('/api/lab/offline-export')
    def lab_offline_export():
        from metadata_export import export_metadata
        from uuid import uuid4
        b=body();s=snapshot(b)
        if b.get('working') is True:s=store().effective(s)
        s['data_state']='working' if b.get('working') is True else 'captured'
        identity=uuid4().hex
        return jsonify(job=owner.launch(lambda p:export_metadata(s,owner.DATA/'quick-exports',identity,owner.ROOT/'static',p,title=b.get('title') or s['label'],include_paths=False,temporary_root=owner.TEMPORARY.folder('exports')),'Exporting the selected snapshot as offline HTML'))
