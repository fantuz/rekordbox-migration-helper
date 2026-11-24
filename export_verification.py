"""Read completed exports against expectations frozen from the original inputs.

This reader does not call either writer or trust their validation summaries.
Bookkeeping timestamps and update counters are excluded from semantic checks.
"""
from collections import Counter
from contextlib import closing
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
import struct
from urllib.parse import quote
import zipfile

from lxml import etree

BOOKKEEPING={'created_at','updated_at','rb_local_usn','usn','rb_local_synced','rb_local_deleted'}
NAMED={'artist':('ArtistID','djmdArtist'),'album':('AlbumID','djmdAlbum'),'genre':('GenreID','djmdGenre'),
       'label':('LabelID','djmdLabel'),'composer':('ComposerID','djmdArtist')}
XML_FIELDS={'title':'Name','artist':'Artist','album':'Album','genre':'Genre','year':'Year','rating':'Rating','comment':'Comments','colour':'Colour','label':'Label','composer':'Composer'}
CONTENT_FIELDS={'title':'Title','year':'ReleaseYear','rating':'Rating','comment':'Commnt'}
HOT_NUMBERS=dict(zip((1,2,3,5,*range(6,18)),range(16)))


def digest(value):
    return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=lambda b:bytes(b).hex(),separators=(',',':')).encode()).hexdigest()


def node(element):
    return [element.tag,dict(element.attrib),[node(c) for c in element if isinstance(c.tag,str)]]


def xml_state(path, transform=None, mapping=None):
    tracks={};playlists=[];declared=None;source_ids=set();references=[]
    for _,element in etree.iterparse(str(path),events=('end',),resolve_entities=False,no_network=True,huge_tree=True):
        parent=element.getparent()
        if element.tag=='TRACK' and parent is not None and parent.tag=='COLLECTION':
            identity=element.get('TrackID')
            if not identity or identity in source_ids:raise ValueError('Independent XML verification found missing or repeated track IDs')
            source_ids.add(identity)
            selected=transform(identity,element) if transform else (identity,element)
            if selected:
                identity,element_value=selected
                if identity in tracks:raise ValueError('Independent XML verification found repeated surviving IDs')
                tracks[identity]=digest(node(element_value))
            element.clear()
            while element.getprevious() is not None:del parent[0]
        elif element.tag=='COLLECTION':
            declared=element.get('Entries');element.clear()
        elif element.tag=='PLAYLISTS':
            if mapping:
                for reference in element.iter('TRACK'):
                    reference.set('Key',mapping.get(reference.get('Key'),reference.get('Key')))
            references.extend(r.get('Key') for r in element.iter('TRACK'))
            playlists.append(digest(node(element)));element.clear()
        if element.getparent() is None and element.getroottree().docinfo.doctype:
            raise ValueError('Independent XML verification rejects DTD declarations')
    return {'tracks':tracks,'playlists':playlists,'declared':declared,'source_ids':sorted(source_ids),'references':references}


def xml_edits(element, fields):
    for field,value in fields.items():
        attr=XML_FIELDS[field]
        if field=='year' and value is None:element.attrib.pop(attr,None)
        elif field=='colour':element.set(attr,'0x'+value[1:] if value else '')
        else:element.set(attr,str(value*51 if field=='rating' else value))


def xml_cues(element,result):
    element.set('Rating',str(result['rating']*51))
    for old in list(element.findall('POSITION_MARK')):element.remove(old)
    for cue in result['cues']:
        end=cue.get('OutMsec');end=end if end is not None and end>=0 else -1
        attrs={'Name':cue.get('Comment') or '', 'Type':'4' if end>=0 else '0',
               'Start':f"{cue['InMsec']/1000:.3f}",'Num':str(HOT_NUMBERS.get(cue['Kind'],-1))}
        if end>=0:attrs['End']=f'{end/1000:.3f}'
        color=cue.get('Color')
        if color is not None and color>=0:
            attrs.update(Red=str((color>>16)&255),Green=str((color>>8)&255),Blue=str(color&255))
        etree.SubElement(element,'POSITION_MARK',**attrs)


def rows(db, table, active=True):
    quoted='"'+table.replace('"','""')+'"'
    columns={r[1] for r in db.execute('PRAGMA table_info('+quoted+')')}
    cursor=db.execute('SELECT * FROM '+quoted+(' WHERE coalesce(rb_local_deleted,0)=0' if active and 'rb_local_deleted' in columns else ''))
    names=[c[0] for c in cursor.description]
    return (dict(zip(names,row)) for row in cursor)


def schema(db):
    return {r[0]:[c[1] for c in db.execute('PRAGMA table_info("'+r[0].replace('"','""')+'")')]
            for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}


def cue_value(cue):
    return {key:cue.get(key) for key in ('ID','Kind','InMsec','OutMsec','Comment','Color')}


def native_state(db, mapping=None, results=None, edits=None, relocations=None):
    """Hash active metadata and relation multisets, preserving playlist order fields."""
    from export_references import decoded_path
    from track_tags import native_colour,editable_colour
    expected=mapping is not None
    mapping=mapping or {};results=results or {};edits=edits or {};relocations=relocations or {}
    tables=schema(db)
    names={table:{str(r['ID']):r.get('Name') for r in rows(db,table)}
           for table in {table for _,table in NAMED.values()} if table in tables}
    keys={str(r['ID']):r.get('ScaleName') for r in rows(db,'djmdKey')} if 'djmdKey' in tables else {}
    colors={str(r['ID']):r for r in rows(db,'djmdColor')} if 'djmdColor' in tables else {}
    uuids={str(r['ID']):r.get('UUID') for r in rows(db,'djmdContent')}
    cue_rows={str(r['ID']):r for r in rows(db,'djmdCue',active=False)} if expected and results and 'djmdCue' in tables else {}
    if expected and results and 'contentCue' in tables:
        for row in rows(db,'contentCue',active=False):
            for cue in json.loads(row.get('Cues') or '[]'):
                cue_rows.setdefault(str(cue.get('ID')),cue)
    selected={}
    if expected:
        for keeper,result in results.items():
            selected[keeper]=[]
            for cue in result['cues']:
                original=deepcopy(cue_rows.get(str(cue.get('ID')),{}))
                if not original:raise ValueError('Independent verification cannot establish the original native cue')
                original.update({k:v for k,v in cue.items() if k in tables.get('djmdCue',[]) and k not in ('ID','UUID','ContentUUID','ContentID','created_at','rb_local_usn','usn')})
                original.update(ContentID=keeper,rb_local_deleted=0)
                if 'ContentUUID' in tables.get('djmdCue',[]):original['ContentUUID']=uuids[keeper]
                selected[keeper].append(original)
    checks={}
    for table,columns in tables.items():
        if table not in ('djmdContent','djmdCue','djmdPlaylist','contentCue') and table.casefold() != 'hotcuebanklistcue' and not any(k in columns for k in ('ContentID','ContentID1','ContentID2')):continue
        values=Counter()
        source=list(rows(db,table)) if expected and results and table in ('djmdCue','contentCue') else rows(db,table)
        if expected and results and table=='djmdCue':
            source=[r for r in source if str(r.get('ContentID')) not in mapping and str(r.get('ContentID')) not in results]
            source.extend(c for cues in selected.values() for c in cues)
        if expected and results and table=='contentCue':
            source=[r for r in source if str(r.get('ContentID')) not in mapping and str(r.get('ContentID')) not in results]
            source.extend({'ContentID':keeper,'Cues':json.dumps(cues),'rb_cue_count':len(cues)} for keeper,cues in selected.items())
        for raw in source:
            row=dict(raw);identity=str(row.get('ID'))
            if table=='djmdContent':
                if expected and identity in mapping:continue
                fields=edits.get(identity,{})
                if expected:
                    if identity in results:
                        row['Rating']=results[identity]['rating']
                        if 'CueUpdated' in row:row['CueUpdated']=1
                    if identity in relocations:row['FolderPath']=decoded_path(relocations[identity])
                    for field,column in CONTENT_FIELDS.items():
                        if field in fields:row[column]=0 if field=='year' and fields[field] is None else fields[field]
                for field,(column,lookup) in NAMED.items():
                    row['@'+field]=(fields[field] or None) if expected and field in fields else names.get(lookup,{}).get(str(row.get(column)))
                    if field in fields:row.pop(column,None)
                row['@key']=keys.get(str(row.get('KeyID')))
                row['@colour']=fields['colour'] if expected and 'colour' in fields else editable_colour(native_colour(row.get('ColorID'),colors.get(str(row.get('ColorID')))))
                if 'colour' in fields:row.pop('ColorID',None)
            elif table=='contentCue':
                row={'ContentID':str(row.get('ContentID')),'rb_cue_count':row.get('rb_cue_count'),
                     'cues':sorted(digest(cue_value(c)) for c in json.loads(row.get('Cues') or '[]'))}
            elif expected:
                old=str(row.get('ContentID'))
                if old in mapping:
                    if table in ('contentFile','djmdMixerParam'):continue
                    row['ContentID']=mapping[old]
                    if 'ContentUUID' in row:row['ContentUUID']=uuids[mapping[old]]
                for key in ('ContentID1','ContentID2'):
                    if str(row.get(key)) in mapping:row[key]=mapping[str(row[key])]
            ignored=BOOKKEEPING|({'UUID'} if table=='djmdCue' else set())
            values[digest({k:v for k,v in row.items() if k not in ignored})]+=1
        checks[table]=values
    return {'schema':tables,'tables':checks}


class ExportExpectations:
    def __init__(self,catalog,mapping,results,edits,relocations,kind,folder):
        from engine import open_master,asset_key,read_tags
        self.folder=Path(folder);self.xml=None;self.native=None
        self.edits=deepcopy(edits);self.original=Path(catalog.metadata['zip_path'])
        source=self.folder/'.verify-source.db'
        try:
            with zipfile.ZipFile(self.original) as archive:
                self.members={r.filename:(r.CRC,r.file_size) for r in archive.infolist()}
                if len(self.members)!=len(archive.infolist()):raise ValueError('Independent verification rejects duplicate archive members')
                with archive.open('master.db') as src,source.open('wb') as dst:shutil.copyfileobj(src,dst,2*1024**2)
                with closing(open_master(source.resolve())) as db:
                    if kind in ('zip','pair'):
                        self.native=native_state(db,mapping,results,edits,relocations)
                        self.contents=etree.fromstring(archive.read('contents.xml'),etree.XMLParser(resolve_entities=False,no_network=True))
                        count=sum(self.native['tables']['djmdContent'].values())
                        for value in self.contents.iter('VALUE'):
                            if value.get('name')=='CONTENT_NUM':value.set('val',str(count))
                        self.contents=digest(node(self.contents))
                    if kind in ('xml','pair'):
                        def transform(identity,element):
                            keeper=mapping.get(identity,identity)
                            if identity in mapping:return None
                            if keeper in results:xml_cues(element,results[keeper])
                            if keeper in relocations:element.set('Location',relocations[keeper])
                            xml_edits(element,edits.get(keeper,{}))
                            return keeper,element
                        self.xml=xml_state(Path(catalog.metadata['xml_path']),transform,mapping)
                        # Missing native keepers and native-only playlist references
                        # are reconstructed from the original database and grids.
                        wanted={mapping.get(i,i) for i in self.xml['source_ids']}|set(self.xml['references'])
                        index={asset_key(r.filename):r for r in archive.infolist()}
                        for identity in wanted-self.xml['tracks'].keys():
                            if identity not in catalog.tracks:raise ValueError('Independent verification found an unknown playlist reference')
                            cursor=db.execute('''SELECT c.*,a.Name AS Artist,al.Name AS Album,g.Name AS Genre,k.ScaleName AS Tonality
                                FROM djmdContent c LEFT JOIN djmdArtist a ON a.ID=c.ArtistID
                                LEFT JOIN djmdAlbum al ON al.ID=c.AlbumID LEFT JOIN djmdGenre g ON g.ID=c.GenreID
                                LEFT JOIN djmdKey k ON k.ID=c.KeyID WHERE c.ID=?''',(identity,))
                            names=[c[0] for c in cursor.description];row=dict(zip(names,cursor.fetchone()))
                            track=catalog.tracks[identity];location=relocations.get(identity) or track.get('xml_location')
                            if not location:location='file://localhost/'+quote((track.get('original_path') or track.get('current_path') or '').replace('\\','/').lstrip('/'),safe='/:')
                            attrs={'TrackID':identity,'Name':row['Title'] or '', 'Artist':row['Artist'] or '', 'Album':row['Album'] or '', 'Genre':row['Genre'] or '',
                                   'AverageBpm':f"{(row['BPM'] or 0)/100:.2f}",'Rating':(row['Rating'] or 0)*51,
                                   'DateAdded':(row['StockDate'] or '')[:10],'Location':location,'Comments':row['Commnt'] or '',
                                   'PlayCount':row['DJPlayCount'] or 0,'SampleRate':row['SampleRate'] or 0,'BitRate':row['BitRate'] or 0,'Tonality':row['Tonality'] or ''}
                            for attr,column in (('Size','FileSize'),('TotalTime','Length')):
                                if row[column] is not None:attrs[attr]=row[column]
                            if row.get('ReleaseYear'):attrs['Year']=row['ReleaseYear']
                            element=etree.Element('TRACK',{k:str(v) for k,v in attrs.items()})
                            member=index.get(asset_key(track.get('analysis_path')))
                            if member:
                                grid=read_tags(archive,member).get(b'PQTZ',b'')
                                for offset in range(0,len(grid)-7,8):
                                    beat,bpm,ms=struct.unpack_from('>HHI',grid,offset)
                                    etree.SubElement(element,'TEMPO',Inizio=f'{ms/1000:.3f}',Bpm=f'{bpm/100:.2f}',Metro='4/4',Battito=str(beat))
                            xml_cues(element,results.get(identity,{'cues':catalog.cues[identity],'rating':row['Rating'] or 0}))
                            xml_edits(element,edits.get(identity,{}));self.xml['tracks'][identity]=digest(node(element))
        finally:source.unlink(missing_ok=True)
        self.expectation_sha256=digest({'xml':self.xml,'native':self.native})

    def check(self,kind,path,progress):
        from engine import open_master
        progress(99,'Independently verifying written '+kind.upper())
        if kind=='xml':
            actual=xml_state(path)
            if actual['tracks']!=self.xml['tracks']:
                raise ValueError('Independent XML verification failed: track metadata, references, cues or grids differ from the frozen plan')
            if actual['playlists']!=self.xml['playlists']:
                raise ValueError('Independent XML verification failed: playlist hierarchy, order or references differ')
            if actual['declared']!=str(len(actual['tracks'])):
                raise ValueError('Independent XML verification failed: collection count differs')
            checks=['track_ids','metadata','file_references','cue_labels_positions_colours','tempo_grids','playlist_hierarchy_and_order']
        else:
            target=self.folder/'.verify-readback.db'
            try:
                with zipfile.ZipFile(path) as archive:
                    members={r.filename:(r.CRC,r.file_size) for r in archive.infolist()}
                    if len(members)!=len(archive.infolist()) or members.keys()!=self.members.keys():
                        raise ValueError('Independent ZIP verification failed: archive members differ')
                    if any(members[k]!=v for k,v in self.members.items() if k not in ('master.db','contents.xml')):
                        raise ValueError('Independent ZIP verification failed: an unrelated archive member changed')
                    contents=etree.fromstring(archive.read('contents.xml'),etree.XMLParser(resolve_entities=False,no_network=True))
                    if digest(node(contents))!=self.contents:raise ValueError('Independent ZIP verification failed: contents manifest differs')
                    with archive.open('master.db') as src,target.open('wb') as dst:shutil.copyfileobj(src,dst,2*1024**2)
                with closing(open_master(target.resolve())) as db:actual=native_state(db,edits=self.edits)
                if actual['schema']!=self.native['schema']:raise ValueError('Independent ZIP verification failed: database schema differs')
                for table,expected in self.native['tables'].items():
                    if actual['tables'].get(table)!=expected:
                        raise ValueError('Independent ZIP verification failed: metadata, cues or ordered references differ in '+table)
            finally:target.unlink(missing_ok=True)
            checks=['active_track_ids','metadata','file_references','cue_rows_and_serialized_cues','playlist_hierarchy_and_order','content_relations','archive_member_directory']
        return {'status':'passed','basis':'original inputs and frozen review decisions','expectation_sha256':self.expectation_sha256,'checks':checks}


def freeze(catalog,decisions,relocations,kind,folder):
    from engine import decision_map
    from metadata_overrides import plan
    mapping,results=decision_map(catalog,deepcopy(decisions))
    return ExportExpectations(catalog,deepcopy(mapping),deepcopy(results),deepcopy(plan(catalog,mapping)),deepcopy(relocations),kind,folder)

