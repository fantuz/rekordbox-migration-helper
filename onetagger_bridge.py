"""Explicit local playlist handoff, tag read-back and reviewed sidecar edits."""
from hashlib import sha256
from datetime import date
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
from onetagger_results import MAX_BYTES,decode_report,validate_report,FIELDS as V1_FIELDS,EXTENDED_FIELDS
from track_playback import available_audio
from workbench_store import Store,encoded,now

FIELDS=EXTENDED_FIELDS
LIMIT=500
TAGGABLE={'.mp3','.flac','.aif','.aiff','.m4a','.wav','.ogg','.opus'}
SCALAR_LIST_FORMATS={'.mp3','.aif','.aiff','.m4a','.wav'}


def stamp(path):
    value=path.stat()
    return [value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns]


def read_tags(path):
    from tinytag import TinyTag,TinyTagException
    before=stamp(path)
    try:tag=TinyTag.get(path,duration=False,image=False)
    except TinyTagException as error:raise ValueError('Could not read file tags: '+str(error)) from error
    values={};warnings=[]
    extension=path.suffix.lower()
    lists=tag.as_dict() if extension in SCALAR_LIST_FORMATS else {}
    for field in FIELDS:
        raw=getattr(tag,field,None)
        if field=='label':
            label_values=tag.other.get('label' if extension=='.m4a' else 'publisher',[])
            raw=(', '.join(label_values) if extension in SCALAR_LIST_FORMATS else label_values[0]) if label_values else None
        elif field!='year' and isinstance(lists.get(field),list):
            raw=', '.join(lists[field])
        # Absent tags do not silently erase captured library metadata.
        if raw in (None,''):continue
        # OneTagger's report reads the year component of stored release dates.
        try:
            if field=='year' and isinstance(raw,str):
                match=re.fullmatch(r'([0-9]{4})(?:([-/])([0-9]{2})(?:\2([0-9]{2})(?:[T ].*)?)?)?',raw.strip())
                if match:
                    year,_,month,day=match.groups()
                    raw=date(int(year),int(month or 1),int(day or 1)).year
            values[field]=validate(field,raw)
        except ValueError as error:warnings.append({'field':field,'reason':str(error)})
    if stamp(path)!=before:raise Conflict('An audio file changed while its tags were being read. Rescan it.')
    return values,before,warnings


class ReadBatch:
    """Reuse read-back only within one operation; validate every reuse by stat."""
    def __init__(self):self.files={}
    def read(self,path):
        cached=self.files.get(path)
        if cached is not None:
            if stamp(path)!=cached[1]:raise Conflict('An audio file changed while its tags were being read. Rescan it.')
            return cached
        result=read_tags(path);self.files[path]=result
        return result


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
        manifest={'schema':1,'results_version':2,'id':uuid4().hex,'created':now(),'snapshot':snapshot['id'],
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
            result=jsonify(id=identity,snapshot=manifest['snapshot'],scan=manifest.get('scan'),
                           edit_revision=store().edit_state(manifest['scope_key'])['edit_revision'])
            if request.args.get('download')=='1':result.headers['Content-Disposition']='attachment; filename="onetagger-review.json"'
            return result
        else:raise ValueError('Choose the playlist, manifest or scanned review')
        return owner.app.response_class(content,mimetype=mime,headers={'Content-Disposition':'attachment; filename="'+filename+'"'})

    def scan_selection(identity,imported=None):
        saved=store();manifest=record(saved,identity);snapshot,mappings,tracks=context(saved,manifest)
        generation=uuid4().hex
        with owner.lock:
            manifest=record(saved,identity);manifest['scan_generation']=generation
            saved.set_setting('onetagger:'+identity,manifest)
        edit_state=saved.edit_state(snapshot['scope_key'])
        def work(progress):
            output=[];reads=ReadBatch()
            fields=V1_FIELDS if imported and imported['version']==1 else FIELDS
            for n,row in enumerate(manifest['tracks']):
                progress(95*n/len(manifest['tracks']),'Reading OneTagger tags: '+str(n+1)+' / '+str(len(manifest['tracks'])))
                track=tracks[row['track_id']]
                evidence=imported['rows'][track['id']] if imported else None
                try:
                    if evidence and evidence['status']!='written':
                        output.append({'track_id':track['id'],'title':track.get('title'),'status':'reported',
                                       'verification':'not_written','report':evidence,'changes':[]});continue
                    path=path_for(track,row,mappings);tags,file_stamp,warnings=reads.read(path)
                    tags={f:v for f,v in tags.items() if f in fields}
                    if evidence:
                        expected=evidence['after'];state=evidence['file_state']
                        if expected is None or state is None or evidence['after_error']:
                            raise ValueError('OneTagger could not verify the final tags; rescan the file before reviewing changes')
                        if state['size']!=file_stamp[2] or state['modified_ns']!=str(file_stamp[3]):
                            raise Conflict('Audio file changed after the OneTagger report. Rescan or create a new report.')
                        expected={f:validate(f,v) for f,v in expected.items() if v not in (None,'')}
                        if any(comparable(f,expected.get(f))!=comparable(f,tags.get(f)) for f in fields):
                            raise Conflict('Audio tags differ from the report. Rescan and review the current file.')
                    changes=[]
                    for field,value in tags.items():
                        staged=edit_state['overrides'].get(track['id'],{}).get(field)
                        before=staged['value'] if staged else track.get(field)
                        if comparable(field,before)!=comparable(field,value):
                            changes.append({'field':field,'library_value':track.get(field),'working_value':before,'value':value,'replaces_staged_edit':staged is not None})
                    output.append({'track_id':track['id'],'title':track.get('title'),'status':'read','verification':'verified',
                                   'tags':tags,'file_stamp':file_stamp,'warnings':warnings,'changes':changes,**({'report':evidence} if evidence else {})})
                except (OSError,ValueError,Conflict) as error:
                    output.append({'track_id':track['id'],'title':track.get('title'),'status':'unreadable','verification':'not_verified',
                                   'error':str(error),'changes':[],**({'report':evidence} if evidence else {})})
            scan={'generation':generation,'created':now(),'rows':output,'edit_revision':edit_state['edit_revision']}
            if imported:scan['report']={k:v for k,v in imported.items() if k!='rows'}
            scan['summary']={'tracks':len(output),'verified':sum(r['status']=='read' for r in output),
                             'unreadable':sum(r['status']=='unreadable' for r in output),
                             'not_written':sum(r['status']=='reported' for r in output),
                             'changes':sum(len(r['changes']) for r in output)}
            scan['review_revision']=sha256(encoded(scan).encode()).hexdigest()
            with owner.lock:
                current=record(saved,identity);context(saved,current)
                if current['scan_generation']!=generation:raise Conflict('A newer rescan replaced this request')
                current['scan']=scan;saved.set_setting('onetagger:'+identity,current)
            return {'id':identity,'tracks':len(output),'changes':sum(len(r['changes']) for r in output),'unreadable':sum(r['status']=='unreadable' for r in output)}
        return jsonify(job=owner.launch(work,'Reading tags after OneTagger'),id=identity)

    @owner.app.post('/api/onetagger/<identity>/rescan',endpoint='onetagger_rescan')
    def rescan(identity):
        body();return scan_selection(identity)

    @owner.app.post('/api/onetagger/<identity>/import-results',endpoint='onetagger_import_results')
    def import_results(identity):
        local()
        if not request.is_json:raise ValueError('Choose a OneTagger results JSON report')
        if request.content_length is not None and request.content_length>MAX_BYTES:
            raise ValueError('Choose a results report smaller than 8 MiB')
        data=request.stream.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES:raise ValueError('Choose a results report smaller than 8 MiB')
        value=decode_report(data)
        saved=store();manifest=record(saved,identity);context(saved,manifest)
        imported=validate_report(value,manifest)
        imported['digest']=sha256(data).hexdigest()
        imported['digest_basis']='uploaded_json_bytes'
        return scan_selection(identity,imported)

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
        reads=ReadBatch()
        fields=V1_FIELDS if scan.get('report',{}).get('version')==1 else FIELDS
        for track_id in {i for i,_ in pairs}:
            path=path_for(tracks[track_id],selected_rows[track_id],mappings)
            tags,file_stamp,_=reads.read(path)
            tags={f:v for f,v in tags.items() if f in fields}
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
                report_origin={}
                if scan.get('report'):
                    report_origin={'report':scan['report'],'attempts':checked[track_id]['report']['attempts']}
                origin=encoded({**report_origin,'provider':'OneTagger bridge','selection_id':identity,'review_revision':scan['review_revision'],'scanned_at':scan['created'],'reviewed_at':now()})
                db.execute('INSERT INTO override_history VALUES (?,?,?,?,?,?,?)',(uuid4().hex,snapshot['scope_key'],track_id,field,old['value'] if old else None,encoded(value),now()))
                db.execute('INSERT OR REPLACE INTO overrides VALUES (?,?,?,?,?,?,?)',(snapshot['scope_key'],track_id,field,encoded(value),encoded(baseline),origin,now()))
            # If files changed while staging, roll back values, history and revisions.
            for track_id in {i for i,_ in pairs}:
                path=path_for(tracks[track_id],selected_rows[track_id],mappings)
                if stamp(path)!=checked[track_id]['file_stamp']:
                    raise Conflict('Audio tags changed while staging the review. Rescan before staging them.')
            stamp_value=revision(db,snapshot['scope_key'])
        return jsonify(staged=len(pairs),edit_revision=stamp_value,audio_files_modified=False,recorded_references_modified=False)


