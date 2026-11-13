"""Read metadata-only rekordbox XML from any supported export version."""
from collections import Counter,defaultdict
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
from xml.parsers import expat

from engine import parse_xml,path_key,is_auto,HOT_NUMBERS
from media import file_record
from metadata_export import track


def analyze_xml(source,output,progress):
    source,output=Path(source),Path(output);before=file_record(source)
    if before['cloud_only']:raise ValueError('Make this XML available locally before reading it')
    if before['size']>4*1024**3:raise ValueError('XML exceeds the 4 GB analysis limit')
    records,_,version,digest=parse_xml(source,progress)
    tracks=[];by_location=defaultdict(list);hot={value:key for key,value in HOT_NUMBERS.items()}
    for identity,record in records.items():
        a=record['attrs'];marks=record['marks'];rating=None
        try:
            raw=float(a['Rating']);rating=raw/51 if 0<=raw<=255 else None
        except (KeyError,ValueError):pass
        auto=sum(is_auto({'Comment':m.get('Name','')}) for m in marks)
        t=track({'id':identity,'title':a.get('Name'),'artist':a.get('Artist'),'album':a.get('Album'),'genre':a.get('Genre'),
                 'year':a.get('Year'),'bpm':a.get('AverageBpm'),'duration':a.get('TotalTime'),'rating':rating,'label':a.get('Label'),
                 'composer':a.get('Composer'),'play_count':a.get('PlayCount'),'date_added':a.get('DateAdded'),'bitrate':a.get('BitRate'),
                 'sample_rate':a.get('SampleRate'),'current_path':a.get('Location'),'manual_cues':len(marks)-auto,'auto_cues':auto})
        t.update(cues=None,raw_tags={'year':a.get('Year'),'bpm':a.get('AverageBpm'),'duration':a.get('TotalTime'),'rating':rating},uuid=None,isrc=a.get('ISRC',''))
        tracks.append(t);by_location[path_key(a.get('Location'))].append(identity)
    lookup={t['id']:t for t in tracks};playlists=[];stack=[];scope='';unresolved=0
    parser=expat.ParserCreate()
    def start(name,attrs):
        nonlocal scope,unresolved
        if name in ('COLLECTION','PLAYLISTS'):scope=name
        if scope!='PLAYLISTS':return
        if name=='NODE':
            identity='xml-playlist:'+str(len(playlists));p={'id':identity,'name':attrs.get('Name',''),'parent':stack[-1]['id'] if stack else '',
                'folder':attrs.get('Type')=='0','tracks':[],'key_type':attrs.get('KeyType','0'),'smart':False}
            playlists.append(p);stack.append(p)
        elif name=='TRACK' and stack:
            key=attrs.get('Key','');p=stack[-1]
            ids=by_location.get(path_key(key),[]) if p['key_type']=='1' else [key]
            if len(ids)==1 and ids[0] in lookup:p['tracks'].append(ids[0]);lookup[ids[0]]['playlists'].append(p['name'])
            else:unresolved+=1
    def end(name):
        nonlocal scope
        if name=='NODE' and scope=='PLAYLISTS' and stack:stack.pop()
        if name in ('COLLECTION','PLAYLISTS'):scope=''
    def reject(*args):raise ValueError('DTD and entity declarations are unsupported')
    parser.StartElementHandler=start;parser.EndElementHandler=end;parser.StartDoctypeDeclHandler=reject;parser.EntityDeclHandler=reject
    with source.open('rb') as stream:
        while chunk:=stream.read(2*1024**2):parser.Parse(chunk,False)
        parser.Parse(b'',True)
    if file_record(source)!=before:raise ValueError('The XML changed while being read; capture it again')
    captured=datetime.now(timezone.utc).isoformat();output.mkdir(parents=True,exist_ok=True)
    metadata={'schema':1,'source_kind':'rekordbox XML metadata export','scope':'xml','version':version or None,'captured':captured,'scope_key':'capture:'+output.name,
              'tracks':tracks,'playlists':playlists,'asset_references':[],'capabilities':{'cue_positions':False,'playlist_order':True,'analysis_references':False},
              'cue_basis':'Counts of exported XML markers only; absence in XML does not establish absence in the native library.'}
    for name in ('metadata.json','comparison.json'):(output/name).write_text(json.dumps(metadata,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    counters={'tracks':len(tracks),'artists':len({t['artist'].casefold() for t in tracks if t['artist']}),'albums':len({t['album'].casefold() for t in tracks if t['album']}),
              'genres':len({t['genre'].casefold() for t in tracks if t['genre']}),'playlists':sum(not p['folder'] for p in playlists),
              'bpm_known':sum(t['bpm'] is not None for t in tracks),'duration_known':sum(t['duration'] is not None for t in tracks),
              'total_duration_seconds':sum(t['duration'] or 0 for t in tracks),'unresolved_playlist_references':unresolved}
    report={'id':output.name,'created':captured,'source':str(source),'version_hint':version,'format':'rekordbox '+(version or '(version unspecified)')+' XML metadata',
            'read_status':'checked','source_writes':False,'database':None,'xml':{'counters':counters,'sha256':digest},'metadata_available':True,'track_paths_available':False,
            'messages':[{'level':'info','text':'Read-only XML metadata statistics. No native v5 .edb records were decoded. Missing fields remain unknown; XML may cover only part of the library. Generate an offline explorer for genre, BPM, duration and artist tables.'}],
            'footprint':{'bytes':before['size'],'files':1,'cloud_placeholders':0,'extensions':[{'extension':'.xml','files':1,'bytes':before['size']}]}}
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
