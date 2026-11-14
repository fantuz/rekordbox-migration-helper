"""Synthetic regressions for native contexts and reversible investigation cleanup."""
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app as application
from analyzer import analyze_folder
from collection_views import duplicate_groups, statistics
from research_capture import capture_private_database
from test_discovery_history import native_fixture
from workbench_store import Store, encoded, now


class NativeViewsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.data = self.root / 'work'
        self.source = self.root / 'source'
        self.source.mkdir()
        self.dbpath = self.source / 'master.db'
        with native_fixture(self.dbpath) as db:
            db.execute("INSERT INTO djmdContent VALUES('duplicate','Track A','/Music/a.mp3','artist',243,'2023-03-01',0)")
        db.close()
        self.original = self.dbpath.read_bytes()
        self.identity = 'c' * 32
        self.capture = self.data / 'analyzers' / self.identity
        analyze_folder(self.dbpath, self.capture, lambda *_: None)
        self.scope = 'capture:' + self.identity
        for name, value in [('DATA', self.data), ('active', None), ('sessions', {}), ('tasks', {})]:
            p = patch.object(application, name, value)
            p.start(); self.addCleanup(p.stop)
        p = patch.object(application, 'lab_jobs_active', lambda: False)
        p.start(); self.addCleanup(p.stop)
        self.client = application.app.test_client()
        self.headers = {'X-Workbench-Token': application.TOKEN}
        self.store = Store(self.data / 'workbench-sidecar.sqlite3')

    def post(self, route, value):
        return self.client.post(route, json=value, headers=self.headers)

    def test_native_views_work_without_workspace_or_retained_database(self):
        for p in (self.capture / 'snapshot').glob('*'):
            p.unlink()
        self.assertEqual(self.post('/api/journeys/context', {'source': self.scope}).status_code, 200)
        r = self.client.get('/api/collection/statistics', query_string={'source': self.scope})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json['counters']['total'], 3)
        self.assertIsNone(r.json['counters']['rated'])
        self.assertIsNone(r.json['counters']['missing_media'])
        r = self.client.get('/api/collection/duplicates', query_string={'source': self.scope})
        self.assertEqual(r.json['groups'], 1)
        group = r.json['rows'][0]['id']
        detail = self.client.get('/api/collection/duplicates/' + group, query_string={'source': self.scope})
        self.assertEqual(detail.json['count'], 2)
        self.assertEqual(self.post('/api/collection/duplicates/' + group + '/review', {'source': self.scope, 'status': 'keep_separate'}).status_code, 200)
        self.assertEqual(self.client.get('/api/collection/duplicates', query_string={'source': self.scope}).json['rows'][0]['review'], 'keep_separate')
        self.assertEqual(self.client.get('/api/collection/references', query_string={'source': self.scope}).json['total'], 3)
        h = self.client.get('/api/lab/history', query_string={'snapshot': self.scope}).json
        self.assertEqual(h['entries_total'], 5)
        self.assertEqual(self.client.get('/api/lab/history/h', query_string={'snapshot': self.scope}).json['repeated_entries'], 1)
        self.assertEqual(self.dbpath.read_bytes(), self.original)
        self.assertEqual(self.post('/api/playback/availability', {'snapshot': self.scope, 'track_ids': ['a']}).status_code, 200)

    def test_unknown_and_malformed_ranges_and_source_do_not_fall_back(self):
        for values in [{'min': 'nan'}, {'max': 'inf'}, {'min': '-1'}, {'min': '3', 'max': '2'}]:
            self.assertEqual(self.client.get('/api/collection/statistics', query_string={'source': self.scope, **values}).status_code, 400)
        self.assertEqual(self.client.get('/api/collection/statistics', query_string={'source': 'capture:../outside'}).status_code, 400)
        self.assertEqual(self.client.get('/api/lab/history', query_string={'source': 'capture:' + 'f'*32}).status_code, 400)

    def test_duplicates_preserve_versions_and_posix_case_and_missing_metadata(self):
        s = {'tracks': [{'id': '1', 'artist': 'Example', 'title': 'Track', 'current_path': '/Music/A.mp3'},
                        {'id': '2', 'artist': 'EXAMPLE', 'title': 'Track (remix)', 'current_path': '/Music/a.mp3'},
                        {'id': '3', 'current_path': 'C:\\Music\\A.mp3'}, {'id': '4', 'current_path': 'c:/music/a.mp3'}]}
        self.assertEqual(len(duplicate_groups(s)), 1)
        self.assertEqual(duplicate_groups(s, 'metadata'), [])
        self.assertEqual(statistics({'tracks': [{'id': 'a', 'duration': None}]})['unknown_duration'], 1)

    def test_capture_playlist_order_tolerates_text_and_missing_positions(self):
        with native_fixture(self.root / 'positions.db') as db:
            db.executescript('''CREATE TABLE djmdPlaylist(ID TEXT,Name TEXT,Attribute INTEGER);
                CREATE TABLE djmdSongPlaylist(ID TEXT,PlaylistID TEXT,ContentID TEXT,TrackNo);
                INSERT INTO djmdPlaylist VALUES('p','Synthetic list',0);
                INSERT INTO djmdSongPlaylist VALUES('e3','p','a','unknown');
                INSERT INTO djmdSongPlaylist VALUES('e2','p','b','2');
                INSERT INTO djmdSongPlaylist VALUES('e1','p','a',1);''')
            s = capture_private_database(db, 'test')
        db.close()
        self.assertEqual(s['playlists'][0]['tracks'], ['a', 'b', 'a'])

    def test_cleanup_preview_dependencies_archive_and_restore(self):
        snapshot = json.loads((self.capture / 'comparison.json').read_text())
        saved = self.store.save_snapshot(snapshot, 'Synthetic library')
        report = self.store.save_report('Synthetic report', [saved['id']], {'tracks': 3}, [{'section': 'check'}])
        selected = ['snapshots:' + saved['id']]
        r = self.post('/api/investigations/preview', {'keys': selected})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json['blockers'][0]['key'], 'reports:' + report['id'])
        self.assertEqual(self.post('/api/investigations/archive', {'keys': selected, 'token': r.json['token']}).status_code, 400)
        selected += ['reports:' + report['id'], 'captures:' + self.identity]
        self.post('/api/journeys/context', {'source': self.scope})
        r = self.post('/api/investigations/preview', {'keys': selected})
        token = r.json['token']
        r = self.post('/api/investigations/archive', {'keys': selected, 'token': token})
        self.assertEqual(r.status_code, 200, r.json)
        self.assertFalse(self.capture.exists())
        self.assertEqual(self.store.snapshots(), [])
        self.assertEqual(self.store.reports(), [])
        self.assertEqual(self.store.setting('collection_context'), '')
        self.assertEqual(self.client.get('/api/journeys').json['sources'], [])
        self.assertEqual(self.post('/api/investigations/' + r.json['id'] + '/restore', {}).status_code, 200)
        self.assertTrue(self.capture.exists())
        self.assertEqual(self.store.snapshot(saved['id'])['tracks'], snapshot['tracks'])
        self.assertEqual(self.store.report(report['id'])['rows'], [{'section': 'check'}])
        self.assertEqual(self.dbpath.read_bytes(), self.original)

    def test_cleanup_blocks_active_work_and_stale_preview(self):
        keys = ['captures:' + self.identity]
        p = self.post('/api/investigations/preview', {'keys': keys}).json
        report = self.capture / 'report.json'
        report.write_text(report.read_text() + '\n')
        self.assertEqual(self.post('/api/investigations/archive', {'keys': keys, 'token': p['token']}).status_code, 400)
        with patch.object(application, 'tasks', {'task': {'status': 'running'}}):
            self.assertEqual(self.post('/api/investigations/preview', {'keys': keys}).status_code, 400)
        with patch.object(application, 'lab_jobs_active', lambda: True):
            self.assertEqual(self.post('/api/investigations/preview', {'keys': keys}).status_code, 400)
        self.assertTrue(self.capture.exists())

    def test_workspace_cleanup_preserves_inputs_and_exports(self):
        identity = 'd'*32
        folder = self.data / identity
        folder.mkdir()
        (folder / 'state.json').write_text(encoded({'id': identity, 'name': 'Old test', 'created': now()}))
        (folder / 'export.zip').write_bytes(b'preserve export')
        (self.data / 'inputs').mkdir()
        (self.data / 'inputs/master.db').write_bytes(b'preserve input')
        keys = ['workspaces:' + identity]
        with patch.object(application, 'active', identity):
            p = self.post('/api/investigations/preview', {'keys': keys}).json
            self.assertTrue(p['blockers'])
        p = self.post('/api/investigations/preview', {'keys': keys}).json
        r = self.post('/api/investigations/archive', {'keys': keys, 'token': p['token']})
        self.assertEqual(r.status_code, 200, r.json)
        self.assertEqual((folder / 'export.zip').read_bytes(), b'preserve export')
        self.assertEqual((self.data / 'inputs/master.db').read_bytes(), b'preserve input')
        self.assertFalse((folder / 'state.json').exists())
        self.assertEqual(self.post('/api/investigations/' + r.json['id'] + '/restore', {}).status_code, 200)
        self.assertTrue((folder / 'state.json').exists())


if __name__ == '__main__':
    unittest.main()
