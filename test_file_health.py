"""Private file-health index: scoped, opt-in, bounded, read-only and sortable."""
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app as application
from workbench_store import Store


class FileHealthTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.data=self.root/'work'
        self.audio=self.root/'Synthetic Audio.mp3';self.audio.write_bytes(b'never touched')
        self.records=[
          {'id':'playable','title':'Z playable','artist':'DJ Beta','genre':'House','current_path':str(self.audio)},
          {'id':'missing','title':'A missing','artist':'DJ Alpha','genre':'Techno','current_path':str(self.root/'not-there.mp3')},
          {'id':'unknown','title':'M unknown','artist':'DJ Gamma','genre':'','current_path':None}]
        self.store=Store(self.data/'workbench-sidecar.sqlite3')
        saved=self.store.save_snapshot({'schema':1,'scope_key':'synthetic:file-health','tracks':self.records,
                                        'playlists':[],'capabilities':{}},'Synthetic status fixture')
        self.source='snapshot:'+saved['id']
        for name,value in [('DATA',self.data),('sessions',{}),('tasks',{}),('active',None)]:
            p=patch.object(application,name,value);p.start();self.addCleanup(p.stop)
        # Run explicit jobs synchronously; no external paths or real libraries.
        def execute(work,_message):
            self.result=work(lambda *_:None)
            return 'synthetic-health-job'
        p=patch.object(application,'launch',execute);p.start();self.addCleanup(p.stop)
        self.client=application.app.test_client()
        self.headers={'X-Workbench-Token':application.TOKEN}

    def query(self,**kwargs):
        return self.client.get('/api/file-health',query_string={'source':self.source,**kwargs})

    def scan(self,**kwargs):
        return self.client.post('/api/file-health/scan',
            json={'source':self.source,**kwargs},headers=self.headers)

    def test_explicit_scan_and_file_statuses_are_distinct_from_unchecked(self):
        initial=self.query()
        self.assertEqual(initial.status_code,200)
        self.assertEqual(initial.json['unchecked'],3)
        self.assertEqual(initial.json['counts']['unverified'],0)
        self.assertEqual(initial.json['rows'],[])
        scanned=self.scan()
        self.assertEqual(scanned.status_code,200,scanned.json)
        self.assertEqual(self.result['checked'],3)
        self.assertEqual(self.audio.read_bytes(),b'never touched')
        status=self.query().json
        self.assertEqual(status['scan_state'],'complete')
        self.assertEqual(status['unchecked'],0)
        self.assertEqual(status['counts'],{'playable':1,'missing':1,'inaccessible':0,'unverified':1})
        self.assertEqual(self.query(status='missing').json['rows'][0]['track_id'],'missing')
        self.assertEqual(self.query(status='unverified').json['rows'][0]['track_id'],'unknown')
        self.assertEqual(self.query(q='dj gamma').json['rows'][0]['track_id'],'unknown')
        self.assertEqual([r['track_id'] for r in self.query(sort='title').json['rows']],['missing','unknown','playable'])
        self.assertEqual([r['track_id'] for r in self.query(sort='status').json['rows']],['playable','missing','unknown'])
        self.assertEqual([r['track_id'] for r in self.query(sort='title',direction='desc').json['rows']],['playable','unknown','missing'])
        self.assertFalse(any('current_path' in r for r in status['rows']))

    def test_explicit_refresh_recaptures_changed_media_state(self):
        self.scan()
        self.audio.unlink()
        self.assertEqual(self.query(status='playable').json['total'],1)
        self.assertEqual(self.scan(force=True).status_code,200)
        self.assertEqual(self.query(status='playable').json['total'],0)
        self.assertEqual(self.query(status='missing').json['total'],2)

    def test_input_and_remote_guards_and_read_only_scope(self):
        for kwargs in ({'status':'garbage'},{'sort':'status;DELETE'},{'direction':'up'},{'offset':'nope'}):
            self.assertEqual(self.query(**kwargs).status_code,400)
        self.assertEqual(self.client.get('/api/file-health',query_string={'source':'../malformed'}).status_code,400)
        response=self.client.post('/api/file-health/scan',json={'source':self.source},headers=self.headers,
                                  environ_overrides={'REMOTE_ADDR':'8.8.8.8'})
        self.assertEqual(response.status_code,400)
        self.assertEqual(self.audio.read_bytes(),b'never touched')

    def test_pagination_across_the_index_not_the_rendered_rows(self):
        tracks=[{'id':str(n),'title':'Track '+str(n),'artist':'DJ','current_path':None} for n in range(61)]
        saved=self.store.save_snapshot({'schema':1,'scope_key':'synthetic:large','tracks':tracks,
                                        'playlists':[]},'61 synthetic')
        self.source='snapshot:'+saved['id']
        self.assertEqual(self.scan().status_code,200)
        first=self.query(sort='title').json
        later=self.query(sort='title',offset=50).json
        self.assertEqual(first['total'],61)
        self.assertEqual(len(first['rows']),50)
        self.assertEqual(len(later['rows']),11)
        self.assertFalse({r['track_id'] for r in first['rows']} & {r['track_id'] for r in later['rows']})


if __name__=='__main__':unittest.main()
