"""Record relationship coverage while the detached native source is still available."""
import json


# IDs are read only from columns found in the private database's schema. Do not
# retain unrelated records, raw bank payloads or remote identifiers in snapshots.
def _quote(name):
    return '"' + name.replace('"','""') + '"'


def _entries(raw):
    if not isinstance(raw, str) or len(raw) > 4 * 1024 ** 2:
        raise ValueError('Unrecognized serialized collection links')
    def unique(items):
        result = dict(items)
        if len(result) != len(items):
            raise ValueError('Ambiguous serialized collection links')
        return result
    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, list) or not all(isinstance(entry, dict) for entry in value):
        raise ValueError('Unknown serialized collection links')
    return value


def capture_links(db, columns, snapshot):
    """Keep per-owner protection flags and distinguish incomplete captures from checked empty tables."""
    caps = snapshot['capabilities']
    complete = all(caps.get(name) for name in ('cue_positions', 'playlist_membership', 'analysis_references', 'history_details'))
    required = {'Rating','DJPlayCount','ServiceID','FileSize','OrgFolderPath','Analysed','Commnt'}
    complete = complete and required <= columns['djmdContent']
    gaps = set() if complete else {'missing_native_columns'}
    playlists = snapshot.get('playlists', [])
    if any(p.get('smart') for p in playlists) or (playlists and not {'Attribute', 'SmartList'} & columns.get('djmdPlaylist', set())):
        # Workbench preserves smart definitions but does not evaluate Rekordbox's membership rules.
        gaps.add('smart_membership')
    tracks = {track['id']:track for track in snapshot['tracks']}
    cue_owners = {}
    def index_cue(cue, owner):
        if isinstance(cue, (str, int)) and not isinstance(cue, bool) and cue not in ('', 0, '0'):
            cue_owners.setdefault(str(cue), set()).add(str(owner))
    for track in tracks.values():
        for cue in track.get('cues') or ():
            index_cue(cue.get('id'), track['id'])
    unresolved = False
    uuids = {str(track['uuid']):identity for identity,track in tracks.items() if track.get('uuid')}
    linked = {}
    def protect(identity, code):
        if str(identity) in tracks:
            linked.setdefault(str(identity), set()).add(code)
            return True
        return False

    def rows(table, fields):
        condition = ' WHERE COALESCE(rb_local_deleted,0)=0' if 'rb_local_deleted' in columns[table] else ''
        projection = ','.join(_quote(field) for field in fields) or '1'
        return db.execute('SELECT ' + projection + ' FROM ' + _quote(table) + condition)

    if 'CloudID' in columns['djmdContent']:
        for identity, cloud in rows('djmdContent', ['ID','CloudID']):
            if cloud not in ('','0',None,0):
                protect(identity, 'cloud_reference')
    for table, fields in columns.items():
        name = table.casefold()
        if name == 'contentcue':
            if {'ContentID','Cues'} <= fields:
                for owner, raw in rows(table, ['ContentID','Cues']):
                    if owner in (None, '', 0, '0'):
                        unresolved = True
                        continue
                    if raw is None or raw == '':
                        protect(owner, 'unknown_metadata')
                        continue
                    try:
                        serialized = _entries(raw)
                    except (TypeError,ValueError,RecursionError):
                        protect(owner,'unknown_metadata')
                        continue
                    if serialized:
                        protect(owner,'cues')
                    for cue in serialized:
                        index_cue(cue.get('ID'), owner)
            else:
                unresolved = True
            continue
        if name in ('djmdcontent','hotcuebanklistcue','djmdsonghotcuebanklist'):
            continue
        fields_to_check = [field for field in fields if field.lower() in ('contentid','contentid1','contentid2','contentuuid')]
        if not fields_to_check:
            if name == 'contentfile' and next(iter(rows(table, [])), None) is not None:
                unresolved = True
            continue
        code = {'djmdsongplaylist':'playlist','djmdsonghistory':'play_history','djmdcue':'cues','contentfile':'native_link'}.get(name, 'native_link')
        for row in rows(table, fields_to_check):
            found = False
            for field, value in zip(fields_to_check, row):
                owner = uuids.get(str(value)) if field.lower() == 'contentuuid' else value
                if protect(owner, code):
                    found = True
            if name == 'contentfile' and not found:
                # Its assets have been captured but their relationship to individual tracks is unknown.
                unresolved = True
    # Bank lists can reference only a cue ID. Resolve those against both ordinary
    # and serialized native cues before allowing any row from this capture.
    def bank_link(entry):
        content, cue = entry.get('ContentID'), entry.get('CueID')
        if any(v is not None and (not isinstance(v, (str,int)) or isinstance(v, bool)) for v in (content, cue)):
            return False
        if content not in (None,'',0,'0') and not protect(content, 'hot_cue_bank'):
            return False
        if cue not in (None,'',0,'0'):
            owners = cue_owners.get(str(cue), set())
            if len(owners) != 1 or not protect(next(iter(owners)), 'hot_cue_bank'):
                return False
        return any(v not in (None,'',0,'0') for v in (content, cue))

    for table, fields in columns.items():
        if table.casefold() == 'djmdsonghotcuebanklist':
            if not {'ContentID','CueID'} <= fields:
                unresolved = True
            else:
                for content, cue in rows(table, ['ContentID','CueID']):
                    if not bank_link({'ContentID':content,'CueID':cue}):
                        unresolved = True
        if table.casefold() == 'hotcuebanklistcue':
            if 'Cues' not in fields:
                unresolved = True
            else:
                for raw, in rows(table,['Cues']):
                    try:
                        for entry in _entries(raw):
                            if not bank_link(entry):
                                unresolved = True
                    except (TypeError,ValueError,RecursionError):
                        unresolved = True
    for identity, codes in linked.items():
        tracks[identity]['cleanup_links'] = sorted(codes)
    if unresolved:
        gaps.add('unresolved_native_links')
    snapshot['cleanup_coverage'] = {'version':1, 'scope':'native', 'complete':not gaps, 'gaps':sorted(gaps)}
