"""Logical Serato target paths; never inspect or modify a live installation."""
import re
import sys

from serato_reader import relative_path

PROFILES=('auto','windows','macos')


def _root(value):
    if not isinstance(value,str):raise ValueError('Choose a music volume root')
    if any(ord(c)<32 for c in value):raise ValueError('Invalid target volume root')
    value=value.replace('\\','/').strip()
    if value.startswith('/') and not value.startswith('//'):value=value.rstrip('/') or '/'
    return value


def _mac_volume(value):
    return value=='/' or bool(re.fullmatch(r'/Volumes/[^/]+',value) and
                              value.rsplit('/',1)[-1] not in ('.','..'))


def resolve_serato_profile(source_root,target_root='',profile='auto',host=None):
    host=sys.platform if host is None else host
    if profile not in PROFILES:raise ValueError('Choose an available Serato target profile')
    source_root=_root(source_root)
    target_root=_root(target_root)
    if not source_root:raise ValueError('Choose a music volume root')
    source_windows=bool(re.match(r'^[A-Za-z]:/',source_root))
    if target_root:
        inferred='windows' if re.match(r'^[A-Za-z]:',target_root) else 'macos'
        target=inferred if profile=='auto' else profile
    else:
        target=('windows' if source_windows else 'macos') if profile=='auto' else profile
        # Keep compatible volume roots; cross-platform/default simulation uses
        # an explicit conventional destination, without inspecting local disks.
        target_root=(source_root if re.fullmatch(r'[A-Za-z]:/',source_root) else 'C:/') if target=='windows' else (
            source_root if _mac_volume(source_root) else '/Volumes/DJ')
    if any(ord(c)<32 for c in target_root):raise ValueError('Invalid target volume root')
    if target=='windows':
        if not re.fullmatch(r'[A-Za-z]:/',target_root):
            raise ValueError('Windows target requires a drive root such as D:/')
        target_root=target_root[0].upper()+':/'
        paths={'music':'%USERPROFILE%/Music/_Serato_',
               'library':'%LOCALAPPDATA%/Serato/Library',
               'external':target_root+'_Serato_'}
    else:
        if not _mac_volume(target_root):
            raise ValueError('macOS target requires / or /Volumes/<drive>')
        paths={'music':'~/Music/_Serato_',
               'library':'~/Library/Application Support/Serato/Library',
               'external':target_root.rstrip('/')+'/_Serato_'}
    native=(host.startswith('win') and target=='windows') or (host=='darwin' and target=='macos')
    return {'target':target,'requested_profile':profile,'simulated':not native,
            'source_volume_root':source_root,'target_volume_root':target_root,'paths':paths,
            'legacy_database_only':True,
            'note':'Path profile only: no Serato 4.x SQLite output or live application compatibility is claimed.'}


def mapped_serato_path(relative,profile):
    return profile['target_volume_root'].rstrip('/')+'/'+relative_path(relative)
