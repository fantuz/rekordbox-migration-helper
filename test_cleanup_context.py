from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock
from types import SimpleNamespace
import json
import unittest
from unittest.mock import patch
from flask import Flask

from cleanup_context import build_context, workspace_stamp
from collection_views import duplicate_groups, register
from workbench_store import Store


class CleanupContextTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.owner = SimpleNamespace(DATA=Path(tmp.name), sessions={}, active=None, lock=RLock())
        self.store = Store(self.owner.DATA / 'private.db')
        self.scope = 'capture:' + 'a' * 32
        self.snapshot = {'scope_key': self.scope, 'tracks': [
            {'id': str(i), 'current_path': f'C:/Users/DJ/Music/{i}.wav'} for i in range(9)]}
        self.snapshot['id'] = self.store.save_snapshot(self.snapshot, 'Test capture')['id']
        self.source = 'snapshot:' + self.snapshot['id']

    def test_mappings_and_historical_cloud_evidence_never_grant_access(self):
        with self.store.connection() as db:
            for table in ['dropbox_records', 'google_drive_records']:
                db.execute(f'CREATE TABLE {table}(source TEXT,binding TEXT,track_id TEXT,payload TEXT)')
                db.executemany(f'INSERT INTO {table} VALUES(?,?,?,?)', [
                    (self.source, 'old authorization', '0', '{"status":"present"}'),
                    (self.scope, 'old parent capture', '1', '{"status":"not_found"}'),
                    (self.source, 'current', '2', '{"status":"unmapped"}'),
                    ('snapshot:other', 'other account', '3', '{"status":"present"}')])
            db.executemany('INSERT INTO file_health_records(source,track_id,providers,cloud_state) VALUES(?,?,?,?)', [
                (self.source, '4', 0, 'online_only'), (self.scope, '5', 2, 'local'),
                ('capture:other', '3', 1, 'online_only'), (self.source, '3', 0, 'local')])
        self.snapshot['tracks'][6]['original_path'] = 'file://localhost/D:/Imports/6.wav'
        self.snapshot['tracks'][7]['original_path'] = 'file://localhost/D:/ImportSub/7.wav'
        self.store.set_setting('audio_paths:' + self.scope,
                               [{'recorded_root': 'D:/Imports', 'local_root': '/Users/test/Attached'}])
        self.store.set_setting('dropbox_mapping', {'source': self.source, 'scope_key': self.scope,
                              'local_root': '/Users/test/Attached', 'managed_root': '/Users/test/Attached'})
        self.store.set_setting('google_drive_mapping', {'source': 'snapshot:other', 'scope_key': self.scope,
                              'local_root': '/private/unrelated/source'})
        with (patch('audio_paths.mapped_path', side_effect=AssertionError('Filesystem mapping')),
             patch('cloud_file_evidence.cached_evidence', side_effect=AssertionError('Provider access'))):
            result = build_context(self.owner, self.store, self.snapshot)
        self.assertEqual(result['cloud_ids'], {'0', '1', '4', '5', '6'})
        self.assertEqual(result['protected_ids'], {'6': {'mapped_path'}})
        self.assertEqual(result['extra_cloud_roots'], ('/Users/test/Attached',))

    def test_keepers_history_enrichment_and_manual_reviews_are_scoped(self):
        for item in self.snapshot['tracks'][:2]:
            item.update(artist='Artist', title='Mix')
        group = duplicate_groups(self.snapshot, 'metadata')[0]['id']
        self.store.set_setting('duplicate_reviews:' + self.source, {group: 'keep_separate'})
        self.store.save_override(self.scope, '2', 'rating', 4, 0)
        self.store.save_override(self.scope, '3', 'rating', 4, 0)
        self.store.clear_override(self.scope, '3', 'rating')
        self.store.save_override('capture:other', '4', 'rating', 4, 0)
        self.store.set_setting('onetagger:review', {'snapshot': self.snapshot['id'], 'tracks': [{'track_id': '5'}]})
        self.store.set_setting('onetagger:other', {'snapshot': 'other', 'tracks': [{'track_id': '4'}]})
        with self.store.connection() as db:
            db.executemany('INSERT INTO mb_batches VALUES (?,?,?,?,?,?)', [
                ('one', self.snapshot['id'], '', 'preview', '{}', json.dumps([{'id': '6'}])),
                ('two', 'other', '', 'preview', '{}', json.dumps([{'id': '4'}]))])
        result = build_context(self.owner, self.store, self.snapshot)
        self.assertEqual(result['protected_ids'], {
            '0': {'keep_separate'}, '1': {'keep_separate'},
            '2': {'metadata_edit', 'edit_history'}, '3': {'edit_history'},
            '5': {'enrichment_review'}, '6': {'enrichment_review'}})
        # Recheck reads the writer's uncommitted final state too.
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM settings WHERE name=?', ('duplicate_reviews:' + self.source,))
            self.assertNotIn('0', build_context(self.owner, self.store, self.snapshot, db=db)['protected_ids'])
            db.rollback()
        self.assertEqual(build_context(self.owner, self.store, self.snapshot), result)

    def test_session_switch_reopen_and_edits_invalidate_context(self):
        self.snapshot['scope_key'] = 'session:work'
        self.owner.sessions['work'] = {'id': 'work', '_workspace_generation': 'a', '_state_commit': '1',
                'relocations': {'2': '/some/path'}, 'held_pairs': {'p': 'Review'}, 'decisions': {'q': {'action':'skip'}},
                'catalog': SimpleNamespace(tracks={row['id']:row for row in self.snapshot['tracks']},
                                           pairs={'p': {'a': '0', 'b':'1'}, 'q': {'a':'0','b':'3'}})}
        self.owner.active = 'work'
        result = build_context(self.owner, self.store, self.snapshot)
        self.assertEqual(result['protected_ids'], {'0':{'workspace_decision'}, '1':{'workspace_decision'},
                                                   '2':{'workspace_relocation'}, '3':{'workspace_decision'}})
        first = workspace_stamp(self.owner, self.snapshot)
        self.owner.sessions['work']['_state_commit'] = '2'
        second = workspace_stamp(self.owner, self.snapshot)
        self.owner.sessions['work']['_workspace_generation'] = 'b'
        self.assertNotEqual(first, second)
        self.assertNotEqual(second, workspace_stamp(self.owner, self.snapshot))
        self.owner.active = 'elsewhere'
        self.assertEqual(workspace_stamp(self.owner, self.snapshot), 'unavailable')
        protected = build_context(self.owner, self.store, self.snapshot)['protected_ids']
        self.assertEqual(set(protected), {str(i) for i in range(9)})
        self.assertTrue(all(v == {'workspace_unavailable'} for v in protected.values()))
        self.snapshot['scope_key'] = 'cleanup:' + self.snapshot['id']
        protected = build_context(self.owner, self.store, self.snapshot)['protected_ids']
        self.assertTrue(all(v == {'derived_snapshot'} for v in protected.values()))
        self.assertEqual(workspace_stamp(self.owner, self.snapshot), '')

    def test_native_snapshot_holds_xml_only_preparation_and_inventory_candidates(self):
        self.owner.active = 'joined'
        self.snapshot['scope_key'] = 'session:joined'
        tracks = {row['id']:dict(row) for row in self.snapshot['tracks']}
        tracks['0']['xml_marks'] = [{'Name':'New cue'}]
        tracks['1']['xml_tempo_entries'] = 2
        tracks['2']['xml_location'] = 'file://localhost/Volumes/Drive/2.wav'
        tracks['3']['xml_location'] = 'file://localhost/C:/Users/DJ/Music/3.wav'
        del tracks['7']
        self.owner.sessions['joined'] = {'id':'joined', 'catalog':SimpleNamespace(
            tracks=tracks, pairs={'pair': {'a':'6','b':'8'}}),
            'inventory': {'matches': {
                '3': {'status':'found','candidates':[{'path':'C:/Users/DJ/Music/3.wav'}]},
                '4': {'status':'review','candidates':[{'path':'E:/Recovered/4.wav'}]},
                '5': {'status':'cloud_only','candidates':[{'path':'C:/Users/DJ/Music/5.wav','cloud_only':True}]}}},
            'batches': [{'previous_held': {'pair':'Awaiting review'}}]}
        protected = build_context(self.owner, self.store, self.snapshot)['protected_ids']
        self.assertEqual(protected, {
            '0': {'cues'}, '1': {'analysis'}, '2': {'alternate_reference'},
            '4': {'alternate_reference'}, '5': {'cloud_reference'}, '6': {'workspace_decision'},
            '7': {'workspace_unavailable'}, '8': {'workspace_decision'}})

    def test_older_duplicate_reviews_can_be_superseded_only_in_the_current_workspace(self):
        self.store = Store(self.owner.DATA / 'workbench-sidecar.sqlite3')
        self.owner.active = 'one'
        self.snapshot['scope_key'] = 'session:one'
        for row in self.snapshot['tracks'][:2]:
            row.update(title='S', artist='A')
        catalog = SimpleNamespace(tracks={row['id']:row for row in self.snapshot['tracks']}, pairs={})
        self.owner.sessions['one'] = {'id':'one','catalog':catalog}
        self.owner.sessions['two'] = {'id':'two','catalog':catalog}
        group = duplicate_groups(self.snapshot, 'metadata')[0]['id']
        self.store.set_setting('duplicate_reviews:workspace', {group:'keep_separate'})
        holds = lambda: build_context(self.owner, self.store, self.snapshot)['protected_ids']
        self.assertEqual(holds(), {'0':{'keep_separate'}, '1':{'keep_separate'}})
        self.owner.app = Flask(__name__)
        register(self.owner)
        with patch('collection_views.resolve', return_value=self.snapshot):
            response = self.owner.app.test_client().post('/api/collection/duplicates/' + group + '/review',
                 json={'source':'workspace','status':'unreviewed','basis':'metadata'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.setting('duplicate_reviews:session:one'), {group:'unreviewed'})
        self.assertEqual(self.store.setting('duplicate_reviews:workspace'), {group:'keep_separate'})
        self.assertEqual(holds(), {})
        self.owner.active = 'two'
        self.snapshot['scope_key'] = 'session:two'
        self.assertEqual(holds(), {'0':{'keep_separate'}, '1':{'keep_separate'}})


if __name__ == '__main__':
    unittest.main()
