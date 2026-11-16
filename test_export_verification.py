"""Real encrypted exports must survive an independent, source-based reader."""
from collections import defaultdict
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import json
import zipfile

from lxml import etree

from engine import Catalog,export_xml
from file_workflow import prepare_export,list_exports
from native_export import mutable_copy,export_native,rewrite_archive


class IndependentExportTests(TestCase):
    def setUp(self):
        tmp=TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.master=self.root/'original.db';self.backup=self.root/'source.zip';self.xml=self.root/'source.xml'
        with closing(mutable_copy(self.master)) as db:
            db.executescript('''
              CREATE TABLE djmdContent(ID TEXT PRIMARY KEY,UUID TEXT,Title TEXT,ArtistID TEXT,AlbumID TEXT,GenreID TEXT,KeyID TEXT,
                FileSize INTEGER,Length INTEGER,BPM INTEGER,Rating INTEGER,StockDate TEXT,Commnt TEXT,DJPlayCount INTEGER,
                SampleRate INTEGER,BitRate INTEGER,FolderPath TEXT,OrgFolderPath TEXT,ServiceID INTEGER,CueUpdated INTEGER,
                rb_local_deleted INTEGER,rb_local_usn INTEGER,rb_local_synced INTEGER,updated_at TEXT,ReleaseYear INTEGER);
              CREATE TABLE agentRegistry(registry_id TEXT,int_1 INTEGER,updated_at TEXT);
              INSERT INTO agentRegistry VALUES('localUpdateCount',0,'old');
              CREATE TABLE djmdArtist(ID TEXT,Name TEXT,UUID TEXT,rb_local_deleted INTEGER,rb_local_usn INTEGER,updated_at TEXT);
              CREATE TABLE djmdAlbum(ID TEXT,Name TEXT,UUID TEXT,rb_local_deleted INTEGER,rb_local_usn INTEGER,updated_at TEXT);
              CREATE TABLE djmdGenre(ID TEXT,Name TEXT,UUID TEXT,rb_local_deleted INTEGER,rb_local_usn INTEGER,updated_at TEXT);
              CREATE TABLE djmdKey(ID TEXT,ScaleName TEXT);
              INSERT INTO djmdArtist VALUES('artist','DJ','artist-uuid',0,0,'old');
              INSERT INTO djmdAlbum VALUES('album','Album','album-uuid',0,0,'old');
              INSERT INTO djmdGenre VALUES('genre','House','genre-uuid',0,0,'old');
              INSERT INTO djmdKey VALUES('key','Am');
              CREATE TABLE djmdCue(ID TEXT,ContentID TEXT,ContentUUID TEXT,UUID TEXT,Kind INTEGER,InMsec INTEGER,OutMsec INTEGER,
                Comment TEXT,Color INTEGER,rb_local_deleted INTEGER,rb_local_usn INTEGER,rb_local_synced INTEGER,updated_at TEXT,created_at TEXT);
              CREATE TABLE contentCue(ID TEXT,ContentID TEXT,Cues TEXT,rb_cue_count INTEGER,UUID TEXT,rb_local_deleted INTEGER,
                rb_local_usn INTEGER,updated_at TEXT,created_at TEXT);
              CREATE TABLE djmdPlaylist(ID TEXT,Name TEXT,ParentID TEXT,Seq INTEGER,rb_local_deleted INTEGER);
              INSERT INTO djmdPlaylist VALUES('mix','Night set','root',1,0);
              CREATE TABLE djmdSongPlaylist(ID TEXT,ContentID TEXT,ContentUUID TEXT,PlaylistID TEXT,TrackNo INTEGER,
                rb_local_deleted INTEGER,rb_local_usn INTEGER,rb_local_synced INTEGER,updated_at TEXT);
            ''')
            cues={}
            for identity,n in (('a',1),('b',2)):
                path='D:/Music/'+identity+'.wav'
                db.execute('INSERT INTO djmdContent VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (identity,identity+'-uuid','Song '+identity,'artist','album','genre','key',100,180,12800,4,'2026-01-01','Private '+identity,
                     5,44100,320,path,path,0,0,0,0,1,'old',2000))
                db.execute('INSERT INTO djmdCue VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    ('cue-'+identity,identity,identity+'-uuid','cue-uuid-'+identity,n,n*1000,-1,'Label '+identity,0xFF0000,0,0,1,'old','old'))
                cursor=db.execute('SELECT * FROM djmdCue WHERE ContentID=?',(identity,));cue=dict(zip([c[0] for c in cursor.description],cursor.fetchone()))
                cues[identity]=[cue]
                db.execute('INSERT INTO contentCue VALUES (?,?,?,?,?,?,?,?,?)',('cache-'+identity,identity,json.dumps([cue]),1,'cache-uuid-'+identity,0,0,'old','old'))
            for n,identity in enumerate(('b','a','b'),1):
                db.execute('INSERT INTO djmdSongPlaylist VALUES (?,?,?,?,?,?,?,?,?)',(str(n),identity,identity+'-uuid','mix',n,0,0,1,'old'))
            db.commit()
        with zipfile.ZipFile(self.backup,'w') as archive:
            archive.write(self.master,'master.db');archive.writestr('contents.xml','<ROOT><VALUE name="CONTENT_NUM" val="2"/></ROOT>');archive.writestr('artwork/a.jpg',b'original asset')
        self.xml.write_text('''<DJ_PLAYLISTS><PRODUCT Version="7.0"/><COLLECTION Entries="2">
          <TRACK TrackID="a" Name="Song a" Artist="DJ" Genre="House" Year="2000" Rating="204" Location="file://localhost/D:/Music/a.wav">
            <TEMPO Inizio="0.000" Bpm="128.00" Metro="4/4" Battito="1"/><POSITION_MARK Name="Label a" Type="0" Start="1.000" Num="0"/>
          </TRACK><TRACK TrackID="b" Name="Song b" Location="file://localhost/D:/Music/b.wav"/>
          </COLLECTION><PLAYLISTS><NODE Type="0" Name="ROOT" Count="1"><NODE Type="1" Name="Night set" Entries="3">
          <TRACK Key="b"/><TRACK Key="a"/><TRACK Key="b"/></NODE></NODE></PLAYLISTS></DJ_PLAYLISTS>''',encoding='utf-8')
        c=Catalog.__new__(Catalog);c.policy='newest';c.source_cue_conflicts=defaultdict(list);c.cues=cues
        c.tracks={i:{'track_id':i,'title':'Song '+i,'artist':'DJ','rating':4,'october_xml':True,'date_added':'2026-01-01',
                     'last_played':None,'play_count':5,'current_path':'D:/Music/'+i+'.wav','original_path':'D:/Music/'+i+'.wav',
                     'xml_location':'file://localhost/D:/Music/'+i+'.wav','analysis_path':None} for i in ('a','b')}
        c.pairs={'a~b':{'a':'a','b':'b'}}
        c.metadata={'xml_path':str(self.xml),'zip_path':str(self.backup),'version':'7.0','export_target':'windows',
                    'field_overrides':{'a':{'title':'Reviewed title','genre':'Techno','year':2020}}}
        self.catalog=c;self.originals=(self.backup.read_bytes(),self.xml.read_bytes())

    def prepare(self,kind='pair',decisions=None,relocations=None,**kwargs):
        return prepare_export(self.catalog,decisions or {},relocations or {},{'id':'synthetic'},self.root/'exports','a'*32,kind,lambda *_:None,**kwargs)

    def test_both_written_formats_pass_for_real_metadata_and_relocations(self):
        result=self.prepare(relocations={'a':'file://localhost/E:/DJ/a.wav'})
        self.assertEqual(set(result['validation']),{'xml','zip'})
        for value in result['validation'].values():
            self.assertEqual(value['independent_verification']['status'],'passed')
            self.assertEqual(len(value['independent_verification']['expectation_sha256']),64)
        self.assertEqual((self.backup.read_bytes(),self.xml.read_bytes()),self.originals)

    def test_merge_cue_labels_and_repeated_playlist_references_pass(self):
        result=self.prepare(decisions={'a~b':{'action':'merge','keeper':'a'}})
        folder=Path(result['directory']);tree=etree.parse(str(folder/'edited-collection.xml'))
        self.assertEqual([e.get('Key') for e in tree.findall('.//PLAYLISTS//TRACK')],['a','a','a'])
        self.assertEqual({e.get('Name') for e in tree.findall('.//POSITION_MARK')},{'Label a','Label b'})
        self.assertEqual((self.backup.read_bytes(),self.xml.read_bytes()),self.originals)

    def test_native_only_playlist_track_is_reconstructed_from_source(self):
        self.catalog.tracks['b']['october_xml']=False
        tree=etree.parse(str(self.xml));collection=tree.find('COLLECTION');collection.remove(collection.findall('TRACK')[1]);collection.set('Entries','1');tree.write(str(self.xml),encoding='utf-8')
        result=self.prepare('xml')
        self.assertEqual(result['validation']['playlist_tracks_recovered'],1)
        self.assertEqual(result['validation']['independent_verification']['status'],'passed')

    def test_xml_mutations_after_writer_validation_are_blocked(self):
        mutations={
          'playlist_order':lambda t:t.find('.//PLAYLISTS//TRACK').set('Key','a'),
          'path':lambda t:t.find('.//COLLECTION/TRACK').set('Location','file://localhost/Z:/wrong.wav'),
          'cue_label':lambda t:t.find('.//POSITION_MARK').set('Name','Wrong label'),
          'metadata':lambda t:t.find('.//COLLECTION/TRACK').set('Name','Wrong title'),
          'grid':lambda t:t.find('.//TEMPO').set('Bpm','140.00'),
        }
        for name,mutate in mutations.items():
            with self.subTest(mutation=name):
                def writer(c,d,r,path,p):
                    result=export_xml(c,d,r,path,p);tree=etree.parse(str(path));mutate(tree);tree.write(str(path),encoding='utf-8');return result
                with self.assertRaisesRegex(ValueError,'Independent XML verification'):
                    self.prepare('xml',xml_writer=writer)
                self.assertEqual(list_exports(self.root/'exports'),[])
                self.assertEqual(list((self.root/'exports').iterdir()),[])

    def test_native_mutations_after_writer_validation_are_blocked(self):
        for sql in ("UPDATE djmdSongPlaylist SET TrackNo=99 WHERE ID='1'",
                    "UPDATE djmdContent SET FolderPath='Z:/wrong.wav' WHERE ID='a'",
                    "UPDATE djmdCue SET Comment='Wrong label' WHERE ID='cue-a'",
                    "UPDATE djmdContent SET Title='Wrong title' WHERE ID='a'",
                    "UPDATE djmdArtist SET Name='Wrong artist'",
                    "UPDATE djmdAlbum SET Name='Wrong album'",
                    "UPDATE djmdGenre SET Name='Wrong genre'",
                    "UPDATE djmdKey SET ScaleName='Wrong key'",
                    "UPDATE contentCue SET Cues='[]' WHERE ContentID='a'"):
            with self.subTest(sql=sql):
                def writer(c,d,r,path,p):
                    result=export_native(c,d,r,path,p);changed=self.root/'mutated.db'
                    with zipfile.ZipFile(path) as archive:changed.write_bytes(archive.read('master.db'))
                    with closing(mutable_copy(changed)) as db:db.execute(sql);db.commit()
                    rewritten=self.root/'rewritten.zip';rewrite_archive(path,rewritten,{'master.db':changed},lambda *_:None);rewritten.replace(path)
                    return result
                with self.assertRaisesRegex(ValueError,'Independent ZIP verification'):
                    self.prepare('zip',native_writer=writer)
                self.assertEqual(list_exports(self.root/'exports'),[])

