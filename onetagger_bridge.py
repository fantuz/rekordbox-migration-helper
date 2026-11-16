"""Explicit local playlist handoff, tag read-back and reviewed sidecar edits."""
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import quote
from uuid import uuid4

from flask import jsonify,request
from werkzeug.exceptions import Conflict

from audio_paths import mappings_for,signature
from file_health import local_request
from metadata_concurrency import require_revision,revision
from metadata_overrides import comparable,validate
from track_playback import available_audio
from workbench_store import Store,encoded,now

FIELDS=('title','artist','album','genre','year')
LIMIT=500
TAGGABLE={'.mp3','.flac','.aif','.aiff','.m4a','.wav','.ogg','.opus'}


def stamp(path):
    value=path.stat()
    return [value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns]


def read_tags(path):
    from tinytag import TinyTag,TinyTagException
    before=stamp(path)
    try:tag=TinyTag.get(path,duration=False,image=False)
    except TinyTagException as error:raise ValueError('Could not read file tags: '+str(error)) from error
    values={};warnings=[]
    for field in FIELDS:
        raw=getattr(tag,field,None)
        # Absent tags do not silently erase captured library metadata.
        if raw in (None,''):continue
        try:values[field]=validate(field,raw)
        except ValueError as error:warnings.append({'field':field,'reason':str(error)})
    if stamp(path)!=before:raise Conflict('An audio file changed while its tags were being read. Rescan it.')
    return values,before,warnings


def playlist(manifest):
    # OneTagger percent-decodes M3U entries. Encode literal percent signs too,
    # so a filename such as "100%20Mix" does not become "100 Mix".
    return '#EXTM3U\n'+'\n'.join(quote(row['local_path'],safe='/:\\') for row in manifest['tracks'])+'\n'


def register(owner,unlocked):
    def store():return Store(owner.DATA/'workbench-sidecar.sqlite3')
    def local():
        if not local_request():raise ValueError('The OneTagger bridge requires the local application')
    def body():
        local();value=request.get_json(silent=True)
        if not isinstance(value,dict):raise ValueError('Choose a OneTagger bridge action')
        return value
    def record(saved,identity):
        if not re.fullmatch('[0-9a-f]{32}',identity):raise ValueError('Choose an existing OneTagger selection')
        result=saved.setting('onetagger:'+identity)
        if not isinstance(result,dict):raise ValueError('Choose an existing OneTagger selection')
        return result
    def context(saved,manifest):
        snapshot=saved.snapshot(manifest['snapshot'])
        if snapshot['scope_key']!=manifest['scope_key'] or sha256(encoded(snapshot).encode()).hexdigest()!=manifest['snapshot_digest']:
            raise Conflict('The source snapshot changed. Create a new OneTagger selection.')
        mappings=mappings_for(saved,snapshot)
        if signature(mappings)!=manifest['mapping_revision']:
            raise Conflict('Audio folders changed. Create a new OneTagger selection.')
        return snapshot,mappings,{t['id']:t for t in snapshot['tracks']}
    def path_for(track,row,mappings):
        path=available_audio(track,mappings)
        if path is None or str(path)!=row['local_path']:
            raise Conflict('The selected audio file moved or became unavailable. Create a new selection.')
        return path
    def summary(manifest):
        return {k:manifest[k] for k in ('id','snapshot','created')}|{'tracks':len(manifest['tracks']),'scanned':manifest.get('scan') is not None}

    @owner.app.get('/api/onetagger',endpoint='onetagger_selections')
    def selections():
        local();saved=store();identity=request.args.get('snapshot','')
        choices=saved.snapshots();tracks=[];total=0;jobs=[]
        if identity:
            snapshot=saved.snapshot(identity);query=request.args.get('q','').strip().casefold()
            try:offset=int(request.args.get('offset',0))
            except (TypeError,ValueError):raise ValueError('Choose a valid selection page') from None
            if not 0<=offset<=250000 or len(query)>200:raise ValueError('Choose a valid selection page and search')
            matching=[t for t in snapshot['tracks'] if not query or query in ' '.join(str(t.get(k) or '') for k in ('id','title','artist')).casefold()]
            total=len(matching);tracks=[{k:t.get(k) for k in ('id','title','artist')} for t in matching[offset:offset+50]]
            with saved.connection() as db:
                for row in db.execute("SELECT value FROM settings WHERE name LIKE 'onetagger:%'"):
                    manifest=json.loads(row[0])
                    if manifest['snapshot']==identity:jobs.append(summary(manifest))
        return jsonify(snapshots=choices,tracks=tracks,total=total,selections=sorted(jobs,key=lambda r:r['created'],reverse=True)[:20],limit=LIMIT)

    @owner.app.post('/api/onetagger/export',endpoint='onetagger_handoff')
    def handoff():
        b=body();saved=store();snapshot=saved.snapshot(b.get('snapshot',''));ids=b.get('track_ids')
        if not isinstance(ids,list) or not 1<=len(ids)<=LIMIT or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):
            raise ValueError('Select between 1 and 500 distinct tracks')
        tracks={t['id']:t for t in snapshot['tracks']}
        if any(i not in tracks for i in ids):raise ValueError('Select tracks from this snapshot')
        mappings=mappings_for(saved,snapshot);selected=[]
        for identity in ids:
            track=tracks[identity];path=available_audio(track,mappings)
            if path is None:raise ValueError('Some selected audio is unavailable. Check Audio folders and select accessible tracks.')
            if path.suffix.lower() not in TAGGABLE:raise ValueError('A selected audio format is not supported by this OneTagger tag-readback bridge')
            if any(ord(c)<32 for c in str(path)):raise ValueError('A selected filename cannot be represented safely in an M3U playlist')
            selected.append({'track_id':identity,'local_path':str(path),
                             'recorded_references':{k:track.get(k) for k in ('current_path','xml_location','original_path')},
                             'library_tags':{k:track.get(k) for k in FIELDS}})
        manifest={'schema':1,'id':uuid4().hex,'created':now(),'snapshot':snapshot['id'],
                  'snapshot_digest':sha256(encoded(snapshot).encode()).hexdigest(),'scope_key':snapshot['scope_key'],
                  'mapping_revision':signature(mappings),'tracks':selected,'scan':None,'scan_generation':None,
                  'audio_files_modified':False,'note':'Local paths are access aliases. Recorded references and track IDs are preserved. OneTagger edits the selected audio files separately.'}
        if signature(mappings_for(saved,snapshot))!=manifest['mapping_revision']:raise Conflict('Audio folders changed. Create the selection again.')
        saved.set_setting('onetagger:'+manifest['id'],manifest)
        return jsonify(**summary(manifest),playlist='/api/onetagger/'+manifest['id']+'/playlist',manifest='/api/onetagger/'+manifest['id']+'/manifest')

    @owner.app.get('/api/onetagger/<identity>/<kind>',endpoint='onetagger_download')
    def download(identity,kind):
        local();manifest=record(store(),identity)
        if kind=='playlist':content=playlist(manifest);mime='audio/x-mpegurl';filename='onetagger-selection.m3u'
        elif kind=='manifest':
            content=json.dumps({k:v for k,v in manifest.items() if k not in ('scan','scan_generation')},ensure_ascii=False,indent=2)
            mime='application/json';filename='onetagger-selection.json'
        elif kind=='review':
            return jsonify(id=identity,snapshot=manifest['snapshot'],scan=manifest.get('scan'),
                           edit_revision=store().edit_state(manifest['scope_key'])['edit_revision'])
        else:raise ValueError('Choose the playlist, manifest or scanned review')
        return owner.app.response_class(content,mimetype=mime,headers={'Content-Disposition':'attachment; filename="'+filename+'"'})

    @owner.app.post('/api/onetagger/<identity>/rescan',endpoint='onetagger_rescan')
    def rescan(identity):
        body();saved=store();manifest=record(saved,identity);snapshot,mappings,tracks=context(saved,manifest)
        generation=uuid4().hex
        with owner.lock:
            manifest=record(saved,identity);manifest['scan_generation']=generation
            saved.set_setting('onetagger:'+identity,manifest)
        edit_state=saved.edit_state(snapshot['scope_key'])
        def work(progress):
            output=[]
            for n,row in enumerate(manifest['tracks']):
                progress(95*n/len(manifest['tracks']),'Reading OneTagger tags: '+str(n+1)+' / '+str(len(manifest['tracks'])))
                track=tracks[row['track_id']]
                try:
                    path=path_for(track,row,mappings);tags,file_stamp,warnings=read_tags(path)
                    changes=[]
                    for field,value in tags.items():
                        staged=edit_state['overrides'].get(track['id'],{}).get(field)
                        before=staged['value'] if staged else track.get(field)
                        if comparable(field,before)!=comparable(field,value):
                            changes.append({'field':field,'library_value':track.get(field),'working_value':before,'value':value,'replaces_staged_edit':staged is not None})
                    output.append({'track_id':track['id'],'title':track.get('title'),'status':'read','tags':tags,'file_stamp':file_stamp,'warnings':warnings,'changes':changes})
                except (OSError,ValueError,Conflict) as error:
                    output.append({'track_id':track['id'],'title':track.get('title'),'status':'unreadable','error':str(error),'changes':[]})
            scan={'generation':generation,'created':now(),'rows':output,'edit_revision':edit_state['edit_revision']}
            scan['review_revision']=sha256(encoded(scan).encode()).hexdigest()
            with owner.lock:
                current=record(saved,identity);context(saved,current)
                if current['scan_generation']!=generation:raise Conflict('A newer rescan replaced this request')
                current['scan']=scan;saved.set_setting('onetagger:'+identity,current)
            return {'id':identity,'tracks':len(output),'changes':sum(len(r['changes']) for r in output),'unreadable':sum(r['status']=='unreadable' for r in output)}
        return jsonify(job=owner.launch(work,'Reading tags after OneTagger'),id=identity)

    @owner.app.post('/api/onetagger/<identity>/stage',endpoint='onetagger_stage')
    def stage(identity):
        b=body();saved=store();manifest=record(saved,identity);snapshot,mappings,tracks=context(saved,manifest);unlocked(snapshot)
        scan=manifest.get('scan');choices=b.get('changes')
        if b.get('reviewed') is not True:raise ValueError('Review and select the tag fields before staging them')
        if not scan or scan['generation']!=manifest['scan_generation'] or b.get('review_revision')!=scan['review_revision']:
            raise Conflict('Tag review changed. Rescan and review the selection again.')
        if not isinstance(choices,list) or not 1<=len(choices)<=LIMIT*len(FIELDS) or any(not isinstance(c,dict) for c in choices):
            raise ValueError('Select the tag fields to stage')
        pairs=[(c.get('track_id'),c.get('field')) for c in choices]
        if any(not isinstance(i,str) or f not in FIELDS for i,f in pairs) or len(set(pairs))!=len(pairs):
            raise ValueError('Select distinct tag fields from this review')
        proposals={(r['track_id'],c['field']):c for r in scan['rows'] for c in r['changes']}
        if any(pair not in proposals for pair in pairs):raise ValueError('Choose fields present in this tag review')
        selected_rows={r['track_id']:r for r in manifest['tracks']}
        checked={r['track_id']:r for r in scan['rows']}
        for track_id in {i for i,_ in pairs}:
            path=path_for(tracks[track_id],selected_rows[track_id],mappings)
            tags,file_stamp,_=read_tags(path)
            if file_stamp!=checked[track_id]['file_stamp'] or tags!=checked[track_id]['tags']:
                raise Conflict('Audio tags changed since the review. Rescan before staging them.')
        with owner.lock,saved.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            require_revision(db,snapshot['scope_key'],b.get('edit_revision'))
            if b.get('edit_revision')!=scan['edit_revision']:raise Conflict('Staged metadata changed since the tag review. Rescan first.')
            # Do not let a concurrent mapping/rescan supersede reviewed evidence.
            current_row=db.execute('SELECT value FROM settings WHERE name=?',('onetagger:'+identity,)).fetchone()
            current=json.loads(current_row[0])
            if current['scan_generation']!=scan['generation']:raise Conflict('A newer rescan replaced this review')
            live_maps=db.execute('SELECT value FROM settings WHERE name=?',('audio_paths:'+snapshot['scope_key'],)).fetchone()
            if signature(json.loads(live_maps[0]) if live_maps else [])!=manifest['mapping_revision']:raise Conflict('Audio folders changed. Create a new selection.')
            for track_id,field in pairs:
                baseline=tracks[track_id].get(field);value=proposals[(track_id,field)]['value']
                old=db.execute('SELECT value,baseline FROM overrides WHERE scope_key=? AND track_id=? AND field=?',(snapshot['scope_key'],track_id,field)).fetchone()
                if old and comparable(field,json.loads(old['baseline']))!=comparable(field,baseline):raise Conflict('The library baseline changed. Capture and review again.')
                origin=encoded({'provider':'OneTagger bridge','selection_id':identity,'review_revision':scan['review_revision'],'scanned_at':scan['created'],'reviewed_at':now()})
                db.execute('INSERT INTO override_history VALUES (?,?,?,?,?,?,?)',(uuid4().hex,snapshot['scope_key'],track_id,field,old['value'] if old else None,encoded(value),now()))
                db.execute('INSERT OR REPLACE INTO overrides VALUES (?,?,?,?,?,?,?)',(snapshot['scope_key'],track_id,field,encoded(value),encoded(baseline),origin,now()))
            stamp_value=revision(db,snapshot['scope_key'])
        return jsonify(staged=len(pairs),edit_revision=stamp_value,audio_files_modified=False,recorded_references_modified=False)
