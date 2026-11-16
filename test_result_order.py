"""Collection-wide pagination regressions, including effective metadata."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import app as application
from workbench_store import Store
from result_order import ordered
from test_dj_insights import song

class ResultOrderTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name);p=patch.object(application,'DATA',root);p.start();self.addCleanup(p.stop)
        self.store=Store(root/'workbench-sidecar.sqlite3')
        tracks=[song(str(i),title=f'Track {i:03}',bpm=100+i/1000,genre='House') for i in range(75)]
        self.source={'scope_key':'sort-test','tracks':tracks,'capabilities':{'history_details':True,'history_order':True,'playlist_order':True},
                     'histories':[{'id':'h','name':'Saved','entries':[{'track_id':str(i),'position':i+1} for i in range(75)]}],
                     'playlists':[{'id':'p','name':'Playlist','tracks':[str(i) for i in range(75)]}]}
        self.identity=self.store.save_snapshot(self.source,'Sorting')['id']
        self.client=application.app.test_client()

    def test_all_track_browsers_sort_before_page_and_preserve_original_sequence(self):
        for path,extra,key in [
            ('/api/insights/tracks',{'perspective':'all'},'id'),
            ('/api/lab/history/h',{},'track_id'),
            ('/api/intelligence/contents',{'playlist':'p'},'track_id'),
            ('/api/intelligence/lenses',{'lens':'all'},'track_id'),
            ('/api/intelligence/session',{'history':'h'},'track_id')]:
            with self.subTest(path=path):
                values={'snapshot':self.identity,'sort':'bpm','direction':'desc',**extra}
                first=self.client.get(path,query_string=values)
                self.assertEqual(first.status_code,200,first.json)
                second=self.client.get(path,query_string={**values,'offset':50}).json
                rows=first.json['rows']+second['rows']
                self.assertEqual([r[key] for r in rows],[str(i) for i in reversed(range(75))])
                self.assertEqual(first.json['sort_scope'],'collection')
                if path.endswith('/session'):
                    self.assertEqual(rows[0]['sequence'],75)
                    self.assertEqual(rows[-1]['bpm_delta'],None)

    def test_effective_metadata_and_report_sort_include_later_pages(self):
        self.store.save_override('sort-test','74','title','AAA','Track 074')
        result=self.client.get('/api/lab/tracks',query_string={'snapshot':self.identity,'sort':'title'}).json
        self.assertEqual(result['rows'][0]['original']['id'],'74')
        self.assertEqual(result['rows'][0]['original']['title'],'Track 074')
        report=self.store.save_report('sort',[self.identity],{},[{'section':'test','title':f'{i:03}'} for i in range(75)])
        response=self.client.get('/api/lab/reports/'+report['id'],query_string={'sort':'title','direction':'desc'})
        self.assertEqual(response.json['rows'][0]['title'],'074')
        full=self.client.get('/api/lab/reports/'+report['id']+'/download',query_string={'sort':'title','direction':'desc'}).json
        self.assertEqual(len(full['rows']),75);self.assertEqual(full['rows'][-1]['title'],'000')

    def test_missing_last_both_directions_and_no_client_controlled_sql(self):
        rows=[{'id':'a','bpm':None},{'id':'b','bpm':100.001},{'id':'c','bpm':100.002},{'id':'d','bpm':100.001}]
        self.assertEqual([r['id'] for r in ordered(rows,'bpm','desc')],['c','b','d','a'])
        self.assertEqual([r['id'] for r in ordered(rows,'bpm','asc')],['b','d','c','a'])
        for field in ('bad','title; DROP TABLE snapshots'):
            self.assertEqual(self.client.get('/api/lab/tracks',query_string={'snapshot':self.identity,'sort':field}).status_code,400)
        self.assertEqual(len(self.store.snapshots()),1)
