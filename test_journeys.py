"""Synthetic journey/evidence regression cases. No real libraries or network."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from flask import Flask, jsonify

from journeys import context, integrity, new_plan, update_plan
from journeys_routes import register
from metadata_export import track
from workbench_store import Store


def snapshot():
    return {'scope_key': 'scope', 'captured': '2026-01-01', 'tracks': [track({
        'id': '1', 'title': '日本 🎵', 'artist': 'A', 'album': 'B', 'genre': 'House',
        'year': 2020, 'bpm': 120, 'duration': 200, 'rating': 2})], 'playlists': [],
        'capabilities': {'cue_positions': False, 'playlist_order': True}}


class EvidenceTests(unittest.TestCase):
    def test_xml_cannot_establish_native_integrity_and_unscanned_is_not_missing(self):
        summary, rows = integrity(snapshot())
        checks = {r['section']: r for r in rows if 'status' in r}
        self.assertEqual(checks['database']['status'], 'not_checked')
        self.assertEqual(checks['audio']['status'], 'not_checked')
        self.assertEqual(checks['assets']['status'], 'not_checked')
        self.assertEqual(checks['cloud']['status'], 'unknown')
        self.assertFalse(summary['source_writes'])
        self.assertEqual(summary['checks']['unknown'], 2)

    def test_recorded_failure_and_duplicates_have_distinct_severity(self):
        saved = {'database': {'integrity_ok': False, 'missing_core_columns': [],
                 'health': {'broken_track_links': 3, 'duplicate_recorded_path_groups': 2}}}
        _, rows = integrity(snapshot(), saved)
        checks = {r['section']: r for r in rows if 'status' in r}
        self.assertEqual(checks['database']['status'], 'issue')
        self.assertEqual(checks['relationships']['count'], 3)
        self.assertEqual(checks['duplicate_paths']['status'], 'review')

    def test_partial_asset_audit_and_inventory_cannot_be_clear(self):
        assets = {'inventory_complete': False, 'ownership_complete': True, 'missing_in_scope': 0}
        _, rows = integrity(snapshot(), inventory={'counts': {}, 'warnings': ['not read']},
                            asset_summary=assets, depth='deep')
        checks = {r['section']: r for r in rows if 'status' in r}
        self.assertEqual(checks['audio']['status'], 'unknown')
        self.assertEqual(checks['assets']['status'], 'unknown')

    def test_context_separates_working_edits_and_capabilities(self):
        s = snapshot()
        c = context(s, source='snapshot:one', overrides=4)
        self.assertEqual(c['working_override_fields'], 4)
        self.assertFalse(c['cleanup_plan_applied'])
        self.assertFalse(c['capabilities']['cue_positions'])
        self.assertTrue(c['capabilities']['playlist_order'])
        self.assertEqual(c['captured'], '2026-01-01')

    def test_confirmations_never_turn_into_machine_verification(self):
        p = new_plan('migration')
        p = update_plan(p, {'step': 'restore', 'status': 'confirmed', 'notes': '私のメモ'}, lambda _: None)
        self.assertEqual(p['steps']['restore']['basis'], 'user statement')
        self.assertIsNone(p['comparison'])
        self.assertEqual(p['notes'], '私のメモ')
        with self.assertRaises(ValueError):
            update_plan(p, {'step': 'backup', 'status': 'skipped'}, lambda _: None)
        with self.assertRaises(ValueError):
            update_plan(p, {'notes': '\x00'}, lambda _: None)
        with self.assertRaises(ValueError):
            update_plan(p, {'verified_restore': True}, lambda _: None)

    def test_changing_comparison_sources_invalidates_evidence_link(self):
        p = new_plan('migration', 'snapshot:one')
        p['comparison'] = {'id': 'old'}
        p = update_plan(p, {'before_snapshot': 'two'}, lambda _: None)
        self.assertIsNone(p['comparison'])
        self.assertEqual(p['before_snapshot'], 'two')


class JourneyRoutesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        app = Flask(__name__)
        @app.errorhandler(ValueError)
        def invalid(error):
            return jsonify(error=str(error)), 400
        self.results = {}
        def launch(work, message):
            identity = 'task-' + str(len(self.results))
            self.results[identity] = work(lambda *args: None)
            return identity
        self.owner = SimpleNamespace(app=app, DATA=self.root, sessions={}, active=None, launch=launch)
        self.store = Store(self.root / 'workbench-sidecar.sqlite3')
        self.saved = self.store.save_snapshot(snapshot(), 'My source')
        register(self.owner)
        self.client = app.test_client()

    def create(self, kind='migration'):
        r = self.client.post('/api/journeys', json={'kind': kind, 'source': 'snapshot:' + self.saved['id']})
        self.assertEqual(r.status_code, 200)
        return r.json

    def test_context_and_journey_survive_new_store_connections(self):
        source = 'snapshot:' + self.saved['id']
        self.assertEqual(self.client.post('/api/journeys/context', json={'source': source}).status_code, 200)
        p = self.create()
        self.client.post('/api/journeys/' + p['id'], json={'notes': 'continue later'})
        state = self.client.get('/api/journeys').json
        self.assertEqual(state['selected'], source)
        self.assertEqual(state['sources'][0]['id'], source)
        self.assertEqual(state['context']['tracks'], 1)
        self.assertEqual(state['plans'][0]['notes'], 'continue later')
        self.assertEqual(Store(self.store.path).setting('journey_plans')[p['id']]['notes'], 'continue later')

    def test_old_plan_snapshots_remain_selectable_outside_recent_list(self):
        p = self.create()
        with patch.object(Store, 'snapshots', return_value=[]):
            state = self.client.get('/api/journeys').json
        self.assertIn('snapshot:' + self.saved['id'], {s['id'] for s in state['sources']})
        self.assertEqual(state['plans'][0]['before_snapshot'], self.saved['id'])
        self.assertEqual(state['plans'][0]['id'], p['id'])

    def test_quick_scope_never_inventories_supplied_paths(self):
        p = self.create('integrity')
        with patch('journeys_routes.audit_assets') as audit:
            response = self.client.post('/api/journeys/' + p['id'] + '/check', json={'depth': 'quick', 'asset_paths': ['/not-scanned']})
            self.assertEqual(response.status_code, 400)
            audit.assert_not_called()
            response = self.client.post('/api/journeys/' + p['id'] + '/check', json={'depth': 'quick'})
            self.assertEqual(response.status_code, 200)
            audit.assert_not_called()
        result = self.results[response.json['job']]
        self.assertEqual(result['kind'], 'integrity journey')
        self.assertEqual(self.store.report(result['id'])['summary']['depth'], 'quick')

    def test_deep_scope_uses_only_explicit_paths(self):
        p = self.create('integrity')
        with patch('journeys_routes.audit_assets', return_value=({'inventory_complete': True, 'ownership_complete': True}, [])) as audit:
            response = self.client.post('/api/journeys/' + p['id'] + '/check', json={'depth': 'deep', 'asset_paths': ['/chosen'], 'verify_assets': False})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(audit.call_args.args[1], ['/chosen'])
            self.assertFalse(audit.call_args.args[3])

    def test_existing_source_capture_is_context_without_reading_original(self):
        identity = 'a' * 32
        folder = self.root / 'analyzers' / identity
        folder.mkdir(parents=True)
        s = snapshot()
        (folder / 'metadata.json').write_text(json.dumps(s), encoding='utf-8')
        report = {'created': '2026-02-01', 'format': 'Saved XML', 'source': '/unavailable/original.xml',
                  'xml': {'counters': {'unresolved_playlist_references': 2}}}
        (folder / 'report.json').write_text(json.dumps(report), encoding='utf-8')
        response = self.client.post('/api/journeys/context', json={'source': 'capture:' + identity})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['captured'], '2026-02-01')
        self.assertIsNone(response.json['snapshot'])
        p = self.client.post('/api/journeys', json={'kind': 'integrity', 'source': 'capture:' + identity}).json
        response = self.client.post('/api/journeys/' + p['id'] + '/check', json={'depth': 'quick'})
        result = self.store.report(self.results[response.json['job']]['id'])
        broken = next(r for r in result['rows'] if r['section'] == 'relationships')
        self.assertEqual(broken['status'], 'issue')
        self.assertEqual(broken['count'], 2)

    def test_compare_requires_distinct_snapshots_and_retains_report(self):
        p = self.create()
        path = '/api/journeys/' + p['id']
        response = self.client.post(path + '/compare', json={})
        self.assertEqual(response.status_code, 400)
        later = deepcopy(snapshot())
        later['tracks'][0]['rating'] = 5
        after = self.store.save_snapshot(later, 'Destination')
        self.client.post(path, json={'after_snapshot': after['id']})
        response = self.client.post(path + '/compare', json={})
        self.assertEqual(response.status_code, 200)
        result = self.results[response.json['job']]
        self.assertEqual(result['summary']['ratings_changed'], 1)
        self.assertEqual(self.client.get('/api/journeys').json['plans'][0]['comparison']['id'], result['id'])


if __name__ == '__main__':
    unittest.main()
