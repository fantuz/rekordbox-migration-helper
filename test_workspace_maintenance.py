from test_support import workspace_client
"""Synthetic cache freshness, reversible reset and permanent-delete boundaries."""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from metadata_export import track
from report_files import save_json
from workbench_store import Store


class WorkspaceMaintenanceTests(unittest.TestCase):
    def setUp(self):
        import app
        self.app=app;self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.root=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for name,value in [('DATA',self.root),('active',None),('sessions',{}),('tasks',{})]:self.stack.enter_context(patch.object(app,name,value))
        self.store=Store(self.root/'workbench-sidecar.sqlite3');self.client=workspace_client(app);self.headers={'X-Workbench-Token':app.TOKEN}
        self.data={'scope_key':'synthetic:maintenance','tracks':[track({'id':'a','title':'Synthetic A','artist':'Test artist','current_path':'C:/Synthetic/A.wav','duration':120}),track({'id':'b','title':'Synthetic B','artist':'Test artist','current_path':'C:/Synthetic/A.wav','duration':120})],'capabilities':{},'playlists':[]}
        self.sid=self.store.save_snapshot(self.data,'Synthetic maintenance')['id'];self.source='snapshot:'+self.sid
        self.original=self.root/'original.db';self.original.write_bytes(b'original source must remain')
        (self.root/'exports').mkdir();(self.root/'exports'/'keep.html').write_text('completed export')

    def post(self,path,data=None):return self.client.post('/api/investigations/'+path,json=data or {},headers=self.headers)
    def get_stats(self):return self.client.get('/api/collection/statistics',query_string={'source':self.source})

    def test_cache_hits_without_recomputing_and_persists_in_sidecar(self):
        first=self.get_stats();self.assertEqual(first.status_code,200);self.assertEqual(first.headers['X-Workbench-Cache'],'miss')
        with patch('collection_views.statistics',side_effect=AssertionError('must reuse')):
            second=self.get_stats()
        self.assertEqual(second.headers['X-Workbench-Cache'],'hit');self.assertEqual(first.json,second.json)
        with Store(self.store.path).connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM result_cache').fetchone()[0],1)
        self.assertEqual(self.post('cache/clear').status_code,200);self.assertEqual(self.get_stats().headers['X-Workbench-Cache'],'miss')

    def test_cache_limits_expiry_and_csrf(self):
        import result_cache
        from result_cache import connection
        with patch.object(result_cache,'MAX_ENTRIES',2):
            for value in (0,1,2):
                self.client.get('/api/collection/statistics',query_string={'source':self.source,'min':value})
        with connection(self.app) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM result_cache').fetchone()[0],2)
            db.execute('UPDATE result_cache SET created=0')
        self.assertEqual(self.get_stats().headers['X-Workbench-Cache'],'miss')
        with connection(self.app) as db:self.assertEqual(db.execute('SELECT count(*) FROM result_cache').fetchone()[0],1)
        self.post('cache/clear')
        with patch.object(result_cache,'MAX_BYTES',1):self.get_stats()
        with connection(self.app) as db:self.assertEqual(db.execute('SELECT count(*) FROM result_cache').fetchone()[0],0)
        self.assertEqual(self.client.post('/api/investigations/cache/clear',json={}).status_code,403)

    def test_snapshot_health_cache_tracks_its_saved_report(self):
        identity=uuid4().hex;folder=self.root/'analyzers'/identity
        self.data['source_capture']=identity
        self.source='snapshot:'+self.store.save_snapshot(self.data,'Report evidence')['id']
        save_json(folder/'report.json',{'database':{'health':{'broken_track_links':1}}})
        self.assertEqual(self.get_stats().json['counters']['broken_database_links'],1)
        save_json(folder/'report.json',{'database':{'health':{'broken_track_links':2}}})
        response=self.get_stats();self.assertEqual(response.headers['X-Workbench-Cache'],'miss')
        self.assertEqual(response.json['counters']['broken_database_links'],2)

    def test_changed_duplicate_decisions_never_reuse_previous_status(self):
        url='/api/collection/duplicates';query={'source':self.source}
        response=self.client.get(url,query_string=query);group=response.json['rows'][0]['id']
        self.assertEqual(response.json['rows'][0]['review'],'unreviewed')
        result=self.client.post(url+'/'+group+'/review',json={'source':self.source,'status':'keep_separate'},headers=self.headers)
        self.assertEqual(result.status_code,200)
        response=self.client.get(url,query_string=query);self.assertEqual(response.json['rows'][0]['review'],'keep_separate')

    def test_cache_does_not_resurrect_deleted_snapshots(self):
        self.get_stats()
        with self.store.connection() as db:db.execute('DELETE FROM snapshots WHERE id=?',(self.sid,))
        self.assertEqual(self.get_stats().status_code,400)

    def test_capture_file_change_invalidates_cached_evidence(self):
        identity=uuid4().hex;folder=self.root/'analyzers'/identity;folder.mkdir(parents=True)
        save_json(folder/'metadata.json',self.data);save_json(folder/'report.json',{'created':'2026-01-01','format':'Synthetic'})
        self.source='capture:'+identity;first=self.get_stats();self.assertEqual(first.status_code,200)
        changed=deepcopy(self.data);changed['tracks']=changed['tracks'][:1];save_json(folder/'metadata.json',changed)
        second=self.get_stats();self.assertEqual(second.headers['X-Workbench-Cache'],'miss');self.assertNotEqual(first.json,second.json)

    def test_stale_fresh_preview_is_rejected_and_running_tasks_block_cleanup(self):
        preview=self.post('preview',{'fresh':True}).json
        self.store.save_snapshot(self.data,'New analysis')
        self.assertEqual(self.post('archive',{'fresh':True,'token':preview['token']}).status_code,400)
        with patch.object(self.app,'tasks',{'job':{'status':'running'}}):
            self.assertEqual(self.post('preview',{'fresh':True}).status_code,400)
            self.assertEqual(self.post('cache/clear').status_code,400)

    def test_fresh_start_archives_staged_edits_and_detaches_active_workspace(self):
        identity=uuid4().hex;folder=self.root/identity;folder.mkdir();save_json(folder/'state.json',{'id':identity,'name':'Synthetic workspace'})
        self.app.active=identity;self.app.sessions[identity]={'id':identity}
        self.store.save_bulk(self.store.snapshot(self.sid),['a'],'comment','Synthetic edit')
        with self.store.connection() as db:before=[dict(r) for r in db.execute('SELECT * FROM overrides')]
        preview=self.post('preview',{'fresh':True});self.assertEqual(preview.status_code,200);self.assertEqual(preview.json['blockers'],[])
        response=self.post('archive',{'fresh':True,'token':preview.json['token']});self.assertEqual(response.status_code,200,response.json)
        self.assertIsNone(self.app.active);self.assertEqual(self.app.sessions,{})
        self.assertEqual(self.client.get('/api/investigations').json['items'],[])
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM overrides').fetchone()[0],0)
        result=self.post(response.json['id']+'/restore');self.assertEqual(result.status_code,200,result.json)
        with self.store.connection() as db:self.assertEqual([dict(r) for r in db.execute('SELECT * FROM overrides')],before)
        self.assertTrue((folder/'state.json').exists());self.assertEqual(self.original.read_bytes(),b'original source must remain')
        self.assertTrue((self.root/'exports'/'keep.html').exists())

    def test_discovery_storage_and_incomplete_captures_are_managed_together(self):
        discovery=uuid4().hex;capture=uuid4().hex;storage=uuid4().hex
        save_json(self.root/'discovery'/(discovery+'.json'),{'created':'2026-01-01'})
        (self.root/'analyzers'/capture).mkdir(parents=True)
        save_json(self.root/'storage'/storage/'summary.json',{'created':'2026-01-01','source_report':capture})
        items=self.client.get('/api/investigations').json['items'];kinds={r['kind'] for r in items}
        self.assertTrue({'discovery','storage','captures'}.issubset(kinds))
        preview=self.post('preview',{'keys':['captures:'+capture]});self.assertEqual(len(preview.json['blockers']),1)
        preview=self.post('preview',{'fresh':True}).json;archive=self.post('archive',{'fresh':True,'token':preview['token']}).json
        self.assertEqual(self.post(archive['id']+'/restore').status_code,200)
        self.assertTrue((self.root/'discovery'/(discovery+'.json')).is_file())
        self.assertTrue((self.root/'storage'/storage/'summary.json').is_file())

    def test_permanent_deletion_requires_matching_preview_and_preserves_external_files(self):
        preview=self.post('preview',{'fresh':True}).json;archive=self.post('archive',{'fresh':True,'token':preview['token']}).json
        ids=[archive['id']];preview=self.post('purge-preview',{'ids':ids}).json
        self.assertEqual(self.post('purge',{'ids':ids,'token':preview['token']}).status_code,400)
        self.assertEqual(self.post('purge',{'ids':ids,'token':'stale','confirmed':True}).status_code,400)
        folder=self.root/'archived-investigations'/ids[0]
        try:(folder/'external-link').symlink_to(self.original)
        except OSError:pass
        response=self.post('purge',{'ids':ids,'token':preview['token'],'confirmed':True});self.assertEqual(response.status_code,200,response.json)
        self.assertFalse(folder.exists());self.assertEqual(self.client.get('/api/investigations').json['archives'],[])
        self.assertEqual(self.original.read_bytes(),b'original source must remain');self.assertTrue((self.root/'exports'/'keep.html').exists())
        self.assertEqual(self.post('purge-preview',{'ids':['../original.db']}).status_code,400)

    def test_linked_archive_root_is_never_removed(self):
        preview=self.post('preview',{'fresh':True}).json
        archive=self.post('archive',{'fresh':True,'token':preview['token']}).json
        ids=[archive['id']];preview=self.post('purge-preview',{'ids':ids}).json
        base=self.root/'archived-investigations';held=self.root/'held-archives';base.rename(held)
        try:base.symlink_to(held,target_is_directory=True)
        except OSError:self.skipTest('Directory symlinks unavailable')
        response=self.post('purge',{'ids':ids,'token':preview['token'],'confirmed':True})
        self.assertEqual(response.status_code,400);self.assertTrue((held/ids[0]).is_dir())
        self.assertEqual(len(self.client.get('/api/investigations').json['archives']),1)

    def test_report_publication_keeps_previous_report_when_replace_fails(self):
        path=self.root/'report.json';save_json(path,{'complete':True})
        with patch('report_files.os.replace',side_effect=OSError('synthetic write failure')):
            with self.assertRaises(OSError):save_json(path,{'complete':False})
        self.assertEqual(json.loads(path.read_text()),{'complete':True});self.assertEqual(list(self.root.glob('.report-*.tmp')),[])

if __name__=='__main__':unittest.main()
