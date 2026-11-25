"""Disposable private sidecar regressions for review, publication and recovery."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Barrier
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from werkzeug.exceptions import Conflict

from cleanup_operation import apply_cleanup, preview_cleanup
from workbench_store import Store


class CleanupPublication(TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(Path(folder.name) / 'workbench-sidecar.sqlite3')
        platform = patch('cleanup_operation.sys', SimpleNamespace(platform='win32'))
        platform.start()
        self.addCleanup(platform.stop)
        self.parent = self.store.save_snapshot({'scope_key':'capture:original','source_capture':'original',
            'source_kind':'Fixture', 'tracks':[{'id':str(i),'title':str(i),'comment':''} for i in range(4)],
            'playlists':[{'id':'p','tracks':['3']}], 'histories':[]}, 'Private test')
        self.source = self.parent['id']
        self.selected = ['0','1']
        self.live = {}
        for i in range(4):
            identity = str(i)
            self.live[identity] = {'track_id':identity,'id':identity,'path':'Music/'+identity,'title':'Track '+identity,
                                'candidate':None,'proof':None,'protected':False,'reasons':[], 'status':'present',
                                'evidence':identity+'file','location_evidence':identity+'location'}
        self.live['0'].update(candidate='missing', status='missing',proof='absent')
        self.live['1'].update(candidate='duplicate', keeper_id='2', keeper_path='Music/2',proof='sha256')
        self.live['3'].update(protected=True,reasons=['playlist'])
        self.stamp = 'source-session'
        self.report = self.store.save_report('collection cleanup',[self.source],dict(source_digest=self.parent['digest'],
                can_apply=True,compare_bytes=True), list(self.live.values()))['id']

    def recheck(self, snapshot, compare_bytes, ids, *, db=None, context_only=False, locations=None):
        self.assertTrue(compare_bytes)
        self.assertIsNotNone(db)
        if context_only:
            self.assertEqual(locations,{i:self.live[i]['path'] for i in ids})
            return {'context_stamp':self.stamp,'locations':{i:self.live[i]['location_evidence'] for i in ids}}
        return {'can_apply':True,'context_stamp':self.stamp,'rows':[deepcopy(self.live[i]) for i in ids]}

    def preview(self):
        return preview_cleanup(self.store,self.source,self.report,self.selected,self.recheck)

    def apply(self, p, **kwargs):
        return apply_cleanup(self.store,self.source,self.report,self.selected,p['token'],'COPY 2',
                             True,True,self.recheck,**kwargs)

    def test_retained_original_and_edits_are_independent_and_retry_is_idempotent(self):
        self.store.save_override('capture:original','3','comment','Working note','','manual')
        parent = self.store.snapshot(self.source)
        p = self.preview()
        self.assertEqual((p['before_count'],p['after_count'],p['selected_count'],p['confirmation']),(4,2,2,'COPY 2'))
        self.assertEqual(p['selected'][1]['keeper_path'],'Music/2')
        first = self.apply(p)
        self.assertEqual(self.apply(p),first)
        self.assertEqual(first['parent_snapshot_id'],self.source)
        self.assertEqual(self.store.snapshot(self.source),parent)
        child = self.store.snapshot(first['snapshot_id'])
        self.assertEqual(child['cleanup_lineage']['parent_digest'],self.parent['digest'])
        self.assertEqual(child['cleanup_lineage']['removed_ids'],self.selected)
        self.assertNotEqual(child['scope_key'],parent['scope_key'])
        self.assertNotIn('source_capture',child)
        self.assertEqual([t['id'] for t in child['tracks']],['2','3'])
        self.assertEqual(child['tracks'][1]['comment'],'Working note')
        self.assertEqual(child['playlists'],parent['playlists'])
        self.store.save_override(child['scope_key'],'3','comment','Copy edit','Working note','manual')
        self.assertEqual(self.store.effective(parent)['tracks'][3]['comment'],'Working note')
        self.assertEqual(len(self.store.snapshots()),2)

    def test_platform_selection_source_confirmation_and_keeper_guards(self):
        for selected in ([],['0','0'],[str(i) for i in range(26)],['0','1','2','3'],['3']):
            with self.subTest(selected=selected),self.assertRaises((Conflict,ValueError)):
                preview_cleanup(self.store,self.source,self.report,selected,self.recheck)
        with self.assertRaises(Conflict):
            preview_cleanup(self.store,self.source,self.report,['1','2'],self.recheck)
        p = self.preview()
        for args in ((self.source,self.report,['1'],p['token'],'COPY 1',True,True),
                     (self.source,self.report,self.selected,p['token'],'COPY 2',1,True),
                     (self.source,self.report,self.selected,p['token'],'COPY 2',True,False),
                     (self.source,self.report,self.selected,p['token'],'COPY 1',True,True),
                     (uuid4().hex,self.report,self.selected,p['token'],'COPY 2',True,True),
                     (self.source,uuid4().hex,self.selected,p['token'],'COPY 2',True,True)):
            with self.assertRaises((Conflict,ValueError)):
                apply_cleanup(self.store,*args,self.recheck)
        with patch('cleanup_operation.sys',SimpleNamespace(platform='linux')), self.assertRaisesRegex(ValueError,'report-only'):
            self.apply(p)
        self.assertEqual(len(self.store.snapshots()),1)

    def test_stale_files_keepers_and_source_digest_stop_publication(self):
        p = self.preview()
        self.live['2']['evidence'] = 'replacement'
        with self.assertRaises(Conflict):self.apply(p)
        self.live['2']['evidence'] = '2file'
        self.live['0'].update(status='present',candidate=None,proof=None)
        with self.assertRaises(Conflict):self.apply(p)
        self.live['0'].update(status='missing',candidate='missing',proof='absent')
        self.stamp = 'different-session'
        with self.assertRaises(Conflict):self.apply(p)
        self.stamp = 'source-session'
        with self.store.connection() as db:
            db.execute("UPDATE snapshots SET payload=replace(payload,'Private test','Changed') WHERE id=?", (self.source,))
        with self.assertRaisesRegex(Conflict,'integrity'):self.apply(p)
        self.assertEqual(len(self.store.snapshots()),1)

    def test_cloud_hold_sidecar_edits_and_location_change_during_apply_stop_publication(self):
        p = self.preview()
        with self.assertRaisesRegex(Conflict,'Workspace evidence changed'):
            self.apply(p,checkpoint=lambda:self.store.set_setting('cloud_hold','1'))
        with self.assertRaisesRegex(Conflict,'local folder changed'):
            self.apply(p,checkpoint=lambda:self.live['0'].update(location_evidence='parent replaced'))
        self.assertEqual(len(self.store.snapshots()),1)

    def test_atomic_rollback_and_concurrent_retry_leave_exactly_one_result(self):
        p = self.preview()
        with self.store.connection() as db:
            db.execute("CREATE TRIGGER fail_receipt BEFORE UPDATE ON collection_cleanup_previews BEGIN SELECT RAISE(ABORT,'receipt'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.apply(p)
        self.assertEqual(len(self.store.snapshots()),1)
        with self.store.connection() as db:db.execute('DROP TRIGGER fail_receipt')
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.apply,p,checkpoint=lambda:barrier.wait(15)) for _ in range(2)]
            results = [job.result(timeout=25) for job in futures]
        self.assertEqual(results[0]['snapshot_id'],results[1]['snapshot_id'])
        self.assertEqual(len(self.store.snapshots()),2)

    def test_expired_or_archived_preview_requires_new_review(self):
        p = self.preview()
        with self.store.connection() as db:db.execute('UPDATE collection_cleanup_previews SET expires=0')
        with self.assertRaisesRegex(Conflict,'expired'):self.apply(p)
        p = self.preview()
        with self.store.connection() as db:db.execute('DELETE FROM reports WHERE id=?',(self.report,))
        with self.assertRaisesRegex(Conflict,'exact saved snapshot'):self.apply(p)
        self.assertEqual(len(self.store.snapshots()),1)

    def test_saved_investigations_keeps_recovery_parent_and_archives_copy_reversibly(self):
        import app
        from test_support import workspace_client
        result = self.apply(self.preview())
        key = 'snapshots:' + result['snapshot_id']
        with patch.object(app,'DATA',self.store.path.parent), patch.object(app,'tasks',{}), patch.object(app,'active',None):
            client = workspace_client(app)
            def post(name, body):
                response = client.post('/api/investigations/'+name,json=body,headers={'X-Workbench-Token':app.TOKEN})
                self.assertEqual(response.status_code,200,response.get_json())
                return response.get_json()
            for protect in ('snapshots:'+self.source,'reports:'+self.report):
                self.assertIn(key,{item['key'] for item in post('preview',{'keys':[protect]})['blockers']})
            plan = post('preview',{'keys':[key]})
            self.assertEqual(plan['blockers'],[])
            archived = post('archive',{'keys':[key],'token':plan['token']})
            self.assertEqual(len(self.store.snapshots()),1)
            self.assertEqual(len(self.store.snapshot(self.source)['tracks']),4)
            post(archived['id']+'/restore',{})
            self.assertEqual(self.store.snapshot(result['snapshot_id'])['cleanup_lineage']['parent_snapshot_id'],self.source)

    def test_generic_report_views_keep_cleanup_paths_local(self):
        import app
        from test_support import workspace_client
        ordinary = self.store.save_report('coverage',[self.source],{},[])['id']
        with patch.object(app,'DATA',self.store.path.parent), patch.object(app,'active',None):
            client = workspace_client(app)
            endpoint = '/api/lab/reports/'+self.report
            for suffix in ('','/download'):
                self.assertEqual(client.get(endpoint+suffix).status_code,200)
                with patch.object(Store,'report',side_effect=AssertionError('must reject before loading rows')):
                    self.assertEqual(client.get(endpoint+suffix,environ_overrides={'REMOTE_ADDR':'192.0.2.12'}).status_code,403)
                    # The HTTP Host allowlist can reject this request before it reaches the route.
                    self.assertIn(client.get(endpoint+suffix,base_url='http://library.example').status_code,(400,403))
            remote={'REMOTE_ADDR':'192.0.2.12'}
            self.assertEqual(client.get('/api/lab/reports/'+ordinary,environ_overrides=remote).status_code,200)
            self.assertIn(self.report,{r['id'] for r in client.get('/api/lab').get_json()['reports']})
            self.assertEqual({r['id'] for r in client.get('/api/lab',environ_overrides=remote).get_json()['reports']},{ordinary})
