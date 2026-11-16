"""Raw clients deliberately retain old review tokens; no automatic fixture refresh."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from werkzeug.exceptions import Conflict

import app as application
from test_library_lab import snapshot,song
from workbench_store import Store
from workspace_safety import revision


class MetadataConcurrencyTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        p=patch.object(application,'DATA',self.root);p.start();self.addCleanup(p.stop)
        self.store=Store(self.root/'workbench-sidecar.sqlite3')
        self.source=snapshot([song('one'),song('two')]);self.scope=self.source['scope_key']
        self.sid=self.store.save_snapshot(self.source,'Review')['id']
        self.client=application.app.test_client();self.headers={'X-Workbench-Token':application.TOKEN}
        self.client.post('/api/lab/unlock',json={'snapshot':self.sid,'unlocked':True},headers=self.headers)

    def state(self):return self.store.edit_state(self.scope,history=True)
    def post(self,stamp,value='First'):
        return self.client.post('/api/lab/overrides',json={'snapshot':self.sid,'track_id':'one','field':'genre','value':value,'edit_revision':stamp},headers=self.headers)

    def test_two_tabs_cannot_overwrite_reset_or_normalize_newer_edits(self):
        shown=self.client.get('/api/lab/track',query_string={'snapshot':self.sid,'track_id':'one'}).json
        old=shown['edit_revision'];response=self.post(old)
        self.assertEqual(response.status_code,200,response.json);before=self.state()
        self.assertNotEqual(old,response.json['edit_revision'])
        self.assertEqual(self.post(old,'Stale').status_code,409)
        reset=self.client.delete('/api/lab/overrides',json={'snapshot':self.sid,'track_id':'one','field':'genre','edit_revision':old},headers=self.headers)
        bulk=self.client.post('/api/lab/normalize',json={'snapshot':self.sid,'track_ids':['one','two'],'field':'genre','value':'Stale bulk','edit_revision':old},headers=self.headers)
        self.assertEqual(reset.status_code,409);self.assertEqual(bulk.status_code,409)
        self.assertEqual(self.state(),before)
        self.assertEqual(self.post(None).status_code,409)
        self.assertEqual(self.post(before['edit_revision'],'Reviewed').status_code,200)

    def test_reset_and_restart_do_not_reuse_an_old_revision(self):
        first=self.post('0');stamp=first.json['edit_revision']
        reset=self.client.delete('/api/lab/overrides',json={'snapshot':self.sid,'track_id':'one','field':'genre','edit_revision':stamp},headers=self.headers)
        self.assertEqual(reset.status_code,200);self.assertEqual(reset.json['overrides'],{})
        reopened=Store(self.store.path)
        self.assertEqual(reopened.edit_state(self.scope)['edit_revision'],reset.json['edit_revision'])
        self.assertNotEqual(reset.json['edit_revision'],'0');self.assertEqual(self.post('0').status_code,409)

    def test_concurrent_writers_with_same_revision_have_exactly_one_winner(self):
        barrier=Barrier(2)
        def write(value):
            barrier.wait(timeout=10)
            try:
                self.store.save_override(self.scope,'one','genre',value,'House',expected_revision='0')
                return 'saved'
            except Conflict:return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(write,['First','Second']))
        self.assertCountEqual(results,['saved','conflict']);self.assertEqual(len(self.state()['history']),1)

    def test_snapshot_freezes_revision_values_and_history_together(self):
        self.post('0');before=self.state();original=self.store.overrides
        other=Store(self.store.path)
        def interleave(scope,db=None):
            other.save_override(scope,'one','genre','Later','House')
            return original(scope,db)
        with patch.object(self.store,'overrides',side_effect=interleave):
            frozen=self.state()
        self.assertEqual(frozen,before)
        self.assertEqual(other.overrides(self.scope)['one']['genre']['value'],'Later')

    def test_bulk_baseline_failure_rolls_back_every_write_and_revision(self):
        self.store.save_override(self.scope,'two','genre','Previous','Different baseline')
        before=self.state()
        with self.assertRaisesRegex(ValueError,'baseline changed'):
            self.store.save_bulk(self.source,['one','two'],'genre','Bulk',expected_revision=before['edit_revision'])
        self.assertEqual(self.state(),before)

    def test_metadata_change_invalidates_export_approval(self):
        session={'id':'workspace','catalog':SimpleNamespace(),'metadata':{},'decisions':{},'relocations':{}}
        old=revision(session,self.root)
        self.store.save_override('session:workspace','one','genre','New','House')
        self.assertNotEqual(old,revision(session,self.root))
        with patch.object(application,'active','workspace'),patch.object(application,'sessions',{'workspace':session}),patch.object(application,'launch') as launch:
            response=self.client.post('/api/export',json={'format':'xml'},headers={**self.headers,
                'X-Workbench-Workspace':'workspace','X-Workbench-Revision':old})
        self.assertEqual(response.status_code,409);launch.assert_not_called()

    def test_write_during_workspace_response_is_not_silently_approved(self):
        session={'id':'workspace','name':'Before','catalog':SimpleNamespace(metadata={},counts={},tracks={}),
                 'metadata':{'name':'Before'},'decisions':{},'relocations':{},'events':[],'policy':'newest'}
        old=revision(session,self.root);persist=application.persist
        def save_then_edit(current):
            persist(current)
            self.store.save_override('session:workspace','one','genre','Concurrent','House')
        with patch.object(application,'active','workspace'),patch.object(application,'sessions',{'workspace':session}),patch.object(application,'persist',side_effect=save_then_edit):
            response=self.client.post('/api/session/name',json={'name':'Reviewed'},headers={**self.headers,
                'X-Workbench-Workspace':'workspace','X-Workbench-Revision':old})
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['session']['revision'],response.headers['X-Workbench-Revision'])
        self.assertNotEqual(response.json['session']['revision'],revision(session,self.root))
