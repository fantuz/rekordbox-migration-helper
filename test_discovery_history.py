"""Synthetic fixtures only; formal execution belongs to GitHub CI."""
from hashlib import sha256
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import app as application
from analysis_audit import audit_assets
from discovery import suggestions,scan_roots,mounted_roots
from history_browser import list_history,history_session,added_years
from metadata_export import payload
from research_capture import capture_private_database
from workbench_store import Store


def native_fixture(path):
    db=sqlite3.connect(path)
    db.executescript('''
        CREATE TABLE djmdContent(ID TEXT,Title TEXT,FolderPath TEXT,ArtistID TEXT,Length INTEGER,StockDate TEXT,rb_local_deleted INTEGER);
        CREATE TABLE djmdArtist(ID TEXT,Name TEXT,rb_local_deleted INTEGER);
        CREATE TABLE djmdHistory(ID TEXT,UUID TEXT,Name TEXT,DateCreated TEXT,ParentID TEXT,Attribute INTEGER,rb_local_deleted INTEGER);
        CREATE TABLE djmdSongHistory(ID TEXT,ContentID TEXT,HistoryID TEXT,TrackNo INTEGER,rb_local_deleted INTEGER);
        INSERT INTO djmdArtist VALUES('artist','An artist',0);
        INSERT INTO djmdContent VALUES('a','Track A','/Music/a.mp3','artist',240,'2022-03-01',0);
        INSERT INTO djmdContent VALUES('b','Track B','/Music/b.mp3','artist',180,'2024-02-01',0);
        INSERT INTO djmdContent VALUES('gone','Archived track','/Music/gone.mp3','artist',200,'2021-01-01',1);
        INSERT INTO djmdHistory VALUES('folder','u0','Old sessions',NULL,'root',1,0);
        INSERT INTO djmdHistory VALUES('h','u1','Synthetic gig','2024-02-10 20:00:00','folder',0,0);
        INSERT INTO djmdHistory VALUES('empty','u2','Empty saved session',NULL,'root',0,0);
        INSERT INTO djmdHistory VALUES('deleted','u3','Deleted session','2024-02-11','root',0,1);
        INSERT INTO djmdSongHistory VALUES('entry2','b','h',2,0);
        INSERT INTO djmdSongHistory VALUES('entry1','a','h',1,0);
        INSERT INTO djmdSongHistory VALUES('entry3','gone','h',3,0);
        INSERT INTO djmdSongHistory VALUES('entry4','not-found','h',4,0);
        INSERT INTO djmdSongHistory VALUES('entry5','a','h',5,0);
        INSERT INTO djmdSongHistory VALUES('deleted-entry','b','h',6,1);
    ''');db.commit();return db


class HistoryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name).resolve()

    def test_native_history_keeps_order_repeats_and_missing_members(self):
        db=native_fixture(self.root/'private.db');self.addCleanup(db.close)
        s=capture_private_database(db,'synthetic');r=list_history(s)
        self.assertTrue(r['available']);self.assertEqual(r['sessions_total'],2);self.assertEqual(r['entries_total'],5)
        self.assertEqual(r['years'],[{'year':'2024','sessions':1}]);self.assertEqual(r['unknown_dates'],1)
        detail=history_session(s,'h')
        self.assertEqual([t['track_id'] for t in detail['rows']],['a','b','gone','not-found','a'])
        self.assertEqual(detail['rows'][2]['title'],'Archived track');self.assertTrue(detail['rows'][2]['missing_from_active_collection'])
        self.assertEqual(detail['rows'][3]['title'],'Track metadata unavailable')
        self.assertEqual(detail['missing_track_metadata'],2);self.assertEqual(detail['track_duration_sum'],660)
        self.assertEqual(history_session(s,'h','Track A')['total'],2)
        self.assertEqual(list_history(s,year='unknown')['rows'][0]['id'],'empty')
        self.assertEqual(list_history(s,query='gig')['total'],1)

    def test_unknown_capability_is_distinct_from_empty_and_survives_database_cleanup(self):
        path=self.root/'private.db'
        with native_fixture(path) as db:s=capture_private_database(db,'synthetic')
        db.close();store=Store(self.root/'working.sqlite3');record=store.save_snapshot(s,'Synthetic history')
        path.unlink();saved=store.snapshot(record['id'])
        self.assertEqual(history_session(saved,'h')['recorded_entries'],5)
        unknown={'tracks':[],'capabilities':{}}
        self.assertFalse(list_history(unknown)['available'])
        with self.assertRaises(ValueError):history_session(unknown,'h')
        empty={'tracks':[],'histories':[],'capabilities':{'history_details':True}}
        self.assertTrue(list_history(empty)['available']);self.assertEqual(list_history(empty)['sessions_total'],0)
        # Shareable offline metadata never includes session names/dates/membership.
        exported=json.dumps(payload(saved,'Synthetic library'))
        self.assertNotIn('Synthetic gig',exported);self.assertNotIn('histories',exported)

    def test_dates_are_addition_years_and_unknowns_do_not_disappear(self):
        result=added_years([{'date_added':v} for v in ('2024-02-01','20240102','2022/01/01',None,'garbage','0000-00-00')])
        self.assertEqual(result['years'],[{'year':'2024','tracks':2},{'year':'2022','tracks':1}]);self.assertEqual(result['unknown'],3)
        self.assertEqual(result['tracks'],6)

    def test_history_endpoints_are_read_only_and_download_complete_membership(self):
        with native_fixture(self.root/'private.db') as db:s=capture_private_database(db,'synthetic')
        db.close();record=Store(self.root/'workbench-sidecar.sqlite3').save_snapshot(s,'Test')
        with patch.object(application,'DATA',self.root):
            client=application.app.test_client()
            response=client.get('/api/lab/history',query_string={'snapshot':record['id']})
            self.assertEqual(response.status_code,200);self.assertEqual(response.json['sessions_total'],2)
            response=client.get('/api/lab/history/h/download',query_string={'snapshot':record['id']})
            self.assertIn('attachment',response.headers['Content-Disposition']);self.assertEqual(len(response.json['rows']),5)
            self.assertEqual(client.get('/api/lab/history/no-session',query_string={'snapshot':record['id']}).status_code,400)


class DiscoveryAndMultiScopeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name).resolve()

    def test_inaccessible_mount_does_not_break_analyzer_or_hide_other_libraries(self):
        denied=self.root/'restricted-volume';denied.mkdir()
        readable=self.root/'readable-volume';readable.mkdir()
        database=readable/'master.db';original=b'discovery must not open or modify this database';database.write_bytes(original)
        real_exists=Path.exists
        def exists(path,*args,**kwargs):
            if path==denied/'Users':raise PermissionError('Synthetic inaccessible mounted directory')
            return real_exists(path,*args,**kwargs)
        def discover():
            return suggestions('linux',{},self.root/'home',volumes=[{'path':str(p),'kind':'synthetic mounted volume'} for p in (denied,readable)])
        with patch.object(Path,'exists',exists),patch.object(application,'discover_locations',side_effect=discover),patch.object(application,'DATA',self.root/'workspace'):
            response=application.app.test_client().get('/api/analyzer')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['suggestions'],[str(readable)])
        self.assertEqual(database.read_bytes(),original)

    def test_mounted_windows_profile_and_relocated_settings_are_suggestions_only(self):
        profile=self.root/'Users'/'DJ'/'AppData'/'Roaming'/'Pioneer'/'rekordbox';profile.mkdir(parents=True)
        relocated=self.root/'DJ Music'/'Library';relocated.mkdir(parents=True)
        (relocated/'master.db').write_bytes(b'not SQL: discovery must not open it')
        (relocated/'share'/'USBANLZ').mkdir(parents=True)
        (profile/'rekordbox3.settings').write_text('<PROPERTIES><VALUE name="masterDbDirectory" val="C:\\DJ Music\\Library"/></PROPERTIES>')
        r=suggestions('linux',{},self.root/'home',volumes=[{'path':str(self.root),'kind':'test mounted volume'}])
        self.assertEqual([x['path'] for x in r['found']],[str(relocated)])
        self.assertEqual(r['analysis_paths'][0]['path'],str(relocated/'share'/'USBANLZ'))
        self.assertIn('responsibility',r['help'])
        mounts=mounted_roots('linux',self.root/'home',f'1 0 8:0 / {str(self.root).replace(" ",chr(92)+"040")} rw - ntfs3 /dev/test rw')
        self.assertIn(str(self.root),[m['path'] for m in mounts])

    def test_bounded_discovery_is_nonmutating_and_stops_at_analysis_root(self):
        (self.root/'library').mkdir();db=self.root/'library'/'master.db';db.write_bytes(b'not a database')
        assets=self.root/'share'/'USBANLZ'/'a'/'b';assets.mkdir(parents=True);(assets/'ANLZ0000.DAT').write_bytes(b'asset')
        hidden=self.root/'Windows'/'hidden';hidden.mkdir(parents=True);(hidden/'master.db').write_bytes(b'skip')
        before=sha256(db.read_bytes()).hexdigest()
        r=scan_roots([str(self.root)],lambda *_:None)
        self.assertEqual(len(r['libraries']),1);self.assertEqual(r['analysis_paths'][0]['path'],str(self.root/'share'/'USBANLZ'))
        self.assertFalse(r['database_queries']);self.assertFalse(r['source_writes']);self.assertEqual(sha256(db.read_bytes()).hexdigest(),before)
        limited=scan_roots([str(self.root)],lambda *_:None,max_directories=1)
        self.assertTrue(limited['partial']);self.assertTrue(limited['warnings'])
        shallow=scan_roots([str(self.root)],lambda *_:None,depth=0);self.assertEqual(shallow['libraries'],[])

    def test_mounted_agent_options_and_mac_profiles_and_external_master(self):
        win=self.root/'Users/DJ/AppData/Roaming/Pioneer/rekordboxAgent/storage';win.mkdir(parents=True)
        library=self.root/'DJ Music/Library';library.mkdir(parents=True);(library/'master.db').write_bytes(b'Windows DB')
        assets=self.root/'DJ Music/Assets/USBANLZ';assets.mkdir(parents=True)
        options=win/'options.json';options.write_text(json.dumps({'options':[['db-path','D:\\DJ Music\\Library\\master.db'],['analysis-data-root-path','D:\\DJ Music\\Assets'],['dp','not returned']]}))
        mac=self.root/'Users/Other/Library/Pioneer/rekordbox';mac.mkdir(parents=True);(mac/'master.db').write_bytes(b'Mac DB')
        external=self.root/'PIONEER/Master';external.mkdir(parents=True);(external/'master.db').write_bytes(b'External DB')
        before=options.read_bytes();result=suggestions('linux',{},self.root/'home',volumes=[{'path':str(self.root),'kind':'test'}])
        self.assertEqual({r['path'] for r in result['found']},{str(library),str(mac),str(external)})
        self.assertIn(str(assets),{r['path'] for r in result['analysis_paths']})
        self.assertNotIn('not returned',json.dumps(result));self.assertEqual(options.read_bytes(),before)

    def test_multiple_asset_roots_keep_same_reference_copies_separate(self):
        roots=[]
        for name,data in [('local',b'same'),('cloud',b'same'),('different',b'else')]:
            folder=self.root/name/'USBANLZ'/'a'/'id';folder.mkdir(parents=True);(folder/'ANLZ0000.DAT').write_bytes(data);roots.append(str(self.root/name))
        s={'asset_references':['/USBANLZ/a/id/ANLZ0000.DAT'],'capabilities':{'analysis_references':True}}
        summary,rows=audit_assets(s,roots+[str(self.root/'local'/'USBANLZ')],lambda *_:None,True)
        self.assertEqual(summary['folders'],3);self.assertEqual(summary['files'],3)
        self.assertEqual(summary['verified_duplicate_groups'],1);self.assertEqual(summary['verified_extra_logical_bytes'],4)
        verified=next(r for r in rows if r['section']=='asset_duplicate_verified')
        self.assertEqual(len(verified['locations']),2);self.assertEqual(len(set(x['path'] for x in verified['locations'])),2)
        self.assertTrue(any(r['section']=='asset_bytes_differ' for r in rows))
        self.assertEqual(summary['unreferenced_folders'],0)

    def test_zip_and_folder_are_separate_scopes_stems_evidence_is_not_readiness(self):
        folder=self.root/'USBANLZ'/'a'/'b';folder.mkdir(parents=True);(folder/'ANLZ0000.3EX').write_bytes(b'not proof of stems')
        (self.root/'drums.rbsc').write_bytes(b'sample')
        archive=self.root/'backup.zip'
        with zipfile.ZipFile(archive,'w') as z:z.writestr('USBANLZ/a/b/ANLZ0000.3EX',b'not proof of stems');z.writestr('STEMS/candidate.bin',b'hint')
        s={'asset_references':[],'capabilities':{'analysis_references':False}}
        summary,rows=audit_assets(s,[str(folder),str(archive),str(self.root)],lambda *_:None,True)
        self.assertIsNone(summary['stems']['prepared_tracks']);self.assertEqual(summary['stems']['rbsc_drum_capture_files'],1)
        self.assertEqual(summary['stems']['related_candidate_files'],2);self.assertEqual(summary['folders'],2)
        self.assertIsNone(summary['unreferenced_folders']);self.assertTrue(any(r['section']=='asset_ownership_unknown' for r in rows))

    def test_discovery_api_saves_report_without_starting_analyzer(self):
        (self.root/'master.db').write_bytes(b'discovery only');outputs=[]
        def launch(work,_):outputs.append(work(lambda *_:None));return 'job'
        with patch.object(application,'DATA',self.root),patch.object(application,'launch',launch):
            client=application.app.test_client();r=client.post('/api/discovery/scan',json={'roots':[str(self.root)]},headers={'X-Workbench-Token':application.TOKEN})
            self.assertEqual(r.status_code,200);report=outputs[0]
            self.assertFalse(report['database_queries']);self.assertEqual(len(report['libraries']),1)
            self.assertEqual(client.get(report['download']).status_code,200)
            self.assertFalse((self.root/'analyzers').exists())


if __name__=='__main__':unittest.main()
