"""Explicit local cloud attachment roles, independent of a desktop sync client.

No function opens audio. A detected directory is evidence about a provider,
whereas an attachment records the folder the user actually approved.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import stat

from audio_paths import allowed_roots,confined_folder,mapped_path,mapping_applies,recorded
from cloud_file_status import lexical_path
from cloud_locations import provider_roots
from media import cloud_placeholder
from track_playback import AUDIO_EXTENSIONS

PROVIDERS=('dropbox','google_drive')


def ordinary_chain(path):
    """Inspect directory entries only; never hydrate a file or create folders."""
    try:
        for part in (path,*path.parents):
            info=part.lstat()
            if part.is_symlink() or part.is_junction() or cloud_placeholder(info) or not stat.S_ISDIR(info.st_mode):
                raise ValueError('Choose an existing local folder without links or online-only directories.')
    except OSError as error:
        raise ValueError('Connect the local folder before attaching it.') from error


def local_mapping(owner,local_root,provider,sync_mode='selected',recorded_root=None):
    """Constrain browser input before constructing or inspecting its Path."""
    if provider not in PROVIDERS or sync_mode not in ('selected','all'):
        raise ValueError('Choose a supported cloud provider and synchronization method.')
    if provider=='google_drive' and sync_mode!='selected':
        raise ValueError('Rekordbox Google Drive supports selected-file synchronization only.')
    if (not isinstance(local_root,str) or not local_root or len(local_root)>4096
            or any(ord(c)<32 for c in local_root) or local_root.startswith(('//','\\\\'))):
        raise ValueError('Choose an existing absolute local folder.')
    records=provider_roots(include_unavailable=True)
    strong=[row for row in records if row.get('kind')==provider and row.get('provider_verified')]
    if sync_mode=='all':
        # Provider configuration, rather than a folder-name hint, establishes
        # the managed root for Dropbox desktop all-files mode.
        boundaries=[]
        for row in strong:
            try:
                candidate=Path(row['root']);ordinary_chain(candidate)
                boundaries.append(candidate.resolve(strict=True))
            except (OSError,RuntimeError,ValueError):continue
        if not boundaries:
            raise ValueError('All-files mode requires a Dropbox folder detected from its local configuration.')
    else:boundaries=allowed_roots(owner)
    canonical=confined_folder(local_root,boundaries)
    expanded=os.path.normcase(os.path.abspath(os.path.expanduser(local_root)))
    if expanded!=os.path.normcase(str(canonical)):
        raise ValueError('Choose a local folder without symbolic-link aliases.')
    ordinary_chain(canonical)
    info=canonical.stat()
    managed=[];evidence=[];foreign=[]
    for row in records:
        try:
            root=Path(row['root'])
            if not root.is_absolute():continue
            ordinary_chain(root);root=root.resolve(strict=True)
        except (OSError,RuntimeError,ValueError,KeyError):continue
        if row.get('provider_verified') and row.get('kind') in PROVIDERS and row['kind']!=provider:
            foreign.append(str(root))
            if canonical.is_relative_to(root):
                raise ValueError('Choose a download folder outside the other cloud provider, or choose the matching provider.')
        if canonical.is_relative_to(root):
            managed.append(root)
            evidence.append({'kind':row.get('kind'),'root':str(root),
                             'evidence':row.get('evidence','unknown'),
                             'provider_verified':bool(row.get('provider_verified'))})
    # Even a selected-files cache might live in another provider's managed
    # tree. Staging must be outside its outermost ancestor, not just this cache.
    managed_root=min(managed,key=lambda p:len(p.parts)) if managed else canonical
    managed_info=managed_root.stat()
    result={'local_root':str(canonical),'device':info.st_dev,'inode':info.st_ino,
            'managed_root':str(managed_root),'managed_device':managed_info.st_dev,
            'managed_inode':managed_info.st_ino,'provider':provider,'sync_mode':sync_mode,
            'location_role':'desktop_folder' if sync_mode=='all' else 'selected_download_folder',
            'provider_evidence':evidence,'foreign_provider_roots':foreign}
    if recorded_root not in (None,''):
        prefix=recorded(recorded_root)
        if prefix is None:raise ValueError('Choose an absolute recorded library folder.')
        # Keep a Windows drive root absolute after recorded() normalizes it.
        if len(prefix)==2 and prefix[1]==':':prefix+='/'
        result['recorded_root']=prefix
    return result


def validate_local(mapping):
    """Recheck root confinement and identities without cloud API requests."""
    try:
        root=Path(mapping['local_root']);managed=Path(mapping['managed_root'])
        if (not root.is_absolute() or not managed.is_absolute() or '..' in root.parts or '..' in managed.parts
                or not root.is_relative_to(managed)):
            raise ValueError('The cloud attachment folder changed. Verify it again.')
        ordinary_chain(root);ordinary_chain(managed)
        info=root.stat();outer=managed.stat()
        if ((info.st_dev,info.st_ino)!=(mapping['device'],mapping['inode']) or
                (outer.st_dev,outer.st_ino)!=(mapping['managed_device'],mapping['managed_inode'])):
            raise ValueError('The cloud attachment folder changed. Verify it again.')
        prefix=mapping.get('recorded_root')
        if prefix is not None and recorded(prefix) is None:
            raise ValueError('The recorded cloud folder changed. Verify it again.')
    except (KeyError,TypeError) as error:
        raise ValueError('Verify the cloud attachment again.') from error


def track_target(track,mapping,audio_mappings=None):
    """Translate complete relative paths; never identify a file by basename."""
    local=lexical_path(mapping['local_root']);prefix=lexical_path(mapping.get('recorded_root'))
    for field in ('current_path','xml_location','original_path'):
        value=track.get(field)
        if not value:continue
        if mapping_applies(value,audio_mappings):
            mapped=mapped_path(value,audio_mappings)
            if mapped is None:continue
            candidate=lexical_path(str(mapped))
            base=local
        else:
            candidate=lexical_path(value)
            base=prefix if (prefix and candidate and type(prefix) is type(candidate)
                            and candidate.is_relative_to(prefix)) else local
        if (not candidate or not base or type(candidate) is not type(base)
                or not candidate.is_relative_to(base)):
            continue
        parts=candidate.relative_to(base).parts
        if not parts or candidate.suffix.lower() not in AUDIO_EXTENSIONS:continue
        # Local destination uses only relative path components that lexical_path
        # already checked for traversal/UNC/Windows stream aliases.
        destination=Path(mapping['local_root']).joinpath(*parts)
        if any(destination.is_relative_to(Path(root)) for root in mapping.get('foreign_provider_roots',[])):
            continue
        return {'local_path':str(destination),
                'relative_path':'/'.join(parts),'filename':parts[-1],
                'recorded_path':str(value),'reference_field':field}
    return None


def digest(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def local_presence(value):
    """Return filesystem attributes only, including placeholder uncertainty."""
    try:
        path=Path(value);info=path.lstat()
        if path.is_symlink() or path.is_junction() or not stat.S_ISREG(info.st_mode):
            return {'local_available':False,'local_state':'unverified','local_size':None}
        if cloud_placeholder(info):return {'local_available':False,'local_state':'online_only','local_size':info.st_size}
        return {'local_available':bool(info.st_size>0 and os.access(path,os.R_OK)),
                'local_state':'present','local_size':info.st_size}
    except FileNotFoundError:return {'local_available':False,'local_state':'not_local','local_size':None}
    except OSError:return {'local_available':False,'local_state':'unverified','local_size':None}


def validate_destination(mapping,value):
    """Fresh metadata-only check for a nested or newly configured other root."""
    provider=mapping.get('provider','dropbox')
    path=Path(value)
    for row in provider_roots(include_unavailable=True):
        if not row.get('provider_verified') or row.get('kind') not in PROVIDERS or row['kind']==provider:continue
        try:
            root=Path(row['root'])
            if root.is_absolute() and path.is_relative_to(root.resolve()):
                raise ValueError('The download destination belongs to the other cloud provider. Verify another local folder.')
        except (OSError,RuntimeError,KeyError):continue
