"""Audit selected analysis locations without changing sources or deleting assets."""
from collections import defaultdict
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import errno
import os
import stat
import time
import zipfile

from analyzer import analysis_folder
from discovery import ANALYSIS
from media import file_record,cloud_placeholder
from asset_formats import format_candidate,inspect_format,PROBE_LIMIT,SETTINGS,CATALOGS,basename
from task_control import OperationCancelled
from stems_formats import stem_candidate,cache_candidate,CACHE_FOLDERS,ContainerLimit
from stems_cache import provider_report,recordbox_inventory
from stems_eligibility import context as stems_context


def asset_stamp(path,strong=False):
    record=file_record(path)
    if strong:
        current=path.stat()
        record.update(inode=current.st_ino,device=current.st_dev,ctime_ns=current.st_ctime_ns)
    return record


def audit_assets(snapshot,source,progress,verify=False,max_hash_bytes=256*1024**2,
                 max_directories=160000,max_files=300000,max_seconds=45,inspect=False,max_inspect_bytes=8*1024**2,profile=None,allow_empty=False):
    values=source if isinstance(source,list) else [source]
    if not 1<=len(values)<=20:raise ValueError('Choose between one and twenty analysis folders or backup ZIPs')
    roots=[];root_keys=set();source_aliases=[]
    for value in values:
        path=Path(str(value).strip().strip('"')).expanduser()
        if not path.is_absolute() or not path.exists():raise ValueError('Choose accessible absolute paths to analysis folders or backup ZIPs')
        selected=path;path=path.resolve()
        if path.is_dir():source_aliases.append((selected,path))
        if str(path) not in root_keys:roots.append(path);root_keys.add(str(path))
    folders={};seen_files=set();scopes=[];warnings=[];hash_bytes=0;skipped=0;partial=False;directories=0;files_seen=0;started=time.monotonic()
    stem_files={};inspection_records={};extension_counts=defaultdict(lambda:{'files':0,'bytes':0})
    def stem_evidence(path,size,identity,record,scope):
        name=path.replace('\\','/').casefold();parts=name.split('/')
        documented=name.endswith('.rbsc')
        hint=stem_candidate(path) or cache_candidate(path)
        if hint:stem_files[identity]={'path':path,'scope':scope,'bytes':size,'evidence':'RBSC drum-capture filename type; binary format unverified' if documented else 'Filename/folder candidate; purpose unverified','rbsc':documented}
        if inspect and (hint or format_candidate(path)):inspection_records[identity]=(path,scope,record)
    def exceeded():return directories>=max_directories or files_seen>=max_files or time.monotonic()-started>=max_seconds
    def add(scope,location,reference,record,identity):
        if identity in seen_files:return
        seen_files.add(identity)
        if inspect:inspection_records[identity]=(location+'/'+record['name'],scope,record)
        folder=folders.setdefault(location,{'path':location,'reference_key':reference,'scope':scope,'files':[]})
        folder['files'].append(record)
        ext=Path(record['name']).suffix.casefold() or '(none)';extension_counts[ext]['files']+=1;extension_counts[ext]['bytes']+=record['bytes']
    with ExitStack() as stack:
        archive_stamps=[];incomplete_archives=set()
        for root in roots:
            if exceeded():partial=True;warnings.append('Inventory budget reached; selected scopes were only partially inspected.');break
            scope=str(root);scopes.append({'path':scope,'kind':'ZIP' if root.is_file() else 'folder'})
            progress(5,'Inventorying selected analysis scope: '+root.name)
            if root.is_file():
                if root.suffix.lower()!='.zip':raise ValueError('Choose analysis folders or native backup ZIPs')
                stamp=asset_stamp(root,inspect)
                if stamp['cloud_only']:raise ValueError('Make the selected backup ZIP available locally first')
                archive=stack.enter_context(zipfile.ZipFile(root));archive_stamps.append((root,stamp))
                archive_names=set()
                for info in archive.infolist():
                    files_seen+=1
                    if exceeded():
                        partial=True
                        incomplete_archives.add(scope)
                        break
                    name=info.filename.replace('\\','/');reference=analysis_folder(name)
                    parts=Path(name).parts
                    if name.startswith('/') or '..' in parts or ':' in name or name in archive_names or stat.S_ISLNK(info.external_attr>>16):
                        raise ValueError('Backup contains repeated, linked or unsafe member paths')
                    archive_names.add(name)
                    record={'name':Path(name).name,'bytes':info.file_size,'crc':info.CRC,'source':info.filename,'archive':archive,'cloud':False}
                    if not info.is_dir():stem_evidence(name,info.file_size,(scope,info.filename),record,scope)
                    if info.is_dir() or not (reference or ANALYSIS.fullmatch(Path(name).name)):continue
                    location=scope+'!/'+name.rpartition('/')[0]
                    add(scope,location,reference,record,(scope,info.filename))
            else:
                def on_error(error):warnings.append(str(error))
                for directory,dirs,names in os.walk(root,followlinks=False,onerror=on_error):
                    directories+=1
                    if exceeded():partial=True;break
                    children=[]
                    for n in dirs:
                        child=Path(directory)/n
                        try:
                            if child.is_symlink() or child.is_junction():continue
                            if cloud_placeholder(child.stat()):warnings.append('Skipped online-only folder: '+str(child));continue
                            children.append(n)
                        except OSError as error:warnings.append(str(error))
                    dirs[:]=children
                    for name in names:
                        files_seen+=1
                        if exceeded():partial=True;break
                        path=Path(directory)/name;reference=analysis_folder(str(path))
                        if path.is_symlink():continue
                        hint=stem_candidate(str(path)) or cache_candidate(str(path))
                        if not (reference or ANALYSIS.fullmatch(name) or hint or inspect and format_candidate(name)):continue
                        try:stamp=asset_stamp(path,inspect)
                        except OSError as error:warnings.append(str(error));continue
                        record={'name':name,'bytes':stamp['size'],'source':str(path),'archive':None,'cloud':stamp['cloud_only'],'stamp':stamp}
                        stem_evidence(str(path),stamp['size'],str(path),record,scope)
                        if not (reference or ANALYSIS.fullmatch(name)):continue
                        add(scope,str(path.parent),reference,record,str(path))
                    if directories%250==0:progress(15,'Indexed '+str(len(folders))+' analysis locations')
                    if partial:break
            if partial:warnings.append('Inventory budget reached; results are partial. Choose narrower paths.');break
        if not allow_empty and not folders and not stem_files and not inspection_records:raise ValueError('No analysis, STEMS, player-settings or device-catalog candidate assets were found in these selected scopes')
        references={k for p in snapshot.get('asset_references',[]) if (k:=analysis_folder(p))}
        complete=snapshot.get('capabilities',{}).get('analysis_references',False)
        found_keys={f['reference_key'] for f in folders.values() if f['reference_key']}
        rows=[]
        rows.extend({'section':'stems_related_asset','asset_family':'candidate','provider':'unknown','severity':'info' if f['rbsc'] else 'review','title':Path(f['path']).name,'detail':f['evidence'],**f} for f in stem_files.values())
        for key in sorted(references-found_keys):rows.append({'section':'asset_missing','severity':'review','title':key,'detail':'Referenced folder not found in the inspected scope'+(' (inventory incomplete)' if partial or warnings else '')})
        for location,folder in folders.items():
            key=folder['reference_key']
            if not key or key not in references:
                known=complete and bool(key)
                rows.append({'section':'asset_unreferenced' if known else 'asset_ownership_unknown','severity':'review','title':key or location,
                             'detail':'No active owner in this captured reference set; another library may still own these assets' if known else 'Ownership cannot be established from this snapshot/path layout',
                             'path':location,'scope':folder['scope'],'bytes':sum(f['bytes'] for f in folder['files'])})
        profiles=defaultdict(list)
        for location,folder in folders.items():profiles[tuple(sorted((f['name'].casefold(),f['bytes']) for f in folder['files']))].append(location)
        candidates=verified_groups=verified_bytes=0
        def duplicate_row(section,locations,detail,reason=''):
            return {'section':section,'severity':'review','title':folders[locations[0]]['reference_key'] or locations[0],'detail':detail,
                    'folders':[folders[k]['reference_key'] for k in locations],
                    'locations':[{'path':k,'scope':folders[k]['scope'],'reference_key':folders[k]['reference_key']} for k in locations],
                    'potential_extra_bytes':sum(f['bytes'] for k in locations[1:] for f in folders[k]['files']),'verification_note':reason}
        for locations in profiles.values():
            if len(locations)<2:continue
            candidates+=1;digests={};reason=''
            if verify and not partial and not warnings:
                for location in locations:
                    digest=sha256()
                    for f in sorted(folders[location]['files'],key=lambda f:f['name'].casefold()):
                        if f['cloud']:reason='Online-only analysis assets were not read';skipped+=1;break
                        if not ANALYSIS.fullmatch(f['name']):reason='Verification is limited to recognized ANLZ analysis members';skipped+=1;break
                        if hash_bytes+f['bytes']>max_hash_bytes:reason='Explicit verification byte budget reached';skipped+=1;break
                        if not f['archive'] and asset_stamp(Path(f['source']),inspect)!=f['stamp']:raise ValueError('An analysis file changed after inventory; capture again')
                        digest.update((f['name'].casefold()+'\0'+str(f['bytes'])+'\0').encode())
                        stream=f['archive'].open(f['source']) if f['archive'] else Path(f['source']).open('rb')
                        with stream:
                            while chunk:=stream.read(min(2*1024**2,max_hash_bytes-hash_bytes+1)):
                                if hash_bytes+len(chunk)>max_hash_bytes:reason='Explicit verification byte budget reached';skipped+=1;break
                                digest.update(chunk);hash_bytes+=len(chunk)
                        if not f['archive'] and asset_stamp(Path(f['source']),inspect)!=f['stamp']:raise ValueError('An analysis file changed during verification; capture again')
                        progress(50,'Verifying explicitly selected candidate analysis bytes')
                        if reason:break
                    if reason:break
                    digests[location]=digest.hexdigest()
            elif verify:reason='Incomplete inventory; whole analysis-member sets were not verified'
            if len(digests)==len(locations) and not reason:
                equals=defaultdict(list)
                for location,digest in digests.items():equals[digest].append(location)
                for group in equals.values():
                    if len(group)<2:continue
                    record=duplicate_row('asset_duplicate_verified',group,'Identical analysis member names and bytes verified by SHA-256')
                    rows.append(record);verified_groups+=1;verified_bytes+=record['potential_extra_bytes']
                if len(equals)>1:
                    record=duplicate_row('asset_bytes_differ',locations,'Matching member names/sizes, but SHA-256 content differs')
                    record['potential_extra_bytes']=0;rows.append(record)
            else:rows.append(duplicate_row('asset_duplicate_candidate',locations,'Matching analysis member names/sizes; content equality not established',reason))
        inspection_summary={}
        if inspect:
            inspection_rows,inspection_summary,used=inspect_records(inspection_records,progress,verify,
                max_inspect_bytes,max(0,max_hash_bytes-hash_bytes),deadline=started+max_seconds)
            comparisons=compare_analysis_tempos(snapshot,inspection_rows)
            inspection_summary['tempo_disagreements']=len(comparisons)
            provider_rows,provider_summary=provider_report(inspection_rows,roots,profile or stems_context(),progress,
                started+max_seconds,inventory_complete=not partial and not warnings,source_aliases=source_aliases)
            pairs,inspection_summary['recordbox_saved_stems']=recordbox_inventory(inspection_rows,progress,incomplete_archives)
            rows.extend(usb_catalog_folders(inspection_rows))
            for record in inspection_rows:
                for key in list(record):
                    if key.startswith('_'):record.pop(key)
            for _,_,f in inspection_records.values():
                if not f['archive'] and asset_stamp(Path(f['source']),True)!=f['stamp']:
                    raise ValueError('An asset changed before report publication; capture again')
            rows.extend(inspection_rows);rows.extend(comparisons);rows.extend(provider_rows);hash_bytes+=used
            rows.extend(pairs)
            inspection_summary['provider_cache']=provider_summary
        for root,stamp in archive_stamps:
            if asset_stamp(root,inspect)!=stamp:raise ValueError('A backup ZIP changed during the audit; capture again')
        return {'scopes':scopes,'folders':len(folders),'files':sum(len(f['files']) for f in folders.values()),
                'analysis_extensions':[{'extension':ext,**totals} for ext,totals in sorted(extension_counts.items(),key=lambda item:-item[1]['bytes'])],
                'stems':{'prepared_tracks':None,'preparation_status':'Unavailable: no validated persistent per-track STEMS indicator is decoded',
                         'related_candidate_files':len(stem_files),'related_candidate_bytes':sum(f['bytes'] for f in stem_files.values()),
                         'rbsc_drum_capture_files':sum(f['rbsc'] for f in stem_files.values()),
                         'note':'RBSC captures and filename hints do not establish how many tracks are STEMS-ready. General ANLZ containers are not counted as separated audio.'},
                **({'format_inspection':inspection_summary} if inspect else {}),
                'logical_bytes':sum(m['bytes'] for f in folders.values() for m in f['files']),
                'missing_in_scope':len(references-found_keys),'ownership_complete':complete,
                'unreferenced_folders':sum(bool(f['reference_key']) and f['reference_key'] not in references for f in folders.values()) if complete else None,
                'ownership_unknown_folders':sum(not f['reference_key'] or not complete for f in folders.values()),
                'duplicate_candidate_groups':candidates,'verified_duplicate_groups':verified_groups,'verified_extra_logical_bytes':verified_bytes,
                'bytes_hashed':hash_bytes,'verification_skipped':skipped,'inventory_complete':not partial and not warnings,'source_writes':False,'scope_warnings':warnings[:100]},rows


def usb_catalog_folders(records):
    """Group observed catalog names within their own device directory or ZIP member prefix."""
    folders = {}
    for row in records:
        name = row['title']
        if name.casefold() not in CATALOGS:
            continue
        archive = row['_archive_scope']
        if archive:
            # ZIP names are literal. Do not combine aliases such as a/./PIONEER and a/PIONEER.
            parent = row['_source'].replace('\\', '/').rpartition('/')[0]
            parts = parent.rsplit('/', 2)[-2:]
        else:
            directory = Path(row['_source']).parent
            parent = str(directory)
            parts = directory.parts[-2:]
        if tuple(part.casefold() for part in parts) != ('pioneer', 'rekordbox'):
            continue
        # Keep the directory spelling: case-distinct folders can coexist in a ZIP or on Linux.
        members = folders.setdefault((archive, parent), {})
        # Keep one spelling per role even for case-sensitive archives with many variants.
        label, count = members.get(name.casefold(), (name, 0))
        members[name.casefold()] = (min(label, name), count + 1)

    for (archive, parent), members in sorted(folders.items()):
        classic = 'export.pdb' in members
        onelibrary = 'exportlibrary.db' in members
        if classic and onelibrary:
            layout = 'mixed'
            detail = 'Both catalog names were found. Their playlists and histories can differ.'
        elif classic:
            layout = 'classic'
            detail = 'Found the classic Device Library catalog name.'
        elif onelibrary:
            layout = 'onelibrary'
            detail = 'Found the OneLibrary catalog name.'
        else:
            layout = 'companion'
            detail = 'Found the classic companion file without an observed main catalog.'
        location = archive + '!/' + parent if archive else parent
        yield {'section':'usb_catalog_folder', 'severity':'info', 'asset_family':'device_catalog',
               'provider':'rekordbox', 'title':location, 'path':location, 'detail':detail,
               'source_kind':'ZIP' if archive else 'folder', 'catalog_directory':parent,
               'catalog_layout':layout, 'catalog_filenames':dict(sorted(members.values())), 'records_decoded':False,
               'player_compatibility':None}


def inspect_records(records,progress,verify,max_inspect_bytes,max_hash_bytes,deadline):
    """Bound reads by bytes actually consumed; only local files allow sparse metadata seeks."""
    from pathlib import PurePosixPath
    rows=[];counts=defaultdict(int);inspected=hashed=0
    marker_roots=[]
    for _,scope,f in records.values():
        if basename(f['name'])=='.rbstemsplus-cache':marker_roots.append((scope if f['archive'] else '',PurePosixPath(f['source'].replace('\\','/')).parent))
    def unchanged(f):
        if not f['archive'] and (Path(f['source']).is_symlink() or asset_stamp(Path(f['source']),True)!=f['stamp']):
            raise ValueError('An asset changed during format inspection; capture again')
    def stream(f):
        if f['archive']:
            return f['archive'].open(f['source'])
        path = Path(f['source'])
        if path.suffix.lower() == '.stems':
            if hasattr(os, 'O_NOATIME'):
                # Recordbox uses last access to choose which saved separations to evict.
                try:
                    return open(path, 'rb', buffering=0, opener=lambda name, flags: os.open(name, flags | os.O_NOATIME))
                except OSError as error:
                    if error.errno not in (errno.EPERM, errno.EACCES, errno.EINVAL, errno.EOPNOTSUPP):
                        raise
            return path.open('rb', buffering=0)
        return path.open('rb')
    def wanted(f,prefix):
        name=basename(f['name'])
        if prefix.startswith(b'PMAI'):return PROBE_LIMIT
        if prefix.startswith(b'PDSTEMS1'):return 16
        if name in SETTINGS:return 160
        if name in ('export.pdb','exportext.pdb'):return 1052
        if prefix.startswith(b'rbstemsplus-') or name.endswith(('.manifest','.kept')):return PROBE_LIMIT
        if prefix.startswith((b'RBD1',b'RBD2')) or name.endswith('.desc'):return 8216
        if prefix[4:8]==b'ftyp' and f['archive']:return PROBE_LIMIT
        return 64
    for path,scope,f in records.values():
        progress(75,'Inspecting selected file formats')
        source=PurePosixPath(f['source'].replace('\\','/'));archive_scope=scope if f['archive'] else ''
        provider_context=any(part.casefold() in CACHE_FOLDERS for part in source.parts[:-1]) or any(s==archive_scope and source.is_relative_to(root) for s,root in marker_roots)
        record={'section':'format_evidence','title':f['name'],'path':path,'scope':scope,'bytes':f['bytes'],
                'validation':'not_checked','format':'unknown','checksum_status':'not_checked',
                'native_stems_readiness':None,'source_association':'unknown','_source':f['source'],'_archive_scope':archive_scope}
        if f['cloud']:record['detail']='Online-only asset was not opened'
        elif time.monotonic()>=deadline:record['detail']='Format inspection time budget reached'
        elif inspected>=max_inspect_bytes:record['detail']='Format inspection byte budget reached'
        else:
            unchanged(f)
            try:
                initial=min(f['bytes'],16,max_inspect_bytes-inspected)
                with stream(f) as reader:
                    prefix=reader.read(initial);inspected+=len(prefix)
                    limit=max(len(prefix),min(f['bytes'],wanted(f,prefix),max_inspect_bytes-inspected+len(prefix)))
                    if limit>len(prefix):
                        extra=reader.read(limit-len(prefix));prefix+=extra;inspected+=len(extra)
                    def read_at(offset,length):
                        nonlocal inspected
                        if offset+length<=len(prefix):return prefix[offset:offset+length]
                        if f['archive']:raise ContainerLimit('Movie metadata is beyond the bounded ZIP prefix; inspect a selected local copy')
                        if length>max_inspect_bytes-inspected or time.monotonic()>=deadline:raise ContainerLimit('Container inspection byte or time budget reached')
                        progress(75,'Reading bounded container metadata')
                        reader.seek(offset);value=reader.read(length);inspected+=len(value)
                        return value
                    minimum=16 if prefix.startswith(b'PDSTEMS1') else 64
                    ready=len(prefix)==limit and len(prefix)>=min(f['bytes'],minimum)
                    if len(prefix)!=limit:record.update(validation='corrupt',detail='Asset became shorter than its inventoried size')
                    elif not ready:record['detail']='Format inspection byte budget reached before the initial probe was complete'
                    elif prefix[4:8]==b'ftyp':record.update(inspect_format(f['name'],prefix,f['bytes'],read_at=read_at))
                # Prefix-only parsers need no live handle. Closing it also lets
                # Windows replacements be detected by the final identity check.
                if ready and prefix[4:8]!=b'ftyp':
                    if cache_candidate(f['source']):record.update(inspect_format(f['name'],prefix,f['bytes'],provider_context=provider_context))
                    else:record.update(inspect_format(f['name'],prefix,f['bytes']))
                if verify:
                    if f['bytes']>max_hash_bytes-hashed:record['checksum_status']='budget_exceeded'
                    elif time.monotonic()>=deadline:record['checksum_status']='time_budget_exceeded'
                    else:
                        digest=sha256();actual=0;complete=True
                        with stream(f) as reader:
                            while chunk:=reader.read(min(1024**2,max_hash_bytes-hashed+1)):
                                progress(80,'Verifying selected asset bytes')
                                hashed+=len(chunk);actual+=len(chunk)
                                if hashed>max_hash_bytes:raise ValueError('Asset verification exceeded its byte budget')
                                digest.update(chunk)
                                if time.monotonic()>=deadline:complete=False;break
                        if complete and actual==f['bytes']:
                            record.update(checksum_status='computed',sha256=digest.hexdigest(),zip_crc_verified=bool(f['archive']),
                                          checksum_basis='SHA-256 fingerprint computed; no trusted reference digest was supplied')
                        elif complete:
                            record.update(checksum_status='size_mismatch',validation='corrupt',
                                          detail=f'Full read returned {actual} bytes. The inventoried size is {f["bytes"]} bytes.')
                        else:record['checksum_status']='time_budget_exceeded'
            except OperationCancelled:raise
            except (OSError,zipfile.BadZipFile,RuntimeError) as error:
                record.update(validation='corrupt' if isinstance(error,zipfile.BadZipFile) else 'not_checked',
                              detail='Asset could not be completely inspected: '+str(error),checksum_status='failed')
            unchanged(f)
        kind=record['format']
        family,provider={'anlz':('analysis','rekordbox'),'anlz_3ex':('analysis','rekordbox'),'player_settings':('player_settings','rekordbox'),
                         'device_sql':('device_catalog','rekordbox'),'onelibrary_catalog':('device_catalog','rekordbox'),
                         'recordbox_stems_v1':('separation_cache','recordbox'),'rbsc_candidate':('capture','rekordbox')}.get(kind,('candidate','unknown'))
        record.setdefault('asset_family',family);record.setdefault('provider',provider)
        if record.get('cache_state')=='present' and record['validation']!='recognized':
            record['cache_state']='unknown'
        if kind=='recordbox_stems_v1':record.setdefault('cache_state','present' if record['validation']=='recognized' else 'unknown')
        record['severity']='info' if record['validation']=='recognized' else 'review'
        record['section']={'anlz':'analysis_format','anlz_3ex':'analysis_format','player_settings':'player_settings','device_sql':'device_catalog',
                           'onelibrary_catalog':'device_catalog','recordbox_stems_v1':'stems_cache','ni_stems_v1':'stems_container'}.get(kind,'provider_cache_metadata' if kind.startswith('rbstems_') else 'format_candidate')
        counts[record['validation']]+=1;counts[kind]+=1;counts[kind+'_'+record['validation']]+=1
        if record['checksum_status']=='computed':counts['fingerprinted_files']+=1
        rows.append(record)
    return rows,{'files':len(rows),'recognized':counts['recognized'],'corrupt':counts['corrupt'],
                 'unsupported':counts['unsupported'],'not_checked':counts['not_checked'],
                 'recognized_stems_caches':counts['recordbox_stems_v1_recognized'],
                 'recognized_ni_containers':counts['ni_stems_v1_recognized'],
                 'stems_cache_candidates':counts['recordbox_stems_v1'],'fingerprinted_files':counts['fingerprinted_files'],
                 'valid_player_settings':counts['player_settings_recognized'],
                 'classic_catalog_headers':counts['device_sql_recognized'],'onelibrary_candidates':counts['onelibrary_catalog'],
                 'bytes_inspected':inspected,'inspection_budget_bytes':max_inspect_bytes,
                 'bytes_hashed':hashed,'checksum_budget_bytes':max_hash_bytes,
                 'catalogs':counts['device_sql']+counts['onelibrary_catalog'],
                 'note':'Recognized structure does not prove source association, native STEMS readiness or target-player support'},hashed


def compare_analysis_tempos(snapshot,rows):
    from backup_manifest import analysis_member
    from migration_readiness import finite
    by_reference=defaultdict(list);findings=[]
    for track in snapshot.get('tracks',[]):
        if key:=analysis_member(track.get('analysis_path')):by_reference[key].append(track)
    for row in rows:
        if row.get('format')!='anlz' or row['validation']!='recognized':continue
        candidates=by_reference.get(analysis_member(row['path']),[])
        if len(candidates)!=1:continue
        track=candidates[0];saved=finite(track.get('bpm'))
        tempos=sorted({bpm for grid in row.get('tempo_evidence',[]) for bpm in grid['bpms']})
        row['tempo_reference']={'track_id':track.get('id'),'saved_bpm':saved,
                                'basis':'Normalized captured file reference; content association is not verified',
                                'grid_tempos_complete':all(g.get('bpms_complete',True) for g in row.get('tempo_evidence',[]))}
        if saved is None or not tempos:continue
        if not row['tempo_reference']['grid_tempos_complete']:continue
        if not any(abs(saved-bpm)<=.02 for bpm in tempos):
            findings.append({'section':'analysis_tempo_disagreement','severity':'review','validation':'recognized',
                             'track_id':track.get('id'),'title':track.get('title',''),'artist':track.get('artist',''),
                             'saved_bpm':saved,'analysis_bpms':tempos,'path':row['path'],'scope':row['scope'],
                             'half_double':any(abs(saved*2-bpm)<=.04 or abs(saved-bpm*2)<=.04 for bpm in tempos),
                             'detail':'Captured saved BPM differs from this referenced analysis grid; review tempo evidence before migration'})
    return findings
