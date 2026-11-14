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


def available_audio(track):
    """Current recorded location wins; only recorded alternatives are considered."""
    for key in ('current_path','xml_location','original_path'):
        path=recorded_path(track.get(key))
        if path is None:continue
        try:
            resolved=path.resolve(strict=True)
            if resolved.suffix.lower() not in AUDIO_EXTENSIONS:continue
            if resolved.is_file() and os.access(resolved,os.R_OK):return resolved
        except (OSError,ValueError,RuntimeError):continue
    return None


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
            return session['catalog'].tracks
        saved=Store(owner.DATA/'workbench-sidecar.sqlite3').snapshot(value.get('snapshot',''))
        return {str(t['id']):t for t in saved['tracks']}
    @app.post('/api/playback/availability')
    def availability():
        value=body();ids=value.get('track_ids')
        if not isinstance(ids,list) or not 1<=len(ids)<=100 or any(not isinstance(i,str) or len(i)>200 for i in ids):
            raise ValueError('Choose up to 100 captured tracks')
        source=tracks(value)
        return jsonify(tracks={i:available_audio(source.get(i,{})) is not None for i in ids})
    @app.post('/api/playback/open')
    def launch():
        value=body();identity=value.get('track_id')
        if not isinstance(identity,str):raise ValueError('Choose a captured track')
        track=tracks(value).get(identity)
        if track is None:raise ValueError('This track is not in the selected library')
        path=available_audio(track)
        if path is None:raise ValueError('Audio file unavailable at the recorded library paths')
        open_audio(path)
        return jsonify(opened=True)
