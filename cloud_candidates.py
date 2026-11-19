"""Suggest captured library folders without probing or opening music files.

Provider configuration, captured paths and local availability are separate
evidence. Suggestions never attach a folder or infer an account or sync mode.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import islice
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


@dataclass(slots=True)
class _Candidate:
    tracks: int = 0
    last_track: int = -1
    common_parts: tuple = ()
    fields: set = field(default_factory=set)
    samples: list = field(default_factory=list)

    def observe(self, track_index, reference_field, path):
        # Tracks arrive in order. Multiple references from one track may add
        # field evidence, but contribute only one to this folder's count.
        parent = path.parts[:-1]
        if self.last_track == -1:
            self.common_parts = parent
        elif parent[:len(self.common_parts)] != self.common_parts:
            length = min(len(parent), len(self.common_parts))
            for index in range(length):
                first, other = self.common_parts[index], parent[index]
                if first == other or (isinstance(path, PureWindowsPath) and first.lower() == other.lower()):
                    continue
                length = index
                break
            self.common_parts = self.common_parts[:length]
        if self.last_track != track_index:
            self.tracks += 1
            self.last_track = track_index
        self.fields.add(reference_field)
        if len(self.samples) < 3 and (track_index, path) not in self.samples:
            self.samples.append((track_index, path))


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
    groups=defaultdict(_Candidate)
    for identity,track in enumerate(islice(snapshot.get('tracks',[]),250000)):
        references=[(field,path) for field in FIELDS if (path:=lexical_path(track.get(field))) is not None]
        for field,path in references:
            candidates=[(base,row) for base,row in known if type(base) is type(path) and path.is_relative_to(base)]
            if candidates:
                base,row=max(candidates,key=lambda item:len(item[0].parts))
                key=(row['kind'],base,'provider_configuration' if row.get('provider_verified') else 'folder_hint')
            else:
                kind,hint=_hint(path)
                key=(kind,hint or _bucket(path),'captured_provider_hint' if hint else 'captured_path')
            groups[key].observe(identity,field,path)
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
                groups[key].observe(identity,original_field,original)
                groups[key].fields.add(field)
                correlated.add(kind)
            is_contents=bool(re.fullmatch(r'contents_[A-Za-z0-9_-]+',path.parts[1],re.I))
            for kind in correlated or ({'unknown'} if is_contents else set()):
                groups[kind,PurePosixPath('/'),'cloud_relative_reference'].observe(identity,field,path)
    priority={'correlated_cloud_paths':0,'cloud_relative_reference':1}
    ordered=sorted(groups.items(),key=lambda item:(priority.get(item[0][2],2),item[0][0]=='unknown',-item[1].tracks))
    result=[];seen=set()
    for (kind,base,evidence),group in ordered[:20]:
        common=type(base)(*group.common_parts) if group.common_parts else None
        logical=evidence=='cloud_relative_reference'
        folders=(base,) if logical else (base,common) if evidence=='correlated_cloud_paths' else (common,base)
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
                           'evidence':evidence,'tracks':group.tracks,'available':None if logical else available,
                           'foreign':True if logical else foreign,'recorded_library_root':logical,
                           'reference_fields':[field for field in FIELDS if field in group.fields],
                           'samples':[str(path) for _,path in group.samples]})
    return result[:20]
