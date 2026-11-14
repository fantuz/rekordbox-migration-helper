"""Detached Serato metadata/crate draft. Never opens or changes audio or databases.

Independent encoder based on public format descriptions. See docs/SERATO-BRIDGE.md.
Application compatibility remains unverified until a real Serato import is tested.
"""
from io import BytesIO
from pathlib import PureWindowsPath,PurePosixPath
from hashlib import sha256
import json
import re
import struct
import zipfile

from chart_playlists import local_audio_path
from library_intelligence import playlists
from workbench_store import now


def field(tag,value):
    payload=value.encode('utf-16-be') if isinstance(value,str) else value
    if len(payload)>64*1024**2:raise ValueError('Serato draft field exceeds the size limit')
    return tag.encode('ascii')+struct.pack('>I',len(payload))+payload


def volume_relative(path,volume):
    path=local_audio_path(path).replace('\\','/')
    volume=local_audio_path(volume).replace('\\','/')
    windows=bool(re.match(r'^[A-Za-z]:/',volume))
    if windows:
        root=PureWindowsPath(volume);source=PureWindowsPath(path)
        if len(root.parts)!=1:raise ValueError('For Windows, select a drive root such as C:/')
        if not re.match(r'^[A-Za-z]:/',path):raise ValueError('Track is outside the selected Windows volume')
    else:
        if re.match(r'^[A-Za-z]:/',path):raise ValueError('Track is outside the selected POSIX volume')
        root=PurePosixPath(volume);source=PurePosixPath(path)
    try:relative=source.relative_to(root).as_posix()
    except ValueError:raise ValueError('Track is outside the selected volume') from None
    if relative in ('','.') or '..' in relative.split('/'):raise ValueError('Track path does not identify a file')
    return relative


def safe_name(name):
    clean=re.sub(r'[\\\\/:*?"<>|%\x00-\x1f]','_',str(name or 'Playlist')).strip(' .')
    return (clean or 'Playlist')[:65]


def draft_package(snapshot,volume):
    volume=local_audio_path(volume)
    if re.match(r'^[A-Za-z]:',volume) and len(PureWindowsPath(volume).parts)!=1:
        raise ValueError('For Windows, select a drive root such as C:/')
    if len(snapshot['tracks'])>100000:raise ValueError('This draft is limited to 100000 captured tracks')
    data=[field('vrsn','2.0/Serato Scratch LIVE Database')];paths={};seen=set();omitted=[];written=0;size=0
    mapping={'tsng':'title','tart':'artist','talb':'album','tgen':'genre','tbpm':'bpm','tkey':'tonality','ttyr':'year','tlbl':'label','tcmp':'composer','tcom':'comment'}
    for track in snapshot['tracks']:
        try:relative=volume_relative(track.get('current_path'),volume)
        except ValueError as error:
            omitted.append({'track_id':track['id'],'reason':str(error)});continue
        paths[track['id']]=relative
        key=relative.casefold() if re.match(r'^[A-Za-z]:',volume) else relative
        if key in seen:
            omitted.append({'track_id':track['id'],'reason':'Duplicate recorded path; first record retained in database'});continue
        seen.add(key)
        fields=[field('pfil',relative),field('ttyp',PurePosixPath(relative).suffix.lstrip('.').lower())]
        for tag,name in mapping.items():
            value=track.get(name)
            if value is not None and str(value):fields.append(field(tag,str(value)))
        duration=track.get('duration')
        if isinstance(duration,(int,float)) and 0<=duration<864000:
            seconds=int(duration);fields.append(field('tlen',str(seconds//60)+':'+str(seconds%60).zfill(2)))
        blob=field('otrk',b''.join(fields));size+=len(blob)
        if size>64*1024**2:raise ValueError('Serato draft exceeds 64 MB')
        data.append(blob);written+=1
    if not written:raise ValueError('No tracks have local paths on the selected volume')
    lists=playlists(snapshot)
    if len(lists)>10000:raise ValueError('This draft is limited to 10000 playlists')
    output=BytesIO();crate_rows=[];nodes={str(p['id']):p for p in snapshot.get('playlists',[])}
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('_Serato_/database V2',b''.join(data))
        for playlist in lists:
            parent=str(playlist.get('parent') or '');parents=[];visited={playlist['id']}
            while parent in nodes and parent not in visited and len(parents)<6:
                visited.add(parent);node=nodes[parent]
                # XML's ROOT container is structural, not a user crate.
                if node.get('name')!='ROOT':parents.append(safe_name(node.get('name')))
                parent=str(node.get('parent') or '')
            suffix=sha256(playlist['id'].encode()).hexdigest()[:10]
            filename='%%'.join([*reversed(parents),safe_name(playlist['name'])+'-'+suffix])+'.crate'
            # Keep a single filename within common Windows/macOS filesystem limits.
            if len(filename.encode('utf-8'))>220:
                stem=safe_name(playlist['name']).encode('utf-8')[:180].decode('utf-8','ignore')
                filename=stem+'-'+suffix+'.crate'
            members=[paths[i] for i in playlist['tracks'] if i in paths]
            content=field('vrsn','1.0/Serato ScratchLive Crate')+b''.join(field('otrk',field('ptrk',p)) for p in members)
            size+=len(content)
            if size>64*1024**2:raise ValueError('Serato draft exceeds 64 MB')
            archive.writestr('_Serato_/Subcrates/'+filename,content)
            crate_rows.append({'name':playlist['name'],'file':filename,'entries':len(members),
                               'omitted_entries':len(playlist['tracks'])-len(members),'smart_rules_transferred':False})
        manifest={'kind':'Serato interoperability draft','created':now(),'snapshot_id':snapshot['id'],'volume_root':volume,
                  'tracks_written':written,'crates':crate_rows,'omitted':omitted,'source_writes':False,'audio_writes':False,
                  'serato_import_verified':False,'paths_verified_on_disk':False,
                  'not_transferred':['ratings','hot cues','memory cues','loops','beatgrids','waveforms','play history','smart-playlist rules'],
                  'notes':'Basic metadata and captured playlist membership only. Crates become static. This is a detached draft, not a complete or certified migration.'}
        archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        archive.writestr('READ-ME.txt',
            'SERATO INTEROPERABILITY DRAFT\n\n'
            'Not yet validated in a real Serato installation. Use an isolated test library first.\n'
            'This archive contains no music and has not verified that paths still exist.\n'
            'Paths are relative to the volume root you selected: '+volume+'\n\n'
            'Extract to a staging folder. Do not overwrite an existing _Serato_ database.\n'
            'Test with Serato closed and a backed-up, disposable _Serato_ folder. External-drive\n'
            'libraries use a _Serato_ folder at the volume root; the primary library normally\n'
            'uses Music/_Serato_. This exporter does not install or merge the output.\n'
            'Check tracks, Unicode names, crate order and paths before relying on it.\n'
            'Cues, loops, grids, ratings, history and smart rules are not transferred.\n'
            'Review manifest.json for omissions. Original source files and audio are unchanged.\n')
    return output.getvalue(),manifest
