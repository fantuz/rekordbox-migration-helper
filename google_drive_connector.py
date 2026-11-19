"""Explicit Google Drive authorization, metadata checks and one-file downloads."""
import json
import logging
from pathlib import Path
import re
import secrets
import sqlite3
from threading import RLock
import time
from urllib.parse import parse_qs, unquote, urlsplit

from flask import jsonify, redirect, request

from collection_sources import resolve
from file_health import local_request, selected_source
from workbench_store import Store
import google_drive_files as files

STATES=('present','not_found','unmapped','ambiguous','unverified')
_connection_lock=RLock()


def connection(owner):
    from google_drive_auth import GoogleDriveConnection
    profile=owner.DATA.resolve()
    with _connection_lock:
        if getattr(owner,'_google_drive_profile',None)!=profile:
            owner.google_drive_connection=GoogleDriveConnection(owner)
            owner._google_drive_profile=profile
        return owner.google_drive_connection


def evidence_context(owner,source):
    """Identify cached evidence without remote requests or audio reads."""
    from cloud_file_evidence import provider_context
    return provider_context(owner,source,'google_drive_mapping',connection(owner),files)


class _CallbackLogFilter(logging.Filter):
    def filter(self,record):
        def redact(value):
            if not isinstance(value,str):return value
            def replace(match):
                target=match.group(1)
                return target+'?[redacted]' if unquote(target).endswith('/api/google-drive/callback') else match.group(0)
            return re.sub(r'([^\s\"]+)\?[^\s\"]*',replace,value)
        record.msg=redact(record.msg)
        if isinstance(record.args,tuple):record.args=tuple(redact(value) for value in record.args)
        return True


def register(owner):
    app=owner.app
    intents={};guard=RLock();authorization_errors={};running={};oauth_returns={}
    logging.getLogger('werkzeug').addFilter(_CallbackLogFilter())
    def connected():return connection(owner)
    def store():
        saved=Store(owner.DATA/'workbench-sidecar.sqlite3')
        with saved.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS google_drive_records (binding TEXT,source TEXT,track_id TEXT,payload TEXT,PRIMARY KEY(binding,source,track_id))')
            db.execute('CREATE TABLE IF NOT EXISTS google_drive_scans (binding TEXT,source TEXT,payload TEXT,PRIMARY KEY(binding,source))')
            db.execute("CREATE INDEX IF NOT EXISTS google_drive_records_status ON google_drive_records(binding,source,json_extract(payload,'$.status'))")
        return saved
    def local():
        if not local_request():raise ValueError('Use Google Drive from the local Workbench application.')
        origin_header=request.headers.get('Origin')
        if origin_header and origin_header.rstrip('/')!=request.host_url.rstrip('/'):
            raise ValueError('Use Google Drive from the local Workbench application.')
    def body():
        local();value=request.get_json(silent=True)
        if not isinstance(value,dict):raise ValueError('Provide a Google Drive request object.')
        return value
    def mapping():return store().setting('google_drive_mapping',None)
    def context(source):
        state=evidence_context(owner,source)
        return state['mapping'],state['key'],state['audio']
    def origin():
        local();parsed=urlsplit(request.host_url)
        if parsed.scheme!='http' or parsed.username or parsed.password:
            raise ValueError('Use the local HTTP Workbench address for Google authorization.')
        from cloud_oauth import authorization_origin
        return authorization_origin()
    def status():
        state=connected().status();value=mapping();account=state.get('account') or {}
        if value and value.get('account_id')!=account.get('account_id'):value=None
        return {**state,'account':{**account,'name':account.get('name') or account.get('display_name','')},
                'redirect_uri':origin()+'/api/google-drive/callback','roots':files.detected_roots(),
                'mapping':value,'credential_storage':{'available':state.get('secure_storage_available',False),
                'persistent':state.get('persistent',False)},
                'authorization_error':authorization_errors.get(str(owner.DATA.resolve()))}

    @app.after_request
    def private_google_drive_response(response):
        if request.path.startswith('/api/google-drive/'):
            response.headers['Cache-Control']='no-store'
            response.headers['Referrer-Policy']='no-referrer'
        return response

    @app.get('/api/google-drive/status')
    def google_drive_status():local();return jsonify(status())

    @app.post('/api/google-drive/configure')
    def google_drive_configure():
        value=body()
        connected().configure(value.get('client_id'),value.get('client_secret'),value.get('remember',False))
        return jsonify(status())

    @app.post('/api/google-drive/connect')
    def google_drive_connect():
        value=body();return_to=value.get('return_to','google-drive')
        if return_to not in ('google-drive','cloud-connect'):
            raise ValueError('Choose a valid Google connection return page.')
        result=connected().begin(origin());profile=str(owner.DATA.resolve())
        state=parse_qs(urlsplit(result['authorize_url']).query).get('state',[''])[0]
        with guard:oauth_returns[profile]={'state':state,'return_to':return_to,'created':time.monotonic()}
        authorization_errors.pop(profile,None)
        return jsonify(**result)

    @app.get('/api/google-drive/callback')
    def google_drive_callback():
        local();profile=str(owner.DATA.resolve());return_to='google-drive';state=request.args.get('state')
        with guard:
            pending=oauth_returns.get(profile)
            if (pending and isinstance(state,str) and secrets.compare_digest(state,pending['state'])
                    and 0<=time.monotonic()-pending['created']<=600):
                return_to=pending['return_to'];oauth_returns.pop(profile,None)
        try:
            connected().callback(state,request.args.get('code'),request.args.get('error'),callback_origin=request.host_url.rstrip('/'))
            authorization_errors.pop(profile,None)
        except ValueError as error:authorization_errors[profile]=str(error)
        return redirect('/#'+return_to,code=303)

    @app.post('/api/google-drive/disconnect')
    def google_drive_disconnect():
        body();connected().disconnect()
        with guard:intents.clear();oauth_returns.pop(str(owner.DATA.resolve()),None)
        return jsonify(status())

    @app.get('/api/google-drive/folders')
    def google_drive_folders():
        local()
        if request.headers.get('X-Workbench-Token')!=owner.TOKEN:
            raise ValueError('Reload the local page before browsing Google Drive folders.')
        return jsonify(files.browse_folders(connected(),request.args.get('parent','root'),request.args.get('page_token')))

    @app.post('/api/google-drive/mapping')
    def google_drive_mapping():
        body()
        raise ValueError('Verify and attach this Google Drive folder through Cloud connections.')

    @app.post('/api/google-drive/check')
    def google_drive_check():
        value=body();source=selected_source(value.get('source'));snapshot=resolve(owner,source)
        if len(snapshot['tracks'])>250000 or len({str(t['id']) for t in snapshot['tracks']})!=len(snapshot['tracks']):
            raise ValueError('Choose a library with at most 250000 unique track IDs.')
        mapped,key,audio=context(source);profile=owner.DATA.resolve();identity=(profile,source,key)
        task_store=store();client=connected()
        def work(progress):
            def checkpoint(amount,message):
                if owner.DATA.resolve()!=profile or context(source)[1]!=key:
                    raise ValueError('Google Drive connection, source or attachment changed. Check metadata again.')
                progress(amount,message)
            entries,complete=files.inventory(client,mapped,checkpoint);rows=[]
            for i,track in enumerate(snapshot['tracks']):
                if i%100==0:checkpoint(70+25*i/max(1,len(snapshot['tracks'])),'Matching library paths with Google Drive metadata')
                destination=files.target(track,mapped,audio)
                remote,state=files.lookup(entries,destination['relative_path']) if destination else (None,'unmapped')
                if state=='not_found' and not complete:state='unverified'
                rows.append({'track_id':str(track['id']),'title':str(track.get('title') or ''),'artist':str(track.get('artist') or ''),
                             'status':state,**(destination or {}),'size':int(remote['size']) if remote and remote.get('size') is not None else None,'remote':remote})
            checkpoint(98,'Saving Google Drive metadata evidence');checked=time.time()
            with task_store.connection() as db:
                db.execute('DELETE FROM google_drive_records WHERE binding=? AND source=?',(key,source))
                db.executemany('INSERT INTO google_drive_records VALUES (?,?,?,?)',[(key,source,row['track_id'],json.dumps(row)) for row in rows])
                db.execute('INSERT OR REPLACE INTO google_drive_scans VALUES (?,?,?)',(key,source,json.dumps({'checked_at':checked,'complete':complete,'tracks':len(rows)})))
            return {'checked':len(rows),'complete':complete,'audio_contents_read':False,'downloads':0}
        def finished(_state):
            with guard:running.pop(identity,None)
        with guard:
            if identity in running:return jsonify(job=running[identity],source=source)
            running[identity]=None
            try:job=owner.launch(work,'Checking Google Drive metadata',on_finished=finished)
            except Exception:running.pop(identity,None);raise
            if identity in running:running[identity]=job
        return jsonify(job=job,source=source)

    @app.get('/api/google-drive/files')
    def google_drive_rows():
        local();source=selected_source(request.args.get('source'))
        mapped,key,_=context(source);state=request.args.get('status','all');query=request.args.get('q','').strip().casefold()
        try:offset=int(request.args.get('offset',0))
        except (TypeError,ValueError):raise ValueError('Choose a valid Google Drive page.') from None
        if state not in ('all',*STATES) or not 0<=offset<=250000 or len(query)>200:
            raise ValueError('Choose a valid Google Drive file filter.')
        where='binding=? AND source=?';params=[key,source]
        if state!='all':where+=" AND json_extract(payload,'$.status')=?";params.append(state)
        if query:
            search=" || ' ' || ".join("coalesce(json_extract(payload,'$."+field+"'),'')" for field in ('track_id','title','artist','filename'))
            where+=' AND instr(google_drive_casefold('+search+'),?)>0';params.append(query)
        counts={name:0 for name in STATES}
        with store().connection() as db:
            db.create_function('google_drive_casefold',1,lambda value:str(value or '').casefold(),deterministic=True)
            for row in db.execute("SELECT json_extract(payload,'$.status'),count(*) FROM google_drive_records WHERE binding=? AND source=? GROUP BY json_extract(payload,'$.status')",(key,source)):
                if row[0] in counts:counts[row[0]]=row[1]
            total=db.execute('SELECT count(*) FROM google_drive_records WHERE '+where,params).fetchone()[0]
            order="google_drive_casefold(json_extract(payload,'$.artist')),google_drive_casefold(json_extract(payload,'$.title')),track_id"
            values=[json.loads(row[0]) for row in db.execute('SELECT payload FROM google_drive_records WHERE '+where+' ORDER BY '+order+' LIMIT 50 OFFSET ?',(*params,offset))]
            scan=db.execute('SELECT payload FROM google_drive_scans WHERE binding=? AND source=?',(key,source)).fetchone()
        from dropbox_files import local_available
        from media import cloud_placeholder
        from google_drive_download import metadata_details
        for row in values:
            remote=row.pop('remote',None);path=row.get('local_path')
            row['local_available']=bool(path and local_available(path));absent=False
            if not path:row['local_state']='unmapped'
            else:
                try:
                    info=Path(path).lstat();row['local_state']='online_only' if cloud_placeholder(info) else 'present'
                except FileNotFoundError:absent=True;row['local_state']='not_local'
                except OSError:row['local_state']='unverified'
            try:eligible=bool(remote and metadata_details(remote))
            except ValueError:eligible=False
            row['downloadable']=bool(eligible and absent and row['status']=='present')
        return jsonify(rows=values,total=total,offset=offset,counts=counts,**(json.loads(scan[0]) if scan else {}))

    def selected(value):
        source=selected_source(value.get('source'));identity=value.get('track_id')
        if not isinstance(identity,str) or not 1<=len(identity)<=200:raise ValueError('Choose one library track.')
        snapshot=resolve(owner,source);track=next((track for track in snapshot['tracks'] if str(track['id'])==identity),None)
        if not track:raise ValueError('This track is not in the selected library.')
        mapped,key,audio=context(source);destination=files.target(track,mapped,audio)
        if not destination:raise ValueError('This track has no path inside the attached Google Drive location.')
        from cloud_attachments import validate_destination
        validate_destination(mapped,destination['local_path'])
        return source,identity,mapped,key,destination,track

    @app.post('/api/google-drive/download/prepare')
    def google_drive_prepare():
        from google_drive_download import metadata_details,prepare_target
        value=body();source,identity,mapped,key,destination,track=selected(value)
        target_state=prepare_target(destination['local_path'],mapped['local_root'])
        remote=files.resolve_file(connected(),mapped,destination['relative_path']);details=metadata_details(remote)
        token=secrets.token_urlsafe(32)
        with guard:
            for old in list(intents):
                if time.monotonic()-intents[old]['created']>120:intents.pop(old,None)
            while len(intents)>=128:intents.pop(next(iter(intents)))
            intents[token]={'created':time.monotonic(),'source':source,'track_id':identity,'binding':key,
                            'destination':destination,'target':target_state,'remote':remote}
        return jsonify(confirmation_required=True,confirmation_token=token,title=str(track.get('title') or identity),
                       filename=destination['filename'],local_path=destination['local_path'],size=details[2])

    @app.post('/api/google-drive/download')
    def google_drive_download():
        from google_drive_download import download_file,metadata_fingerprint,prepare_target
        value=body()
        if value.get('confirm') is not True:raise ValueError('Confirm downloading this one track.')
        token=value.get('confirmation_token')
        with guard:intent=intents.pop(token,None) if isinstance(token,str) and len(token)<=128 else None
        if not intent or not 0<=time.monotonic()-intent['created']<=120:
            raise ValueError('Download confirmation expired. Choose the track again.')
        source,identity,mapped,key,destination,track=selected(value)
        if (source,identity,key,destination)!=(intent['source'],intent['track_id'],intent['binding'],intent['destination']):
            raise ValueError('Download details changed. Confirm this track again.')
        client=connected();remote=files.resolve_file(client,mapped,destination['relative_path'])
        fingerprint=metadata_fingerprint(remote)
        if fingerprint!=metadata_fingerprint(intent['remote']):
            raise ValueError('Google Drive file details changed. Confirm this track again.')
        if prepare_target(destination['local_path'],mapped['local_root'])!=intent['target']:
            raise ValueError('The download destination changed. Confirm this track again.')
        profile=owner.DATA.resolve();generation=client.status()['connection_id'];last_check=[0.0]
        task_audio=context(source)[2]
        def validate(force=False):
            if owner.DATA.resolve()!=profile or connected().status().get('connection_id')!=generation:
                raise ValueError('Download connection or profile changed.')
            now=time.monotonic()
            if force or now-last_check[0]>=0.25:
                if context(source)[1]!=key:raise ValueError('Download attachment or source changed.')
                from cloud_attachments import validate_destination
                validate_destination(mapped,destination['local_path'])
                last_check[0]=now
        def work(progress):
            def checkpoint(amount,message):
                validate(force=amount>=99)
                if amount>=99 and metadata_fingerprint(files.resolve_file(client,mapped,destination['relative_path']))!=fingerprint:
                    raise ValueError('The Google Drive file location changed during download.')
                progress(amount,message)
            validate(force=True)
            from cloud_locations import provider_roots
            excluded=[row['root'] for row in provider_roots(include_unavailable=True)]
            result=download_file(client,remote,destination['local_path'],mapped['local_root'],
                                 validate=validate,progress=checkpoint,expected_target=intent['target'],
                                 staging_dir=profile/'cloud-downloads',managed_root=mapped['managed_root'],excluded_roots=excluded)
            from cloud_file_evidence import refresh_download
            try:result['local_evidence']=refresh_download(profile,source,identity,track,task_audio)
            except (OSError,ValueError,sqlite3.DatabaseError):result['local_evidence_refreshed']=False
            return result
        job=owner.launch(work,'Downloading one approved Google Drive track')
        return jsonify(job=job,source=source,track_id=identity)
