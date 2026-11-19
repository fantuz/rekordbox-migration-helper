"""Dropbox path mapping and bounded metadata inventory; never read audio content."""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import unicodedata

from cloud_file_status import lexical_path
from cloud_locations import provider_roots
from media import cloud_placeholder
from track_playback import AUDIO_EXTENSIONS

MAX_ENTRIES=250000
MAX_PAGES=150


def detected_roots():
    return [r for r in provider_roots(include_unavailable=True) if r.get('kind')=='dropbox' and r.get('provider_verified')]


def ordinary_chain(path):
    try:
        for item in (path,*path.parents):
            info=item.lstat()
            if item.is_symlink() or item.is_junction() or cloud_placeholder(info) or not stat.S_ISDIR(info.st_mode):
                raise ValueError('Choose an existing local Dropbox folder without links or online-only directories.')
    except OSError as error:
        raise ValueError('Connect the existing local Dropbox folder before checking its mapping.') from error


def remote_path(value):
    if not isinstance(value,str) or len(value)>4096 or any(ord(c)<32 for c in value) or '\\' in value:
        raise ValueError('Enter a Dropbox folder path beginning with /.')
    if value=='/':return ''
    if value.endswith('/'):value=value[:-1]
    if value and (not value.startswith('/') or any(p in ('','.','..') for p in value[1:].split('/'))):
        raise ValueError('Enter a Dropbox folder path beginning with /.')
    return value


def path_key(value):return unicodedata.normalize('NFC',value).lower()


def mapping_record(connection,local_root,remote_root,namespace=None):
    if not isinstance(local_root,str) or any(ord(c)<32 for c in local_root):raise ValueError('Choose a detected Dropbox folder.')
    path=Path(local_root).expanduser()
    if not path.is_absolute() or '..' in path.parts:raise ValueError('Choose a detected Dropbox folder.')
    ordinary_chain(path)
    canonical=path.resolve(strict=True)
    managed=[]
    for row in detected_roots():
        root=Path(row['root'])
        try:
            ordinary_chain(root)
            boundary=root.resolve(strict=True)
            if canonical.is_relative_to(boundary):managed.append(boundary)
        except (OSError,RuntimeError,ValueError):continue
    if not managed:
        raise ValueError('Choose a folder inside a Dropbox root detected from local provider configuration.')
    # Use the outermost managed root: staging in an ancestor of the selected
    # music subfolder must still not create a partially synced Dropbox file.
    managed_root=min(managed,key=lambda p:len(p.parts))
    managed_info=managed_root.stat()
    state=connection.status();account=state.get('account') or {}
    if not state.get('connected'):raise ValueError('Connect Dropbox before mapping a folder.')
    namespace=namespace or account.get('root_namespace_id')
    if not isinstance(namespace,str) or not re.fullmatch(r'\d{1,40}',namespace):raise ValueError('Choose a valid Dropbox namespace.')
    remote_root=remote_path(remote_root)
    root={'.tag':'namespace_id','namespace_id':namespace}
    if remote_root:
        info=connection.rpc('files/get_metadata',{'path':remote_root},path_root=root)
        if info.get('.tag')!='folder':raise ValueError('Choose a Dropbox folder, not a file.')
    else:connection.rpc('files/list_folder',{'path':'','limit':1,'recursive':False},path_root=root)
    info=canonical.stat()
    return {'local_root':str(canonical),'remote_root':remote_root,'namespace':namespace,
            'account_id':account.get('account_id'),'device':info.st_dev,'inode':info.st_ino,
            'managed_root':str(managed_root),'managed_device':managed_info.st_dev,'managed_inode':managed_info.st_ino}


def validate_mapping(connection,mapping):
    state=connection.status();account=state.get('account') or {}
    if not state.get('connected') or not mapping or account.get('account_id')!=mapping.get('account_id'):
        raise ValueError('Connect the matching Dropbox account and verify its folder mapping.')
    try:
        path=Path(mapping['local_root']);managed=Path(mapping['managed_root'])
        if not path.is_absolute() or not managed.is_absolute() or '..' in path.parts or '..' in managed.parts:
            raise ValueError('The Dropbox folder changed. Verify its mapping again.')
        ordinary_chain(path);ordinary_chain(managed)
        if not path.is_relative_to(managed):raise ValueError('The Dropbox folder changed. Verify its mapping again.')
        info=path.stat();managed_info=managed.stat()
        if ((info.st_dev,info.st_ino)!=(mapping['device'],mapping['inode']) or
                (managed_info.st_dev,managed_info.st_ino)!=(mapping['managed_device'],mapping['managed_inode'])):
            raise ValueError('The Dropbox folder changed. Verify its mapping again.')
        if mapping['remote_root']!=remote_path(mapping['remote_root']):
            raise ValueError('The Dropbox folder changed. Verify its mapping again.')
        if not isinstance(mapping['namespace'],str) or not re.fullmatch(r'\d{1,40}',mapping['namespace']):
            raise ValueError('The Dropbox folder changed. Verify its mapping again.')
    except (KeyError,TypeError) as error:
        raise ValueError('Verify the Dropbox folder mapping again before checking files.') from error
    return state


def binding(connection,mapping):
    state=validate_mapping(connection,mapping)
    return sha256(json.dumps([state['connection_id'],mapping],sort_keys=True).encode()).hexdigest()


def target(track,mapping,audio_mappings=None):
    from audio_paths import mapped_path,mapping_applies
    root=lexical_path(mapping['local_root'])
    for field in ('current_path','xml_location','original_path'):
        value=track.get(field)
        if not value:continue
        if mapping_applies(value,audio_mappings):
            mapped=mapped_path(value,audio_mappings)
            if mapped is None:continue
            value=str(mapped)
        path=lexical_path(value)
        if not path or type(path) is not type(root) or not path.is_relative_to(root):continue
        parts=path.relative_to(root).parts
        if not parts or path.suffix.lower() not in AUDIO_EXTENSIONS:continue
        remote=remote_path(mapping['remote_root']+'/'+ '/'.join(parts))
        return {'local_path':str(Path(mapping['local_root']).joinpath(*parts)),'remote_path':remote,'filename':parts[-1]}
    return None


def local_available(path):
    try:
        path=Path(path);info=path.lstat()
        return stat.S_ISREG(info.st_mode) and not path.is_symlink() and not cloud_placeholder(info) and info.st_size>0 and os.access(path,os.R_OK)
    except OSError:return False


def inventory(connection,mapping,progress):
    """List the selected remote subtree once, including explicitly reported pagination."""
    root={'.tag':'namespace_id','namespace_id':mapping['namespace']}
    route='files/list_folder';payload={'path':mapping['remote_root'],'recursive':True,'include_deleted':False,'limit':2000}
    files={};seen=0;cursors=set();paths=set();identities=set()
    for page in range(MAX_PAGES):
        progress(5+min(60,page), 'Checking Dropbox file metadata')
        result=connection.rpc(route,payload,path_root=root)
        if not isinstance(result,dict):raise ValueError('Dropbox returned an invalid metadata listing.')
        entries=result.get('entries');more=result.get('has_more')
        if not isinstance(entries,list) or not isinstance(more,bool):raise ValueError('Dropbox returned an invalid metadata listing.')
        for entry in entries:
            seen+=1
            if seen>MAX_ENTRIES:return files,False
            if not isinstance(entry,dict) or entry.get('.tag') not in ('file','folder'):
                raise ValueError('Dropbox returned an invalid metadata entry.')
            path=entry.get('path_lower') or entry.get('path_display')
            if not isinstance(path,str) or not path or path!=remote_path(path):
                raise ValueError('Dropbox returned an invalid metadata path.')
            prefix=path_key(mapping['remote_root'])
            key=path_key(path)
            if prefix and not key.startswith(prefix+'/'):
                raise ValueError('Dropbox returned a path outside the selected folder.')
            identity=entry.get('id')
            if (not isinstance(identity,str) or not identity or len(identity)>4096 or
                    any(ord(c)<32 for c in identity)):
                raise ValueError('Dropbox returned an invalid metadata identity.')
            if key in paths or identity in identities:raise ValueError('Dropbox returned ambiguous file paths.')
            paths.add(key);identities.add(identity)
            display=entry.get('path_display')
            if display is not None and (not isinstance(display,str) or display!=remote_path(display) or path_key(display)!=key):
                raise ValueError('Dropbox returned inconsistent metadata paths.')
            if entry['.tag']=='folder':continue
            if (not isinstance(entry.get('rev'),str) or not entry['rev'] or len(entry['rev'])>4096 or
                    any(ord(c)<32 for c in entry['rev']) or type(entry.get('size')) is not int or entry['size']<0 or
                    ('is_downloadable' in entry and type(entry['is_downloadable']) is not bool)):
                raise ValueError('Dropbox returned invalid file metadata.')
            files[key]=entry
        if not more:return files,True
        cursor=result.get('cursor')
        if not isinstance(cursor,str) or not cursor or cursor in cursors:raise ValueError('Dropbox returned an invalid listing cursor.')
        cursors.add(cursor);route='files/list_folder/continue';payload={'cursor':cursor}
    return files,False
