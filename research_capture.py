"""Evidence snapshots for comparisons, captured only from detached working data."""
from collections import defaultdict
from copy import deepcopy
from datetime import datetime,timezone
from hashlib import sha256
import json
import sqlite3

from engine import is_auto
from metadata_export import capture_database,capture_catalog


def open_capture(path):
    """Open only a detached app-owned copy, including its private WAL recovery."""
    with path.open('rb') as stream:plaintext=stream.read(16)==b'SQLite format 3\x00'
    if plaintext:return sqlite3.connect(path)
    from native_export import mutable_copy
    return mutable_copy(path)


def capture_private_database(db,scope_key):
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
    columns={t:{c[1] for c in db.execute('PRAGMA table_info("'+t.replace('"','""')+'")')} for t in tables}
    if not {'ID','Title','FolderPath'}<=columns.get('djmdContent',set()):raise ValueError('This private copy has no supported track schema')
    db.execute('PRAGMA query_only=ON')
    snapshot=capture_database(db,columns)
    def rows(table,wanted,include_deleted=False):
        if table not in columns:return []
        fields=','.join('"'+f+'"' if f in columns[table] else 'NULL AS "'+f+'"' for f in wanted)
        active=' WHERE coalesce(rb_local_deleted,0)=0' if 'rb_local_deleted' in columns[table] and not include_deleted else ''
        return [dict(zip(wanted,r)) for r in db.execute('SELECT '+fields+' FROM "'+table+'"'+active)]
    cues=defaultdict(list)
    for r in rows('djmdCue',('ID','UUID','ContentID','Kind','InMsec','OutMsec','Comment','Color')):
        cues[str(r['ContentID'])].append({'id':r['ID'],'uuid':r['UUID'],'kind':r['Kind'],'in_ms':r['InMsec'],'out_ms':r['OutMsec'],'label':r['Comment'] or '', 'color':r['Color'],'auto':is_auto(r)})
    details={str(r['ID']):r for r in rows('djmdContent',('ID','UUID','ISRC','FileSize','AnalysisDataPath','ReleaseYear','BPM','Rating','Length'))}
    history_rows=rows('djmdHistory',('ID','UUID','Name','DateCreated','ParentID','Attribute'))
    history={str(r['ID']):r['DateCreated'] for r in history_rows}
    history_members=rows('djmdSongHistory',('ID','ContentID','HistoryID','TrackNo'))
    last_played={}
    for r in history_members:
        value=history.get(str(r['HistoryID']))
        if value:last_played[str(r['ContentID'])]=max(str(value),last_played.get(str(r['ContentID']),''))
    historical_missing={str(r['ContentID']) for r in history_members}-details.keys()
    archived={}
    if historical_missing:
        artists={str(r['ID']):r['Name'] for r in rows('djmdArtist',('ID','Name'),True)}
        archived={str(r['ID']):{'title':r['Title'] or '', 'artist':artists.get(str(r['ArtistID']),''), 'missing_from_active_collection':True}
                  for r in rows('djmdContent',('ID','Title','ArtistID'),True) if str(r['ID']) in historical_missing}
    saved_members=defaultdict(list)
    def order(value):
        try:return (0,int(value))
        except (TypeError,ValueError):return (1,str(value or ''))
    for r in history_members:
        saved_members[str(r['HistoryID'])].append({'track_id':str(r['ContentID']),'position':r['TrackNo'],'entry_id':str(r['ID']),**archived.get(str(r['ContentID']),{})})
    snapshot['histories']=[{'id':str(r['ID']),'uuid':r['UUID'],'name':r['Name'] or str(r['ID']),'date':r['DateCreated'],
                            'parent':r['ParentID'],'folder':r['Attribute']==1,
                            'entries':sorted(saved_members[str(r['ID'])],key=lambda m:(order(m['position']),m['entry_id']))} for r in history_rows]
    for track in snapshot['tracks']:
        r=details[track['id']]
        track.update(uuid=r['UUID'],isrc=r['ISRC'] or '',size=r['FileSize'],analysis_path=r['AnalysisDataPath'],
                     raw_tags={'year':r['ReleaseYear'],'bpm':r['BPM']/100 if isinstance(r['BPM'],(int,float)) else r['BPM'],'rating':r['Rating'],'duration':r['Length']},
                     cues=cues[track['id']] if {'ContentID','Kind','InMsec'}<=columns.get('djmdCue',set()) else None,
                     last_played=last_played.get(track['id']))
    members=defaultdict(list)
    for r in rows('djmdSongPlaylist',('PlaylistID','ContentID','TrackNo','ID')):members[str(r['PlaylistID'])].append(r)
    snapshot['playlists']=[]
    for r in rows('djmdPlaylist',('ID','UUID','Name','ParentID','Attribute','SmartList')):
        entries=sorted(members[str(r['ID'])],key=lambda x:(x['TrackNo'] or 0,str(x['ID'])))
        snapshot['playlists'].append({'id':str(r['ID']),'uuid':r['UUID'],'name':r['Name'] or '', 'parent':r['ParentID'],
                                      'folder':r['Attribute']==1,'smart':bool(r['SmartList']),
                                      'criteria_sha256':sha256(str(r['SmartList'] or '').encode()).hexdigest(),
                                      'tracks':[str(x['ContentID']) for x in entries]})
    references=[t['analysis_path'] for t in snapshot['tracks'] if t.get('analysis_path')]
    references.extend(r['Path'] for r in rows('contentFile',('Path',)) if r['Path'])
    snapshot.update(schema=1,scope_key=scope_key,asset_references=references,
                    capabilities={'cue_positions':{'ContentID','Kind','InMsec'}<=columns.get('djmdCue',set()),
                                  'playlist_order':{'ContentID','PlaylistID','TrackNo'}<=columns.get('djmdSongPlaylist',set()),
                                  'history_details':{'ID','DateCreated'}<=columns.get('djmdHistory',set()) and {'ContentID','HistoryID'}<=columns.get('djmdSongHistory',set()),
                                  'history_order':'TrackNo' in columns.get('djmdSongHistory',set()),
                                  'analysis_references':'AnalysisDataPath' in columns['djmdContent'] and 'Path' in columns.get('contentFile',set())})
    return snapshot


def capture_workspace(catalog,scope_key):
    snapshot=capture_catalog(catalog)
    for track in snapshot['tracks']:
        raw=catalog.tracks[track['id']]
        track.update(size=raw.get('size_bytes'),uuid=raw.get('uuid'),isrc=raw.get('isrc') or '',analysis_path=raw.get('analysis_path'),
                     raw_tags={field:raw.get(field) for field in ('year','bpm','rating')},
                     cues=[{'id':c.get('ID'),'uuid':c.get('UUID'),'kind':c['Kind'],'in_ms':c['InMsec'],'out_ms':c.get('OutMsec'),
                            'label':c.get('Comment') or '', 'color':c.get('Color'),'auto':is_auto(c)} for c in catalog.cues[track['id']]])
    snapshot.update(schema=1,scope_key=scope_key,playlists=[],asset_references=[],
                    histories=[],capabilities={'cue_positions':True,'playlist_order':False,'analysis_references':False,
                                               'history_details':False,'history_order':False})
    return snapshot
