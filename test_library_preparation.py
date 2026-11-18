"""Preparation must bind evidence to the intended edition without touching audio."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from flask import Flask, jsonify

from library_preparation import latest_snapshot, register
from metadata_export import track
from workbench_store import Store


class PreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        app = Flask(__name__)
        @app.errorhandler(ValueError)
        def invalid(error):
            return jsonify(error=str(error)), 400
        catalog = SimpleNamespace(metadata={'version': '7'},
            tracks={'one': {'track_id': 'one', 'title': '日本 House', 'artist': 'Artist', 'genre': 'House',
                            'current_path': str(self.root / 'unmounted.wav'), 'size_bytes': 123}},
            cues={'one': []}, cue_summary=lambda identity: {'auto': 0, 'other': 0})
        self.session = {'id': 'a' * 32, 'name': 'First library', 'catalog': catalog}
        self.results = {}
        self.owner = SimpleNamespace(app=app, DATA=self.root, sessions={self.session['id']: self.session},
            active=self.session['id'], TEMPORARY=SimpleNamespace(path=self.root / 'temporary'), tasks={})
        self.owner.current = lambda: self.owner.sessions[self.owner.active]
        def launch(work, message):
            identity = 'job-' + str(len(self.results))
            self.results[identity] = work(lambda *args: None)
            return identity
        self.owner.launch = launch
        register(self.owner)
        self.client = app.test_client()
        self.saved = Store(self.root / 'workbench-sidecar.sqlite3')

    def prepare(self, source='workspace', **extra):
        response = self.client.post('/api/library-preparation', json={'source': source, 'workspace': self.session['id'], **extra})
        self.assertEqual(response.status_code, 200, response.json)
        return self.results[response.json['job']]

    def capture(self, identity='b' * 32):
        folder = self.root / 'analyzers' / identity
        folder.mkdir(parents=True)
        payload = {'scope_key': 'capture:' + identity, 'tracks': [track({'id': 'n', 'title': 'Native song'})],
                   'playlists': [], 'capabilities': {'history_details': False}}
        (folder / 'metadata.json').write_text(json.dumps(payload))
        (folder / 'report.json').write_text(json.dumps({'format': 'Native library', 'created': '2026-11-18T10:00:00Z'}))
        return 'capture:' + identity, folder

    def test_readiness_is_advisory_without_snapshot_creation_or_audio_reads(self):
        with patch('track_playback.inspect_audio', side_effect=AssertionError('Unexpected audio read')):
            response = self.client.get('/api/library-preparation', query_string={'source': 'workspace', 'workspace': self.session['id']})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json['snapshot'])
        self.assertEqual(response.json['file_health']['state'], 'not_started')
        self.assertEqual(response.json['extra_rekordbox_exports'], 0)
        self.assertEqual(self.saved.snapshots(), [])

    def test_workspace_preparation_reuses_the_same_immutable_snapshot(self):
        original = deepcopy(self.session['catalog'].tracks)
        with patch('track_playback.inspect_audio', side_effect=AssertionError('Unexpected audio read')):
            first = self.prepare()
            second = self.prepare()
        self.assertFalse(first['reused'])
        self.assertTrue(second['reused'])
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(len(self.saved.snapshots()), 1)
        self.assertEqual(self.saved.snapshot(first['id'])['tracks'][0]['title'], '日本 House')
        self.assertEqual(self.session['catalog'].tracks, original)

    def test_native_capture_and_xml_metadata_need_no_second_user_export(self):
        source, folder = self.capture()
        before = {p.name: p.read_bytes() for p in folder.iterdir()}
        prepared = self.prepare(source)
        self.assertEqual(self.saved.snapshot(prepared['id'])['scope_key'], source)
        self.assertEqual(before, {p.name: p.read_bytes() for p in folder.iterdir()})
        self.assertEqual(self.prepare(source)['id'], prepared['id'])
        self.assertEqual(self.prepare('snapshot:' + prepared['id'])['id'], prepared['id'])

    def test_scan_state_is_bound_to_the_exact_snapshot(self):
        prepared = self.prepare()
        with self.saved.connection() as db:
            db.execute('INSERT INTO file_health_scans VALUES (?,?,?,?,?)',
                       ('snapshot:' + prepared['id'], 10, 3, 1, 'partial'))
        response = self.client.get('/api/library-preparation', query_string={'source': 'workspace', 'workspace': self.session['id']})
        self.assertEqual(response.json['file_health']['state'], 'partial')
        source, _ = self.capture()
        other = self.client.get('/api/library-preparation', query_string={'source': source})
        self.assertEqual(other.json['file_health']['state'], 'not_started')

    def test_stale_or_malformed_selection_cannot_prepare_another_library(self):
        for body in ({'source': 'workspace'}, {'source': 'workspace', 'workspace': 'c' * 32},
                     {'source': []}, {'source': 'capture:../wrong'}, {'source': 'snapshot:' + 'd' * 32}):
            response = self.client.post('/api/library-preparation', json=body)
            self.assertEqual(response.status_code, 400, response.json)
        self.assertFalse(self.saved.snapshots())

    def test_delayed_worker_freezes_the_original_workspace(self):
        pending = []
        self.owner.launch = lambda work, message: pending.append(work) or 'delayed'
        self.client.post('/api/library-preparation', json={'source': 'workspace', 'workspace': self.session['id']})
        another = deepcopy(self.session)
        another.update(id='c' * 32, name='Second library')
        another['catalog'].tracks['one']['title'] = 'Wrong collection'
        self.owner.sessions[another['id']] = another
        self.owner.active = another['id']
        prepared = pending[0](lambda *args: None)
        snapshot = self.saved.snapshot(prepared['id'])
        self.assertEqual(snapshot['scope_key'], 'session:' + self.session['id'])
        self.assertEqual(snapshot['tracks'][0]['title'], '日本 House')

    def test_duplicate_running_preparations_share_a_job(self):
        self.owner.tasks['existing'] = {'id': 'existing', 'status': 'running',
            'preparation_scope': (str(self.root.resolve()), 'session:' + self.session['id'])}
        response = self.client.post('/api/library-preparation', json={'source': 'workspace', 'workspace': self.session['id']})
        self.assertEqual(response.json, {'job': 'existing'})
        self.assertFalse(self.saved.snapshots())

    def test_reuse_finds_snapshots_outside_the_display_limit(self):
        prepared = self.prepare()
        with self.saved.connection() as db:
            for index in range(101):
                db.execute('INSERT INTO snapshots SELECT ?,label,?,source_kind,?,digest,payload FROM snapshots WHERE id=?',
                           (str(index), '9999', 'other:' + str(index), prepared['id']))
        self.assertNotIn(prepared['id'], [s['id'] for s in self.saved.snapshots()])
        self.assertEqual(latest_snapshot(self.saved, 'session:' + self.session['id'])['id'], prepared['id'])

    def test_selected_older_snapshot_remains_available_to_insight_selectors(self):
        import app as application
        prepared=self.prepare()
        with self.saved.connection() as db:
            for index in range(101):
                db.execute('INSERT INTO snapshots SELECT ?,label,?,source_kind,?,digest,payload FROM snapshots WHERE id=?',
                           (str(index),'9999','other:'+str(index),prepared['id']))
        self.saved.set_setting('collection_context','snapshot:'+prepared['id'])
        with patch.object(application,'DATA',self.root),patch.object(application,'sessions',{}),patch.object(application,'active',None):
            response=application.app.test_client().get('/api/lab')
        self.assertEqual(response.status_code,200)
        self.assertIn(prepared['id'],[row['id'] for row in response.json['snapshots']])
        self.assertEqual(len(response.json['snapshots']),101)
