"""Detached Serato metadata/crate draft. Never opens or changes audio or databases.

Independent encoder based on public format descriptions. See docs/SERATO-BRIDGE.md.
Application compatibility remains unverified until a real Serato import is tested.
"""
from collections import Counter
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
from serato_reader import validate_export,relative_path


def field(tag,value):
    try:payload=value.encode('utf-16-be') if isinstance(value,str) else value
    except UnicodeError as error:raise ValueError('Metadata contains invalid Unicode') from error
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
    return relative_path(relative)


def safe_name(name):
    clean=re.sub(r'[\\\\/:*?"<>|%\x00-\x1f]','_',str(name or 'Playlist')).strip(' .')
    return (clean or 'Playlist')[:65]


def crate_component(node):
    return safe_name(node.get('name'))+'-'+sha256(str(node['id']).encode()).hexdigest()[:10]


def build_plan(snapshot,volume):
    volume=local_audio_path(volume)
    if re.match(r'^[A-Za-z]:',volume) and len(PureWindowsPath(volume).parts)!=1:
        raise ValueError('For Windows, select a drive root such as C:/')
    if len(snapshot['tracks'])>100000:raise ValueError('This draft is limited to 100000 captured tracks')
    records=[];paths={};canonical={};omitted=[];identities=set();field_counts=Counter()
    mapping={'tsng':'title','tart':'artist','talb':'album','tgen':'genre','tbpm':'bpm','tkey':'tonality','ttyr':'year','tlbl':'label','tcmp':'composer','tcom':'comment'}
    size=0
    for track in snapshot['tracks']:
        identity=str(track['id'])
        if identity in identities:raise ValueError('Duplicate track identity in the captured library')
        identities.add(identity)
        try:relative=volume_relative(track.get('current_path'),volume)
        except ValueError as error:
            omitted.append({'track_id':identity,'code':'unusable_path','reason':str(error)});continue
        key=relative.casefold() if re.match(r'^[A-Za-z]:',volume) else relative
        if key in canonical:
            paths[identity]=canonical[key]
            omitted.append({'track_id':identity,'code':'duplicate_path','reason':'Duplicate recorded path; first record retained in database'})
            continue
        row={'pfil':relative}
        suffix=PurePosixPath(relative).suffix.lstrip('.').lower()
        if suffix:row['ttyp']=suffix
        for tag,name in mapping.items():
            value=track.get(name)
            if value is not None and str(value):row[tag]=str(value)
        duration=track.get('duration')
        if isinstance(duration,(int,float)) and not isinstance(duration,bool) and 0<=duration<864000:
            seconds=int(duration);row['tlen']=str(seconds//60)+':'+str(seconds%60).zfill(2)
        try:encoded=field('otrk',b''.join(field(tag,value) for tag,value in row.items()))
        except ValueError as error:
            omitted.append({'track_id':identity,'code':'invalid_metadata','reason':str(error)});continue
        size+=len(encoded)
        if size>64*1024**2:raise ValueError('Serato draft exceeds 64 MB')
        paths[identity]=relative;canonical[key]=relative;records.append(row)
        field_counts.update(name for tag,name in mapping.items() if tag in row)
        if 'tlen' in row:field_counts['duration']+=1
    nodes={str(p['id']):p for p in snapshot.get('playlists',[])}
    if len(nodes)!=len(snapshot.get('playlists',[])):raise ValueError('Duplicate playlist identity in the captured library')
    lists=playlists(snapshot)
    structural={key for key,node in nodes.items() if node.get('folder') and node.get('name')=='ROOT' and not node.get('parent')}
    lists += [{**node,'id':key,'tracks':[],'folder':True} for key,node in nodes.items() if node.get('folder') and key not in structural]
    if len(lists)>10000:raise ValueError('This draft is limited to 10000 playlists')
    crates={};crate_rows=[];filenames=set();omitted_entries=[];warnings=[]
    for playlist in lists:
        identity=str(playlist['id']);parent=str(playlist.get('parent') or '');parents=[];visited={identity};notes=[]
        while parent and parent not in structural:
            if parent in visited or len(parents)>=64:
                notes.append('Invalid or excessively deep hierarchy; crate exported at the top level');parents=[];break
            if parent not in nodes:
                notes.append('Parent folder was not captured; available hierarchy retained');break
            visited.add(parent);node=nodes[parent];parents.append(crate_component(node));parent=str(node.get('parent') or '')
        filename='%%'.join([*reversed(parents),crate_component(playlist)])+'.crate'
        if len(filename.encode('utf-8'))>220:
            suffix=sha256(identity.encode()).hexdigest()[:10]
            stem=safe_name(playlist['name']).encode('utf-8')[:180].decode('utf-8','ignore')
            filename=stem+'-'+suffix+'.crate';notes.append('Long hierarchy flattened to fit the crate filename limit')
        if filename.casefold() in filenames:raise ValueError('Crate filenames collide after normalization')
        filenames.add(filename.casefold());members=[]
        for position,track_id in enumerate(playlist.get('tracks',[]),1):
            track_id=str(track_id)
            if track_id in paths:members.append(paths[track_id])
            else:omitted_entries.append({'playlist_id':identity,'playlist':playlist['name'],'position':position,'track_id':track_id,
                                        'reason':'Track has no exported local path' if track_id in identities else 'Track identity was not captured'})
        if playlist.get('smart'):notes.append('Smart playlist exported as static membership')
        if not playlist.get('folder') and not playlist.get('order_available'):notes.append('Original playlist order was not captured')
        warnings.extend({'playlist_id':identity,'reason':reason} for reason in notes)
        content=field('vrsn','1.0/Serato ScratchLive Crate')+b''.join(field('otrk',field('ptrk',path)) for path in members)
        size+=len(content)
        if size>64*1024**2:raise ValueError('Serato draft exceeds 64 MB')
        crates[filename]=members
        crate_rows.append({'id':identity,'name':playlist['name'],'file':filename,'entries':len(members),
                           'folder':bool(playlist.get('folder')),'omitted_entries':len(playlist.get('tracks',[]))-len(members),
                           'order_available':bool(playlist.get('order_available')),'smart_rules_transferred':False,'warnings':notes})
    manifest={'kind':'Serato interoperability draft','created':now(),'snapshot_id':snapshot['id'],'volume_root':volume,
              'source_tracks':len(snapshot['tracks']),'tracks_written':len(records),'crates':crate_rows,'omitted':omitted,
              'omitted_playlist_entries':omitted_entries,'warnings':warnings,'metadata_fields':dict(field_counts),
              'omission_counts':dict(Counter(row['code'] for row in omitted)),
              'source_writes':False,'audio_writes':False,'serato_import_verified':False,'paths_verified_on_disk':False,
              'not_transferred':['ratings','hot cues','memory cues','loops','beatgrids','waveforms','play history','smart-playlist rules'],
              'notes':'Basic metadata and captured playlist membership only. Crates become static. This is a detached draft, not a complete or certified migration.'}
    return records,crates,manifest


def encode_plan(records,crates,manifest):
    database=field('vrsn','2.0/Serato Scratch LIVE Database')+b''.join(field('otrk',b''.join(field(k,v) for k,v in row.items())) for row in records)
    encoded={name:field('vrsn','1.0/Serato ScratchLive Crate')+b''.join(field('otrk',field('ptrk',p)) for p in members) for name,members in crates.items()}
    if len(database)+sum(map(len,encoded.values()))>64*1024**2:raise ValueError('Serato draft exceeds 64 MB')
    manifest['validation']=validate_export(database,encoded,records,crates)
    return database,encoded


def preview_package(snapshot,volume):
    records,crates,manifest=build_plan(snapshot,volume)
    encode_plan(records,crates,manifest)
    # The complete details are retained in the downloadable manifest.
    for key in ('crates','omitted','omitted_playlist_entries','warnings'):
        manifest[key+'_total']=len(manifest[key]);manifest[key]=manifest[key][:100]
    manifest['export_ready']=bool(records)
    return manifest


def draft_package(snapshot,volume):
    records,crates,manifest=build_plan(snapshot,volume)
    if not records:raise ValueError('No tracks have local paths on the selected volume')
    database,encoded=encode_plan(records,crates,manifest)
    output=BytesIO()
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('_Serato_/database V2',database)
        for name,content in encoded.items():archive.writestr('_Serato_/Subcrates/'+name,content)
        archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        archive.writestr('READ-ME.txt',
            'SERATO INTEROPERABILITY DRAFT\n\n'
            'The encoded database and crates passed independent strict readback checks.\n'
            'Not yet validated in a real Serato installation. Use an isolated test library first.\n'
            'This archive contains no music and has not verified that paths still exist.\n'
            'Paths are relative to the volume root you selected: '+volume+'\n\n'
            'Extract to a staging folder. Do not overwrite an existing _Serato_ database.\n'
            'Test with Serato closed and a backed-up, disposable _Serato_ folder.\n'
            'Check tracks, Unicode names, crate hierarchy, order and paths before relying on it.\n'
            'Cues, loops, grids, ratings, history and smart rules are not transferred.\n'
            'Review manifest.json for omissions and hierarchy warnings.\n')
    return output.getvalue(),manifest
