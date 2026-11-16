"""Bind new lookups to an available workspace or connected Rekordbox source."""
import json
from pathlib import Path
import re
from uuid import uuid4

from collection_sources import resolve
from research_capture import capture_workspace
from workbench_store import now


def source_details(owner, source):
    if source.startswith('session:'):
        session=owner.sessions.get(owner.active)
        if not session or source!='session:'+session['id'] or not session['catalog'].tracks:
            raise ValueError('Load a library with tracks before starting enrichment')
        if not all(Path(session['metadata'].get(key,'')).is_file() for key in ('zip_path','xml_path')):
            raise ValueError('Reconnect the loaded XML and ZIP files before starting enrichment')
        return {'id':source,'label':session.get('name','Loaded XML + ZIP'),'kind':'workspace'}
    if not re.fullmatch(r'capture:[0-9a-f]{32}',source):
        raise ValueError('Choose a loaded library or connected Rekordbox source')
    folder=owner.DATA/'analyzers'/source[8:]
    report=folder/'report.json'
    if folder.is_symlink() or folder.is_junction() or report.is_symlink() or not report.is_file():
        raise ValueError('Choose an available source capture')
    info=json.loads(report.read_text(encoding='utf-8'))
    path=Path(info.get('source',''))
    # Only connected desktop databases qualify as a current source. A saved
    # XML-only capture or an archived metadata sample remains review-only.
    if not path.is_absolute() or path.is_symlink() or path.is_junction():
        raise ValueError('Reconnect the Rekordbox source before starting enrichment')
    database=path if path.is_file() and path.name.casefold()=='master.db' else None
    if path.is_dir():
        database=next((p for p in path.iterdir() if p.name.casefold()=='master.db' and p.is_file()),None)
    if database is None or database.is_symlink() or database.is_junction():
        raise ValueError('Reconnect the Rekordbox source before starting enrichment')
    return {'id':source,'label':str(path),'kind':'source','path':str(path),'created':info.get('created','')}


def require_snapshot(owner, snapshot):
    if not snapshot.get('tracks'):
        raise ValueError('This collection has no tracks to enrich')
    return source_details(owner,str(snapshot.get('scope_key','')))


def context(owner, store):
    sources=[]
    cached={}
    def details(source):
        if source not in cached:
            try:cached[source]=source_details(owner,source)
            except (ValueError,OSError):cached[source]=None
        return cached[source]
    session=owner.sessions.get(owner.active)
    if session:
        item=details('session:'+session['id'])
        if item:sources.append(item)
    captures=[]
    for report in (owner.DATA/'analyzers').glob('*/report.json'):
        item=details('capture:'+report.parent.name)
        if item:captures.append(item)
    seen=set()
    for item in sorted(captures,key=lambda r:r['created'],reverse=True):
        if item['path'] not in seen:
            sources.append(item);seen.add(item['path'])
    snapshots=[]
    for item in store.snapshots():
        if details(str(item.get('scope_key',''))):snapshots.append(item)
    return {'sources':sources,'snapshots':snapshots}


def prepare(owner, store, source, progress):
    details=source_details(owner,source)
    if details['kind']=='workspace':
        session=owner.sessions[owner.active]
        if source!='session:'+session['id']:raise ValueError('The loaded workspace changed')
        progress(10,'Preparing metadata from the loaded library')
        payload=capture_workspace(session['catalog'],source)
        source_details(owner,source)
    else:
        from analyzer import analyze_folder
        identity=uuid4().hex
        report=analyze_folder(details['path'],owner.DATA/'analyzers'/identity,progress,
                              snapshot_root=owner.TEMPORARY.folder('analyzers',identity))
        if report.get('read_status') not in ('checked','needs_review'):
            raise ValueError('The connected source has no readable collection metadata')
        from audio_paths import inherit
        inherit(store,source,'capture:'+identity)
        source='capture:'+identity
        payload=resolve(owner,source)
    payload.update(scope_key=source,captured=now(),source_kind='Current library enrichment',
                   source_capture=source[8:] if source.startswith('capture:') else 'session')
    require_snapshot(owner,payload)
    progress(95,'Saving local metadata for batch review')
    return {**store.save_snapshot(payload,details['label']), 'source':source}


def playable_collection(snapshot, include_unavailable, progress, mappings=None):
    if not isinstance(include_unavailable,bool):raise ValueError('Choose whether to include unavailable audio')
    if include_unavailable:return snapshot,0
    from track_playback import inspect_audio
    tracks=snapshot['tracks']
    if len(tracks)>250000:raise ValueError('This collection exceeds the local availability scan limit')
    playable=[]
    for n,track in enumerate(tracks):
        if n%100==0:progress(90*n/max(1,len(tracks)),f'Checking playable audio: {n:,} / {len(tracks):,}')
        if inspect_audio(track,mappings)[0]=='playable':playable.append(track)
    if not playable:
        raise ValueError('No readable audio files were found. If this library came from Windows or another computer, map its recorded folder to your local mount in Audio folders, then preview again. You can also explicitly include unavailable audio.')
    return {**snapshot,'tracks':playable},len(tracks)-len(playable)
