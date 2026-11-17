"""Independent bounded readers for stem containers and third-party cache metadata."""
from collections import Counter
import json
import math
from pathlib import PurePosixPath
import re
import struct
from uuid import UUID

STEMS_SUFFIXES=('.rbsc','.stem','.stems','.stem.mp4','.stems.mp4','.stem.m4a','.stems.m4a')
STEMS_FOLDERS={'stems','stem','track separation','track_separation','trackseparation'}
CACHE_FOLDERS={'rbstemsplus','rb stems plus cache.noindex'}
HEX64=re.compile(r'^[0-9a-f]{64}$')
MAX_REFERENCES=16384
MAX_METADATA=2*1024**2


def stem_candidate(path):
    path=str(path).replace('\\','/').casefold();parts=path.split('/')
    return path.endswith(STEMS_SUFFIXES) or any(p in STEMS_FOLDERS for p in parts[:-1])


def cache_candidate(path):
    parts=str(path).replace('\\','/').casefold().split('/');name=parts[-1]
    return (name=='.rbstemsplus-cache' or name.endswith(('.kept','.manifest')) or
            name.endswith(('.flac','.desc')) and bool(HEX64.fullmatch(name.rsplit('.',1)[0])) or
            any(p in CACHE_FOLDERS for p in parts[:-1]) and name.endswith(('.flac','.desc','.tmp','.part')))


def evidence(kind,state,detail,**facts):
    return {'format':kind,'validation':state,'detail':detail,'asset_family':'separation_cache',
            'provider':'rbstemsplus','native_stems_readiness':None,'source_association':'unknown',**facts}


def inspect_cache_file(name,data,size,provider_context=False):
    name=PurePosixPath(str(name).replace('\\','/')).name.casefold()
    if name=='.rbstemsplus-cache':
        try:
            if len(data)!=size or size>4096:return evidence('rbstems_marker','not_checked','Cache marker exceeds the bounded read')
            pairs=[line.split('=',1) for line in data.decode('utf-8').splitlines()]
            if any(len(p)!=2 for p in pairs) or len({p[0] for p in pairs})!=len(pairs):raise ValueError()
            marker=dict(pairs)
            if set(marker)!={'id','format'}:raise ValueError()
            UUID(marker['id'])
            if marker['format']!='rbstems-v1':return evidence('rbstems_marker','unsupported','Unknown cache-location format revision')
            return evidence('rbstems_marker','recognized','RB Stems Plus cache-location marker recognized',location_id=marker['id'],cache_state='present')
        except (ValueError,UnicodeError):return evidence('rbstems_marker','corrupt','Invalid RB Stems Plus cache-location marker')
    if name.endswith(('.tmp','.part')):
        if not provider_context:return None
        return evidence('rbstems_partial','not_checked','Temporary cache output; completion has not been established',cache_state='incomplete')
    if name.endswith('.flac'):
        if not provider_context:return None
        if len(data)<42 or data[:4]!=b'fLaC' or data[4]&127!=0 or int.from_bytes(data[5:8],'big')!=34:
            return evidence('rbstems_flac','corrupt','Missing or truncated FLAC STREAMINFO')
        value=int.from_bytes(data[18:26],'big')
        rate=value>>44;channels=((value>>41)&7)+1;bits=((value>>36)&31)+1;frames=value&((1<<36)-1)
        facts={'sample_rate':rate,'channels':channels,'bits_per_sample':bits,'frames':frames,
               'duration_seconds':frames/rate if rate else None,'stored_gain':.5,'restore_gain':2,
               'source_order':['drums','bass','other','vocals'],'payload_verified':False}
        if (rate,channels,bits)!=(44100,8,16):return evidence('rbstems_flac','unsupported','FLAC properties do not match the inspected cache profile',**facts)
        if not frames:return evidence('rbstems_flac','not_checked','Cache sample count is unavailable',**facts)
        return evidence('rbstems_flac','recognized','Eight-channel cache STREAMINFO recognized; audio frames were not decoded',**facts)
    if name.endswith('.desc'):
        if not provider_context and not data.startswith((b'RBD1',b'RBD2')):return None
        if len(data)<16 or data[:4] not in (b'RBD1',b'RBD2'):return evidence('rbstems_descriptor','corrupt','Invalid cache descriptor header')
        frames=struct.unpack_from('<i',data,4)[0]
        if not 1<=frames<=512:return evidence('rbstems_descriptor','corrupt','Invalid descriptor frame count')
        expected=16+8*frames+(8+8*frames if data[:4]==b'RBD2' else 0)
        if size!=expected:return evidence('rbstems_descriptor','corrupt','Descriptor length disagrees with its frame count')
        if len(data)<size:return evidence('rbstems_descriptor','not_checked','Descriptor exceeds the inspection byte budget')
        values=struct.unpack_from('<'+'f'*((size-8)//4),data,8)
        if not all(math.isfinite(v) for v in values):return evidence('rbstems_descriptor','corrupt','Descriptor contains nonfinite values')
        return evidence('rbstems_descriptor','recognized','Finite cache descriptor recognized',descriptor_version=data[3]-48,
                        descriptor_frames=frames,descriptor_hop=4410,residual=values[0],gain=values[1])
    if name.endswith(('.kept','.manifest')):
        if not provider_context and not data.startswith(b'rbstemsplus-'):return None
        return inspect_manifest(data,size,name.endswith('.kept'))
    return None


def inspect_manifest(data,size,kept=False):
    kind='rbstems_kept' if kept else 'rbstems_manifest';family='retention_set' if kept else 'preparation_manifest'
    def out(state,detail,**facts):return evidence(kind,state,detail,asset_family=family,**facts)
    if size>MAX_METADATA or len(data)!=size:return out('not_checked','Provider metadata exceeds the inspection byte budget')
    try:
        text=data.decode('utf-8')
        if not text.endswith('\n') or '\x00' in text or '\r' in text:raise ValueError()
        lines=text.splitlines()
        if kept:
            if len(lines)<2 or lines[0]!='rbstemsplus-kept 1' or not re.fullmatch(r'until [0-9]{1,12}',lines[1]):raise ValueError()
            if len(lines)-2>MAX_REFERENCES:return out('not_checked','Retention reference-count budget reached')
            pairs=[]
            for line in lines[2:]:
                pair=line.split(' ')
                if len(pair)!=2 or not all(HEX64.fullmatch(v) for v in pair):raise ValueError()
                pairs.append(pair)
            return out('recognized','Provider retention set decoded; retention does not establish track readiness',
                       until=int(lines[1][6:]),_kept_pairs=pairs,referenced_chunks=len({tuple(p) for p in pairs}))
        if len(lines)<5 or lines[0]!='rbstemsplus-manifest 1':raise ValueError()
        if not re.fullmatch(r'helper [^\s]{1,15}',lines[1]) or not lines[2].startswith('model ') or not HEX64.fullmatch(lines[2][6:]):raise ValueError()
        if not lines[3].startswith('playlist ') or not 1<=len(lines[3][9:])<=64:raise ValueError()
        rate=lines[4].split(' ')
        if len(rate)!=4 or rate[0]!='rate' or not 0<=int(rate[1])<2**63 or not math.isfinite(float(rate[2])) or float(rate[2])<0 or not 0<=int(rate[3])<=1024:raise ValueError()
        entries=[];at=5;refs=0
        while at<len(lines):
            match=re.fullmatch(r'file ([0-9]+) (-?[0-9]+) ([01]) ([0-9]+) (.+)',lines[at])
            if not match:raise ValueError()
            length,stamp,complete,count=int(match[1]),int(match[2]),int(match[3]),int(match[4]);path=match[5]
            if not 0<=length<2**63 or not -2**63<=stamp<2**63 or len(path)>4096:raise ValueError()
            refs+=count
            if refs>MAX_REFERENCES or len(entries)>=10000:return out('not_checked','Preparation manifest reference-count budget reached')
            if count>len(lines)-at-1:raise ValueError()
            keys=lines[at+1:at+1+count]
            if not all(HEX64.fullmatch(key) for key in keys):raise ValueError()
            entries.append({'path':path,'size':length,'mtime_ns':stamp,'complete':bool(complete),'keys':list(dict.fromkeys(keys))})
            at+=1+count
        return out('recognized','Provider preparation manifest decoded; file and chunk evidence require separate checks',
                   helper_version=lines[1][7:],model_namespace=lines[2][6:],playlist_id=lines[3][9:],
                   referenced_files=len(entries),referenced_chunks=refs,_manifest_records=entries)
    except (ValueError,UnicodeError,OverflowError):return out('corrupt','Invalid provider metadata syntax, values or reference counts')


class ContainerLimit(Exception):pass
class ContainerInvalid(Exception):pass
class ContainerUnsupported(Exception):pass


def inspect_iso(read,size):
    """READ(offset,length) is bounded by the caller; media payload boxes are skipped."""
    result={'format':'iso_media_candidate','asset_family':'stem_container','provider':'unknown',
            'native_stems_readiness':None,'source_association':'unknown','payload_verified':False}
    nodes=0
    def take(at,n):
        if at<0 or n<0 or at+n>size:raise ContainerInvalid('Container field exceeds its file boundary')
        value=read(at,n)
        if len(value)!=n:raise ContainerLimit('Required container metadata is outside the bounded read')
        return value
    def boxes(start,end,depth=0):
        nonlocal nodes
        if depth>8:raise ContainerLimit('Container depth budget reached')
        while start<end:
            nodes+=1
            if nodes>2048:raise ContainerLimit('Container box-count budget reached')
            if end-start<8:raise ContainerInvalid('Truncated container box header')
            length,tag=struct.unpack('>I4s',take(start,8));header=8
            if length==1:
                if end-start<16:raise ContainerInvalid('Truncated extended container box header')
                length=struct.unpack('>Q',take(start+8,8))[0];header=16
            elif length==0:length=end-start
            if length<header or length>end-start:raise ContainerInvalid('Invalid container box length')
            yield tag,start+header,start+length,depth+1
            start+=length
    def children(item):return list(boxes(item[1],item[2],item[3]))
    def one(items,tag,required=True):
        found=[v for v in items if v[0]==tag]
        if len(found)>1:raise ContainerInvalid('Duplicate required container metadata box')
        if not found and required:raise ContainerUnsupported('Required NI container metadata is unavailable')
        return found[0] if found else None
    def payload(item,limit):
        if item[2]-item[1]>limit:raise ContainerLimit('Container metadata field exceeds its byte limit')
        return take(item[1],item[2]-item[1])
    def field(item,length):
        if item[2]-item[1]<length:raise ContainerInvalid('Truncated container metadata field')
        return take(item[1],length)
    try:
        top=list(boxes(0,size));ftyp=one(top,b'ftyp');brand=take(ftyp[1],min(8,ftyp[2]-ftyp[1]))
        if len(brand)<8:raise ContainerInvalid('Truncated file-type box')
        result['major_brand']=brand[:4].decode('ascii',errors='replace')
        moov=one(top,b'moov',False)
        if moov is None:raise ContainerUnsupported('ISO media header recognized; no movie metadata was found')
        movie=children(moov);meta=[]
        for udta in (v for v in movie if v[0]==b'udta'):
            meta.extend(v for v in children(udta) if v[0]==b'stem')
        if not meta:raise ContainerUnsupported('ISO media container found; NI STEM metadata is absent')
        if len(meta)!=1:raise ContainerInvalid('Ambiguous NI STEM metadata boxes')
        result.update(format='ni_stems_v1',provider='native_instruments')
        try:info=json.loads(payload(meta[0],65536).decode('utf-8'),object_pairs_hook=unique_json,
                            parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
        except (ValueError,UnicodeError,RecursionError):raise ContainerInvalid('Invalid NI STEM JSON metadata') from None
        if not isinstance(info,dict) or type(info.get('version')) is not int:raise ContainerInvalid('Missing NI metadata version')
        if info['version']!=1:raise ContainerUnsupported('Unsupported NI STEM metadata version')
        stems=info.get('stems')
        if not isinstance(stems,list) or len(stems)!=4:raise ContainerInvalid('NI metadata requires four stem labels')
        for stem in stems:
            if not isinstance(stem,dict) or not isinstance(stem.get('name'),str) or not 1<=len(stem['name'])<=255 or not re.fullmatch(r'#[0-9a-fA-F]{6}',str(stem.get('color',''))):
                raise ContainerInvalid('Invalid NI stem label or colour')
        result['stem_labels']=[{'name':s['name'],'color':s['color']} for s in stems]
        result['mastering_metadata_present']=isinstance(info.get('mastering_dsp'),dict)
        mvhd=one(movie,b'mvhd');mhead=take(mvhd[1],min(32,mvhd[2]-mvhd[1]))
        if len(mhead)<20 or mhead[0] not in (0,1):raise ContainerUnsupported('Unsupported movie time-header revision')
        rate_at=20 if mhead[0] else 12
        if len(mhead)<rate_at+4:raise ContainerInvalid('Truncated movie timescale')
        movie_rate=struct.unpack_from('>I',mhead,rate_at)[0]
        if not movie_rate:raise ContainerInvalid('Zero movie timescale')
        tracks=[]
        for trak in (v for v in movie if v[0]==b'trak'):
            if len(tracks)>=16:raise ContainerLimit('Container track-count budget reached')
            parts=children(trak);tkhd=one(parts,b'tkhd');flags=field(tkhd,4)
            mdia=children(one(parts,b'mdia'));handler=payload(one(mdia,b'hdlr'),65536)
            if len(handler)<12:raise ContainerInvalid('Truncated track handler')
            if handler[8:12]!=b'soun':raise ContainerUnsupported('NI candidate contains non-audio tracks')
            mdhd=payload(one(mdia,b'mdhd'),128)
            if not mdhd or mdhd[0] not in (0,1):raise ContainerUnsupported('Unsupported media time-header revision')
            at=20 if mdhd[0] else 12;need=at+(12 if mdhd[0] else 8)
            if len(mdhd)<need:raise ContainerInvalid('Truncated media time header')
            timescale=struct.unpack_from('>I',mdhd,at)[0]
            duration=struct.unpack_from('>Q' if mdhd[0] else '>I',mdhd,at+4)[0]
            if not timescale:raise ContainerInvalid('Zero media timescale')
            minf=children(one(mdia,b'minf'));stbl=children(one(minf,b'stbl'));stsd=one(stbl,b'stsd')
            start=field(stsd,8)
            if start[0]!=0 or struct.unpack_from('>I',start,4)[0]!=1:raise ContainerUnsupported('Unsupported audio sample-description table')
            sample=list(boxes(stsd[1]+8,stsd[2],stsd[3]))
            if len(sample)!=1:raise ContainerInvalid('Audio description entry count disagrees with its body')
            audio=field(sample[0],28)
            if struct.unpack_from('>H',audio,8)[0]!=0:raise ContainerUnsupported('Unsupported audio sample-entry revision')
            channels=struct.unpack_from('>H',audio,16)[0];sample_rate=struct.unpack_from('>I',audio,24)[0]/65536
            codec={b'mp4a':'mp4a',b'alac':'alac'}.get(sample[0][0])
            if codec is None:raise ContainerUnsupported('NI audio codec is unsupported or encrypted')
            if not sample_rate or not channels:raise ContainerInvalid('Invalid audio sample rate or channel count')
            track={'enabled':bool(int.from_bytes(flags[1:4],'big')&1),'codec':codec,'codec_profile':'unverified','channels':channels,
                   'sample_rate':sample_rate,'media_duration_seconds':duration/timescale,'start_seconds':0,'duration_seconds':duration/timescale}
            edts=one(parts,b'edts',False)
            if edts:
                elst=payload(one(children(edts),b'elst'),1024)
                if len(elst)<8 or elst[0] not in (0,1):raise ContainerUnsupported('Unsupported edit-list revision')
                n=struct.unpack_from('>I',elst,4)[0];width=20 if elst[0] else 12
                if n>16:raise ContainerLimit('Edit-list entry-count budget reached')
                if 8+n*width!=len(elst):raise ContainerInvalid('Invalid edit-list length')
                edits=[];lead=0;total=0;content=False
                for off in range(8,len(elst),width):
                    segment,media=struct.unpack_from('>Qq' if elst[0] else '>Ii',elst,off)
                    speed=struct.unpack_from('>hh',elst,off+width-4)
                    if speed!=(1,0) or media < -1:raise ContainerUnsupported('Unsupported stem edit rate or media time')
                    if media==-1:
                        if content:raise ContainerUnsupported('Non-leading empty edit requires playback validation')
                        lead+=segment
                    else:content=True
                    total+=segment;edits.append({'segment_seconds':segment/movie_rate,'media_start_seconds':None if media==-1 else media/timescale})
                track.update(start_seconds=lead/movie_rate,duration_seconds=total/movie_rate,edits=edits)
            tracks.append(track)
        result['tracks']=tracks
        if len(tracks)!=5:raise ContainerInvalid('NI metadata requires one mix and four audio stem tracks')
        if [t['enabled'] for t in tracks]!=[True,False,False,False,False]:raise ContainerUnsupported('NI track enable flags require review')
        if any(t['channels']!=2 for t in tracks):raise ContainerUnsupported('NI stem tracks are not consistently stereo')
        tolerance=1/min(t['sample_rate'] for t in tracks)+1e-9
        if any(t['sample_rate']!=tracks[0]['sample_rate'] or abs(t['start_seconds']-tracks[0]['start_seconds'])>tolerance or abs(t['duration_seconds']-tracks[0]['duration_seconds'])>tolerance for t in tracks):
            raise ContainerUnsupported('Stem rates or presentation timelines differ; compatibility requires review')
        return {**result,'validation':'recognized','detail':'NI-style five-stream structure, labels and presentation timelines recognized; player acceptance is unverified',
                'audio_streams':5,'timeline_consistent':True,'cache_state':'present'}
    except ContainerLimit as e:return {**result,'validation':'not_checked','detail':str(e)}
    except ContainerInvalid as e:return {**result,'validation':'corrupt','detail':str(e)}
    except ContainerUnsupported as e:return {**result,'validation':'unsupported','detail':str(e)}


def unique_json(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate metadata key')
        result[key]=value
    return result
