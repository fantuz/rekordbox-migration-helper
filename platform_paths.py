"""Platform data directories and conservative read-only library discovery."""
import os
import json
from pathlib import Path
import sys
from xml.etree import ElementTree


DATABASE_NAMES=('master.db','Master.db','datafile.edb','DataFile.edb','ExtData.edb','extdata.edb')


def configure_packaged_certificates(platform_name=None,environ=None,frozen=None,certificate_files=None):
    """Use the host's CA store when bundled OpenSSL came from another distro."""
    name=platform_name or sys.platform
    env=os.environ if environ is None else environ
    packaged=getattr(sys,'frozen',False) if frozen is None else frozen
    if not packaged or name not in ('linux','darwin') or 'SSL_CERT_FILE' in env or 'SSL_CERT_DIR' in env:return None
    files=certificate_files if certificate_files is not None else (
        '/etc/ssl/certs/ca-certificates.crt','/etc/pki/tls/certs/ca-bundle.crt',
        '/etc/ssl/ca-bundle.pem','/etc/ssl/cert.pem')
    for name in files:
        path=Path(name)
        try:
            if path.is_file():env['SSL_CERT_FILE']=str(path);return str(path)
        except OSError:continue
    return None


def default_data_directory(app_root,platform_name=None,environ=None,home=None,frozen=None):
    name=platform_name or sys.platform
    env=os.environ if environ is None else environ
    user=Path.home() if home is None else Path(home)
    if name=="win32":return Path(env.get("LOCALAPPDATA",str(user/"AppData/Local")))/"LibraryWorkbench"
    if name=="darwin":return user/"Library/Application Support/LibraryWorkbench"
    if (getattr(sys,'frozen',False) if frozen is None else frozen):
        base=Path(env.get('XDG_DATA_HOME') or user/'.local/share')
        if not base.is_absolute():base=user/'.local/share'
        return base/'LibraryWorkbench'
    return Path(app_root)/".data"


def database_names(path,on_entry=None):
    """Bounded name-only probes; an optional shared budget covers each entry."""
    path=Path(path);wanted={n.casefold() for n in DATABASE_NAMES};found=set()
    try:
        if path.is_symlink() or path.is_junction():return []
        # Exact probes still work when a large folder exceeds the listing budget.
        for name in DATABASE_NAMES:
            candidate=path/name
            if candidate.is_file() and not candidate.is_symlink():found.add(name)
        actual=[]
        with os.scandir(path) as entries:
            for index,entry in enumerate(entries):
                if index>=4096 or (on_entry is not None and not on_entry()):break
                if entry.name.casefold() in wanted and not entry.is_symlink() and entry.is_file(follow_symlinks=False):
                    actual.append(entry.name)
        # Case-insensitive hosts can satisfy several exact probes for one file.
        for name in actual:
            found={n for n in found if n.casefold()!=name.casefold()}
        found.update(actual)
    except OSError:pass
    return sorted(found,key=lambda n:(n.casefold(),n))


def linked_directory(path):
    """Auto-discovery must not cross redirected profile/settings directories."""
    for part in (Path(path),*Path(path).parents):
        if not (part.is_symlink() or part.is_junction()):continue
        # macOS itself aliases /var, /tmp and /etc into /private. These system
        # aliases must not hide ordinary libraries or temporary test fixtures.
        if sys.platform=='darwin' and str(part) in ('/var','/tmp','/etc') and part.resolve()==Path('/private')/part.name:
            continue
        return True
    return False


def location_hints(settings_folders,agent_folders):
    """Read only location fields; never return other Agent options or device secrets."""
    hints=[];warnings=[]
    def small(path):
        if linked_directory(path.parent) or path.is_symlink() or path.is_junction() or not path.is_file() or path.stat().st_size>2*1024**2:return None
        return path.read_bytes()
    for folder in agent_folders:
        path=Path(folder)/'storage/options.json'
        try:
            data=small(path)
            if data is None:continue
            value=json.loads(data.decode('utf-8-sig'));options=value.get('options',value) if isinstance(value,dict) else None
            pairs=list(options.items()) if isinstance(options,dict) else options if isinstance(options,list) else []
            for item in pairs[:2048]:
                if not isinstance(item,(list,tuple)) or len(item)!=2:continue
                key,value=item
                if key not in ('db-path','analysis-data-root-path') or not isinstance(value,str) or not value.strip():continue
                hints.append({'value':value,'kind':'database' if key=='db-path' else 'analysis',
                              'origin':'Location saved in rekordbox Agent options','settings_file':str(path)})
        except (OSError,ValueError):warnings.append('A rekordbox Agent options file could not be inspected: '+str(path))
    for folder in settings_folders:
        path=Path(folder)/'rekordbox3.settings'
        try:
            data=small(path)
            if data is None:continue
            if b'<!DOCTYPE' in data.upper().replace(b'\0',b'') or b'<!ENTITY' in data.upper().replace(b'\0',b''):continue
            for value in ElementTree.fromstring(data).iter('VALUE'):
                if value.get('name','').casefold()=='masterdbdirectory' and value.get('val','').strip():
                    hints.append({'value':value.get('val'),'kind':'database','origin':'Database location saved in rekordbox settings','settings_file':str(path)})
        except (OSError,ElementTree.ParseError):warnings.append('A rekordbox settings file could not be inspected: '+str(path))
    return hints,warnings


def discover_sources(platform_name=None,environ=None,home=None):
    name=platform_name or sys.platform
    env=os.environ if environ is None else environ
    user=Path.home() if home is None else Path(home)
    if name=="win32":
        appdata=Path(env.get("APPDATA") or env.get("AppData") or user/"AppData/Roaming")
        bases=[appdata/"Pioneer",appdata/"AlphaTheta"]
        help_text="Windows suggestions check AppData, rekordbox Agent options and saved database locations. Cloud music may be stored in a different folder."
    elif name=="darwin":
        bases=[user/"Library/Pioneer",user/"Library/Application Support/Pioneer",user/"Library/AlphaTheta",user/"Library/Application Support/AlphaTheta"]
        help_text="Mac suggestions check Library folders, rekordbox Agent options and saved database locations. Cloud music may be stored in a different folder."
    else:
        bases=[]
        help_text="On Linux, enter the path to a copied library or a real library on an already-mounted Windows or Mac volume. Manual path selection is always available."
    standard=[base/folder for base in bases for folder in ("rekordbox","rekordbox6","rekordbox7")]
    hints,warnings=location_hints(list(reversed(standard)),[base/'rekordboxAgent' for base in bases])
    candidates=[];analysis=[]
    for hint in hints:
        value=hint['value'].strip()
        # Do not trigger network-share access while assembling local suggestions.
        if any(ord(c)<32 for c in value) or value.startswith(('\\\\','//')):continue
        path=user/value[2:] if value.startswith('~/') else Path(value).expanduser()
        if not path.is_absolute():continue
        if hint['kind']=='analysis':analysis.append({'path':str(path),'origin':hint['origin']});continue
        if path.name.casefold() in {n.casefold() for n in DATABASE_NAMES}:path=path.parent
        candidates.append((path,hint['origin']))
    candidates.extend((path,'Standard application-data location') for path in standard)
    expanded=[]
    for path,origin in candidates:
        expanded.extend((p,origin) for p in (path,path/'Master',path/'PIONEER/Master'))
    found=[];seen=set()
    for path,origin in expanded:
        try:
            if linked_directory(path) or not path.is_dir():continue
            path=path.resolve();key=os.path.normcase(str(path))
            if key in seen:continue
            names=database_names(path)
            if not names:continue
            seen.add(key);found.append({'path':str(path),'origin':origin,'databases':names})
        except OSError:continue
    from cloud_locations import discover
    cloud=discover(name,env,user,hints,cache=platform_name is None and environ is None and home is None)
    for row in cloud['libraries']:
        key=os.path.normcase(row['path'])
        if key not in seen:
            seen.add(key);found.append({k:row[k] for k in ('path','origin','databases')})
    return {'platform':name,'help':help_text,'standard_locations':[str(p) for p in standard],
            'found':found,'warnings':warnings,'analysis_locations':analysis,'cloud_locations':cloud}


def discover_cloud_roots(platform_name=None,environ=None,home=None):
    from cloud_locations import provider_roots
    return [{'root':row['root'],'kind':row['kind']}
            for row in provider_roots(platform_name,environ,home) if row['availability']=='local']
