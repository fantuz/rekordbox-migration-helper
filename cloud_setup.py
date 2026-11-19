"""Guided, explicit account/source/local-folder attachment for cloud providers.

Opening this page reads local settings and discovery evidence only.  Remote
listing happens on Browse/Preview, and never downloads music or changes the
provider desktop application's synchronization policy.
"""
import json
from pathlib import Path
import platform
import re
import secrets
from threading import RLock
import time

from flask import jsonify,request
import audio_paths
from cloud_attachments import digest,local_presence
from cloud_locations import provider_roots
from collection_sources import resolve
from file_health import local_request,selected_source
from workbench_store import Store,encoded

PROVIDERS=('dropbox','google_drive')
MAPPING_KEYS={'dropbox':'dropbox_mapping','google_drive':'google_drive_mapping'}
PREVIEW_SECONDS=120


def _provider(owner,name):
    if name=='dropbox':
        import dropbox_connector as connector
        import dropbox_files as files
    elif name=='google_drive':
        import google_drive_connector as connector
        import google_drive_files as files
    else:raise ValueError('Choose Dropbox or Google Drive.')
    return connector.connection(owner),files


def _stamp(owner,source,*,saved=None,db=None):
    source=selected_source(source)
    if source.startswith('snapshot:'):
        if db is not None:row=db.execute('SELECT digest FROM snapshots WHERE id=?',(source[9:],)).fetchone()
        else:
            saved=saved or Store(owner.DATA/'workbench-sidecar.sqlite3')
            with saved.connection() as connection:
                row=connection.execute('SELECT digest FROM snapshots WHERE id=?',(source[9:],)).fetchone()
        if not row:raise ValueError('Choose an existing saved collection.')
        stamp=row['digest']
    else:
        folder=owner.DATA/'analyzers'/source[8:]
        if folder.is_symlink() or folder.is_junction():raise ValueError('Choose an ordinary saved source capture.')
        metadata=folder/'comparison.json'
        if not metadata.is_file():metadata=folder/'metadata.json'
        values=[]
        for path in (metadata,folder/'report.json'):
            if not path.is_file() or path.is_symlink():raise ValueError('Choose an existing saved source capture.')
            info=path.stat();values.append((info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns))
        stamp=digest(values)
    return stamp


def _source(owner,source):
    stamp=_stamp(owner,source)
    snapshot=resolve(owner,source)
    tracks=snapshot.get('tracks',[])
    if not isinstance(snapshot.get('scope_key'),str) or not snapshot['scope_key']:
        raise ValueError('Choose a collection with a saved source identity.')
    if len(tracks)>250000 or len({str(t['id']) for t in tracks})!=len(tracks):
        raise ValueError('Choose a collection with at most 250000 unique track IDs.')
    return snapshot,stamp


def _configuration(value):
    provider=value.get('provider')
    if provider not in PROVIDERS:raise ValueError('Choose Dropbox or Google Drive.')
    mode=value.get('sync_mode','selected')
    if mode not in ('selected','all') or provider=='google_drive' and mode!='selected':
        raise ValueError('Google Drive uses selected-file synchronization; choose a supported synchronization method.')
    arrangement=value.get('arrangement','own_google' if provider=='google_drive' else 'personal')
    choices=('own_google',) if provider=='google_drive' else ('personal','own_team','cloud_option','professional')
    if arrangement not in choices:raise ValueError('Choose the account arrangement you use in Rekordbox.')
    desktop=value.get('desktop_mode','unknown')
    if desktop not in ('unknown','not_installed','stream','mirror','online_only','local','selective'):
        raise ValueError('Choose a supported desktop availability setting.')
    default=value.get('default_upload','unknown')
    if default not in ('unknown',*PROVIDERS):raise ValueError('Choose the default upload provider recorded in Rekordbox.')
    return {'provider':provider,'arrangement':arrangement,'sync_mode':mode,
            'desktop_mode':desktop,'default_upload':default,'declared_by_user':True,
            'changes_provider_settings':False}


def _mapping(owner,client,files,value,configuration):
    provider=configuration['provider']
    if provider=='dropbox':
        mapping=files.mapping_record(client,value.get('local_root'),value.get('remote_root',''),
            value.get('namespace') or None,owner=owner,
            sync_mode=configuration['sync_mode'],recorded_root=value.get('recorded_root'))
    else:
        mapping=files.mapping_record(client,value.get('local_root'),value.get('remote_folder_id') or value.get('remote_root') or 'root',
            owner=owner,sync_mode=configuration['sync_mode'],recorded_root=value.get('recorded_root'))
    return {**mapping,'provider':provider,'sync_mode':configuration['sync_mode']}


def _remote_identity(client,provider,mapping):
    if provider=='google_drive':
        import google_drive_files
        folder=google_drive_files._folder(client,mapping['remote_folder_id'])
        return folder['id']
    root={'.tag':'namespace_id','namespace_id':mapping['namespace']}
    if not mapping['remote_root']:
        client.rpc('files/list_folder',{'path':'','limit':1,'recursive':False},path_root=root)
        return 'namespace:'+mapping['namespace']
    folder=client.rpc('files/get_metadata',{'path':mapping['remote_root']},path_root=root)
    if folder.get('.tag')!='folder' or not isinstance(folder.get('id'),str) or not folder['id']:
        raise ValueError('Choose an accessible cloud folder with a stable identity.')
    return folder['id']


def _audio_proposal(owner,snapshot,mapping,saved):
    previous=audio_paths.mappings_for(saved,snapshot)
    prefix=mapping.get('recorded_root')
    if not prefix:return previous,None
    proposed=audio_paths.validate([{'recorded_root':prefix,'local_root':mapping['local_root']}],audio_paths.allowed_roots(owner))[0]
    # An unchanged captured path already under this directory needs no alias.
    def prefix_key(value):
        return value.casefold() if re.match(r'^[A-Za-z]:',value) else value
    recorded=audio_paths.recorded(mapping['local_root'])
    if recorded and prefix_key(recorded)==prefix_key(prefix):return previous,None
    for existing in previous:
        if prefix_key(existing['recorded_root'])==prefix_key(proposed['recorded_root']):
            same=(existing.get('local_root')==proposed['local_root'] and
                  (existing.get('device'),existing.get('inode'))==(proposed['device'],proposed['inode']))
            if not same:
                raise ValueError('This recorded folder already has a different Audio folders mapping. Review it before attaching another destination.')
            return previous,None
    if len(previous)>=16:raise ValueError('Review existing Audio folders mappings before adding another one.')
    combined=[*previous,proposed]
    combined.sort(key=lambda row:(-len(row['recorded_root']),row['recorded_root']))
    return combined,proposed


def host_platform():
    """Coarse host context only; never a filesystem authorization signal."""
    return {'windows':'windows','darwin':'mac','linux':'linux'}.get(platform.system().lower(),'unknown')


def register(owner):
    app=owner.app;guard=RLock();previews={}
    def store():return Store(owner.DATA/'workbench-sidecar.sqlite3')
    def local():
        if not local_request():raise ValueError('Connect cloud accounts from the local Workbench application.')
        origin=request.headers.get('Origin')
        if origin and origin.rstrip('/')!=request.host_url.rstrip('/'):
            raise ValueError('Connect cloud accounts from the local Workbench application.')
    def body():
        local();value=request.get_json(silent=True)
        if not isinstance(value,dict):raise ValueError('Provide a cloud setup request object.')
        return value

    @app.after_request
    def private_cloud_setup_response(response):
        if request.path.startswith('/api/cloud-setup/'):
            response.headers['Cache-Control']='no-store';response.headers['Referrer-Policy']='no-referrer'
        return response

    @app.get('/api/cloud-setup/status')
    def cloud_setup_status():
        local();saved=store();providers={};attachments={};settings={}
        roots=provider_roots(include_unavailable=True)
        from cloud_oauth import authorization_origin
        origin=authorization_origin()
        source=request.args.get('source');snapshot=None;context=None
        if source:snapshot,_=_source(owner,source)
        for provider in PROVIDERS:
            client,files=_provider(owner,provider);state=client.status()
            mapping=saved.setting(MAPPING_KEYS[provider],None);active=False;error=None
            if mapping:
                try:
                    files.validate_mapping(client,mapping)
                    if source and not mapping.get('source'):
                        raise ValueError('Preview and confirm this existing location for the selected collection.')
                    if source and mapping.get('source')!=source:
                        raise ValueError('This location is attached to another collection. Preview it for the selected collection.')
                    if snapshot and mapping.get('scope_key') not in (None,snapshot['scope_key']):
                        raise ValueError('The attached collection identity changed. Preview this location again.')
                    active=True
                except ValueError as problem:error=str(problem)
            attachments[provider]=mapping
            settings[provider]=saved.setting('cloud_setup:'+provider,None)
            account=state.get('account') or {}
            callback='/api/dropbox/callback' if provider=='dropbox' else '/api/google-drive/callback'
            providers[provider]={**state,'account':{**account,'name':account.get('name') or account.get('display_name','')},
                                 'redirect_uri':origin+callback,
                                 'credential_storage':{'available':bool(state.get('secure_storage_available',False)),
                                                       'persistent':bool(state.get('persistent',False))},
                                 'mapping':mapping if active else None,
                                 'attachment_active':active,'attachment_error':error}
        if source:
            examples=[]
            for track in snapshot['tracks'][:5]:
                path=next((track.get(k) for k in audio_paths.FIELDS if track.get(k)),'')
                examples.append({'track_id':str(track['id']),'title':str(track.get('title') or ''),'recorded_path':path})
            try:
                from cloud_candidates import suggestions
                candidates=suggestions(snapshot,roots)
            except ImportError:candidates=[]
            context={'id':source,'label':str(snapshot.get('label') or source),'tracks':len(snapshot['tracks']),
                     'examples':examples,'suggestions':candidates,
                     'default_upload':saved.setting('cloud_default_upload:'+snapshot['scope_key'],'unknown')}
            for provider,configuration in settings.items():
                if configuration and configuration.get('source')==source:
                    settings[provider]={**configuration,'default_upload':context['default_upload']}
        return jsonify(providers=providers,roots=roots,attachments=attachments,settings=settings,source=context,host_platform=host_platform())

    @app.post('/api/cloud-setup/folders')
    def cloud_setup_folders():
        value=body();provider=value.get('provider');client,files=_provider(owner,provider)
        state=client.status()
        if not state.get('connected'):raise ValueError('Connect the selected cloud account before browsing its folders.')
        token=value.get('page_token')
        if token is not None and (not isinstance(token,str) or not token or len(token)>8192):
            raise ValueError('Choose a valid cloud folder page.')
        if provider=='google_drive':
            return jsonify(files.browse_folders(client,value.get('remote_folder_id') or 'root',token))
        namespace=value.get('namespace') or (state.get('account') or {}).get('root_namespace_id')
        if not isinstance(namespace,str) or not re.fullmatch(r'\d{1,40}',namespace):raise ValueError('Choose a valid Dropbox namespace.')
        path=files.remote_path(value.get('remote_root',''));root={'.tag':'namespace_id','namespace_id':namespace}
        if token:result=client.rpc('files/list_folder/continue',{'cursor':token},path_root=root)
        else:result=client.rpc('files/list_folder',{'path':path,'recursive':False,'include_deleted':False,'limit':200},path_root=root)
        if not isinstance(result,dict) or not isinstance(result.get('entries'),list) or type(result.get('has_more')) is not bool:
            raise ValueError('Dropbox returned an invalid folder listing.')
        rows=[]
        for entry in result['entries']:
            if not isinstance(entry,dict):raise ValueError('Dropbox returned an invalid folder entry.')
            if entry.get('.tag')!='folder':continue
            remote=entry.get('path_display') or entry.get('path_lower')
            if not isinstance(remote,str) or not isinstance(entry.get('id'),str):raise ValueError('Dropbox returned an invalid folder.')
            remote=files.remote_path(remote)
            if path and not files.path_key(remote).startswith(files.path_key(path)+'/'):
                raise ValueError('Dropbox returned a folder outside the selected location.')
            rows.append({'id':entry['id'],'name':str(entry.get('name') or remote.rsplit('/',1)[-1]),'path':remote})
        next_token=result.get('cursor') if result['has_more'] else None
        return jsonify(folder={'id':'namespace:'+namespace if not path else path,'name':path.rsplit('/',1)[-1] if path else 'Dropbox','path':path},
                       rows=rows,next_page_token=next_token,has_more=result['has_more'])

    @app.post('/api/cloud-setup/preview')
    def cloud_setup_preview():
        value=body();configuration=_configuration(value);provider=configuration['provider']
        source=selected_source(value.get('source'));snapshot,stamp=_source(owner,source)
        client,files=_provider(owner,provider);mapping=_mapping(owner,client,files,value,configuration)
        remote_identity=_remote_identity(client,provider,mapping)
        saved=store();before_audio=audio_paths.mappings_for(saved,snapshot)
        after_audio,audio_proposal=_audio_proposal(owner,snapshot,mapping,saved)
        profile=owner.DATA.resolve();generation=client.status()['connection_id']
        previous_mapping=digest(saved.setting(MAPPING_KEYS[provider],None))
        audio_signature=audio_paths.signature(before_audio)
        def checkpoint():
            if owner.DATA.resolve()!=profile:raise ValueError('The Workbench profile changed. Preview this attachment again.')
            fresh,_=_provider(owner,provider)
            if fresh.status().get('connection_id')!=generation:raise ValueError('The cloud account changed. Preview this attachment again.')
            files.validate_mapping(client,mapping)
            current_stamp=_stamp(owner,source,saved=saved)
            if current_stamp!=stamp or audio_paths.signature(audio_paths.mappings_for(saved,snapshot))!=audio_signature:
                raise ValueError('The collection or Audio folders mappings changed. Preview this attachment again.')
            if digest(saved.setting(MAPPING_KEYS[provider],None))!=previous_mapping:
                raise ValueError('Another cloud attachment changed. Preview this attachment again.')
        def work(progress):
            def update(amount,message):checkpoint();progress(amount,message)
            entries,complete=files.inventory(client,mapping,update)
            counts={name:0 for name in ('matched','unmapped','ambiguous','not_found','unverified')}
            matched_examples=[];other_examples=[];warnings=[]
            for index,track in enumerate(snapshot['tracks']):
                if index%100==0:update(70+25*index/max(1,len(snapshot['tracks'])),'Comparing collection paths with cloud metadata')
                destination=files.target(track,mapping,after_audio)
                if not destination:remote=None;state='unmapped'
                elif provider=='google_drive':
                    remote,state=files.lookup(entries,destination['relative_path'])
                    if state=='present':state='matched'
                    elif state=='not_found' and not complete:state='unverified'
                else:
                    remote=entries.get(files.path_key(destination['remote_path']))
                    state='matched' if remote else 'not_found' if complete else 'unverified'
                counts[state]+=1
                expected=track.get('size');remote_size=remote.get('size') if remote else None
                if isinstance(remote_size,str) and remote_size.isdigit():remote_size=int(remote_size)
                if state=='matched' and type(expected) is int and type(remote_size) is int and expected!=remote_size and len(warnings)<20:
                    warnings.append({'track_id':str(track['id']),'recorded_size':expected,'remote_size':remote_size,
                                     'reason':'Recorded size differs from current cloud metadata.'})
                examples=matched_examples if state=='matched' else other_examples
                if len(examples)<8:
                    recorded=next((track.get(k) for k in audio_paths.FIELDS if track.get(k)),'')
                    examples.append({'track_id':str(track['id']),'title':str(track.get('title') or ''),'recorded_path':recorded,
                        **(destination or {}),'remote_size':remote_size,'status':state,'content_verified':False})
                    if destination:examples[-1].update(local_presence(destination['local_path']))
            update(98,'Preparing the explicit cloud attachment confirmation')
            examples=matched_examples[:6]
            examples+=other_examples[:8-len(examples)]
            if len(examples)<8:examples+=matched_examples[6:6+8-len(examples)]
            attachable=bool(complete and counts['matched'] and not counts['ambiguous'])
            token=None
            if attachable:
                token=secrets.token_urlsafe(32)
                with guard:
                    for old in list(previews):
                        if time.monotonic()-previews[old]['created']>PREVIEW_SECONDS:previews.pop(old,None)
                    while len(previews)>=64:previews.pop(next(iter(previews)))
                    previews[token]={'created':time.monotonic(),'profile':profile,'provider':provider,'source':source,'stamp':stamp,
                        'generation':generation,'mapping':{**mapping,'source':source,'scope_key':snapshot.get('scope_key',''),
                                                        'remote_folder_identity':remote_identity},
                        'previous_mapping':previous_mapping,'before_audio':audio_signature,'after_audio':after_audio,
                        'audio_proposal':audio_proposal,'configuration':configuration,'remote_identity':remote_identity,
                        'matched':counts['matched']}
            reason=None if attachable else ('The selected folders could not be verified against this collection. Choose matching folders and preview again.')
            return {'preview_token':token,'expires_in':PREVIEW_SECONDS,'provider':provider,'source':source,
                'attachable':attachable,'complete':complete,'total':len(snapshot['tracks']),**counts,'counts':counts,
                'mapping':mapping,'proposed_mapping':mapping,'configuration':configuration,'audio_mapping':audio_proposal,
                'examples':examples,'metadata_warnings':warnings,'reason':reason,'content_verified':False,'downloads':0}
        job=owner.launch(work,'Verifying the cloud account and folder attachment')
        return jsonify(job=job)

    @app.post('/api/cloud-setup/attach')
    def cloud_setup_attach():
        value=body()
        if value.get('confirm') is not True:raise ValueError('Confirm attaching the previewed account and folders.')
        token=value.get('preview_token')
        with guard:intent=previews.pop(token,None) if isinstance(token,str) and len(token)<=128 else None
        if not intent or not 0<=time.monotonic()-intent['created']<=PREVIEW_SECONDS:
            raise ValueError('The attachment preview expired. Preview the folders again.')
        provider=intent['provider'];source=intent['source'];mapping=intent['mapping']
        if owner.DATA.resolve()!=intent['profile']:raise ValueError('The Workbench profile changed. Preview the folders again.')
        client,files=_provider(owner,provider);state=files.validate_mapping(client,mapping)
        if state.get('connection_id')!=intent['generation']:raise ValueError('The connected account changed. Preview the folders again.')
        snapshot,stamp=_source(owner,source)
        if stamp!=intent['stamp']:raise ValueError('The selected collection changed. Preview the folders again.')
        if _remote_identity(client,provider,mapping)!=intent['remote_identity']:
            raise ValueError('The cloud folder identity changed. Preview the folders again.')
        files.validate_mapping(client,mapping)
        saved=Store(intent['profile']/'workbench-sidecar.sqlite3');audio_key='audio_paths:'+str(snapshot.get('scope_key',''));mapping_key=MAPPING_KEYS[provider]
        with saved.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            def setting(name,default):
                row=db.execute('SELECT value FROM settings WHERE name=?',(name,)).fetchone()
                return json.loads(row[0]) if row else default
            if (audio_paths.signature(setting(audio_key,[]))!=intent['before_audio'] or
                    digest(setting(mapping_key,None))!=intent['previous_mapping']):
                raise ValueError('The attachment or Audio folders mapping changed. Preview the folders again.')
            fresh,_=_provider(owner,provider)
            if fresh.status().get('connection_id')!=intent['generation'] or owner.DATA.resolve()!=intent['profile']:
                raise ValueError('The cloud connection changed. Preview the folders again.')
            fresh_stamp=_stamp(owner,source,db=db)
            if fresh_stamp!=stamp:raise ValueError('The collection changed. Preview the folders again.')
            config={**intent['configuration'],'source':source,'matched_paths':intent['matched'],'attached_at':time.time(),
                    'audio_mapping_added':intent['audio_proposal']}
            rows=[(mapping_key,mapping),('cloud_setup:'+provider,config)]
            if intent['audio_proposal']:rows.append((audio_key,intent['after_audio']))
            if config['default_upload']!='unknown':
                rows.append(('cloud_default_upload:'+snapshot['scope_key'],config['default_upload']))
            for key,payload in rows:
                db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(key,encoded(payload)))
        return jsonify(provider=provider,attachment=mapping,configuration=config,
                       audio_mapping_applied=bool(intent['audio_proposal']))

    @app.post('/api/cloud-setup/detach')
    def cloud_setup_detach():
        value=body();provider=value.get('provider')
        if provider not in PROVIDERS:raise ValueError('Choose the cloud attachment to remove.')
        saved=store();configuration=saved.setting('cloud_setup:'+provider,None)
        with saved.connection() as db:
            db.execute('DELETE FROM settings WHERE name IN (?,?)',(MAPPING_KEYS[provider],'cloud_setup:'+provider))
        with guard:
            for token in list(previews):
                if previews[token]['provider']==provider:previews.pop(token,None)
        return jsonify(provider=provider,detached=True,files_deleted=0,connection_disconnected=False,
                       audio_mapping_retained=bool(configuration and configuration.get('audio_mapping_added')))
