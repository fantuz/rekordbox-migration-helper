"""Serato target OS profiles for detached, unverified legacy exports.

Do not inspect, access or alter a native Serato installation. All paths below
are documentation hints; a Music volume is not a Serato 4.x SQLite database.
"""
import re
import sys
from pathlib import PurePosixPath,PureWindowsPath

PROFILES=('auto','windows','macos')


def resolve_serato_profile(source_root,target_root='',profile='auto',host=None):
    host=sys.platform if host is None else host
    if profile not in PROFILES:raise ValueError('Choose an available Serato target profile')
    source_root=str(source_root or '').replace('\\','/').strip()
    target_root=str(target_root or source_root).replace('\\','/').strip()
    if not source_root or not target_root:raise ValueError('Choose a music volume root')
    target='windows' if re.fullmatch(r'[A-Za-z]:/',target_root) else 'macos'
    if profile!='auto' and profile!=target:raise ValueError('Target root does not match the selected Serato OS profile')
    if target=='windows':
        if not re.fullmatch(r'[A-Za-z]:/',target_root):raise ValueError('Windows target requires a drive root such as D:/')
        if len(PureWindowsPath(target_root).parts)!=1:raise ValueError('Windows target requires a drive root')
        paths={'music':'%USERPROFILE%/Music/_Serato_',
               'library':'%LOCALAPPDATA%/Serato/Library',
               'external':'<Drive>:/_Serato_'}
    else:
        if not target_root.startswith('/') or target_root.startswith('//') or '..' in PurePosixPath(target_root).parts:
            raise ValueError('macOS target requires an absolute POSIX volume root such as /Volumes/DJ')
        paths={'music':'~/Music/_Serato_',
               'library':'~/Library/Application Support/Serato/Library',
               'external':'/Volumes/<Drive>/_Serato_'}
    native=(host.startswith('win') and target=='windows') or (host=='darwin' and target=='macos')
    return {'target':target,'simulated':not native,'source_volume_root':source_root,
            'target_volume_root':target_root,'paths':paths,
            'note':'Path profile only: no Serato 4.x SQLite output or live application compatibility is claimed.'}
