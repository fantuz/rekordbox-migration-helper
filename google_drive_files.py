"""Google Drive folder identities and bounded metadata-only music inventory.

Names in Drive are neither unique nor case-insensitive.  A path match therefore
requires the complete parent-ID hierarchy below an explicitly selected folder;
duplicate names and shortcuts retain uncertainty rather than selecting a file.
"""
from collections import defaultdict, deque
from hashlib import sha256
import json
import re
import unicodedata
from urllib.parse import parse_qs, urlsplit

from cloud_locations import provider_roots

FOLDER_MIME = 'application/vnd.google-apps.folder'
SHORTCUT_MIME = 'application/vnd.google-apps.shortcut'
FILE_FIELDS = ('id,name,mimeType,parents,size,modifiedTime,version,md5Checksum,'
               'sha256Checksum,trashed,driveId,capabilities(canDownload),shortcutDetails')
MAX_ENTRIES = 250000
MAX_PAGES = 300
MAX_FOLDERS = 25000
PARENT_BATCH = 50


def file_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', value):
        raise ValueError('Choose a valid Google Drive folder or file ID.')
    return value


def folder_id(value):
    """Accept a Drive folder link as a convenience; never fetch the supplied URL."""
    if isinstance(value, str) and value.startswith('https://'):
        parsed = urlsplit(value)
        if (parsed.hostname != 'drive.google.com' or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.fragment):
            raise ValueError('Paste a Google Drive folder link or its folder ID.')
        match = re.fullmatch(r'/drive/(?:u/\d+/)?folders/([A-Za-z0-9_-]+)/?', parsed.path)
        if match:value = match.group(1)
        elif parsed.path == '/open':
            values = parse_qs(parsed.query).get('id', [])
            if len(values) != 1:raise ValueError('Paste a Google Drive folder link or its folder ID.')
            value = values[0]
        else:raise ValueError('Paste a Google Drive folder link or its folder ID.')
    return file_id(value)


def path_key(value):
    return unicodedata.normalize('NFC', value)


def detected_roots():
    return [row for row in provider_roots(include_unavailable=True) if row.get('kind') == 'google_drive']


def _folder(connection, identity):
    value = connection.rpc('files/get', {'fileId': folder_id(identity), 'fields': FILE_FIELDS})
    if (not isinstance(value, dict) or value.get('mimeType') != FOLDER_MIME
            or value.get('trashed') is True):
        raise ValueError('Choose an accessible Google Drive folder, not a file or shortcut.')
    file_id(value.get('id'))
    if value.get('driveId'):
        raise ValueError('Shared Drive folders are not supported by this mapping. Choose a folder in My Drive.')
    return value


def mapping_record(connection, local_root, remote_folder_id, *, owner=None,
                   sync_mode='selected', recorded_root=None):
    from cloud_attachments import local_mapping
    if owner is None:raise ValueError('Choose the local folder from this Workbench installation.')
    if sync_mode != 'selected':raise ValueError('Google Drive uses selected-file synchronization in Rekordbox.')
    state = connection.status()
    account = state.get('account') or {}
    if not state.get('connected') or not account.get('account_id'):
        raise ValueError('Connect Google Drive before attaching a folder.')
    local = local_mapping(owner, local_root, 'google_drive', sync_mode='selected', recorded_root=recorded_root)
    remote = _folder(connection, remote_folder_id)
    return {**local, 'provider': 'google_drive', 'sync_mode': 'selected',
            'remote_root': remote['id'], 'remote_folder_id': remote['id'],
            'remote_root_name': str(remote.get('name') or remote['id']),
            'account_id': account['account_id']}


def validate_mapping(connection, mapping):
    from cloud_attachments import validate_local
    state = connection.status()
    account = state.get('account') or {}
    if (not state.get('connected') or not isinstance(mapping, dict)
            or account.get('account_id') != mapping.get('account_id')):
        raise ValueError('Connect the matching Google Drive account and verify its folder attachment.')
    if mapping.get('sync_mode', 'selected') != 'selected':
        raise ValueError('Google Drive uses selected-file synchronization in Rekordbox.')
    file_id(mapping.get('remote_root'))
    validate_local(mapping)
    return state


def binding(connection, mapping):
    state = validate_mapping(connection, mapping)
    return sha256(json.dumps([state['connection_id'], mapping], sort_keys=True).encode()).hexdigest()


def target(track, mapping, audio_mappings=None):
    from cloud_attachments import track_target
    value = track_target(track, mapping, audio_mappings)
    if not value:return None
    relative = value['relative_path']
    if len(relative)>4096 or len(relative.split('/'))>64:return None
    return {**value, 'remote_path': relative, 'remote_key': path_key(relative)}


class Inventory(dict):
    def __init__(self):
        super().__init__()
        self.blocked = {}
        self.folded = None
        self.folded_blocked = None
        self.pages_read = 0
        self.entries_listed = 0


def lookup(entries, relative_path):
    key = path_key(relative_path)
    blocked = getattr(entries, 'blocked', {})
    if '' in blocked:return None, blocked['']
    # Walk path components instead of scanning every blocked folder for every
    # track in a large collection. No differently cased path selects a Drive ID.
    prefix=[]
    for component in key.split('/'):
        prefix.append(component);candidate='/'.join(prefix)
        if candidate in blocked:return None, blocked[candidate]
    remote = entries.get(key)
    if remote is None:
        if key in entries:return None, 'ambiguous'
        if isinstance(entries,Inventory):
            if entries.folded is None:
                entries.folded={path.casefold() for path in entries}
                entries.folded_blocked={path.casefold() for path in blocked}
            if key.casefold() in entries.folded:return None, 'unverified'
            prefix=[]
            for component in key.split('/'):
                prefix.append(component)
                if '/'.join(prefix).casefold() in entries.folded_blocked:return None,'unverified'
        return None,'not_found'
    return remote, 'present'


def _entry(value, parents):
    if not isinstance(value, dict):raise ValueError('Google Drive returned invalid file metadata.')
    identity = file_id(value.get('id'))
    name = value.get('name')
    mime = value.get('mimeType')
    given_parents = value.get('parents')
    if (not isinstance(name, str) or not name or len(name) > 4096
            or name in ('.', '..') or any(ord(c) < 32 for c in name)
            or '/' in name or '\\' in name or not isinstance(mime, str)
            or not isinstance(given_parents, list) or not given_parents
            or any(not isinstance(p, str) for p in given_parents)
            or not any(p in parents for p in given_parents)
            or value.get('trashed') is True or value.get('driveId')):
        raise ValueError('Google Drive returned an invalid or unsupported folder entry.')
    return identity, name, mime, [p for p in given_parents if p in parents]


def inventory(connection, mapping, progress):
    """Enumerate only the chosen subtree, batching parent IDs rather than names."""
    from cloud_progress import CloudProgress
    result = Inventory()
    pending = deque([(mapping['remote_root'], '')])
    visited = set();complete = True
    last_item = mapping.get('remote_name', '')
    def report_page():
        progress(5 + min(55, result.pages_read // 2), CloudProgress('Google Drive','Reading folder metadata',
                 item=last_item,unit='entries',completed=result.entries_listed,pages=result.pages_read))
    report_page()
    while pending:
        if result.pages_read >= MAX_PAGES:return result, False
        batch = [pending.popleft() for _ in range(min(PARENT_BATCH, len(pending)))]
        parents = dict(batch)
        if any(identity in visited for identity in parents):
            raise ValueError('Google Drive returned a cyclic or ambiguous folder hierarchy.')
        visited.update(parents)
        if len(visited) > MAX_FOLDERS:return result, False
        children = defaultdict(dict);tokens = set();token = None
        while True:
            if result.pages_read >= MAX_PAGES:return result, False
            payload = {'q': '(' + ' or '.join("'" + p + "' in parents" for p in parents) + ') and trashed = false',
                       'pageSize': 1000, 'spaces': 'drive', 'corpora': 'user',
                       'fields': 'nextPageToken,incompleteSearch,files(' + FILE_FIELDS + ')'}
            if token:payload['pageToken'] = token
            response = connection.rpc('files/list', payload);result.pages_read += 1
            if not isinstance(response, dict) or not isinstance(response.get('files'), list):
                raise ValueError('Google Drive returned an invalid metadata listing.')
            incomplete = response.get('incompleteSearch', False)
            if type(incomplete) is not bool:raise ValueError('Google Drive returned invalid listing completeness.')
            if incomplete:
                complete = False
                for prefix in parents.values():result.blocked[prefix] = 'unverified'
            for value in response['files']:
                if result.entries_listed >= MAX_ENTRIES:
                    report_page();return result, False
                identity, name, mime, matched = _entry(value, parents)
                result.entries_listed += 1
                last_item = name
                for parent in matched:
                    prior = children[parent].get(identity)
                    if prior is not None and prior != value:
                        raise ValueError('Google Drive returned inconsistent file identities.')
                    if prior is not None:
                        raise ValueError('Google Drive repeated a file across metadata pages.')
                    children[parent][identity] = value
            report_page()
            token = response.get('nextPageToken')
            if not token:break
            if (not isinstance(token, str) or len(token) > 4096 or any(ord(c) < 32 for c in token)
                    or token in tokens):raise ValueError('Google Drive returned an invalid listing cursor.')
            tokens.add(token)
        for parent, prefix in batch:
            names = defaultdict(list)
            for entry in children[parent].values():names[path_key(entry['name'])].append(entry)
            for name, entries in names.items():
                path = prefix + '/' + name if prefix else name
                if len(entries) != 1:
                    result[path] = None;result.blocked[path] = 'ambiguous'
                    continue
                entry = entries[0];mime = entry['mimeType']
                if mime == FOLDER_MIME:
                    if len(path)>4096 or len(path.split('/'))>=64:
                        result[path]=None;result.blocked[path]='unverified'
                    else:pending.append((entry['id'], path))
                elif mime.startswith('application/vnd.google-apps.'):
                    result[path] = None;result.blocked[path] = 'unverified'
                else:
                    # Existence does not require download eligibility or a hash.
                    size = entry.get('size')
                    if size is not None and (not isinstance(size, (str, int)) or isinstance(size, bool)
                            or not str(size).isdigit()):raise ValueError('Google Drive returned an invalid file size.')
                    result[path] = entry
    return result, complete


def resolve_file(connection, mapping, relative_path):
    """Resolve one path freshly by exact parent IDs, refusing duplicate names."""
    if (not isinstance(relative_path, str) or len(relative_path) > 4096
            or '\\' in relative_path or relative_path.startswith('/')):
        raise ValueError('Choose a file below the attached Google Drive folder.')
    parts = relative_path.split('/')
    if (len(parts) > 64 or any(not p or p in ('.', '..') or any(ord(c)<32 for c in p) for p in parts)):
        raise ValueError('Choose a file below the attached Google Drive folder.')
    parent = _folder(connection, mapping['remote_root'])['id']
    for position, name in enumerate(parts):
        escaped = name.replace('\\', '\\\\').replace("'", "\\'")
        payload = {'q': "'" + parent + "' in parents and trashed = false and name = '" + escaped + "'",
                   'pageSize': 100, 'spaces': 'drive', 'corpora': 'user',
                   'fields': 'nextPageToken,incompleteSearch,files(' + FILE_FIELDS + ')'}
        found = {};tokens = set()
        for page in range(20):
            value = connection.rpc('files/list', payload)
            if (not isinstance(value, dict) or not isinstance(value.get('files'), list)
                    or value.get('incompleteSearch', False)):
                raise ValueError('Google Drive could not verify this file path completely.')
            for candidate in value['files']:
                identity, candidate_name, mime, _ = _entry(candidate, {parent: ''})
                if path_key(candidate_name) != path_key(name):continue
                if identity in found:raise ValueError('Google Drive returned a repeated file identity.')
                found[identity] = candidate
                if len(found)>1:raise ValueError('This Google Drive path has duplicate names. Choose a unique folder or filename.')
            token = value.get('nextPageToken')
            if not token:break
            if (not isinstance(token,str) or len(token)>4096 or token in tokens
                    or any(ord(c)<32 for c in token)):
                raise ValueError('Google Drive returned an invalid listing cursor.')
            tokens.add(token);payload['pageToken']=token
        else:raise ValueError('Google Drive could not verify that this path is unique.')
        if len(found)!=1:raise ValueError('This file path was not found in the attached Google Drive folder.')
        entry=next(iter(found.values()))
        if position<len(parts)-1:
            if entry['mimeType']!=FOLDER_MIME:
                raise ValueError('This Google Drive path contains a file or shortcut where a folder is required.')
            parent=entry['id']
        elif entry['mimeType'].startswith('application/vnd.google-apps.'):
            raise ValueError('Google cloud documents, folders and shortcuts are not downloadable audio files.')
    return entry


def browse_folders(connection, remote_folder_id='root', page_token=None):
    folder = _folder(connection, remote_folder_id)
    if page_token is not None and (not isinstance(page_token, str) or not 1 <= len(page_token) <= 4096
                                   or any(ord(c) < 32 for c in page_token)):
        raise ValueError('Choose a valid Google Drive folder page.')
    payload = {'q': "'" + folder['id'] + "' in parents and trashed = false and mimeType = '" + FOLDER_MIME + "'",
               'pageSize': 100, 'spaces': 'drive', 'corpora': 'user',
               'fields': 'nextPageToken,incompleteSearch,files(id,name,mimeType,parents,trashed,driveId)'}
    if page_token:payload['pageToken'] = page_token
    response = connection.rpc('files/list', payload)
    if (not isinstance(response, dict) or not isinstance(response.get('files'), list)
            or response.get('incompleteSearch', False)):
        raise ValueError('Google Drive could not completely list this folder page.')
    rows=[]
    for row in response['files']:
        identity, name, mime, _ = _entry(row, {folder['id']: ''})
        if mime != FOLDER_MIME:raise ValueError('Google Drive returned an invalid folder choice.')
        rows.append({'id': identity, 'name': name})
    rows.sort(key=lambda row: (row['name'].casefold(), row['id']))
    token=response.get('nextPageToken')
    if token is not None and (not isinstance(token, str) or not token or len(token)>4096
                              or any(ord(c)<32 for c in token)):
        raise ValueError('Google Drive returned an invalid folder cursor.')
    return {'rows': rows, 'next_page_token': token,
            'folder': {'id': folder['id'], 'name': str(folder.get('name') or folder['id'])}}
