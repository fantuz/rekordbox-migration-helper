"""Platform data directories and conservative read-only library discovery."""
import os
import json
from pathlib import Path
import sys
from xml.etree import ElementTree


def default_data_directory(app_root,platform_name=None,environ=None,home=None):
    name=platform_name or sys.platform
    env=os.environ if environ is None else environ
    user=Path.home() if home is None else Path(home)
    if name=="win32":return Path(env.get("LOCALAPPDATA",str(user/"AppData/Local")))/"LibraryWorkbench"
    if name=="darwin":return user/"Library/Application Support/LibraryWorkbench"
    return Path(app_root)/".data"


def discover_sources(platform_name=None,environ=None,home=None):
    name=platform_name or sys.platform
    env=os.environ if environ is None else environ
    user=Path.home() if home is None else Path(home)
    if name=="win32":
        appdata=Path(env.get("APPDATA") or env.get("AppData") or user/"AppData/Roaming")
        bases=[appdata/"Pioneer",appdata/"AlphaTheta"]
        help_text="Windows suggestions use AppData and saved rekordbox database locations. Cloud music may be stored in a different folder."
    elif name=="darwin":
        bases=[user/"Library/Pioneer",user/"Library/Application Support/Pioneer",user/"Library/AlphaTheta",user/"Library/Application Support/AlphaTheta"]
        help_text="Mac suggestions check Library folders and saved rekordbox database locations. Cloud music may be stored in a different folder."
    else:
        bases=[]
        help_text="On Linux, enter the path to a copied rekordbox data folder. The original Windows or Mac path in copied settings may not exist here."
    standard=[base/folder for base in bases for folder in ("rekordbox","rekordbox6")]
    candidates=[(path,"Standard application-data location") for path in standard]
    warnings=[]
    for folder in standard:
        settings=folder/"rekordbox3.settings"
        try:
            if not settings.is_file() or settings.stat().st_size>2*1024**2:continue
            root=ElementTree.fromstring(settings.read_bytes())
            for value in root.iter("VALUE"):
                if value.get("name","").casefold()!="masterdbdirectory":continue
                configured=Path(value.get("val","")).expanduser()
                if configured.is_absolute():candidates.append((configured,"Database location saved in rekordbox settings"))
        except (OSError,ElementTree.ParseError):warnings.append("A rekordbox settings file could not be inspected: "+str(settings))
    found=[];seen=set()
    for path,origin in candidates:
        try:
            if not path.is_dir():continue
            path=path.resolve()
            if str(path) in seen:continue
            databases=[p.name for p in path.iterdir() if p.is_file() and (p.name.lower()=="master.db" or p.suffix.lower()==".edb")]
            if not databases:continue
            seen.add(str(path))
            found.append({"path":str(path),"origin":origin,"databases":databases})
        except OSError:continue
    return {"platform":name,"help":help_text,"standard_locations":[str(p) for p in standard],"found":found,"warnings":warnings}


def discover_cloud_roots():
    user=Path.home()
    candidates=[(user/"Dropbox","dropbox"),(user/"Google Drive","google_drive"),(user/"GoogleDrive","google_drive")]
    configs=[user/".dropbox/info.json",user/"Library/Application Support/Dropbox/info.json"]
    for name in ("APPDATA","LOCALAPPDATA"):
        if os.environ.get(name):configs.append(Path(os.environ[name])/"Dropbox/info.json")
    for path in configs:
        try:
            if not path.is_file() or path.stat().st_size>1024**2:continue
            value=json.loads(path.read_text(encoding="utf-8"))
            for account in value.values():
                if isinstance(account,dict) and account.get("path"):candidates.append((Path(account["path"]),"dropbox"))
        except (OSError,ValueError):continue
    container=user/"Library/CloudStorage"
    try:
        if container.is_dir():
            for path in container.iterdir():
                if path.name.casefold().startswith("dropbox"):candidates.append((path,"dropbox"))
                elif path.name.casefold().startswith("googledrive"):
                    candidates.append((path/"My Drive" if (path/"My Drive").is_dir() else path,"google_drive"))
    except OSError:pass
    result=[];seen=set()
    for path,kind in candidates:
        try:
            if path.is_dir() and str(path.resolve()) not in seen:
                path=path.resolve();seen.add(str(path));result.append({"root":str(path),"kind":kind})
        except OSError:continue
    return result
