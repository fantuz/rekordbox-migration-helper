"""Open a captured audio path through the local desktop's default association."""
import ipaddress
import os
from pathlib import Path
import re
import subprocess
import sys
from threading import Thread
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


def candidate_paths(track, mappings=None):
    from audio_paths import mapped_path,mapping_applies
    for key in ('current_path','xml_location','original_path'):
        value=track.get(key)
        if not value:continue
        # A replaced/disconnected mapped volume must not fall back to another
        # file at the recorded POSIX location and bypass the volume identity.
        yield mapped_path(value,mappings) if mapping_applies(value,mappings) else recorded_path(value)


def available_audio(track, mappings=None):
    """Current recorded location wins; only recorded alternatives are considered."""
    for path in candidate_paths(track,mappings):
        if path is None:continue
        try:
            resolved=path.resolve(strict=True)
            if resolved.suffix.lower() not in AUDIO_EXTENSIONS:continue
            if resolved.is_file() and resolved.stat().st_size>0 and os.access(resolved,os.R_OK):return resolved
        except (OSError,ValueError,RuntimeError):continue
    return None



def inspect_audio(track, mappings=None):
    """Classify recorded locations without attempting to decode or play audio.

    The legacy API state 'playable' means a nonempty, readable, regular
    audio-suffixed file was found (shown as Accessible in the UI), not
    that the OS association or decoder is guaranteed to work. Missing means
    the parent directory is reachable and that particular file is absent.
    """
    if not isinstance(track, dict):
        return 'unverified', None
    seen=set()
    evidence=[]
    for path in candidate_paths(track,mappings):
        if path is None:
            evidence.append('unverified')
            continue
        normalized=str(path)
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            target=path.resolve(strict=True)
            if target.suffix.lower() not in AUDIO_EXTENSIONS or not target.is_file() or target.stat().st_size==0:
                evidence.append('unverified')
            elif os.access(target,os.R_OK):
                return 'playable', target
            else:
                evidence.append('inaccessible')
        except FileNotFoundError:
            try:
                # An unmounted drive or unavailable folder is not proof that
                # an audio recording has been deleted.
                parent=path.parent
                if parent.is_dir() and os.access(parent,os.X_OK):
                    evidence.append('missing')
                else:
                    evidence.append('unverified')
            except (OSError,ValueError,RuntimeError):
                evidence.append('unverified')
        except PermissionError:
            evidence.append('inaccessible')
        except (OSError,ValueError,RuntimeError):
            evidence.append('unverified')
    if 'inaccessible' in evidence:
        return 'inaccessible', None
    if 'unverified' in evidence or not evidence:
        return 'unverified', None
    return 'missing', None


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
        statuses,hits=inspect(owner,{i:source.get(i,{}) for i in ids},
                              refresh=value.get('refresh') is True,mappings=mappings)
        return jsonify(tracks={i:statuses[i]=='playable' for i in ids},
                       statuses=statuses,cached=hits)
    @app.post('/api/playback/open')
    def launch():
        value=body();identity=value.get('track_id')
        if not isinstance(identity,str):raise ValueError('Choose a captured track')
        source,scope=tracks(value)
        track=source.get(identity)
        if track is None:raise ValueError('This track is not in the selected library')
        mappings=Store(owner.DATA/'workbench-sidecar.sqlite3').setting('audio_paths:'+scope,[])
        path=available_audio(track,mappings)
        if path is None:raise ValueError('Audio file unavailable at the recorded library paths')
        open_audio(path)
        return jsonify(opened=True)
