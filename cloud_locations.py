"""Bounded provider-location discovery; no cloud login, hydration or source SQL."""
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import sys
import time
from collections import OrderedDict
from copy import deepcopy
from itertools import islice
from threading import RLock

from media import cloud_placeholder

MAX_CONFIG=1024*1024
MAX_ROOTS=24
MAX_DIRECTORIES=128
MAX_ENTRIES=4096
MAX_SECONDS=2
LIBRARY_FOLDERS=('rekordbox','rekordbox6','rekordbox7','Pioneer/rekordbox','AlphaTheta/rekordbox','PIONEER/Master')
_CACHE=OrderedDict()
_CACHE_LOCK=RLock()


def clear_cache():
    with _CACHE_LOCK:_CACHE.clear()


def safe_directory(path):
    from platform_paths import linked_directory
    try:
        return (not str(path).replace('\\','/').startswith('//') and '..' not in path.parts
                and path.is_absolute() and not linked_directory(path) and path.is_dir())
    except OSError:
        return False


def small_json(path):
    from platform_paths import linked_directory
    if linked_directory(path):return None
    try:
        info=path.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or cloud_placeholder(info) or info.st_size>MAX_CONFIG:return None
        with path.open('rb') as stream:data=stream.read(MAX_CONFIG+1)
        if len(data)>MAX_CONFIG:return None
        value=json.loads(data.decode('utf-8-sig'))
        return value if isinstance(value,dict) else None
    except (OSError,ValueError,RecursionError):return None


def current_windows_sid():
    """Read only this process's user SID; never enumerate other user profiles."""
    if os.name!='nt':return None
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.windll.kernel32;security=ctypes.windll.advapi32
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    security.OpenProcessToken.argtypes=(wintypes.HANDLE,wintypes.DWORD,ctypes.POINTER(wintypes.HANDLE))
    security.GetTokenInformation.argtypes=(wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD))
    security.ConvertSidToStringSidW.argtypes=(ctypes.c_void_p,ctypes.POINTER(wintypes.LPWSTR))
    kernel.CloseHandle.argtypes=(wintypes.HANDLE,)
    kernel.LocalFree.argtypes=(ctypes.c_void_p,)
    token=wintypes.HANDLE();size=wintypes.DWORD();text=wintypes.LPWSTR()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(),8,ctypes.byref(token)):return None
    try:
        security.GetTokenInformation(token,1,None,0,ctypes.byref(size))
        if not 0<size.value<=65536:return None
        buffer=ctypes.create_string_buffer(size.value)
        if not security.GetTokenInformation(token,1,buffer,size,ctypes.byref(size)):return None
        sid=ctypes.cast(buffer,ctypes.POINTER(ctypes.c_void_p))[0]
        if not security.ConvertSidToStringSidW(sid,ctypes.byref(text)):return None
        try:return text.value
        finally:kernel.LocalFree(text)
    finally:kernel.CloseHandle(token)


def windows_provider_paths():
    """Read OS sync-root registrations and labels on fixed local drives only."""
    if os.name!='nt':return []
    import winreg
    records=[];current_sid=current_windows_sid()
    branch=r'Software\Microsoft\Windows\CurrentVersion\Explorer\SyncRootManager'
    for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive,branch) as parent:
                for index in range(min(winreg.QueryInfoKey(parent)[0],128)):
                    name=winreg.EnumKey(parent,index)
                    lower=name.casefold()
                    kind='google_drive' if lower.startswith(('googledrive','google-drive')) else 'dropbox' if lower.startswith('dropbox') else None
                    if not kind:continue
                    try:
                        with winreg.OpenKey(parent,name+r'\UserSyncRoots') as roots:
                            for position in range(min(winreg.QueryInfoKey(roots)[1],16)):
                                sid,value,value_type=winreg.EnumValue(roots,position)
                                if current_sid and sid==current_sid and value_type in (winreg.REG_SZ,winreg.REG_EXPAND_SZ) and isinstance(value,str):
                                    records.append({'root':os.path.expandvars(value),'kind':kind,'evidence':'windows_registration'})
                    except OSError:continue
        except OSError:continue
    # Network shares are deliberately excluded: metadata queries can block.
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.windll.kernel32
    kernel.GetDriveTypeW.argtypes=(wintypes.LPCWSTR,)
    kernel.GetVolumeInformationW.argtypes=(wintypes.LPCWSTR,wintypes.LPWSTR,wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),ctypes.POINTER(wintypes.DWORD),ctypes.POINTER(wintypes.DWORD),wintypes.LPWSTR,wintypes.DWORD)
    mask=kernel.GetLogicalDrives()
    for index in range(26):
        path=chr(65+index)+':\\'
        if not mask&(1<<index) or kernel.GetDriveTypeW(path)!=3:continue
        label=ctypes.create_unicode_buffer(261)
        if kernel.GetVolumeInformationW(path,label,len(label),None,None,None,None,0):
            if re.match(r'^Google\s*Drive(?:\s|$)',label.value,re.I):
                records.append({'root':path,'kind':'google_drive','evidence':'volume_label'})
    return records


def provider_roots(platform_name=None,environ=None,home=None,registrations=None,include_unavailable=False):
    env=os.environ if environ is None else environ
    user=Path.home() if home is None else Path(home)
    platform_name=platform_name or sys.platform
    candidates=[]
    def add(path,kind,evidence,account='unknown'):
        if isinstance(path,str) and path and len(path)<=4096 and '\0' not in path:
            candidates.append((Path(path),kind,evidence,account))
    configs=[user/'.dropbox/info.json',user/'Library/Application Support/Dropbox/info.json']
    for name in ('APPDATA','LOCALAPPDATA'):
        if isinstance(env.get(name),str):configs.append(Path(env[name])/'Dropbox/info.json')
    for config in dict.fromkeys(configs):
        if not config.is_absolute() or str(config).replace('\\','/').startswith('//'):continue
        value=small_json(config)
        if not isinstance(value,dict):continue
        for name,account in islice(value.items(),16):
            if isinstance(account,dict):
                add(account.get('path'),'dropbox','dropbox_config',name if name in ('personal','business') else 'unknown')
    records=windows_provider_paths() if registrations is None and platform_name=='win32' else registrations or []
    for item in records[:64]:
        if isinstance(item,dict) and item.get('kind') in ('dropbox','google_drive'):
            add(item.get('root'),item['kind'],item.get('evidence','windows_registration'))
    for name,kind in (('Dropbox','dropbox'),('Google Drive','google_drive'),('GoogleDrive','google_drive')):
        add(str(user/name),kind,'folder_name')
    # Business Dropbox roots can be called "DJ Team Dropbox", not just Dropbox.
    if safe_directory(user):
        try:
            for folder in islice(user.iterdir(),256):
                if re.search(r'(?:^|[\s_-])Dropbox(?:\s|$)',folder.name,re.I):add(str(folder),'dropbox','folder_name')
        except OSError:pass
    container=user/'Library/CloudStorage'
    if safe_directory(container):
        try:
            for folder in islice(container.iterdir(),128):
                lower=folder.name.casefold()
                if lower.startswith('dropbox'):add(str(folder),'dropbox','file_provider_folder')
                elif lower.startswith('googledrive'):add(str(folder),'google_drive','file_provider_folder')
        except OSError:pass
    roots=[];seen=set()
    for path,kind,evidence,account in candidates:
        # Existing ordinary paths only; absence is not a provider-install claim.
        if not safe_directory(path):
            # File-health attribution can retain an explicitly configured root
            # when its disk/client is offline. Never expose it as a discovery
            # candidate or an allowed audio-access root through the default API.
            if include_unavailable and evidence in ('dropbox_config','windows_registration'):
                from platform_paths import linked_directory
                try:
                    if (path.is_absolute() and '..' not in path.parts and not str(path).replace('\\','/').startswith('//')
                            and not linked_directory(path) and not path.exists() and path!=Path(path.anchor)):
                        roots.append({'root':str(path),'kind':kind,'evidence':evidence,'account':account,
                                      'availability':'unknown','provider_verified':True})
                        if len(roots)>=MAX_ROOTS:break
                except OSError:pass
            continue
        if path==Path(path.anchor) and (platform_name!='win32' or evidence not in ('windows_registration','volume_label')):continue
        try:
            canonical=str(path.resolve())
            availability='online_only' if cloud_placeholder(path.stat()) else 'local'
        except OSError:continue
        key=canonical.casefold() if platform_name=='win32' else canonical
        if key in seen:continue
        seen.add(key)
        roots.append({'root':canonical,'kind':kind,'evidence':evidence,'account':account,
                      'availability':availability,'provider_verified':evidence in ('dropbox_config','windows_registration')})
        if len(roots)>=MAX_ROOTS:break
    return roots


def path_parts(value):
    value=str(value).strip().strip('"')
    windows=PureWindowsPath(value)
    path=windows if windows.drive or '\\' in value else PurePosixPath(value)
    parts=path.parts
    if parts and parts[-1].casefold() in ('master.db','datafile.edb','extdata.edb'):parts=parts[:-1]
    return tuple(part.casefold() for part in parts)


def local_library_folder(value):
    """Canonicalize local settings paths only after rejecting redirected folders."""
    if not isinstance(value,str) or any(ord(c)<32 for c in value):return None
    try:
        path=Path(value.strip().strip('"')).expanduser()
        if path.name.casefold() in ('master.db','datafile.edb','extdata.edb'):path=path.parent
        return path.resolve() if safe_directory(path) else None
    except (OSError,RuntimeError):return None


def relocation_evidence(hints,libraries):
    results=[]
    for hint in hints[:64]:
        if hint.get('kind')!='database' or not isinstance(hint.get('value'),str):continue
        # macOS /var -> /private/var is an OS alias, not a moved library.
        old=path_parts(local_library_folder(hint['value']) or hint['value'])
        scored=[]
        for library in libraries:
            new=path_parts(library['path'])
            if old==new:continue
            common=0
            for left,right in zip(reversed(old),reversed(new)):
                if left!=right:break
                common+=1
            if common>=2:scored.append((common,library))
        if not scored:continue
        best=max(score for score,_ in scored)
        matches=[library for score,library in scored if score==best]
        for library in matches:
            results.append({'previous_path':hint['value'],'candidate_path':library['path'],
                'kind':library['kind'],'evidence':'matching_directory_suffix','matching_components':best,
                'ambiguous':len(matches)>1,'relocation_verified':False,
                'note':'Saved-path and folder-name evidence only; database/audio identity was not inspected'})
    return results[:100]


def discover(platform_name=None,environ=None,home=None,hints=None,registrations=None,clock=time.monotonic,cache=False):
    from platform_paths import database_names
    env=os.environ if environ is None else environ
    key=(platform_name or sys.platform,str(home or Path.home()),env.get('APPDATA',''),env.get('LOCALAPPDATA',''),
         tuple((row.get('kind'),row.get('value')) for row in (hints or [])[:64]))
    if cache:
        with _CACHE_LOCK:
            cached=_CACHE.get(key)
            if cached and clock()-cached[0]<10:return deepcopy(cached[1])
    roots=provider_roots(platform_name,environ,home,registrations)
    libraries=[];seen=set();directories=entries=0;partial=False;started=clock()
    def allow_entry():
        nonlocal entries,partial
        if entries>=MAX_ENTRIES or clock()-started>=MAX_SECONDS:
            partial=True;return False
        entries+=1;return True
    for root in roots:
        if root['availability']!='local':continue
        stack=[(Path(root['root']),0)]
        for hint in (hints or [])[:64]:
            if hint.get('kind')!='database':continue
            path=local_library_folder(hint.get('value'))
            if path is not None and path.is_relative_to(Path(root['root'])):
                stack.append((path,2))
        while stack:
            if directories>=MAX_DIRECTORIES or entries>=MAX_ENTRIES or clock()-started>=MAX_SECONDS:
                partial=True;break
            folder,depth=stack.pop()
            if not safe_directory(folder):continue
            try:
                if cloud_placeholder(folder.stat()):continue
            except OSError:continue
            directories+=1
            for path in (folder,*(folder/item for item in LIBRARY_FOLDERS)):
                if clock()-started>=MAX_SECONDS:partial=True;break
                if not safe_directory(path):continue
                try:
                    if cloud_placeholder(path.stat()):continue
                except OSError:continue
                databases=database_names(path,on_entry=allow_entry)
                identity=str(path.resolve())
                if databases and identity not in seen:
                    seen.add(identity);libraries.append({'path':identity,'databases':databases,'kind':root['kind'],
                        'origin':'Database filenames inside a detected cloud-provider location',
                        'root':root['root'],'database_opened':False})
                if partial:break
            if partial:break
            if depth>=2:continue
            try:
                with os.scandir(folder) as children:
                    for child in children:
                        if not allow_entry():break
                        if child.name.casefold() in ('.git','.dropbox.cache','$recycle.bin') or child.is_symlink():continue
                        try:
                            path=Path(child.path)
                            if child.is_dir(follow_symlinks=False) and not path.is_junction() and not cloud_placeholder(child.stat(follow_symlinks=False)):
                                stack.append((path,depth+1))
                        except OSError:continue
            except OSError:continue
            if partial:break
        if partial:break
    result={'roots':roots,'libraries':libraries,'relocations':relocation_evidence(hints or [],libraries),
            'recorded_locations':sum(row.get('kind')=='database' for row in (hints or [])[:64]),
            'partial':partial or len(roots)>=MAX_ROOTS,'directories_visited':directories,'entries_seen':entries,
            'limits':{'roots':MAX_ROOTS,'directories':MAX_DIRECTORIES,'entries':MAX_ENTRIES,'seconds':MAX_SECONDS},
            'source_writes':False,'database_queries':False,'cloud_login':False}
    if cache:
        with _CACHE_LOCK:
            _CACHE[key]=(clock(),deepcopy(result));_CACHE.move_to_end(key)
            while len(_CACHE)>8:_CACHE.popitem(last=False)
    return result
