"""Explicit, bounded local file-health scans over captured library metadata.

This is advisory evidence, separate from user review decisions. A full scan
runs in the existing cancellable job worker, never during page rendering.
"""
import ipaddress
import json
import re
import time
from flask import jsonify,request

from collection_sources import resolve
from file_status_cache import inspect as cached_inspect
from workbench_store import Store

PAGE_SIZE=50
BATCH_SIZE=100
STATUS=('playable','missing','inaccessible','unverified')
ORDER={'artist':'artist COLLATE NOCASE, title COLLATE NOCASE, track_id',
       'title':'title COLLATE NOCASE, artist COLLATE NOCASE, track_id',
       'status':"CASE status WHEN 'playable' THEN 0 WHEN 'missing' THEN 1 WHEN 'inaccessible' THEN 2 ELSE 3 END, artist COLLATE NOCASE, track_id",
       'checked':'checked_at, track_id',
       'playability':"CASE status WHEN 'playable' THEN 0 WHEN 'missing' THEN 1 WHEN 'inaccessible' THEN 1 ELSE 2 END, artist COLLATE NOCASE, track_id"}


def selected_source(source):
    if not isinstance(source,str) or not (re.fullmatch(r'(?:snapshot:|capture:)[0-9a-f]{32}',source)):
        raise ValueError('Choose a saved library snapshot or source capture')
    return source


def local_request():
    try:
        remote=ipaddress.ip_address(request.remote_addr or '')
        host=request.host.split(':')[0] if not request.host.startswith('[') else request.host[1:].split(']')[0]
        local_host=host=='localhost' or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
    return remote.is_loopback and local_host


def register(owner):
    app=owner.app
    def store():return Store(owner.DATA/'workbench-sidecar.sqlite3')

    @app.get('/api/file-health')
    def get_file_health():
        source=selected_source(request.args.get('source',''))
        status=request.args.get('status','all')
        provider=request.args.get('provider','all')
        sorting=request.args.get('sort','artist')
        direction=request.args.get('direction','asc')
        query=request.args.get('q','').strip().casefold()
        try:offset=int(request.args.get('offset',0))
        except (TypeError,ValueError):raise ValueError('Choose a valid offset') from None
        if (status not in ('all','not_playable','cloud_only','cloud_not_local',*STATUS)
                or provider not in ('all','dropbox','google_drive','other','unknown')
                or sorting not in ORDER or direction not in ('asc','desc') or not 0<=offset<=10000000 or len(query)>200):
            raise ValueError('Choose a supported file-health filter and sort')
        saved=store()
        with saved.connection() as db:
            # After a scan, avoid deserializing the entire (potentially 250k
            # track) saved JSON on every filter, sort or page request. Use the
            # indexed total, but still reject a missing/archived source.
            record=db.execute('SELECT total,done,checked_at,state FROM file_health_scans WHERE source=?',(source,)).fetchone()
            if record:
                if source.startswith('snapshot:'):
                    if not db.execute('SELECT 1 FROM snapshots WHERE id=?',(source[9:],)).fetchone():
                        raise ValueError('Choose an existing saved library snapshot')
                else:
                    root=owner.DATA/'analyzers'/source[8:]
                    report=root/'report.json'
                    metadata=root/'comparison.json' if (root/'comparison.json').is_file() else root/'metadata.json'
                    if (root.is_symlink() or root.is_junction() or
                            not report.is_file() or report.is_symlink() or
                            not metadata.is_file() or metadata.is_symlink()):
                        raise ValueError('Choose an existing saved source capture')
                total_records=record['total']
            else:
                total_records=len(resolve(owner,source)['tracks'])
            if total_records>250000:raise ValueError('This library exceeds the file-health scan limit')
            where='source=?';params=[source]
            if status=='not_playable':where+=" AND (status IN ('missing','inaccessible') OR cloud_state IN ('online_only','not_local'))"
            elif status=='cloud_only':where+=" AND cloud_state='online_only'"
            elif status=='cloud_not_local':where+=" AND cloud_state='not_local'"
            elif status!='all':where+=' AND status=?';params.append(status)
            if provider in ('dropbox','google_drive'):
                where+=' AND provider_checked=1 AND (providers & ?)<>0';params.append(1 if provider=='dropbox' else 2)
            elif provider=='other':where+=' AND provider_checked=1 AND providers=0'
            elif provider=='unknown':where+=' AND provider_checked=0'
            if query:where+=' AND instr(search_text,?)>0';params.append(query)
            matched=db.execute('SELECT count(*) FROM file_health_records WHERE '+where,params).fetchone()[0]
            order=ORDER[sorting]
            # Whitelisted clauses only: no SQL fragments from request values.
            # Reverse only the selected primary key; stable secondary keys
            # make successive pages deterministic.
            if direction=='desc':
                first,separator,tail=order.partition(', ')
                order=first+' DESC'+(separator+tail if separator else '')
            sql='SELECT track_id,title,artist,genre,status,checked_at,providers,provider_checked,cloud_state,logical_size,filename,provider_evidence FROM file_health_records WHERE '+where+' ORDER BY '+order+' LIMIT ? OFFSET ?'
            rows=[dict(r) for r in db.execute(sql,[*params,PAGE_SIZE,offset])]
            for row in rows:
                try:row['provider_evidence']=json.loads(row['provider_evidence'])
                except (TypeError,ValueError):row['provider_evidence']=[]
            counts={r['status']:r['n'] for r in db.execute('SELECT status,count(*) n FROM file_health_records WHERE source=? GROUP BY status',(source,))}
            observed=sum(counts.values())
            provider_counts=dict.fromkeys(('all','dropbox','google_drive','other','unknown'),0)
            provider_counts['all']=observed
            for row in db.execute('SELECT providers,provider_checked,count(*) n FROM file_health_records WHERE source=? GROUP BY providers,provider_checked',(source,)):
                if not row['provider_checked']:provider_counts['unknown']+=row['n'];continue
                if row['providers']&1:provider_counts['dropbox']+=row['n']
                if row['providers']&2:provider_counts['google_drive']+=row['n']
                if not row['providers']:provider_counts['other']+=row['n']
            cloud_counts={r['cloud_state']:r['n'] for r in db.execute('SELECT cloud_state,count(*) n FROM file_health_records WHERE source=? GROUP BY cloud_state',(source,))}
            unavailable=db.execute("SELECT count(*) FROM file_health_records WHERE source=? AND (status IN ('missing','inaccessible') OR cloud_state IN ('online_only','not_local'))",(source,)).fetchone()[0]
        return jsonify(source=source,source_total=total_records,checked=observed,
                       unchecked=max(0,total_records-observed),scan_state=('partial' if record and record['state']=='running' and observed<total_records else record['state']) if record else 'not_started',
                       scan_time=record['checked_at'] if record else None,
                       counts={name:counts.get(name,0) for name in STATUS},
                       provider=provider,provider_counts=provider_counts,cloud_counts=cloud_counts,unavailable_count=unavailable,
                       rows=rows,total=matched,offset=offset,sort=sorting,direction=direction,
                       note='Local metadata evidence from the last explicit scan. Provider labels match recorded or mapped paths, not a verified cloud inventory. Cloud absence is not proof of deletion. Re-scan after storage or path changes.')

    @app.post('/api/file-health/scan')
    def scan_file_health():
        if not local_request():raise ValueError('Local file-health inspection requires the local application')
        value=request.get_json(silent=True)
        if not isinstance(value,dict):raise ValueError('Provide a file-health scan request')
        source=selected_source(value.get('source'))
        # An explicit Scan normally refreshes all evidence; only an explicit
        # Continue partial request reuses previously checked records.
        force=value.get('force',True)
        if not isinstance(force,bool):raise ValueError('Choose a supported refresh mode')
        snapshot=resolve(owner,source)
        from audio_paths import mappings_for, signature
        mappings=mappings_for(store(),snapshot)
        mapping_revision=signature(mappings)
        tracks=snapshot['tracks']
        if len(tracks)>250000:raise ValueError('This library exceeds the file-health scan limit')
        if len({str(t['id']) for t in tracks})!=len(tracks):
            raise ValueError('File-health scanning requires unique track IDs')
        # Duplicate clicks cannot start multiple scans for the same source.
        jobs=getattr(owner,'tasks',{})
        for job in jobs.values():
            if job.get('status')=='running' and job.get('file_health_source')==source:
                return jsonify(job=job['id'],source=source,resumed=True)
        def work(progress):
            started=time.time()
            saved=store()
            progress(0,'Preparing local file-health inspection')
            with saved.connection() as db:
                if force:
                    db.execute('DELETE FROM file_health_records WHERE source=?',(source,))
                prior={row[0] for row in db.execute('SELECT track_id FROM file_health_records WHERE source=? AND provider_checked=1',(source,))}
                db.execute('INSERT OR REPLACE INTO file_health_scans (source,total,done,checked_at,state) VALUES (?,?,?,?,?)',
                           (source,len(tracks),len(prior),started,'running'))
            from cloud_file_status import provider_context
            roots=provider_context()
            remaining=[t for t in tracks if str(t['id']) not in prior]
            finished=False
            try:
                for index in range(0,len(remaining),BATCH_SIZE):
                    if signature(mappings_for(saved,snapshot))!=mapping_revision:
                        raise ValueError('Audio folder mappings changed. Start a new File health scan.')
                    batch=remaining[index:index+BATCH_SIZE]
                    probes={str(t['id']):t for t in batch}
                    # A scan is an explicit request for current filesystem
                    # evidence, never merely a replay of the status TTL.
                    states,_,details=cached_inspect(owner,probes,refresh=True,mappings=mappings,details=True,roots=roots)
                    with saved.connection() as db:
                        db.executemany('INSERT OR REPLACE INTO file_health_records (source,track_id,title,artist,genre,status,checked_at,search_text,providers,provider_checked,cloud_state,logical_size,filename,provider_evidence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            [(source,identity,str(t.get('title') or ''),str(t.get('artist') or ''),
                              str(t.get('genre') or ''),states[identity],time.time(),
                              ' '.join(str(t.get(k) or '') for k in ('id','title','artist','genre')).casefold(),
                              details[identity]['providers'],1,details[identity]['cloud_state'],
                              details[identity]['logical_size'],details[identity]['filename'],json.dumps(details[identity]['provider_evidence']))
                             for identity,t in probes.items()])
                        done=len(prior)+index+len(batch)
                        db.execute('UPDATE file_health_scans SET done=?,checked_at=? WHERE source=?',(done,time.time(),source))
                    progress(100*done/max(1,len(tracks)),f'Checking local files: {done:,} / {len(tracks):,}')
                finished=True
                return {'source':source,'tracks':len(tracks),'checked':len(tracks),'audio_files_modified':False,
                        'audio_contents_read':False,'cloud_api_requests':False}
            finally:
                with saved.connection() as db:
                    db.execute('UPDATE file_health_scans SET state=?,checked_at=? WHERE source=?',
                               ('complete' if finished else 'partial',time.time(),source))
        job=owner.launch(work,'Checking local file health')
        # Keep the existing task list useful for refresh and duplicate-click checks.
        if job in jobs:
            jobs[job]['file_health_source']=source
            jobs[job]['file_health_scope']=snapshot['scope_key']
        return jsonify(job=job,source=source,resumed=False)
