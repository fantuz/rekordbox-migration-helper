"""Platform data directories and conservative read-only library discovery."""
import os
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
