"""Open a captured audio path through the local desktop's default association."""
import ipaddress
import os
from pathlib import Path
import re
import subprocess
import sys
import stat
import secrets
import time
from threading import Thread, RLock
from urllib.parse import unquote,urlsplit

from flask import jsonify,request
from workbench_store import Store

AUDIO_EXTENSIONS={'.mp3','.flac','.wav','.wave','.aif','.aiff','.aifc','.m4a','.aac','.ogg','.opus','.alac','.wma'}


def recorded_path(value):
    if not isinstance(value,str) or not value or any(ord(c)<32 for c in value):return None
    if value.lower().startswith('file:'):
        try:parsed=urlsplit(value)
        except ValueError:return None
        if parsed.netloc.lower() not in ('','localhost') or parsed.query or parsed.fragment:return None
        value=unquote(parsed.path)
        if os.name=='nt' and re.match(r'^/[a-zA-Z]:/',value):value=value[1:]
    elif not (value.startswith('/') or re.match(r'^[a-zA-Z]:[\\/]',value)):return None
    if any(ord(c)<32 for c in value) or value.startswith(('//','\\\\')):return None
    path=Path(value)
    if not path.is_absolute() or '..' in path.parts:return None
    if os.name=='nt' and ':' in str(path)[2:]:return None  # No alternate data streams.
    if path.suffix.lower() not in AUDIO_EXTENSIONS:return None
    return path


def _located_candidates(track, mappings=None):
    from audio_paths import mapped_path,mapping_applies
    for key in ('current_path','xml_location','original_path'):
        value=track.get(key)
        if not value:continue
        # A replaced/disconnected mapped volume must not fall back to another
        # file at the recorded POSIX location and bypass the volume identity.
        if mapping_applies(value,mappings):
            yield mapped_path(value,mappings),'mapped'
        else:
            yield recorded_path(value),'current' if key=='current_path' else 'alternate'


def available_audio(track, mappings=None):
    """Only locally accessible audio; never authorize opening a cloud placeholder."""
    return inspect_audio_details(track, mappings)['path']



def inspect_audio(track, mappings=None):
    """Classify recorded locations without attempting to decode or play audio.

    The legacy API state 'playable' means a nonempty, readable, regular
    audio-suffixed file was found (shown as Accessible in the UI), not
    that the OS association or decoder is guaranteed to work. Missing means
    the parent directory is reachable and that particular file is absent.
    """
    result=inspect_audio_details(track,mappings)
    return result['status'],result['path']


def inspect_audio_details(track, mappings=None, roots=None):
    """Filesystem attributes only. No audio open, decoding, daemon or cloud API."""
    from cloud_file_status import provider_context,track_providers,path_providers,provider_mask,captured_filename
    from media import cloud_placeholder
    result={'status':'unverified','path':None,'open_candidate':None,'providers':0,
            'provider_checked':True,'provider_evidence':[],'cloud_state':'unknown',
            'logical_size':None,'observed_location':None,'filename':'','playback_cloud':False,'cloud_openable':False}
    if not isinstance(track,dict):return result
    roots=provider_context() if roots is None else roots
    matches=track_providers(track,mappings,roots)
    result.update(providers=provider_mask(matches),provider_evidence=[kind+':'+reason for kind,reason in sorted(matches.items())],filename=captured_filename(track))
    seen=set()
    evidence=[]
    placeholders=[]
    for path,location in _located_candidates(track,mappings):
        if path is None:
            evidence.append('unverified')
            continue
        normalized=str(path)
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            # Check the leaf before resolving it. Cloud reparse points are not
            # evidence of resident audio even when they expose a logical size.
            info=path.lstat()
            if stat.S_ISREG(info.st_mode) and cloud_placeholder(info):
                placeholders.append((path,info,location));continue
            target=path.resolve(strict=True)
            info=target.stat()
            if target.suffix.lower() not in AUDIO_EXTENSIONS or not stat.S_ISREG(info.st_mode):
                evidence.append('unverified')
            elif cloud_placeholder(info):
                placeholders.append((target,info,location))
            elif info.st_size==0:
                evidence.append('unverified')
            elif os.access(target,os.R_OK):
                result.update(status='playable',path=target,open_candidate=target,cloud_state='local',
                              logical_size=info.st_size,observed_location=location,filename=target.name,
                              playback_cloud=bool(path_providers(target,roots)))
                result['cloud_openable']=result['playback_cloud']
                return result
            else:
                evidence.append('inaccessible')
        except FileNotFoundError:
            try:
                # An unmounted drive or unavailable folder is not proof that
                # an audio recording has been deleted.
                parent=path.parent
                if path_providers(path,roots):
                    # Selective sync can leave no local placeholder at all.
                    evidence.append('unverified')
                elif parent.is_dir() and os.access(parent,os.X_OK):
                    evidence.append('missing')
                else:
                    evidence.append('unverified')
            except (OSError,ValueError,RuntimeError):
                evidence.append('unverified')
        except PermissionError:
            evidence.append('inaccessible')
        except (OSError,ValueError,RuntimeError):
            evidence.append('unverified')
    if placeholders:
        path,info,location=placeholders[0]
        result.update(open_candidate=path,cloud_state='online_only',logical_size=info.st_size,
                      observed_location=location,filename=path.name,playback_cloud=True,cloud_openable=True)
        return result
    if 'inaccessible' in evidence:result['status']='inaccessible'
    elif 'unverified' not in evidence and evidence:result['status']='missing'
    result['cloud_state']='not_local' if matches else 'unknown'
    return result


def open_audio(path):
    # Only server-resolved, existing audio paths reach this boundary. Never use a shell.
    try:
        if sys.platform=='win32':
            os.startfile(str(path),'open')
        else:
            command=['/usr/bin/open',str(path)] if sys.platform=='darwin' else ['xdg-open',str(path)]
            child=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                if child.wait(timeout=.25):raise ValueError('The default media player could not open this file')
            except subprocess.TimeoutExpired:
                Thread(target=child.wait,daemon=True).start()
    except OSError as error:
        raise ValueError('Set a default media player for this audio format on this computer') from error


def register(owner):
    app=owner.app
    intents={}
    intent_lock=RLock()
    def consent_key(value,identity,scope,mappings,path):
        from audio_paths import signature
        info=path.lstat()
        return (tuple((name,str(value.get(name,''))) for name in ('workspace','snapshot','capture')),
                identity,scope,signature(mappings),str(path),info.st_size,info.st_mtime_ns,
                info.st_dev,info.st_ino,getattr(info,'st_file_attributes',0),getattr(info,'st_flags',0))
    def body():
        # A remote browser must not launch applications on the server.
        try:
            peer=ipaddress.ip_address(request.remote_addr or '')
            host=request.host.split(':')[0] if not request.host.startswith('[') else request.host[1:].split(']')[0]
            local_host=host=='localhost' or ipaddress.ip_address(host).is_loopback
        except ValueError:local_host=False;peer=None
        if not peer or not peer.is_loopback or not local_host:raise ValueError('Playback is available only on the local computer')
        value=request.get_json(silent=True)
        if not isinstance(value,dict):raise ValueError('Provide a JSON object')
        return value
    def tracks(value):
        if value.get('workspace'):
            session=owner.sessions.get(owner.active)
            if not session or session['id']!=value['workspace']:raise ValueError('This workspace is no longer loaded')
            return session['catalog'].tracks, 'session:'+session['id']
        from collection_sources import history_source
        saved=history_source(owner, value)
        return {str(t['id']):t for t in saved['tracks']}, saved['scope_key']
    @app.post('/api/playback/availability')
    def availability():
        value=body();ids=value.get('track_ids')
        if not isinstance(ids,list) or not 1<=len(ids)<=100 or any(not isinstance(i,str) or len(i)>200 for i in ids):
            raise ValueError('Choose up to 100 captured tracks')
        source,scope=tracks(value)
        mappings=Store(owner.DATA/'workbench-sidecar.sqlite3').setting('audio_paths:'+scope,[])
        from file_status_cache import inspect
        statuses,hits,details=inspect(owner,{i:source.get(i,{}) for i in ids},
                              refresh=value.get('refresh') is True,mappings=mappings,details=True)
        return jsonify(tracks={i:statuses[i]=='playable' for i in ids},
                       statuses=statuses,cached=hits,
                       cloud={i:{'can_open':bool(details.get(i,{}).get('cloud_openable')),
                                 'state':details.get(i,{}).get('cloud_state','unknown')}
                              for i in ids if details.get(i,{}).get('playback_cloud')})
    @app.post('/api/playback/open')
    def launch():
        value=body();identity=value.get('track_id')
        if not isinstance(identity,str) or not 1<=len(identity)<=200:raise ValueError('Choose a captured track')
        confirmed=value.get('confirm_cloud_open',False)
        if not isinstance(confirmed,bool):raise ValueError('Choose a supported cloud playback confirmation')
        source,scope=tracks(value)
        track=source.get(identity)
        if track is None:raise ValueError('This track is not in the selected library')
        mappings=Store(owner.DATA/'workbench-sidecar.sqlite3').setting('audio_paths:'+scope,[])
        from cloud_file_status import provider_context,path_providers
        roots=provider_context()
        details=inspect_audio_details(track,mappings,roots)
        path=details['open_candidate']
        if path is None:
            if details['providers']&1:
                raise ValueError('This file is not available locally. Make this single track available in Dropbox or rekordbox, then refresh.')
            raise ValueError('Audio file unavailable at the recorded library paths')
        key=consent_key(value,identity,scope,mappings,path)
        if confirmed:
            token=value.get('confirmation_token')
            with intent_lock:
                entry=intents.pop(token,None) if isinstance(token,str) and len(token)<=128 else None
            if not entry or entry[0]!=key or not 0<=time.monotonic()-entry[1]<=120:
                raise ValueError('Cloud playback details changed or confirmation expired. Choose Play again.')
        elif details['playback_cloud']:
            token=secrets.token_urlsafe(32)
            with intent_lock:
                for old in list(intents):
                    if time.monotonic()-intents[old][1]>120:intents.pop(old,None)
                while len(intents)>=128:intents.pop(next(iter(intents)))
                intents[token]=(key,time.monotonic())
            providers=path_providers(path,roots)
            return jsonify(opened=False,confirmation_required=True,confirmation_token=token,
                           cloud_provider='dropbox' if 'dropbox' in providers else 'google_drive' if 'google_drive' in providers else 'unknown',
                           title=str(track.get('title') or identity)[:200],cloud_state=details['cloud_state'])
        open_audio(path)
        return jsonify(opened=True,cloud_open_confirmed=confirmed)
