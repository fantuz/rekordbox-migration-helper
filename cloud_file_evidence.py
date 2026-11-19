"""Read source-scoped cloud metadata evidence beside local file-health results.

These functions never authorize, refresh tokens, call a provider or open audio.
An indexed cloud result is historical presence evidence, not local residency.
"""
from hashlib import sha256
import json
import math
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

from audio_paths import signature
from file_health import selected_source
from workbench_store import Store

STATUSES=('present','not_found','unmapped','ambiguous','unverified')


def provider_context(owner,source,setting,client,files):
    """Use one exact cache binding for provider pages and the File health join."""
    source=selected_source(source)
    saved=Store(owner.DATA/'workbench-sidecar.sqlite3')
    mapped=saved.setting(setting,None)
    if not isinstance(mapped,dict):raise ValueError('Verify the cloud folder attachment again.')
    key=files.binding(client,mapped)
    if mapped.get('source') and mapped['source']!=source:
        raise ValueError('Choose the collection attached to this cloud folder, or verify a new attachment.')
    if source.startswith('snapshot:'):
        with saved.connection() as db:
            row=db.execute('SELECT scope_key,digest FROM snapshots WHERE id=?',(source[9:],)).fetchone()
        if not row:raise ValueError('Choose an existing saved library snapshot.')
        scope,stamp=row['scope_key'],row['digest']
    else:
        folder=owner.DATA/'analyzers'/source[8:]
        if folder.is_symlink() or folder.is_junction():raise ValueError('Choose an ordinary saved source capture.')
        metadata=folder/'comparison.json'
        if not metadata.is_file():metadata=folder/'metadata.json'
        stamps=[]
        for path in (metadata,folder/'report.json'):
            if not path.is_file() or path.is_symlink():raise ValueError('Choose an existing saved source capture.')
            info=path.stat();stamps.append([info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns])
        scope,stamp=source,stamps
    if mapped.get('scope_key') and mapped['scope_key']!=scope:
        raise ValueError('The attached collection changed. Verify its cloud location again.')
    audio=saved.setting('audio_paths:'+str(scope),[])
    key=sha256(json.dumps([key,stamp,signature(audio)],sort_keys=True).encode()).hexdigest()
    return {'store':saved,'mapping':mapped,'key':key,'audio':audio}


def _summary(state):return {'state':state,'checked_at':None,'complete':None}


def refresh_download(profile,source,identity,track,mappings):
    """Refresh one completed transfer's local attributes, never a whole scan.

    Cloud clients may immediately evict or replace a newly published file.
    Inspect the current attributes instead of inferring access from success.
    Existing File health scan scope/totals are retained; no row is inserted.
    """
    from file_status_cache import inspect
    source=selected_source(source)
    bound=SimpleNamespace(DATA=Path(profile))
    statuses,_,details=inspect(bound,{identity:track},refresh=True,mappings=mappings,details=True)
    info=details[identity];checked=time.time()
    with Store(bound.DATA/'workbench-sidecar.sqlite3').connection() as db:
        updated=db.execute('UPDATE file_health_records SET status=?,checked_at=?,providers=?,provider_checked=1,cloud_state=?,logical_size=?,filename=?,provider_evidence=? WHERE source=? AND track_id=?',
            (statuses[identity],checked,info.get('providers',0),info.get('cloud_state','unknown'),
             info.get('logical_size'),info.get('filename',''),json.dumps(info.get('provider_evidence',[])),source,identity)).rowcount
    return {'status':statuses[identity],'checked_at':checked,'file_health_updated':bool(updated)}


def cached_evidence(owner,source,track_ids):
    """Read at most one displayed File health page from each provider index.

    Providers with no matching scan return no row evidence. A scan that lacks
    a particular indexed row leaves that row unverified, even if it completed.
    """
    import dropbox_connector
    import google_drive_connector
    source=selected_source(source)
    identities=list(dict.fromkeys(str(identity) for identity in track_ids))
    if len(identities)>50:raise ValueError('Read cloud evidence for one File health page at a time.')
    evidence={identity:[] for identity in identities};summaries={}
    providers=(('dropbox',dropbox_connector,'dropbox_mapping','dropbox_records','dropbox_scans'),
               ('google_drive',google_drive_connector,'google_drive_mapping','google_drive_records','google_drive_scans'))
    for provider,connector,setting,records,scans in providers:
        summaries[provider]=_summary('not_connected')
        try:
            client=connector.connection(owner)
            if not client.status().get('connected'):continue
            saved=Store(owner.DATA/'workbench-sidecar.sqlite3')
            if not saved.setting(setting,None):
                summaries[provider]=_summary('not_attached');continue
            context=connector.evidence_context(owner,source)
            summaries[provider]=_summary('not_checked')
            with context['store'].connection() as db:
                available={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?)",(records,scans))}
                if available!={records,scans}:continue
                scan=db.execute('SELECT payload FROM '+scans+' WHERE binding=? AND source=?',(context['key'],source)).fetchone()
                if not scan:continue
                scan=json.loads(scan[0])
                checked=scan.get('checked_at') if isinstance(scan,dict) else None
                if type(checked) not in (int,float) or checked<0 or checked>253402300799 or not math.isfinite(checked):
                    summaries[provider]=_summary('unavailable');continue
                complete=scan.get('complete') is True
                payloads={}
                if identities:
                    placeholders=','.join('?' for _ in identities)
                    for row in db.execute('SELECT track_id,payload FROM '+records+' WHERE binding=? AND source=? AND track_id IN ('+placeholders+')',
                                          (context['key'],source,*identities)):
                        payloads[row['track_id']]=json.loads(row['payload'])
            summaries[provider]={'state':'checked','checked_at':checked,'complete':complete}
            for identity in identities:
                payload=payloads.get(identity)
                status='unverified';remote=None
                if isinstance(payload,dict) and payload.get('track_id')==identity:
                    status=payload.get('status') if payload.get('status') in STATUSES else 'unverified'
                    remote=payload.get('remote')
                if status=='not_found' and not complete:status='unverified'
                if status=='present' and (not isinstance(remote,dict) or not isinstance(remote.get('id'),str) or not remote['id']):
                    status='unverified'
                item={'provider':provider,'status':status,'checked_at':checked,'complete':complete}
                if status=='present':
                    if provider=='dropbox':item['downloadable']=remote.get('is_downloadable',True) is True
                    else:item['downloadable']=isinstance(remote.get('capabilities'),dict) and remote['capabilities'].get('canDownload') is True
                evidence[identity].append(item)
        except (ValueError,OSError,RuntimeError,KeyError,TypeError,sqlite3.DatabaseError):
            # A stale/replaced folder, archived source or corrupt provider cache
            # must not prevent inspection of the separate local scan index.
            summaries[provider]=_summary('unavailable')
    return evidence,summaries
