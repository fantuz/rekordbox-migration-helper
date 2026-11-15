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


    def test_native_sort_orders_full_filtered_set_before_pagination(self):
        tracks = []
        for index in range(60):
            for sibling in range(2 + index % 3):
                tracks.append({'id': f'g{index:03}-{sibling}', 'title': f'Title {59-index:03}',
                               'artist': f'Artist {index % 5}', 'duration': 100 + sibling * 2,
                               'current_path': f'/Music/{index:03}.mp3', 'original_path': f'/Old/{index:03}.mp3',
                               'analysis_path': f'/Analyze/{index:03}'})
        tracks.append({'id': 'unknown-path', 'title': 'Unknown path', 'artist': 'No path',
                       'current_path': None, 'original_path': None, 'analysis_path': None})
        saved = self.store.save_snapshot({'tracks': tracks, 'playlists': [], 'source_kind': 'test'}, 'Sort pages')
        source = 'snapshot:' + saved['id']

        def get(endpoint, sort, direction, offset=0):
            response = self.client.get('/api/collection/' + endpoint,
                                       query_string={'source': source, 'sort': sort, 'direction': direction, 'offset': offset})
            self.assertEqual(response.status_code, 200, response.json)
            return response.json

        first = get('duplicates', 'title', 'asc')
        second = get('duplicates', 'title', 'asc', 50)
        self.assertEqual(first['total'], 60)
        self.assertEqual(len(first['rows']), 50)
        self.assertEqual(len(second['rows']), 10)
        self.assertEqual([r['title'] for r in first['rows'] + second['rows']],
                         [f'Title {n:03}' for n in range(60)])
        self.assertEqual([r['title'] for r in get('duplicates', 'title', 'desc')['rows'][:2]],
                         ['Title 059', 'Title 058'])
        self.assertEqual([r['count'] for r in get('duplicates', 'count', 'desc')['rows'][:10]], [4] * 10)
        self.assertEqual([r['duration_spread'] for r in get('duplicates', 'duration_spread', 'asc')['rows'][:10]], [2] * 10)
        self.assertEqual(first['sort'], 'title')
        self.assertEqual(first['direction'], 'asc')

        # Reference sorting spans multiple 50-row pages and keeps unknown paths
        # at the end, regardless of the requested direction.
        ref_first = get('references', 'current_path', 'desc')
        ref_last = get('references', 'current_path', 'desc', 150)
        self.assertEqual(ref_first['total'], len(tracks))
        self.assertEqual(len(ref_first['rows']), 50)
        self.assertEqual(ref_last['rows'][-1]['id'], 'unknown-path')
        self.assertTrue(all(ref_first['rows'][i]['current_path'] >= ref_first['rows'][i+1]['current_path']
                            for i in range(49)))

        for endpoint in ('duplicates', 'references'):
            for query in ({'sort': '__class__', 'direction': 'asc'},
                          {'sort': 'title', 'direction': 'sideways'}):
                response = self.client.get('/api/collection/' + endpoint, query_string={'source': source, **query})
                self.assertEqual(response.status_code, 400, response.json)

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

    def test_restore_conflict_rolls_back_file_moves_and_keeps_archive(self):
        s = json.loads((self.capture / 'comparison.json').read_text())
        saved = self.store.save_snapshot(s, 'Original snapshot')
        with self.store.connection() as db:
            row = tuple(db.execute('SELECT * FROM snapshots WHERE id=?', (saved['id'],)).fetchone())
        keys = ['captures:' + self.identity, 'snapshots:' + saved['id']]
        preview = self.post('/api/investigations/preview', {'keys': keys}).json
        archived = self.post('/api/investigations/archive', {'keys': keys, 'token': preview['token']}).json
        with self.store.connection() as db:
            db.execute('INSERT INTO snapshots VALUES (?,?,?,?,?,?,?)', row)
        r = self.post('/api/investigations/' + archived['id'] + '/restore', {})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(self.capture.exists())
        self.assertEqual(len(self.client.get('/api/investigations').json['archives']), 1)
        self.assertEqual(self.store.snapshot(saved['id'])['label'], 'Original snapshot')
        self.assertEqual(self.dbpath.read_bytes(), self.original)

    def test_metadata_only_capture_can_use_shared_snapshot_action(self):
        (self.capture / 'comparison.json').unlink()
        for path in (self.capture / 'snapshot').glob('*'):
            path.unlink()
        results = []
        def launch(work, message):
            results.append(work(lambda *_: None))
            return 'synthetic-job'
        with patch.object(application, 'launch', launch):
            r = self.post('/api/lab/snapshots', {'source': self.identity, 'label': 'Metadata-only capture'})
        self.assertEqual(r.status_code, 200, r.json)
        self.assertEqual(len(self.store.snapshot(results[0]['id'])['tracks']), 3)


if __name__ == '__main__':
    unittest.main()
