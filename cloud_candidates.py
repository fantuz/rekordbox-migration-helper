"""Suggest captured library folders without probing or opening music files.

Provider configuration, captured paths and local availability are separate
evidence. Suggestions never attach a folder or infer an account or sync mode.
"""
from collections import defaultdict
import os
from pathlib import PurePosixPath,PureWindowsPath
import re
import unicodedata

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


def _suffix_matches(path,tail):
    if len(tail)<2 or len(path.parts)<=len(tail):return False
    normalized=lambda parts:tuple(unicodedata.normalize('NFC',part).casefold() for part in parts)
    return normalized(path.parts[-len(tail):])==normalized(tail)


def suggestions(snapshot,roots):
    """Return bounded metadata hints; ``available=None`` means uninspected.

    Every captured reference can contribute, but one track counts once per
    candidate. A recorded '/' choice is logical library-root evidence only;
    selecting it must never select this computer's physical filesystem root.
    """
    known=[]
    for row in roots or []:
        base=lexical_path(row.get('root'))
        if base and row.get('kind') in ('dropbox','google_drive'):
            known.append((base,row))
    groups=defaultdict(dict);reference_fields=defaultdict(set)
    def add(key,identity,field,path):
        paths=groups[key].setdefault(identity,[])
        if path not in paths:paths.append(path)
        reference_fields[key].add(field)
    for identity,track in enumerate(snapshot.get('tracks',[])[:250000]):
        references=[(field,path) for field in FIELDS if (path:=lexical_path(track.get(field))) is not None]
        for field,path in references:
            candidates=[(base,row) for base,row in known if type(base) is type(path) and path.is_relative_to(base)]
            if candidates:
                base,row=max(candidates,key=lambda item:len(item[0].parts))
                key=(row['kind'],base,'provider_configuration' if row.get('provider_verified') else 'folder_hint')
            else:
                kind,hint=_hint(path)
                key=(kind,hint or _bucket(path),'captured_provider_hint' if hint else 'captured_path')
            add(key,identity,field,path)
        # Some native cloud references start at the cloud library root, while
        # OrgFolderPath retains another computer's complete Dropbox path.
        # Correlate the entire relative tail, never only the basename.
        for field,path in references:
            if not isinstance(path,PurePosixPath) or len(path.parts)<3:continue
            if any(type(base) is type(path) and path.is_relative_to(base) for base,_ in known):continue
            correlated=set()
            for original_field,original in references:
                if original_field==field:continue
                kind,hint=_hint(original)
                if not hint or not _suffix_matches(original,path.parts[1:]):continue
                prefix=type(original)(*original.parts[:-len(path.parts[1:])])
                if not prefix.is_relative_to(hint):continue
                key=(kind,prefix,'correlated_cloud_paths')
                add(key,identity,original_field,original);reference_fields[key].add(field)
                correlated.add(kind)
            is_contents=bool(re.fullmatch(r'contents_[A-Za-z0-9_-]+',path.parts[1],re.I))
            for kind in correlated or ({'unknown'} if is_contents else set()):
                add((kind,PurePosixPath('/'),'cloud_relative_reference'),identity,field,path)
    priority={'correlated_cloud_paths':0,'cloud_relative_reference':1}
    ordered=sorted(groups.items(),key=lambda item:(priority.get(item[0][2],2),item[0][0]=='unknown',-len(item[1])))
    result=[];seen=set()
    for key,members in ordered[:20]:
        kind,base,evidence=key;paths=[path for values in members.values() for path in values]
        logical=evidence=='cloud_relative_reference'
        folders=(base,) if logical else (base,_common(paths)) if evidence=='correlated_cloud_paths' else (_common(paths),base)
        for folder in folders:
            if not folder or (len(folder.parts)<2 and not logical):continue
            identity=(kind,folder)
            if identity in seen:continue
            seen.add(identity)
            foreign=isinstance(folder,PureWindowsPath) if os.name!='nt' else isinstance(folder,PurePosixPath)
            configured=next((row for root,row in known if root==folder and type(root) is type(folder)),None)
            availability=configured.get('availability') if configured else None
            available=False if foreign else True if availability=='available' else None
            result.append({'path':str(folder),'recorded_root':str(folder),'kind':kind,
                           'evidence':evidence,'tracks':len(members),'available':None if logical else available,
                           'foreign':True if logical else foreign,'recorded_library_root':logical,
                           'reference_fields':[field for field in FIELDS if field in reference_fields[key]],
                           'samples':[str(path) for path in paths[:3]]})
    return result[:20]
