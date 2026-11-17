"""Versioned source/session advisories; declared settings never prove native preparation."""
from collections import Counter
from hashlib import sha256
from pathlib import PureWindowsPath
import re
from urllib.parse import urlsplit

PROFILE_VERSION='2026-11-17.1'
SOURCES={'faq':'https://rekordbox.com/en/support/faq/rekordbox7/',
         'manual':'https://cdn.rekordbox.com/files/20260807093645/rekordbox7.2.18_manual_EN.pdf',
         'cache':'https://github.com/Gabe-LS/rbstemsplus/tree/bb6731672a68b03de2e485901c57736aed349824'}
PIONEER_MODEL='435c987855f7ea74ff5f20090541748cbbce5a2e8e501d07b10f4e703453215a'
ENUMS={'target':('unknown','native','rbstemsplus'),'enabled':('unknown','enabled','disabled'),
       'mode':('unknown','performance','export'),'quality':('unknown','quality','speed'),
       'parts':('unknown','3','4'),'source_provider':('unknown','local','apple_music','spotify','other_streaming'),
       'platform':('unknown','macos','windows','linux'),'architecture':('unknown','arm64','x86_64')}
TEXT_FIELDS=('app_version','engine_version','runtime_version','model_sha256')


def context(value=None):
    if value is None:value={}
    if not isinstance(value,dict) or set(value)-set(ENUMS)-set(TEXT_FIELDS):raise ValueError('Choose supported STEMS session settings')
    result={}
    for key,choices in ENUMS.items():
        field=value.get(key,'unknown')
        if field not in choices:raise ValueError('Choose a supported STEMS '+key.replace('_',' '))
        result[key]=field
    for key in TEXT_FIELDS:
        field=value.get(key,'')
        if not isinstance(field,str) or len(field)>64 or any(ord(c)<32 for c in field):raise ValueError('Provide a bounded STEMS '+key.replace('_',' '))
        result[key]=field.strip()
    if result['model_sha256'] and not re.fullmatch('[0-9a-fA-F]{64}',result['model_sha256']):raise ValueError('Provide a full 64-digit SHA-256 model fingerprint')
    result['model_sha256']=result['model_sha256'].lower()
    result.update(basis='User-declared session settings; not detected from a running application',profile_version=PROFILE_VERSION)
    return result


def namespace_status(namespace,profile):
    digest=profile.get('model_sha256')
    if not digest:return 'unknown'
    possible={digest}
    if digest==PIONEER_MODEL:possible.add(sha256(('rbstems-rebuild-1:'+digest).encode()).hexdigest())
    return 'matches_declared_model' if namespace in possible else 'model_mismatch'


def cache_profile(profile):
    if profile.get('target')!='rbstemsplus':return 'unknown'
    if profile.get('quality')=='speed' or profile.get('mode')=='export' or profile.get('enabled')=='disabled' or profile.get('platform') in ('windows','linux'):return 'profile_mismatch'
    if profile.get('architecture')=='x86_64':return 'unverified_version'
    known={'app_version':{'7.2.17','7.2.18','7.2.19'},'engine_version':{'0002'}}
    for field,values in known.items():
        if profile.get(field) and profile[field] not in values:return 'unverified_version'
    if profile.get('runtime_version') and not re.fullmatch(r'1\.18\.[0-9]+(?:\.[0-9]+)?',profile['runtime_version']):return 'unverified_version'
    required=(profile.get('quality')=='quality' and profile.get('mode')=='performance' and profile.get('enabled')=='enabled'
              and profile.get('platform')=='macos' and profile.get('architecture')=='arm64'
              and all(profile.get(k) for k in ('app_version','engine_version','runtime_version','model_sha256')))
    return 'matches_declared_profile' if required else 'unknown'


def provider(track,profile):
    raw=track.get('source_evidence') or {}
    label=str(raw.get('provider') or track.get('source_provider') or '').casefold().replace(' ','').replace('_','')
    names={'applemusic':'apple_music','spotify':'spotify','local':'local','otherstreaming':'other_streaming'}
    if label in names:return names[label],raw.get('basis','Captured provider label')
    service=raw.get('service_id')
    if service not in (None,''):
        normalized=str(service).casefold().replace(' ','')
        if normalized in names:return names[normalized],'Captured service label'
        if profile.get('source_provider','unknown')!='unknown':return profile['source_provider'],'User-declared fallback; native service identifier is unmapped'
        return 'unknown','Unmapped native service identifier'
    path=str(track.get('current_path') or track.get('xml_location') or '')
    try:
        parts=urlsplit(path);host=(parts.hostname or '').casefold()
        if parts.scheme=='spotify' or host=='open.spotify.com':return 'spotify','Recorded Spotify location'
        if host=='music.apple.com':return 'apple_music','Recorded Apple Music location'
        if path.startswith('/') or PureWindowsPath(path).is_absolute() or parts.scheme=='file':return 'local','Recorded local file reference; access is not checked'
    except ValueError:pass
    return profile.get('source_provider','unknown'),'User-declared fallback provider' if profile.get('source_provider','unknown')!='unknown' else 'Provider evidence unavailable'


def eligibility(snapshot,profile,progress=lambda *_:None,max_rows=10000):
    rows=[];counts=Counter();tracks=snapshot.get('tracks',[])
    for index,track in enumerate(tracks):
        if index%250==0:progress(10+70*index/max(1,len(tracks)),'Checking STEMS source and session evidence')
        service,basis=provider(track,profile);reasons=[]
        if service in ('apple_music','spotify'):reasons.append('The official v7 FAQ excludes STEMS for this provider')
        if profile['enabled']=='disabled':reasons.append('STEMS is declared disabled')
        if profile['mode']=='export':reasons.append('The documented STEMS workflow is PERFORMANCE mode')
        state='blocked' if reasons else 'candidate' if service=='local' and profile['enabled']=='enabled' and profile['mode']=='performance' else 'unknown'
        counts[state]+=1
        if len(rows)>=max_rows:continue
        rows.append({'section':'stems_eligibility','title':track.get('title',''),'artist':track.get('artist',''),'track_id':track.get('id'),
                     'asset_family':'source_eligibility','provider':'rekordbox','source_provider':service,'eligibility':state,
                     'validation':'recognized' if state!='unknown' else 'not_checked','severity':'info' if state=='candidate' else 'review',
                     'provider_basis':basis,'cache_profile_status':cache_profile(profile),'native_stems_readiness':None,
                     'source_evidence':track.get('source_evidence'),
                     'profile_version':PROFILE_VERSION,'detail':'; '.join(reasons) if reasons else
                     'Local source and declared settings permit a candidate; decoding, plan, model and live readiness remain unverified' if state=='candidate' else
                     'Source or session evidence is incomplete; STEMS eligibility is unknown'})
    return {'tracks':len(tracks),'eligible_candidates':counts['candidate'],'blocked':counts['blocked'],'unknown':counts['unknown'],
            'retained_findings':len(rows),'findings_complete':len(rows)==len(tracks),'profile':profile,'sources':SOURCES,
            'native_prepared_tracks':None,'source_writes':False},rows
