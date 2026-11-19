"""Suggest captured library folders without probing or opening music files.

Provider configuration, captured paths and local availability are separate
evidence. Suggestions never attach a folder or infer an account or sync mode.
"""
from collections import defaultdict
import os
from pathlib import PurePosixPath,PureWindowsPath
import re

from cloud_file_status import lexical_path

FIELDS=('current_path','xml_location','original_path')


def _hint(path):
    for index,part in enumerate(path.parts[:-1]):
        if re.search(r'(?:^|[\s_-])dropbox(?:$|[\s_(-])',part,re.I):
            return 'dropbox',type(path)(*path.parts[:index+1])
        if re.match(r'^google\s*drive(?:$|[\s_(-])',part,re.I):
            return 'google_drive',type(path)(*path.parts[:index+1])
    return 'unknown',None


def _bucket(path):
    """Separate Music, Downloads, caches and volumes before finding parents."""
    parts=path.parent.parts
    depth=4 if len(parts)>2 and parts[1].casefold() in ('users','home') else 3
    return type(path)(*parts[:min(depth,len(parts))])


def _common(paths):
    first=paths[0].parent;parts=list(first.parts)
    for path in paths[1:]:
        other=path.parent.parts;limit=min(len(parts),len(other));matched=0
        for index in range(limit):
            if type(first)(parts[index])!=type(first)(other[index]):break
            matched+=1
        del parts[matched:]
    return type(first)(*parts) if parts else None


def suggestions(snapshot,roots):
    """Return bounded metadata hints; ``available=None`` means uninspected."""
    known=[]
    for row in roots or []:
        base=lexical_path(row.get('root'))
        if base and row.get('kind') in ('dropbox','google_drive'):
            known.append((base,row))
    groups=defaultdict(list)
    for track in snapshot.get('tracks',[])[:250000]:
        path=None
        for field in FIELDS:
            path=lexical_path(track.get(field))
            if path:break
        if not path:continue
        candidates=[(base,row) for base,row in known if type(base) is type(path) and path.is_relative_to(base)]
        if candidates:
            base,row=max(candidates,key=lambda item:len(item[0].parts))
            key=(row['kind'],str(base),'provider_configuration' if row.get('provider_verified') else 'folder_hint')
        else:
            kind,hint=_hint(path)
            key=(kind,str(hint or _bucket(path)),'captured_provider_hint' if hint else 'captured_path')
        groups[key].append(path)
    result=[];seen=set()
    for (kind,base,evidence),paths in sorted(groups.items(),key=lambda item:-len(item[1]))[:20]:
        common=_common(paths)
        for folder in (common,lexical_path(base)):
            if not folder or len(folder.parts)<2:continue
            identity=(kind,str(folder))
            if identity in seen:continue
            seen.add(identity)
            foreign=isinstance(folder,PureWindowsPath) if os.name!='nt' else isinstance(folder,PurePosixPath)
            # Existing provider root availability does not establish existence
            # of a recorded subfolder. Never stat those hints on page opening.
            configured=next((row for root,row in known if root==folder and type(root) is type(folder)),None)
            availability=configured.get('availability') if configured else None
            available=False if foreign else True if availability=='available' else None
            result.append({'path':str(folder),'recorded_root':str(folder),'kind':kind,
                           'evidence':evidence,'tracks':len(paths),'available':available,
                           'foreign':foreign,'samples':[str(path) for path in paths[:3]]})
    return result[:20]
