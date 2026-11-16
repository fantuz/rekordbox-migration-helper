"""Read-only ZIP coverage and bounded checksum verification; never extract members."""
from collections import Counter
from hashlib import sha256
from pathlib import Path, PurePosixPath
import stat
import zipfile

from analyzer import analysis_folder

MAX_MEMBERS=100000
MAX_VERIFY_BYTES=512*1024**2
AUDIO={'.mp3','.wav','.aiff','.aif','.flac','.m4a','.aac','.ogg','.opus'}


def component(name):
    path=PurePosixPath(name.casefold())
    if path.name in ('master.db','master.db-wal','master.db-journal') or path.suffix=='.edb':return 'database'
    if analysis_folder(name) or path.suffix in ('.dat','.ext','.2ex'):return 'analysis'
    if path.suffix in ('.jpg','.jpeg','.png','.webp') or 'artwork' in path.parts:return 'artwork'
    if path.suffix in ('.ini','.settings','.plist') or 'settings' in path.parts:return 'settings'
    if path.suffix in AUDIO:return 'music'
    return 'other'


def backup_manifest(snapshot,value,progress,verify=False,max_verify_bytes=MAX_VERIFY_BYTES):
    path=Path(str(value).strip().strip('"')).expanduser()
    if not path.is_absolute() or path.suffix.lower()!='.zip' or not path.is_file():
        raise ValueError('Choose the absolute path to an available backup ZIP')
    before=path.stat();rows=[];counts=Counter();sizes=Counter();seen=set();folders=set();hashed=0
    progress(5,'Reading backup coverage')
    with zipfile.ZipFile(path) as archive:
        members=archive.infolist()
        if len(members)>MAX_MEMBERS:raise ValueError('Backup has too many members; the coverage limit is 100,000')
        for index,info in enumerate(members):
            name=info.filename.replace('\\','/');parts=PurePosixPath(name)
            if (parts.is_absolute() or '..' in parts.parts or ':' in name or name in seen or
                    stat.S_ISLNK(info.external_attr>>16)):
                raise ValueError('Backup contains repeated, linked or unsafe member paths')
            seen.add(name)
            if info.is_dir():continue
            group=component(name);counts[group]+=1;sizes[group]+=info.file_size
            reference=analysis_folder(name)
            if reference:folders.add(reference)
            entry={'section':'backup_member','severity':'info','title':name,'component':group,
                   'bytes':info.file_size,'crc32':f'{info.CRC:08x}','verification':'not_checked',
                   'detail':'Member listed; bytes have not been verified'}
            if verify:
                if hashed+info.file_size>max_verify_bytes:
                    entry.update(verification='budget_exceeded',severity='review',detail='Checksum byte budget reached; member not read')
                else:
                    digest=sha256()
                    with archive.open(info) as stream:
                        while chunk:=stream.read(min(2*1024**2,max_verify_bytes-hashed+1)):
                            hashed+=len(chunk)
                            if hashed>max_verify_bytes:raise ValueError('Backup verification exceeded its byte budget')
                            digest.update(chunk);progress(10+80*(index+1)/max(1,len(members)),'Verifying selected backup members')
                    entry.update(verification='verified',sha256=digest.hexdigest(),detail='Member SHA-256 and ZIP CRC verified')
            rows.append(entry)
            if index%100==0:progress(10+80*(index+1)/max(1,len(members)),'Inspecting backup coverage')
    after=path.stat()
    if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):
        raise ValueError('Backup changed during inspection; choose it again')
    for group in ('database','analysis','artwork','settings','music'):
        rows.insert(0,{'section':'backup_component','severity':'info' if counts[group] else 'review','title':group,
                       'files':counts[group],'bytes':sizes[group],
                       'detail':f'{counts[group]} members, {sizes[group]} bytes; presence does not establish complete recovery' if counts[group] else 'Not present in this ZIP; back up separately if needed'})
    refs={analysis_folder(p) for p in snapshot.get('asset_references',[]) if analysis_folder(p)}
    for missing in sorted(refs-folders):
        rows.append({'section':'missing_analysis','severity':'review','title':missing,
                     'detail':'Captured analysis reference is absent from this ZIP; check that the backup belongs to this collection'})
    verified=sum(r.get('verification')=='verified' for r in rows)
    return {'members':sum(counts.values()),'logical_bytes':sum(sizes.values()),'verified_members':verified,
            'hashed_bytes':hashed,'verification_budget_bytes':max_verify_bytes,
            'missing_analysis_references':len(refs-folders),'analysis_reference_scope':'captured references only' if refs else 'unknown',
            'checksum_status':'verified' if verify and verified==sum(counts.values()) and verified else 'partial' if verify else 'not_checked',
            'source_archive':path.name,'source_archive_bytes':before.st_size,
            'note':'Coverage of this ZIP only. Music and settings may require separate backups. A verified manifest is not a rekordbox restore test.'},rows
