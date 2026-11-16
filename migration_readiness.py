"""Metadata-only migration advisories; no audio analysis or source mutations."""
from collections import Counter
import math
import re
from urllib.parse import unquote, urlsplit

PROFILE_VERSION='2026-11-16.1'
PROFILES={
    'cdj-2000nxs2':{'label':'CDJ-2000NXS2',
                    'formats':('MP3','WAV','AAC','AIFF','FLAC','ALAC'),
                    'source':'https://www.pioneerdj.com/en/product/player/cdj-2000nxs2/black/'},
    'generic':{'label':'Unspecified player','formats':(), 'source':None},
}
FAT32_MAX_BYTES=2**32-1
RESERVED=re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)',re.I)
# Camelot wheel: minor A / major B. Preserve the captured notation in every row.
MINOR=('Ab','Eb','Bb','F','C','G','D','A','E','B','F#','C#')
MAJOR=('B','F#','Db','Ab','Eb','Bb','F','C','G','D','A','E')
PITCH={'C':0,'B#':0,'C#':1,'Db':1,'D':2,'D#':3,'Eb':3,'E':4,'Fb':4,'E#':5,'F':5,'F#':6,'Gb':6,'G':7,'G#':8,'Ab':8,'A':9,'A#':10,'Bb':10,'B':11,'Cb':11}


def finite(value):
    if isinstance(value,bool):return None
    try:
        value=float(value)
        return value if math.isfinite(value) and value>0 else None
    except (ValueError,TypeError):return None


def camelot(value):
    key=str(value or '').strip().replace('♯','#').replace('♭','b')
    wheel=re.fullmatch(r'(1[0-2]|[1-9])([AB])',key,re.I)
    if wheel:return int(wheel[1]),wheel[2].upper()
    note=re.fullmatch(r'([A-Ga-g])([#b]?)(?:\s*(m|min|minor|maj|major))?',key,re.I)
    if not note:return None
    pitch=PITCH.get(note[1].upper()+note[2])
    minor=(note[3] or '').lower() in ('m','min','minor')
    names=MINOR if minor else MAJOR
    return next(((i+1,'A' if minor else 'B') for i,n in enumerate(names) if PITCH[n]==pitch),None)


def finding(section,track,detail,**extra):
    return {'section':section,'severity':'review','track_id':track.get('id',''),
            'title':track.get('title',''),'artist':track.get('artist',''),'detail':detail,**extra}


def export_readiness(snapshot,profile='generic',filesystem='not_checked'):
    if profile not in PROFILES:raise ValueError('Choose a supported player profile')
    if filesystem not in ('fat32','not_checked'):raise ValueError('Choose FAT32 or leave the filesystem unchecked')
    rule=PROFILES[profile];rows=[];counts=Counter(tracks_with_findings=0,tracks_with_unknowns=0)
    for track in snapshot['tracks']:
        issues=[];unknown=[]
        fmt=str(track.get('format') or '').upper()
        fmt={'AIF':'AIFF','APPLE LOSSLESS':'ALAC'}.get(fmt,fmt)
        if not fmt:unknown.append('audio format')
        elif rule['formats'] and fmt not in rule['formats']:issues.append('Format is not listed in the selected profile: '+fmt)
        elif not rule['formats']:unknown.append('player format rules')
        size=finite(track.get('size'))
        if filesystem=='fat32':
            if size is None:unknown.append('file size')
            elif size>FAT32_MAX_BYTES:issues.append('File exceeds the FAT32 single-file limit of 4 GiB minus 1 byte')
        else:unknown.append('destination filesystem')
        path=str(track.get('current_path') or track.get('xml_location') or track.get('original_path') or '')
        if path.startswith('file:'):path=unquote(urlsplit(path).path)
        parts=[p for p in path.replace('\\','/').split('/') if p and not re.fullmatch('[A-Za-z]:',p)]
        if any(RESERVED.match(p) or p.endswith((' ','.')) or any(c in p for c in '<>:"|?*') for p in parts):
            issues.append('Recorded path contains a Windows-reserved name or character; review destination naming')
        if not path:unknown.append('recorded path')
        if track.get('size')==0:issues.append('Captured audio file size is zero')
        counts['tracks_with_findings']+=bool(issues);counts['tracks_with_unknowns']+=bool(unknown)
        rows.append(finding('export_readiness',track,'; '.join(issues+['Unknown: '+', '.join(unknown)] if unknown else issues) or 'No issue in the checked metadata rules',
                            severity='review' if issues else 'unknown' if unknown else 'info',issues=issues,unknown=unknown,
                            captured_format=fmt,captured_bytes=track.get('size')))
    return {'tracks':len(snapshot['tracks']),**counts,'profile':rule['label'],'profile_version':PROFILE_VERSION,
            'rule_source':rule['source'],'filesystem':filesystem,
            'note':'Metadata preflight only. File decoding, sample rate, bit depth, device database, firmware and physical playback are not checked.'},rows


def tempo_key_review(snapshot):
    rows=[];counts=Counter(tempo_disagreements=0,tempo_agreements=0,tempo_comparison_unknown=0,keys_recognized=0,keys_unknown=0)
    for track in snapshot['tracks']:
        saved=finite(track.get('bpm'));other=finite(track.get('xml_bpm'))
        grid=[n for v in (track.get('grid_bpms') or []) if (n:=finite(v)) is not None]
        evidence=sorted(set(([other] if other else [])+grid))
        if saved and evidence:
            mismatch=[v for v in evidence if abs(saved-v)>max(.1,saved*.01)]
            if mismatch:
                half_double=any(abs(saved/v-2)<.02 or abs(v/saved-2)<.02 for v in mismatch)
                rows.append(finding('tempo_disagreement',track,'Possible half/double-tempo disagreement' if half_double else 'Saved BPM differs from captured XML/grid tempo; variable tempo can be intentional',
                                    saved_bpm=saved,evidence_bpms=evidence,half_double=half_double))
                counts['tempo_disagreements']+=1
            else:counts['tempo_agreements']+=1
        else:counts['tempo_comparison_unknown']+=1
        key=camelot(track.get('tonality'))
        if key:
            order=2*(key[0]-1)+(key[1]=='B')
            rows.append(finding('musical_key',track,'Captured key in musical wheel order',severity='info',
                                captured_key=track.get('tonality'),camelot=f'{key[0]}{key[1]}',musical_order=order))
            counts['keys_recognized']+=1
        else:
            rows.append(finding('key_unknown',track,'Missing or unrecognized saved key; no key is inferred',captured_key=track.get('tonality')))
            counts['keys_unknown']+=1
    rows.sort(key=lambda r:(r['section']!='tempo_disagreement',r.get('musical_order',99),str(r.get('title','')),str(r.get('track_id',''))))
    return {'tracks':len(snapshot['tracks']),**counts,
            'note':'Saved metadata only. Musical key rows use Camelot wheel order. No audio was analyzed and no BPM, key or beatgrid was changed.'},rows
