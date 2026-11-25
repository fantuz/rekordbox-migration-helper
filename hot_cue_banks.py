"""Check references from native Hot Cue Banks before consolidating duplicate tracks."""
import json


def _unique_fields(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('duplicate bank field')
        obj[key] = value
    return obj


def _identity(value):
    if value is None:
        return None
    if type(value) not in (str, int):
        raise ValueError('unsupported bank reference')
    return str(value) if value not in ('', '0', 0) else None


def _bank_links(db, tables):
    for table in ('djmdsonghotcuebanklist', 'hotcuebanklistcue'):
        columns = tables.get(table)
        if columns is None:
            continue
        if 'rb_local_deleted' not in columns:
            if db.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone():
                raise ValueError('unknown bank schema')
            continue
        active = f' FROM "{table}" WHERE COALESCE(rb_local_deleted,0)=0'
        if not db.execute('SELECT 1' + active + ' LIMIT 1').fetchone():
            continue
        if table == 'djmdsonghotcuebanklist':
            if not {'contentid', 'cueid'} <= columns:
                raise ValueError('unknown bank link schema')
            yield from db.execute('SELECT ContentID, CueID' + active)
        else:
            if 'cues' not in columns:
                raise ValueError('unknown serialized bank schema')
            for raw, in db.execute('SELECT Cues' + active):
                if not isinstance(raw, str):
                    raise ValueError('invalid serialized bank')
                entries = json.loads(raw, object_pairs_hook=_unique_fields)
                if not isinstance(entries, list):
                    raise ValueError('invalid serialized bank')
                for entry in entries:
                    if not isinstance(entry, dict):
                        raise ValueError('invalid serialized bank entry')
                    yield entry.get('ContentID'), entry.get('CueID')


def _original_cues(db, track_ids):
    # Use the encrypted source. The export will retire even a native cue missing
    # from the reviewed catalog. Some versions also keep serialized-only cues.
    for start in range(0, len(track_ids), 500):
        group = track_ids[start:start+500]
        where = ' WHERE rb_local_deleted=0 AND ContentID IN (' + ','.join('?' for _ in group) + ')'
        native = set()
        for row in db.execute('SELECT * FROM djmdCue' + where, group):
            cue = dict(row)
            owner, cue_id = str(cue['ContentID']), str(cue['ID'])
            native.add((owner, cue_id))
            yield owner, cue_id, cue
        for owner, raw in db.execute('SELECT ContentID,Cues FROM contentCue' + where, group):
            owner = str(owner)
            entries = json.loads(raw or '[]', object_pairs_hook=_unique_fields)
            if not isinstance(entries, list):
                raise ValueError('unrecognized serialized cue layout')
            for cue in entries:
                if not isinstance(cue, dict) or not _identity(cue.get('ID')):
                    raise ValueError('unidentified serialized cue')
                cue_id = str(cue['ID'])
                if (owner, cue_id) not in native:
                    yield owner, cue_id, cue


# A bank also stores its own copy of the position, seek, label and colour.
_BANK_FIELDS = frozenset('Kind InMsec InFrame InMpegFrame InMpegAbs OutMsec OutFrame '
                         'OutMpegFrame OutMpegAbs Color ColorTableIndex ActiveLoop Comment '
                         'BeatLoopSize CueMicrosec InPointSeekInfo OutPointSeekInfo'.split())


def _linked_owner(db, tables, mapping, results):
    referenced_cues = set()
    track_only = set()
    for content, cue in _bank_links(db, tables):
        content, cue = _identity(content), _identity(cue)
        if content in mapping:
            return content
        if cue is not None:
            referenced_cues.add(cue)
        elif content is not None:
            track_only.add(content)
        else:
            raise ValueError('unidentified bank entry')
    if not referenced_cues and track_only.isdisjoint(results):
        return None
    selected = {owner: {str(c['ID']): c for c in result['cues']} for owner, result in results.items()}
    for owner, cue_id, original in _original_cues(db, [*mapping, *results]):
        if cue_id not in referenced_cues and owner not in track_only:
            continue
        retained = selected.get(owner, {}).get(cue_id)
        if retained is None or any(retained[k] != original.get(k) for k in _BANK_FIELDS & retained.keys()):
            return owner
    return None


def check_bank_merges(db, tables, mapping, results):
    if not mapping:
        return
    banks = {name.casefold(): {col.casefold() for col in columns} for name, columns in tables.items()
             if name.casefold() in ('djmdsonghotcuebanklist', 'hotcuebanklistcue')}
    if not banks:
        return
    try:
        owner = _linked_owner(db, banks, mapping, results)
    except (ValueError, TypeError, RecursionError) as error:
        raise ValueError('Cannot verify active Hot Cue Bank links. Review the banks in rekordbox and '
                         'create a fresh backup, or export the XML separately.') from error
    if owner is None:
        return
    keeper = mapping.get(owner, owner)
    donors = ', '.join(results[keeper]['donors'])
    raise ValueError(f'A Hot Cue Bank uses track {owner} or one of its affected cues. '
                     f'Unstage the duplicate merge ({donors} → {keeper}) and export again, '
                     'or review the bank in rekordbox and create a fresh backup.')
