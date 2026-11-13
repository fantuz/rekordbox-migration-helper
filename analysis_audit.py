"""Audit selected analysis locations without changing sources or deleting assets."""
from collections import defaultdict
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import os
import time
import zipfile

from analyzer import analysis_folder
from discovery import ANALYSIS
from media import file_record,cloud_placeholder


def audit_assets(snapshot,source,progress,verify=False,max_hash_bytes=256*1024**2,
                 max_directories=160000,max_files=300000,max_seconds=45):
    values=source if isinstance(source,list) else [source]
    if not 1<=len(values)<=20:raise ValueError('Choose between one and twenty analysis folders or backup ZIPs')
    roots=[];root_keys=set()
    for value in values:
        path=Path(str(value).strip().strip('"')).expanduser()
        if not path.is_absolute() or not path.exists():raise ValueError('Choose accessible absolute paths to analysis folders or backup ZIPs')
        path=path.resolve()
        if str(path) not in root_keys:roots.append(path);root_keys.add(str(path))
    folders={};seen_files=set();scopes=[];warnings=[];hash_bytes=0;skipped=0;partial=False;directories=0;files_seen=0;started=time.monotonic()
    stem_files={};extension_counts=defaultdict(lambda:{'files':0,'bytes':0})
    def stem_evidence(path,size,identity):
        name=path.replace('\\','/').casefold();parts=name.split('/')
        documented=name.endswith('.rbsc')
        hint=documented or name.endswith(('.stem','.stems','.stem.mp4','.stems.mp4')) or any(p in ('stems','stem','track separation','track_separation','trackseparation') for p in parts[:-1])
        if hint:stem_files[identity]={'path':path,'bytes':size,'evidence':'RBSC drum-capture file type' if documented else 'Filename/folder candidate; purpose unverified','rbsc':documented}
    def exceeded():return directories>=max_directories or files_seen>=max_files or time.monotonic()-started>=max_seconds
    def add(scope,location,reference,record,identity):
        if identity in seen_files:return
        seen_files.add(identity)
        folder=folders.setdefault(location,{'path':location,'reference_key':reference,'scope':scope,'files':[]})
        folder['files'].append(record)
        ext=Path(record['name']).suffix.casefold() or '(none)';extension_counts[ext]['files']+=1;extension_counts[ext]['bytes']+=record['bytes']
    with ExitStack() as stack:
        archive_stamps=[]
        for root in roots:
            if exceeded():partial=True;warnings.append('Inventory budget reached; selected scopes were only partially inspected.');break
            scope=str(root);scopes.append({'path':scope,'kind':'ZIP' if root.is_file() else 'folder'})
            progress(5,'Inventorying selected analysis scope: '+root.name)
            if root.is_file():
                if root.suffix.lower()!='.zip':raise ValueError('Choose analysis folders or native backup ZIPs')
                stamp=file_record(root)
                if stamp['cloud_only']:raise ValueError('Make the selected backup ZIP available locally first')
                archive=stack.enter_context(zipfile.ZipFile(root));archive_stamps.append((root,stamp))
                for info in archive.infolist():
                    files_seen+=1
                    if exceeded():partial=True;break
                    name=info.filename.replace('\\','/');reference=analysis_folder(name)
                    if not info.is_dir():stem_evidence(name,info.file_size,(scope,info.filename))
                    if info.is_dir() or not (reference or ANALYSIS.fullmatch(Path(name).name)):continue
                    location=scope+'!/'+name.rpartition('/')[0]
                    add(scope,location,reference,{'name':Path(name).name,'bytes':info.file_size,'crc':info.CRC,'source':info.filename,'archive':archive,'cloud':False},(scope,info.filename))
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
                        hint=path.suffix.casefold() in ('.rbsc','.stem','.stems') or path.name.casefold().endswith(('.stem.mp4','.stems.mp4')) or any(p.casefold() in ('stems','stem','track separation','track_separation','trackseparation') for p in path.parts[:-1])
                        if not (reference or ANALYSIS.fullmatch(name) or hint):continue
                        try:stamp=file_record(path)
                        except OSError as error:warnings.append(str(error));continue
                        if hint:stem_evidence(str(path),stamp['size'],str(path))
                        if not (reference or ANALYSIS.fullmatch(name)):continue
                        add(scope,str(path.parent),reference,{'name':name,'bytes':stamp['size'],'source':str(path),'archive':None,'cloud':stamp['cloud_only'],'stamp':stamp},str(path))
                    if directories%250==0:progress(15,'Indexed '+str(len(folders))+' analysis locations')
                    if partial:break
            if partial:warnings.append('Inventory budget reached; results are partial. Choose narrower paths.');break
        if not folders and not stem_files:raise ValueError('No USBANLZ, ANLZ or STEMS-related candidate assets were found in these selected scopes')
        references={k for p in snapshot.get('asset_references',[]) if (k:=analysis_folder(p))}
        complete=snapshot.get('capabilities',{}).get('analysis_references',False)
        found_keys={f['reference_key'] for f in folders.values() if f['reference_key']}
        rows=[]
        rows.extend({'section':'stems_related_asset','severity':'info' if f['rbsc'] else 'review','title':Path(f['path']).name,'detail':f['evidence'],**f} for f in stem_files.values())
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
                        if not f['archive'] and file_record(Path(f['source']))!=f['stamp']:raise ValueError('An analysis file changed after inventory; capture again')
                        digest.update((f['name'].casefold()+'\0'+str(f['bytes'])+'\0').encode())
                        stream=f['archive'].open(f['source']) if f['archive'] else Path(f['source']).open('rb')
                        with stream:
                            while chunk:=stream.read(min(2*1024**2,max_hash_bytes-hash_bytes+1)):
                                if hash_bytes+len(chunk)>max_hash_bytes:reason='Explicit verification byte budget reached';skipped+=1;break
                                digest.update(chunk);hash_bytes+=len(chunk)
                        if not f['archive'] and file_record(Path(f['source']))!=f['stamp']:raise ValueError('An analysis file changed during verification; capture again')
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
        for root,stamp in archive_stamps:
            if file_record(root)!=stamp:raise ValueError('A backup ZIP changed during the audit; capture again')
        return {'scopes':scopes,'folders':len(folders),'files':sum(len(f['files']) for f in folders.values()),
                'analysis_extensions':[{'extension':ext,**totals} for ext,totals in sorted(extension_counts.items(),key=lambda item:-item[1]['bytes'])],
                'stems':{'prepared_tracks':None,'preparation_status':'Unavailable: no validated persistent per-track STEMS indicator is decoded',
                         'related_candidate_files':len(stem_files),'related_candidate_bytes':sum(f['bytes'] for f in stem_files.values()),
                         'rbsc_drum_capture_files':sum(f['rbsc'] for f in stem_files.values()),
                         'note':'RBSC captures and filename hints do not establish how many tracks are STEMS-ready. General ANLZ containers are not counted as separated audio.'},
                'logical_bytes':sum(m['bytes'] for f in folders.values() for m in f['files']),
                'missing_in_scope':len(references-found_keys),'ownership_complete':complete,
                'unreferenced_folders':sum(bool(f['reference_key']) and f['reference_key'] not in references for f in folders.values()) if complete else None,
                'ownership_unknown_folders':sum(not f['reference_key'] or not complete for f in folders.values()),
                'duplicate_candidate_groups':candidates,'verified_duplicate_groups':verified_groups,'verified_extra_logical_bytes':verified_bytes,
                'bytes_hashed':hash_bytes,'verification_skipped':skipped,'inventory_complete':not partial and not warnings,'source_writes':False,'scope_warnings':warnings[:100]},rows
