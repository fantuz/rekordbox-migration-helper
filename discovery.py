"""Bounded, metadata-only discovery. Never mounts disks or opens source SQL."""
from pathlib import Path,PureWindowsPath
import os
import re
import sys
import time
from xml.etree import ElementTree
from itertools import islice

from platform_paths import discover_sources,location_hints,database_names
from media import cloud_placeholder

DATABASES={'master.db','datafile.edb','extdata.edb'}
ANALYSIS=re.compile(r'^anlz\d*\.(?:dat|ext|2ex|3ex)$',re.I)
SKIP={'$recycle.bin','system volume information','windows','program files','program files (x86)',
      '.git','.cache','.venv','node_modules','.temporary','proc','sys','dev'}
OWNERS=('Pioneer','AlphaTheta')
LIBRARIES=('rekordbox','rekordbox6','rekordbox7')


def _unescape(value):return re.sub(r'\\([0-7]{3})',lambda m:chr(int(m[1],8)),value)


def mounted_roots(platform_name=None,home=None,mountinfo=None):
    name=platform_name or sys.platform;home=Path.home() if home is None else Path(home)
    candidates=[]
    if name=='linux':
        if mountinfo is None:
            try:mountinfo=Path('/proc/self/mountinfo').read_text(encoding='utf-8')
            except OSError:mountinfo=''
        for line in mountinfo.splitlines():
            head,sep,tail=line.partition(' - ');fields=head.split();details=tail.split()
            if sep and len(fields)>=5 and details and details[0] in {'ntfs','ntfs3','fuseblk','exfat','vfat','msdos','apfs','hfsplus','drvfs','9p'}:
                candidates.append((Path(_unescape(fields[4])),details[0]))
        for base in (Path('/mnt'),Path('/media')/home.name,Path('/run/media')/home.name):
            try:candidates.extend((p,'mounted-folder candidate') for p in islice(base.iterdir(),64) if p.is_dir() and not p.is_symlink())
            except OSError:pass
    elif name=='darwin':
        try:candidates.extend((p,'mounted volume') for p in islice(Path('/Volumes').iterdir(),64) if p.is_dir() and not p.is_symlink())
        except OSError:pass
    elif name=='win32' and os.name=='nt':
        import ctypes
        mask=ctypes.windll.kernel32.GetLogicalDrives()
        for n in range(26):
            path=chr(65+n)+':/'
            if mask&(1<<n) and ctypes.windll.kernel32.GetDriveTypeW(path) in (2,3):candidates.append((Path(path),'local drive'))
    found=[];seen=set()
    for path,kind in candidates:
        try:
            if path.is_symlink() or not path.is_dir():continue
            resolved=path.resolve()
            if resolved==Path(resolved.anchor) and name!='win32':continue
            if str(resolved) in seen:continue
            seen.add(str(resolved));found.append({'path':str(resolved),'kind':kind})
        except OSError:continue
    return found[:64]


def _case_path(base,*parts):
    """Resolve Windows spelling on case-sensitive mounted filesystems."""
    path=Path(base)
    for part in parts:
        if part in ('','.') :continue
        if part=='..':return None
        exact=path/part
        try:
            if exact.exists():
                if exact.is_symlink() or exact.is_junction():return None
                path=exact;continue
            matches=[p for p in path.iterdir() if p.name.casefold()==part.casefold() and not p.is_symlink() and not p.is_junction()]
        except OSError:return None
        if len(matches)!=1:return None
        path=matches[0]
    return path


def _mounted_candidates(volume):
    """Check copied Windows/Mac profiles and bounded saved-location hints."""
    volume=Path(volume);candidates=[];users=_case_path(volume,'Users')
    try:profiles=[p for p in islice(users.iterdir(),64) if p.is_dir() and not p.is_symlink() and not p.is_junction()] if users else []
    except OSError:profiles=[]
    for profile in profiles:
        settings=[];agents=[]
        for owner in OWNERS:
            bases=[_case_path(profile,'AppData','Roaming',owner),_case_path(profile,'Library',owner),
                   _case_path(profile,'Library','Application Support',owner)]
            for base in (p for p in bases if p):
                agent=_case_path(base,'rekordboxAgent')
                if agent:agents.append(agent)
                for folder in LIBRARIES:
                    candidate=_case_path(base,folder)
                    if not candidate or not candidate.is_dir():continue
                    settings.append(candidate);candidates.append((candidate,'Standard path in a mounted Windows or Mac profile'))
                    nested=_case_path(candidate,'Master')
                    if nested:candidates.append((nested,'Master subfolder in a mounted profile'))
        hints,_=location_hints(list(reversed(settings)),agents)
        for hint in hints:
            raw=hint['value'];saved=PureWindowsPath(raw)
            if re.fullmatch('[A-Za-z]:',saved.drive) and saved.root and '..' not in saved.parts:
                parts=saved.parts[1:]
            elif raw.startswith('/Users/') and '..' not in Path(raw).parts:
                parts=Path(raw).parts[1:]
            else:continue
            path=_case_path(volume,*parts)
            if path and path.name.casefold()=='master.db':path=path.parent
            if path and path.is_dir():
                kind='analysis' if hint['kind']=='analysis' else 'database'
                candidates.append((path,'Saved '+kind+' path mapped within this mounted volume; verify the drive mapping and chosen library'))
    external=_case_path(volume,'PIONEER','Master')
    if external:candidates.append((external,'External master-database location on a mounted volume'))
    return candidates


def _library(path,origin):
    try:
        names=database_names(path)
        if names:return {'path':str(path.resolve()),'origin':origin,'databases':names}
    except OSError:pass
    return None


def _analysis_candidates(path):
    return [path,*(path/p for p in ('USBANLZ','PIONEER/USBANLZ','share/USBANLZ','share/PIONEER/USBANLZ'))]


def suggestions(platform_name=None,environ=None,home=None,volumes=None):
    native=discover_sources(platform_name,environ,home)
    volumes=mounted_roots(platform_name,home) if volumes is None else volumes
    libraries=list(native['found']);seen={r['path'] for r in libraries}
    candidates=[(Path(r['path']),'Detected library') for r in libraries]
    candidates.extend((Path(r['path']),r['origin']) for r in native.get('analysis_locations',[]))
    for row in volumes:
        volume=Path(row['path']);candidates.extend(_mounted_candidates(volume));candidates.append((volume,'Selected mounted volume root'))
    assets=[];asset_seen=set()
    for path,origin in candidates:
        library=_library(path,origin)
        if library and library['path'] not in seen:libraries.append(library);seen.add(library['path'])
        for candidate in _analysis_candidates(path):
            try:
                if candidate.name.casefold()!='usbanlz' or not candidate.is_dir() or candidate.is_symlink():continue
                key=str(candidate.resolve())
                if key not in asset_seen:assets.append({'path':key,'origin':origin,'kind':'USBANLZ analysis tree'});asset_seen.add(key)
            except OSError:pass
    return {**native,'found':libraries,'mounted_roots':volumes,'analysis_paths':assets,
            'help':native['help']+' Discovery never mounts a filesystem. Mounted Windows volumes and custom paths can be inspected on Linux; mounting is the user’s responsibility.'}


def scan_roots(roots,progress,kind='both',depth=8,max_directories=12000,max_entries=200000,max_seconds=15,clock=time.monotonic):
    if kind not in ('both','libraries','assets'):raise ValueError('Choose library, analysis-asset or combined discovery')
    depth=int(depth)
    if not 0<=depth<=12:raise ValueError('Search depth must be between 0 and 12')
    if not isinstance(roots,list) or not 1<=len(roots)<=20:raise ValueError('Choose between one and twenty search roots')
    selected=[];warnings=[];seen_roots=set()
    for raw in roots:
        path=Path(str(raw).strip().strip('"')).expanduser()
        if not path.is_absolute() or not path.is_dir():raise ValueError('Choose accessible absolute paths to folders already available on this computer')
        path=path.resolve()
        if str(path) in seen_roots:continue
        if sys.platform!='win32' and path==Path(path.anchor):raise ValueError('Choose a mounted volume or specific folder rather than the whole Linux/macOS system root')
        seen_roots.add(str(path));selected.append(path)
    start=clock();directories=entries=0;limited=False;libraries={};assets={};visited={};stack=[(r,depth) for r in reversed(selected)]
    while stack:
        if directories>=max_directories or entries>=max_entries or clock()-start>=max_seconds:
            limited=True;warnings.append('Search budget reached. Results are partial; choose a narrower folder or another search depth.');break
        folder,remaining=stack.pop();key=str(folder)
        if visited.get(key,-1)>=remaining:continue
        visited[key]=remaining;directories+=1;files=[];children=[]
        try:
            with os.scandir(folder) as iterator:
                for item in iterator:
                    entries+=1
                    if entries>max_entries or clock()-start>=max_seconds:limited=True;break
                    if item.is_symlink():continue
                    try:
                        if item.is_dir(follow_symlinks=False):
                            p=Path(item.path)
                            if p.is_junction() or item.name.casefold() in SKIP:continue
                            if cloud_placeholder(item.stat(follow_symlinks=False)):warnings.append('Skipped online-only folder: '+str(p));continue
                            children.append(p)
                        elif item.is_file(follow_symlinks=False):files.append(item.name)
                    except OSError as error:warnings.append(str(error))
        except OSError as error:warnings.append(str(error));continue
        dbs=sorted(n for n in files if n.casefold() in DATABASES)
        if dbs and kind!='assets':libraries[key]={'path':key,'origin':'Bounded search of a user-selected folder','databases':dbs}
        asset_kind='USBANLZ analysis tree' if folder.name.casefold()=='usbanlz' else 'Analysis-file folder' if any(ANALYSIS.fullmatch(n) for n in files) else 'STEMS-related filename candidates' if any(n.casefold().endswith(('.rbsc','.stem','.stems','.stem.mp4','.stems.mp4')) for n in files) else None
        if kind!='libraries' and asset_kind:
            assets[key]={'path':key,'origin':'Bounded search of a user-selected folder','kind':asset_kind}
        # Once a USBANLZ tree is found, list its root rather than thousands of per-track folders.
        if remaining and not (folder.name.casefold()=='usbanlz' and not dbs):stack.extend((p,remaining-1) for p in sorted(children,reverse=True))
        if directories%50==0:progress(min(95,100*directories/max_directories),'Searching folder names and file metadata: '+str(directories)+' folders')
        if limited:warnings.append('Entry/time budget reached; results are partial.');break
    return {'libraries':list(libraries.values()),'analysis_paths':list(assets.values()),'roots':[str(r) for r in selected],
            'directories_visited':directories,'entries_seen':entries,'seconds':round(clock()-start,3),'depth':depth,'partial':limited or bool(warnings),
            'warnings':warnings[:100],'source_writes':False,'database_queries':False,'mounted_by_application':False}
