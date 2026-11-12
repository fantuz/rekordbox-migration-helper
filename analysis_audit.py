"""Analysis asset inventory; possible duplicates require explicit byte verification."""
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
import os
import zipfile

from analyzer import analysis_folder
from media import cloud_placeholder,file_record


def audit_assets(snapshot,source,progress,verify=False,max_hash_bytes=256*1024**2):
    root=Path(str(source).strip().strip('"')).expanduser()
    if not root.is_absolute() or not root.exists():raise ValueError('Choose an accessible analysis folder or backup ZIP')
    root=root.resolve();archive=None;folders=defaultdict(list);skipped=0;hash_bytes=0;warnings=[]
    archive_stamp=file_record(root) if root.is_file() else None
    if archive_stamp and archive_stamp['cloud_only']:raise ValueError('Make this backup ZIP available locally before inspecting it')
    try:
        if root.is_file():
            if root.suffix.lower()!='.zip':raise ValueError('Choose a folder or native backup ZIP')
            archive=zipfile.ZipFile(root)
            for info in archive.infolist():
                key=analysis_folder(info.filename)
                if key and not info.is_dir():folders[key].append({'name':Path(info.filename).name,'bytes':info.file_size,'crc':info.CRC,'source':info.filename,'cloud':False})
        elif root.is_dir():
            for folder,dirs,names in os.walk(root,followlinks=False,onerror=lambda e:warnings.append(str(e))):
                dirs[:]=[n for n in dirs if not (Path(folder)/n).is_symlink() and not (Path(folder)/n).is_junction()]
                for name in names:
                    p=Path(folder)/name;key=analysis_folder(str(p))
                    if not key or p.is_symlink() or not p.is_file():continue
                    try:s=file_record(p)
                    except OSError as error:warnings.append(str(error));continue
                    folders[key].append({'name':name,'bytes':s['size'],'source':str(p),'cloud':s['cloud_only'],'stamp':s})
        if not folders:raise ValueError('No USBANLZ analysis files were found in this selected scope')
        references={k for p in snapshot.get('asset_references',[]) if (k:=analysis_folder(p))}
        complete=snapshot.get('capabilities',{}).get('analysis_references',False)
        rows=[]
        for key in sorted(references-folders.keys()):rows.append({'section':'asset_missing','severity':'review','title':key,'detail':'Referenced folder not present in the selected audit scope'})
        for key,files in folders.items():
            if key not in references:rows.append({'section':'asset_unreferenced' if complete else 'asset_ownership_unknown','severity':'review','title':key,'detail':'No active owner in the complete captured reference set' if complete else 'Ownership cannot be established from this snapshot','bytes':sum(f['bytes'] for f in files)})
        profiles=defaultdict(list)
        for key,files in folders.items():
            profile=tuple(sorted((f['name'].casefold(),f['bytes'],f.get('crc') if archive else None) for f in files))
            profiles[profile].append(key)
        verified_groups=0;candidate_groups=0
        for keys in profiles.values():
            if len(keys)<2:continue
            candidate_groups+=1;digests={};reason=''
            if verify:
                for key in keys:
                    digest=sha256()
                    for f in sorted(folders[key],key=lambda f:f['name'].casefold()):
                        if f['cloud']:reason='Cloud-only assets were not read';skipped+=1;break
                        if hash_bytes+f['bytes']>max_hash_bytes:reason='Explicit verification byte budget reached';skipped+=1;break
                        digest.update(f['name'].casefold().encode())
                        if not archive and file_record(Path(f['source']))!=f['stamp']:raise ValueError('An analysis file changed after inventory; capture again')
                        stream=archive.open(f['source']) if archive else Path(f['source']).open('rb')
                        with stream:
                            while chunk:=stream.read(min(2*1024**2,max_hash_bytes-hash_bytes+1)):
                                if hash_bytes+len(chunk)>max_hash_bytes:reason='Explicit verification byte budget reached';skipped+=1;break
                                digest.update(chunk);hash_bytes+=len(chunk)
                        if not archive and file_record(Path(f['source']))!=f['stamp']:raise ValueError('An analysis file changed during verification; capture again')
                        progress(50,'Verifying selected candidate analysis bytes')
                        if reason:break
                    if reason:break
                    digests[key]=digest.hexdigest()
            identical=verify and not reason and len(set(digests.values()))==1
            verified_groups+=identical
            rows.append({'section':'asset_duplicate_verified' if identical else 'asset_duplicate_candidate','severity':'review','title':keys[0],
                         'detail':'Identical analysis files verified by SHA-256' if identical else 'Matching member names/sizes'+('/CRC' if archive else '')+'; content equality not established',
                         'folders':keys,'potential_extra_bytes':sum(f['bytes'] for k in keys[1:] for f in folders[k]),'verification_note':reason})
        if archive_stamp and file_record(root)!=archive_stamp:raise ValueError('The backup ZIP changed during the audit; capture again')
        return {'folders':len(folders),'files':sum(len(f) for f in folders.values()),'logical_bytes':sum(f['bytes'] for fs in folders.values() for f in fs),
                'missing_in_scope':len(references-folders.keys()),'ownership_complete':complete,'unreferenced_folders':len(folders.keys()-references) if complete else None,
                'duplicate_candidate_groups':candidate_groups,'verified_duplicate_groups':verified_groups,'bytes_hashed':hash_bytes,'verification_skipped':skipped,'source_writes':False,'scope_warnings':warnings[:100]},rows
    finally:
        if archive:archive.close()
