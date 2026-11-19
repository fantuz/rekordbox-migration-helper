"""Explicit Dropbox connection, metadata validation and one-file download routes."""
import json
import logging
from pathlib import Path
import re
import secrets
import sqlite3
from threading import RLock
import time
from urllib.parse import parse_qs,unquote,urlsplit

from flask import jsonify,redirect,request
from collection_sources import resolve
from cloud_locations import provider_roots
from cloud_oauth import callback_errors
from file_health import local_request,selected_source
from workbench_store import Store
import dropbox_files as files


_connection_lock=RLock()


def connection(owner):
    """Keep live credentials bound to the profile that created them."""
    from dropbox_auth import DropboxConnection
    profile=owner.DATA.resolve()
    with _connection_lock:
        if getattr(owner,'_dropbox_profile',None)!=profile:
            owner.dropbox_connection=DropboxConnection(owner)
            owner._dropbox_profile=profile
        return owner.dropbox_connection


def evidence_context(owner,source):
    """Identify cached evidence without remote requests or audio reads."""
    from cloud_file_evidence import provider_context
    return provider_context(owner,source,'dropbox_mapping',connection(owner),files)


class _CallbackLogFilter(logging.Filter):
    """OAuth codes and state must not enter Werkzeug access logs."""
    def filter(self,record):
        def redact(value):
            if not isinstance(value,str):return value
            def query(match):
                target=match.group(1)
                return target+'?[redacted]' if unquote(target).endswith('/api/dropbox/callback') else match.group(0)
            return re.sub(r'([^\s\"]+)\?[^\s\"]*',query,value)
        record.msg=redact(record.msg)
        if isinstance(record.args,tuple):record.args=tuple(redact(v) for v in record.args)
        return True


def register(owner):
    app=owner.app
    intents={};guard=RLock();authorization_errors=callback_errors(app,'dropbox');running={};return_views={}
    logging.getLogger('werkzeug').addFilter(_CallbackLogFilter())
    def connected():return connection(owner)
    def store():
        saved=Store(owner.DATA/'workbench-sidecar.sqlite3')
        with saved.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS dropbox_records (binding TEXT,source TEXT,track_id TEXT,payload TEXT,PRIMARY KEY(binding,source,track_id))')
            db.execute('CREATE TABLE IF NOT EXISTS dropbox_scans (binding TEXT,source TEXT,payload TEXT,PRIMARY KEY(binding,source))')
            db.execute("CREATE INDEX IF NOT EXISTS dropbox_records_status ON dropbox_records(binding,source,json_extract(payload,'$.status'))")
        return saved
    def local():
        if not local_request():raise ValueError('Use Dropbox from the local Workbench application.')
        origin_header=request.headers.get('Origin')
        if origin_header and origin_header.rstrip('/')!=request.host_url.rstrip('/'):
            raise ValueError('Use Dropbox from the local Workbench application.')
    def body():
        local();value=request.get_json(silent=True)
        if not isinstance(value,dict):raise ValueError('Provide a Dropbox request object.')
        return value
    def mapping():return store().setting('dropbox_mapping',None)
    def context(source):
        state=evidence_context(owner,source)
        return state['mapping'],state['key'],state['audio']
    def origin():
        local();parsed=urlsplit(request.host_url)
        if parsed.scheme!='http' or parsed.username or parsed.password:raise ValueError('Use the local HTTP Workbench address for Dropbox authorization.')
        from cloud_oauth import authorization_origin
        return authorization_origin()
    def status():
        state=connected().status();value=mapping();account=state.get('account') or {}
        if value and value.get('account_id')!=account.get('account_id'):value=None
        return {**state,'account':{**account,'name':account.get('display_name','')},
                'redirect_uri':origin()+'/api/dropbox/callback','roots':files.detected_roots(),
                'mapping':value,'credential_storage':{'available':state.get('secure_storage_available',False),
                 'persistent':state.get('persistent',False)},
                'authorization_error':authorization_errors.get(str(owner.DATA.resolve()))}

    @app.after_request
    def private_dropbox_response(response):
        if request.path.startswith('/api/dropbox/'):
            response.headers['Cache-Control']='no-store'
            response.headers['Referrer-Policy']='no-referrer'
        return response

    @app.get('/api/dropbox/status')
    def dropbox_status():local();return jsonify(status())
    @app.post('/api/dropbox/configure')
    def configure():
        value=body();connected().configure(value.get('app_key'),value.get('remember',False));return jsonify(status())
    @app.post('/api/dropbox/connect')
    def connect():
        value=body();destination=value.get('return_to','dropbox')
        if destination not in ('dropbox','cloud-connect'):raise ValueError('Choose a supported Dropbox return page.')
        result=connected().begin(origin())
        state=parse_qs(urlsplit(result['authorize_url']).query).get('state',[''])[0]
        return_views[str(owner.DATA.resolve())]={'view':destination,'state':state}
        authorization_errors.pop(str(owner.DATA.resolve()),None)
        return jsonify(**result)
    @app.get('/api/dropbox/callback')
    def callback():
        local()
        profile=str(owner.DATA.resolve())
        try:
            connected().callback(request.args.get('state'),request.args.get('code'),request.args.get('error'),callback_origin=request.host_url.rstrip('/'))
            authorization_errors.pop(profile,None)
        except ValueError as error:
            authorization_errors[profile]=str(error)
        pending=return_views.get(profile);destination='dropbox'
        if pending and isinstance(request.args.get('state'),str) and secrets.compare_digest(request.args['state'],pending['state']):
            destination=return_views.pop(profile)['view']
        return redirect('/#'+destination,code=303)
    @app.post('/api/dropbox/disconnect')
    def disconnect():
        body();connected().disconnect()
        with guard:intents.clear()
        return jsonify(status())
    @app.post('/api/dropbox/mapping')
    def save_mapping():
        value=body();result=files.mapping_record(connected(),value.get('local_root'),value.get('remote_root',''),value.get('namespace') or None)
        store().set_setting('dropbox_mapping',result)
        with guard:intents.clear()
        return jsonify(mapping=result)
    @app.post('/api/dropbox/check')
    def check():
        value=body();source=selected_source(value.get('source'));snapshot=resolve(owner,source)
        if len(snapshot['tracks'])>250000 or len({str(t['id']) for t in snapshot['tracks']})!=len(snapshot['tracks']):raise ValueError('Choose a library with at most 250000 unique track IDs.')
        mapped,key,audio=context(source);profile=owner.DATA.resolve();identity=(profile,source,key)
        task_store=store();client=connected()
        def work(progress):
            from cloud_file_evidence import size_evidence
            from metadata_sidecars import is_sidecar
            def checkpoint(amount,message):
                if owner.DATA.resolve()!=profile or context(source)[1]!=key:raise ValueError('Dropbox connection, source or mapping changed. Check metadata again.')
                progress(amount,message)
            entries,complete=files.inventory(client,mapped,checkpoint);rows=[]
            unsupported=int(getattr(entries,'unsupported_paths',0));coverage=getattr(entries,'coverage',lambda:None)()
            reasons=(coverage or {}).get('incomplete_reasons',[])
            scan_note=('Some Dropbox paths could not be mapped safely. Only positive path matches are confirmed; '
                       'choose a narrower Rekordbox folder to complete this check.') if unsupported else (
                       'Dropbox metadata listing is incomplete. Only positive path matches are confirmed; '
                       'choose a narrower Rekordbox folder to complete this check.') if not complete else None
            for i,track in enumerate(snapshot['tracks']):
                if i%100==0:checkpoint(70+25*i/max(1,len(snapshot['tracks'])),'Matching library paths with Dropbox metadata')
                destination=files.target(track,mapped,audio);remote=entries.get(files.path_key(destination['remote_path'])) if destination else None
                state='unmapped' if not destination else 'present' if remote else 'not_found' if complete else 'unverified'
                unresolved=('unmapped_path' if state=='unmapped' else 'not_found_in_complete_listing' if state=='not_found'
                            else reasons[0] if state=='unverified' and len(reasons)==1 else 'incomplete_inventory' if state=='unverified' else None)
                rows.append({**({'path_diagnostics':files.path_diagnostics(track,mapped)} if state=='unmapped' else {}),
                             'metadata_sidecar':is_sidecar(track),'unresolved_reason':unresolved,'track_id':str(track['id']),'title':str(track.get('title') or ''),'artist':str(track.get('artist') or ''),
                             'status':state,**(destination or {}),'size':remote.get('size') if remote else None,
                             **size_evidence(track,remote),'remote':remote})
            checkpoint(98,'Saving Dropbox metadata evidence');checked=time.time()
            with task_store.connection() as db:
                db.execute('DELETE FROM dropbox_records WHERE binding=? AND source=?',(key,source))
                db.executemany('INSERT INTO dropbox_records VALUES (?,?,?,?)',[(key,source,r['track_id'],json.dumps(r)) for r in rows])
                db.execute('INSERT OR REPLACE INTO dropbox_scans VALUES (?,?,?)',(key,source,json.dumps({'checked_at':checked,'complete':complete,'tracks':len(rows),'unsupported_paths':unsupported,'scan_note':scan_note,'coverage':coverage})))
            return {'checked':len(rows),'complete':complete,'unsupported_paths':unsupported,'scan_note':scan_note,'coverage':coverage,'audio_contents_read':False,'downloads':0}
        def finished(_state):
            with guard:running.pop(identity,None)
        with guard:
            if identity in running:return jsonify(job=running[identity],source=source)
            # launch completion may be immediate in tests; the RLock permits it.
            running[identity]=None
            try:job=owner.launch(work,'Checking Dropbox metadata',on_finished=finished)
            except Exception:running.pop(identity,None);raise
            if identity in running:running[identity]=job
        return jsonify(job=job,source=source)
    @app.get('/api/dropbox/files')
    def rows():
        local();source=selected_source(request.args.get('source'))
        mapped,key,_=context(source);state=request.args.get('status','all');query=request.args.get('q','').strip().casefold()
        from metadata_sidecars import enabled,summary
        hide_sidecars=enabled(request.args.get('hide_metadata_sidecars',False))
        try:offset=int(request.args.get('offset',0))
        except (TypeError,ValueError):raise ValueError('Choose a valid Dropbox page.') from None
        if state not in ('all','present','not_found','unmapped','unverified') or not 0<=offset<=250000 or len(query)>200:raise ValueError('Choose a valid Dropbox file filter.')
        where='binding=? AND source=?';params=[key,source]
        if state!='all':where+=" AND json_extract(payload,'$.status')=?";params.append(state)
        if query:
            search=" || ' ' || ".join("coalesce(json_extract(payload,'$."+field+"'),'')" for field in ('track_id','title','artist','filename'))
            where+=' AND instr(dropbox_casefold('+search+'),?)>0';params.append(query)
        counts={name:0 for name in ('present','not_found','unmapped','unverified')}
        with store().connection() as db:
            # SQLite's lower()/NOCASE handle ASCII only. Keep Unicode search and
            # ordering identical to the captured display strings without loading
            # every remote metadata payload into Python for each 50-row page.
            db.create_function('dropbox_casefold',1,lambda value:str(value or '').casefold(),deterministic=True)
            total_before=db.execute('SELECT count(*) FROM dropbox_records WHERE '+where,params).fetchone()[0]
            recognized=db.execute("SELECT count(*) FROM dropbox_records WHERE "+where+" AND json_extract(payload,'$.metadata_sidecar')=1",params).fetchone()[0]
            sidecar_filter=" AND coalesce(json_extract(payload,'$.metadata_sidecar'),0)<>1" if hide_sidecars else ''
            for row in db.execute("SELECT json_extract(payload,'$.status'),count(*) FROM dropbox_records WHERE binding=? AND source=?"+sidecar_filter+" GROUP BY json_extract(payload,'$.status')",(key,source)):
                if row[0] in counts:counts[row[0]]=row[1]
            where+=sidecar_filter
            total=db.execute('SELECT count(*) FROM dropbox_records WHERE '+where,params).fetchone()[0]
            order="dropbox_casefold(json_extract(payload,'$.artist')),dropbox_casefold(json_extract(payload,'$.title')),track_id"
            values=[json.loads(r[0]) for r in db.execute('SELECT payload FROM dropbox_records WHERE '+where+' ORDER BY '+order+' LIMIT 50 OFFSET ?',(*params,offset))]
            scan=db.execute('SELECT payload FROM dropbox_scans WHERE binding=? AND source=?',(key,source)).fetchone()
        from cloud_file_evidence import size_evidence
        result=[]
        for r in values:
            remote=r.pop('remote',None);local_path=r.get('local_path')
            r.update(size_evidence({'size':r.get('expected_size')},remote))
            r['local_available']=bool(local_path) and files.local_available(local_path)
            # lstat only: neither inspect nor open an existing cloud placeholder.
            absent=False;r['local_state']='unmapped'
            if local_path:
                try:
                    info=Path(local_path).lstat()
                    from media import cloud_placeholder
                    r['local_state']='online_only' if cloud_placeholder(info) else 'present'
                except FileNotFoundError:absent=True;r['local_state']='not_local'
                except OSError:r['local_state']='unverified'
            r['downloadable']=bool(r.get('status')=='present' and absent and files.downloadable_metadata(remote,r.get('remote_path'),require_hash=False))
            result.append(r)
        return jsonify(rows=result,total=total,offset=offset,counts=counts,sidecars=summary(total_before,recognized,hide_sidecars),**(json.loads(scan[0]) if scan else {}))
    def selected(value):
        source=selected_source(value.get('source'));identity=value.get('track_id')
        if not isinstance(identity,str) or not 1<=len(identity)<=200:raise ValueError('Choose one library track.')
        snapshot=resolve(owner,source);track=next((t for t in snapshot['tracks'] if str(t['id'])==identity),None)
        if not track:raise ValueError('This track is not in the selected library.')
        mapped,key,audio=context(source);destination=files.target(track,mapped,audio)
        if not destination:raise ValueError('This track has no path inside the verified Dropbox mapping.')
        return source,identity,mapped,key,destination,track
    def remote_file(mapped,destination):
        remote=connected().rpc('files/get_metadata',{'path':destination['remote_path']},path_root={'.tag':'namespace_id','namespace_id':mapped['namespace']})
        if not files.downloadable_metadata(remote,destination['remote_path']):
            raise ValueError('This Dropbox entry cannot be downloaded as a verified audio file.')
        return remote
    @app.post('/api/dropbox/download/prepare')
    def prepare():
        from dropbox_download import prepare_target
        from cloud_attachments import validate_destination
        value=body();source,identity,mapped,key,destination,track=selected(value)
        play_after_download=value.get('play_after_download',False)
        if type(play_after_download) is not bool:raise ValueError('Choose whether to play this one track after downloading it.')
        validate_destination(mapped,destination['local_path'])
        target_state=prepare_target(destination['local_path'],mapped['local_root'])
        remote=remote_file(mapped,destination)
        token=secrets.token_urlsafe(32)
        with guard:
            for old in list(intents):
                if time.monotonic()-intents[old]['created']>120:intents.pop(old,None)
            while len(intents)>=128:intents.pop(next(iter(intents)))
            intents[token]={'created':time.monotonic(),'source':source,'track_id':identity,'binding':key,
                           'destination':destination,'target':target_state,'remote':remote,'play_after_download':play_after_download}
        from cloud_file_evidence import size_evidence
        return jsonify(confirmation_required=True,confirmation_token=token,title=str(track.get('title') or identity),
                       filename=destination['filename'],local_path=destination['local_path'],size=remote['size'],
                       play_after_download=play_after_download,
                       **size_evidence(track,remote))
    @app.post('/api/dropbox/download')
    def dropbox_download():
        from dropbox_download import download_file
        from cloud_attachments import validate_destination
        value=body()
        if value.get('confirm') is not True:raise ValueError('Confirm downloading this one track.')
        token=value.get('confirmation_token')
        with guard:intent=intents.pop(token,None) if isinstance(token,str) and len(token)<=128 else None
        if not intent or not 0<=time.monotonic()-intent['created']<=120:raise ValueError('Download confirmation expired. Choose the track again.')
        if ('play_after_download' in value and (type(value['play_after_download']) is not bool
                or value['play_after_download'] is not intent['play_after_download'])):
            raise ValueError('The playback choice changed. Confirm this track again.')
        source,identity,mapped,key,destination,track=selected(value)
        if (source,identity,key,destination)!=(intent['source'],intent['track_id'],intent['binding'],intent['destination']):raise ValueError('Download details changed. Confirm this track again.')
        validate_destination(mapped,destination['local_path'])
        # Revalidate metadata before opening content, including the current path.
        remote=remote_file(mapped,destination)
        if any(remote.get(k)!=intent['remote'].get(k) for k in ('id','rev','size','content_hash')):
            raise ValueError('Dropbox file details changed. Confirm this track again.')
        from dropbox_download import prepare_target
        if prepare_target(destination['local_path'],mapped['local_root'])!=intent['target']:
            raise ValueError('The download destination changed. Confirm this track again.')
        profile=owner.DATA.resolve();client=connected();generation=client.status()['connection_id']
        task_audio=context(source)[2]
        staging_roots=[row['root'] for row in provider_roots(include_unavailable=True)]
        last_check=[0.0]
        def validate(force=False):
            if owner.DATA.resolve()!=profile or connected().status().get('connection_id')!=generation:
                raise ValueError('Download connection or profile changed.')
            now=time.monotonic()
            if force or now-last_check[0]>=0.25:
                if context(source)[1]!=key:raise ValueError('Download mapping or source changed.')
                last_check[0]=now
        def work(progress):
            def checkpoint(amount,message):
                validate(force=amount>=99);progress(amount,message)
            validate(force=True)
            result=download_file(client,remote,destination['local_path'],mapped['local_root'],mapped['namespace'],
                                 validate=validate,progress=checkpoint,expected_target=intent['target'],
                                 staging_dir=profile/'dropbox-downloads',managed_root=mapped['managed_root'],
                                 excluded_roots=staging_roots)
            result.update(play_after_download=intent['play_after_download'],opened=False)
            from cloud_file_evidence import refresh_download
            try:result['local_evidence']=refresh_download(profile,source,identity,track,task_audio)
            except (OSError,ValueError,sqlite3.DatabaseError):result['local_evidence_refreshed']=False
            if intent['play_after_download']:
                try:
                    # Publication remains successful if cancellation arrived
                    # afterwards, but it must still prevent the separate launch.
                    progress(99,'Checking the approved track before playback')
                    validate(force=True)
                    validate_destination(mapped,destination['local_path'])
                    from dropbox_download import resident_file_identity,verify_downloaded_content
                    from track_playback import inspect_audio_details,open_audio
                    details=inspect_audio_details(track,context(source)[2])
                    target=Path(destination['local_path'])
                    fresh=resident_file_identity(target,mapped['local_root'],intent['target'])
                    if (result.get('local_path')!=str(target) or result.get('bytes')!=remote['size']
                            or not result.get('file_identity') or fresh!=result['file_identity']
                            or details['status']!='playable' or details['path']!=target):
                        raise ValueError('The downloaded track changed or is no longer available locally. Choose Play again.')
                    def playback_checkpoint():
                        validate()
                        progress(99,'Verifying the approved downloaded track before playback')
                    verify_downloaded_content(target,mapped['local_root'],intent['target'],fresh,
                                              remote['size'],remote['content_hash'],playback_checkpoint)
                    validate(force=True)
                    if resident_file_identity(target,mapped['local_root'],intent['target'])!=fresh:
                        raise ValueError('The downloaded track changed before playback. Choose Play again.')
                    progress(99,'Opening the approved downloaded track')
                    open_audio(target)
                    result['opened']=True
                except (OSError,ValueError,RuntimeError) as error:
                    result['playback_error']=str(error)
            return result
        job=owner.launch(work,'Downloading and playing one approved Dropbox track' if intent['play_after_download'] else 'Downloading one approved Dropbox track')
        return jsonify(job=job,source=source,track_id=identity,play_after_download=intent['play_after_download'])
