"""Local Library lab endpoints; all mutable state lives in a separate sidecar."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import json
import os
from threading import Event,RLock

from flask import jsonify,request
from engine import open_master
from workbench_store import Store,encoded,now
from research_capture import capture_private_database,capture_workspace,open_capture
from library_checks import compare_snapshots,metadata_consistency,collection_coverage
from analysis_audit import audit_assets
from history_browser import list_history,history_session
from metadata_overrides import FIELDS,FREE_FIELDS,comparable,baseline,validate
from track_tags import editable_colour,snapshot_colour_support
from musicbrainz_pilot import MusicBrainzClient,RateGate,SPEEDS,create_batch,batch_record,run_batch


def workspace_overrides(data,session):
    """Freeze edits only when they still agree with the original workspace."""
    store=Store(data/'workbench-sidecar.sqlite3')
    tracks={t['id']:t for t in __import__('metadata_export').capture_catalog(session['catalog'])['tracks']}
    result={}
    for identity,fields in store.overrides('session:'+session['id']).items():
        if identity not in tracks:raise ValueError('An edited track no longer belongs to this workspace')
        for field,edit in fields.items():
            if comparable(field,baseline(field,tracks[identity]))!=comparable(field,edit['baseline']):
                raise ValueError('Metadata baseline changed for '+identity+' / '+field+'. Capture again and review the edit.')
            result.setdefault(identity,{})[field]=edit['value']
    return result


def register(owner):
    app=owner.app
    edit_unlocked=set();network_pool=ThreadPoolExecutor(max_workers=1)
    gate=RateGate();cancellations={};network_lock=RLock()
    def store():return Store(owner.DATA/'workbench-sidecar.sqlite3')
    def enabled():return os.environ.get('LIBRARY_WORKBENCH_MUSICBRAINZ','1')!='0' and store().setting('musicbrainz_enabled',False) is True
    def cancel_all():
        with network_lock:
            for event in cancellations.values():event.set()
    owner.cancel_lab_jobs=cancel_all
    def snapshot(body):return store().snapshot(body.get('snapshot',''))
    def unlocked(s):
        if s['scope_key'] not in edit_unlocked:raise ValueError('Metadata is read-only. Unlock edits for this snapshot first.')
    def body():return request.get_json(silent=True) or {}
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
        return jsonify(snapshots=store().snapshots(),reports=store().reports(),sources=sources,
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
            if not private.is_file() and not comparison.is_file():raise ValueError('Capture this source folder with Source analyzer first')
        def work(progress):
            progress(10,'Reading the already detached private database copy')
            if source!='session' and comparison.is_file():s=json.loads(comparison.read_text(encoding='utf-8'))
            elif private.is_file():
                with closing(open_capture(private.resolve())) as db:s=capture_private_database(db,scope)
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
        b=body();s=snapshot(b);kind=b.get('kind');working=store().effective(s) if b.get('working') is True else s
        def work(progress):
            if kind=='consistency':summary,rows=metadata_consistency(working)
            elif kind=='coverage':summary,rows=collection_coverage(working,b.get('min_cues',1),b.get('min_manual',0),b.get('require_analysis',True) is True)
            elif kind=='assets':summary,rows=audit_assets(s,b.get('paths') or b.get('path',''),progress,b.get('verify') is True)
            else:raise ValueError('Choose metadata consistency, collection coverage or analysis asset audit')
            summary['working_metadata_applied']=working.get('metadata_overrides_applied',0)
            return store().save_report(kind,[s['id']],summary,rows)
        return jsonify(job=owner.launch(work,'Checking '+str(kind)))

    @app.get('/api/lab/reports/<identity>')
    @app.get('/api/lab/reports/<identity>/download')
    def lab_report(identity):
        result=store().report(identity,request.args.get('offset',0),request.args.get('section',''),request.args.get('q',''),request.path.endswith('/download'))
        if request.path.endswith('/download'):return download(result,'library-lab-report.json')
        return jsonify(result)

    @app.get('/api/lab/tracks')
    def lab_tracks():
        s=store().snapshot(request.args.get('snapshot',''));edits=store().overrides(s['scope_key']);query=request.args.get('q','').casefold()
        tracks=[t for t in s['tracks'] if not query or query in (' '.join(str(t.get(f) or '') for f in ('id','title','artist','album','genre'))).casefold()]
        offset=max(0,int(request.args.get('offset',0)))
        return jsonify(rows=[{'original':{f:t.get(f) for f in ('id',*FIELDS)},'overrides':edits.get(t['id'],{})} for t in tracks[offset:offset+30]],
                       total=len(tracks),offset=offset,unlocked=s['scope_key'] in edit_unlocked,scope=s['scope_key'],override_fields=sum(len(v) for v in edits.values()))

    @app.get('/api/lab/history')
    def lab_history():
        s=store().snapshot(request.args.get('snapshot',''))
        return jsonify(list_history(s,request.args.get('q',''),request.args.get('year',''),request.args.get('offset',0)))

    @app.get('/api/lab/history/<identity>')
    @app.get('/api/lab/history/<identity>/download')
    def lab_history_session(identity):
        s=store().snapshot(request.args.get('snapshot',''));full=request.path.endswith('/download')
        result=history_session(s,identity,request.args.get('q',''),request.args.get('offset',0),full)
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
            store().clear_override(s['scope_key'],identity,field)
            return jsonify(reset=True,overrides=store().overrides(s['scope_key']).get(identity,{}))
        if field=='colour':
            proposed=validate(field,b.get('value'))
            entry=next((p for p in snapshot_colour_support(s)['palette'] if p['value']==proposed),None)
            if not entry or not entry['supported']:raise ValueError(entry['reason'] if entry else 'This colour cannot be represented by the source library')
        value=store().save_override(s['scope_key'],identity,field,b.get('value'),baseline(field,t))
        return jsonify(value=value,overrides=store().overrides(s['scope_key']).get(identity,{}))

    @app.get('/api/lab/track')
    def lab_track_detail():
        s=store().snapshot(request.args.get('snapshot',''));identity=request.args.get('track_id','')
        t=next((t for t in s['tracks'] if t['id']==identity),None)
        if t is None:raise ValueError('Choose a track in this snapshot')
        fields=('id',*FIELDS,'bpm','duration','tonality','color_name','color_hex','color_status','color_basis','play_count','manual_cues','auto_cues','analysed')
        support=snapshot_colour_support(s);original={f:t.get(f) for f in fields};original['colour']=editable_colour(t)
        return jsonify(original=original,overrides=store().overrides(s['scope_key']).get(identity,{}),
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
        return jsonify(count=store().save_bulk(s,b.get('track_ids',[]),b.get('field'),b.get('value')))

    @app.post('/api/lab/features')
    def lab_feature():
        requested=body().get('musicbrainz_enabled') is True
        if requested and os.environ.get('LIBRARY_WORKBENCH_MUSICBRAINZ')=='0':raise ValueError('MusicBrainz is disabled by the application environment')
        store().set_setting('musicbrainz_enabled',requested)
        if not requested:
            cancel_all()
        return jsonify(musicbrainz_enabled=enabled())

    @app.post('/api/lab/musicbrainz/preview')
    def lab_pilot_preview():
        b=body();s=store().effective(snapshot(b));speed=b.get('speed','balanced')
        if speed not in SPEEDS:raise ValueError('Choose gentle, balanced or fast lookup pacing')
        return jsonify(create_batch(store(),s,b.get('top_genres',5),b.get('seed','preview'),SPEEDS[speed]))

    @app.get('/api/lab/musicbrainz/<identity>')
    def lab_pilot_record(identity):return jsonify(batch_record(store(),identity,max(0,int(request.args.get('offset',0)))))

    @app.post('/api/lab/musicbrainz/<identity>/start')
    def lab_pilot_start(identity):
        b=body()
        if not enabled():raise ValueError('Enable the experimental MusicBrainz feature first')
        if b.get('query_consent') is not True:raise ValueError('Review and confirm sending selected public tags/identifiers to MusicBrainz')
        record=batch_record(store(),identity)
        if record['status']=='complete':raise ValueError('This batch is complete. Preview a new sample to run another batch.')
        with network_lock:
            if any(not e.is_set() for e in cancellations.values()):raise ValueError('A pilot is already running. Cancel it or wait until it finishes.')
            event=Event();cancellations[identity]=event
        def work(progress):
            try:
                client=MusicBrainzClient(store(),gate,enabled,record['summary']['seconds_per_request'],event)
                return run_batch(store(),identity,client,progress)
            finally:event.set()
        return jsonify(job=owner.launch(work,'Looking up selected public metadata with MusicBrainz',pool=network_pool))

    @app.post('/api/lab/musicbrainz/<identity>/cancel')
    def lab_pilot_cancel(identity):
        with network_lock:
            if identity in cancellations:cancellations[identity].set()
        return jsonify(cancel_requested=True)

    @app.post('/api/lab/musicbrainz/<identity>/review')
    def lab_pilot_review(identity):
        b=body();track_id=str(b.get('track_id',''))
        with store().connection() as db:
            r=db.execute('SELECT payload FROM mb_results WHERE batch_id=? AND track_id=?',(identity,track_id)).fetchone()
            if not r:raise ValueError('No retrieved match exists for this track')
            result=json.loads(r[0])
            if not result.get('candidates') or not result.get('proposal'):raise ValueError('No candidate with metadata is available')
            result['match_approved']=b.get('approved') is True
            result['reviewed_at']=now()
            db.execute('UPDATE mb_results SET payload=? WHERE batch_id=? AND track_id=?',(encoded(result),identity,track_id))
        return jsonify(match_approved=result['match_approved'],note='Approval records identity only. Stage each metadata field separately in the editor.')

    @app.post('/api/lab/musicbrainz/<identity>/stage')
    def lab_pilot_stage(identity):
        b=body();field=b.get('field');track_id=str(b.get('track_id',''))
        if field not in ('year','genre'):raise ValueError('Stage a proposed year or genre; personal stars remain a manual choice')
        record=batch_record(store(),identity);s=store().snapshot(record['snapshot_id']);unlocked(s)
        with store().connection() as db:r=db.execute('SELECT payload FROM mb_results WHERE batch_id=? AND track_id=?',(identity,track_id)).fetchone()
        result=json.loads(r[0]) if r else {}
        if not result.get('match_approved') or result.get('proposal',{}).get(field) is None:raise ValueError('Approve this retrieved identity before staging its available metadata')
        t=next((t for t in s['tracks'] if t['id']==track_id),None)
        if not t:raise ValueError('The retrieved track is outside the selected snapshot')
        origin='MusicBrainz '+result['candidates'][0]['mbid']+' '+result['proposal']['retrieved_at']
        value=store().save_override(s['scope_key'],track_id,field,result['proposal'][field],t.get(field),origin)
        return jsonify(value=value,origin=origin)

    @app.post('/api/lab/offline-export')
    def lab_offline_export():
        from metadata_export import export_metadata
        from uuid import uuid4
        b=body();s=snapshot(b)
        if b.get('working') is True:s=store().effective(s)
        identity=uuid4().hex
        return jsonify(job=owner.launch(lambda p:export_metadata(s,owner.DATA/'quick-exports',identity,owner.ROOT/'static',p,title=b.get('title') or s['label'],include_paths=False,temporary_root=owner.TEMPORARY.folder('exports')),'Exporting the selected snapshot as offline HTML'))
