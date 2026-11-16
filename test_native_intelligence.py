from test_support import workspace_client
"""Direct native captures and named snapshots must expose the same intelligence."""
from contextlib import ExitStack,closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app
from analyzer import analyze_folder
from collection_sources import resolve
from test_discovery_history import native_fixture
from workbench_store import Store


class NativeIntelligenceTests(unittest.TestCase):
    def setUp(self):
        stack=ExitStack();self.addCleanup(stack.close)
        self.root=Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.data=self.root/'work';self.original=self.root/'source'/'master.db';self.original.parent.mkdir()
        with closing(native_fixture(self.original)) as db:
            db.executescript("""CREATE TABLE djmdPlaylist(ID TEXT,Name TEXT,Attribute INTEGER);
                CREATE TABLE djmdSongPlaylist(ID TEXT,PlaylistID TEXT,ContentID TEXT,TrackNo INTEGER);
                INSERT INTO djmdPlaylist VALUES('p','Synthetic set',0),('q','Related set',0);
                INSERT INTO djmdSongPlaylist VALUES('1','p','a',1),('2','p','b',2),('3','p','a',3),('4','q','b',1),('5','q','a',2);""")
        self.before=self.original.read_bytes();self.capture='c'*32;self.source='capture:'+self.capture
        analyze_folder(self.original,self.data/'analyzers'/self.capture,lambda *_:None)
        for name,value in [('DATA',self.data),('active',None),('sessions',{}),('tasks',{})]:stack.enter_context(patch.object(app,name,value))
        self.client=workspace_client(app);self.headers={'X-Workbench-Token':app.TOKEN}
        self.store=Store(self.data/'workbench-sidecar.sqlite3');self.sid=self.store.save_snapshot(resolve(app,self.source),'Synthetic saved native')['id']

    def test_native_capture_and_saved_snapshot_match(self):
        cases=[('options',{}),('playlists',{'playlist':'p'}),('contents',{'playlist':'p'}),('session',{'history':'h'}),('lenses',{'lens':'all'}),('lenses',{'lens':'history_absent'})]
        for route,params in cases:
            with self.subTest(route=route,params=params):
                direct=self.client.get('/api/intelligence/'+route,query_string={'snapshot':self.source,**params})
                saved=self.client.get('/api/intelligence/'+route,query_string={'snapshot':self.sid,**params})
                self.assertEqual(direct.status_code,200,direct.json);self.assertEqual(direct.json,saved.json)
        report=self.client.post('/api/intelligence/report',json={'kind':'session','snapshot':self.source,'history':'h'},headers=self.headers)
        self.assertEqual(report.status_code,200,report.json)
        self.assertEqual(self.store.report(report.json['id'])['sources'],[self.source])
        self.assertEqual(self.original.read_bytes(),self.before)

    def test_evolution_and_exports_keep_capture_source(self):
        response=self.client.get('/api/intelligence/evolution',query_string={'before':self.source,'after':self.sid})
        self.assertEqual(response.status_code,200,response.json);self.assertEqual(response.json['matched_records'],2)
        response=self.client.post('/api/intelligence/serato/preview',json={'snapshot':self.source,'volume_root':'/','target_profile':'macos'},headers=self.headers)
        self.assertEqual(response.status_code,200,response.json);self.assertEqual(response.json['tracks_written'],2)
        with patch('chart_playlists.ChartClient.fetch',return_value={'period':'week','from_ts':0,'to_ts':1,'rows':[]}):
            response=self.client.post('/api/intelligence/chart',json={'snapshot':self.source,'network_consent':True,'period':'week'},headers=self.headers)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(self.store.report(response.json['report_id'])['sources'],[self.source])

    def test_missing_capture_does_not_fall_back_to_a_saved_library(self):
        for value in ('capture:'+'f'*32,'capture:../../master.db'):
            self.assertEqual(self.client.get('/api/intelligence/options',query_string={'snapshot':value}).status_code,400)
        self.assertEqual(self.client.post('/api/intelligence/duplicate-impact',json={},headers=self.headers).status_code,400)

if __name__=='__main__':unittest.main()
