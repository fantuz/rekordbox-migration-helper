"""Real HTTP/SQLite star edits preserve evidence and reject stale review tokens."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import app as application
from test_library_lab import snapshot, song
from test_support import workspace_client
from workbench_store import Store
from workspace_safety import revision


class InlineRatingTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name, value in [('DATA', self.root), ('sessions', {}), ('active', None)]:
            p = patch.object(application, name, value); p.start(); self.addCleanup(p.stop)
        self.store = Store(self.root / 'workbench-sidecar.sqlite3')
        self.snapshot = snapshot([song('one', rating=2), song('unknown', rating=None), song('zero', rating=0)])
        self.sid = self.store.save_snapshot(self.snapshot, 'Synthetic stars')['id']
        self.source = 'snapshot:' + self.sid
        self.client = workspace_client(application)
        self.headers = {'X-Workbench-Token': application.TOKEN}

    def rows(self, source=None, ids=('one', 'unknown', 'zero')):
        response = self.client.get('/api/ratings', query_string=[('source', source or self.source), *[('track_id', i) for i in ids]])
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def save(self, value=4, **changes):
        state = self.rows(ids=('one',))
        body = {'source': self.source, 'track_id': 'one', 'captured': 2,
                'edit_revision': state['edit_revision'], 'value': value, **changes}
        return self.client.post('/api/ratings', json=body, headers=self.headers)

    def test_save_persists_to_existing_sidecar_and_reset_preserves_other_fields(self):
        before = deepcopy(self.store.snapshot(self.sid))
        response = self.save(); self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual((response.json['value'], response.json['captured'], response.json['staged']), (4, 2, True))
        # Existing detail editor and restarted Store see precisely the same edit.
        detail = self.client.get('/api/lab/track', query_string={'snapshot': self.sid, 'track_id': 'one'}).json
        self.assertEqual(detail['overrides']['rating']['value'], 4)
        self.assertEqual(Store(self.store.path).overrides(self.snapshot['scope_key'])['one']['rating']['value'], 4)
        self.store.save_override(self.snapshot['scope_key'], 'one', 'comment', 'Private draft', None)
        stamp = self.rows(ids=('one',))['edit_revision']
        reset = self.client.delete('/api/ratings', json={'source': self.source, 'track_id': 'one', 'captured': 2, 'edit_revision': stamp}, headers=self.headers)
        self.assertEqual(reset.status_code, 200, reset.json)
        self.assertEqual((reset.json['value'], reset.json['staged']), (2, False))
        self.assertEqual(set(self.store.overrides(self.snapshot['scope_key'])['one']), {'comment'})
        self.assertEqual(self.store.snapshot(self.sid), before)

    def test_unknown_and_zero_are_distinct_and_explicit_clear_is_staged(self):
        before = self.rows(); rows = {r['track_id']: r for r in before['rows']}
        self.assertIsNone(rows['unknown']['value']); self.assertEqual(rows['zero']['value'], 0)
        response = self.save(0, track_id='unknown', captured=None)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual((response.json['value'], response.json['captured'], response.json['staged']), (0, None, True))
        self.assertIsNone(self.store.snapshot(self.sid)['tracks'][1]['rating'])

    def test_stale_or_missing_revision_cannot_overwrite_or_reset(self):
        old = self.rows(ids=('one',))['edit_revision']; saved = self.save()
        self.assertEqual(saved.status_code, 200); before = self.store.edit_state(self.snapshot['scope_key'], history=True)
        for method, stamp in [('POST', old), ('DELETE', old), ('POST', None)]:
            response = self.client.open('/api/ratings', method=method, json={'source': self.source, 'track_id': 'one', 'captured': 2, 'value': 1, 'edit_revision': stamp}, headers=self.headers)
            self.assertEqual(response.status_code, 409, response.json)
        self.assertEqual(self.store.edit_state(self.snapshot['scope_key'], history=True), before)

    def test_rejected_value_or_changed_baseline_creates_no_override(self):
        for value in [True, -1, 6, '3.5', 'four']:
            self.assertEqual(self.save(value).status_code, 400)
        self.assertEqual(self.save(captured=5).status_code, 409)
        self.assertEqual(self.store.overrides(self.snapshot['scope_key']), {})
        self.assertEqual(self.store.override_history(self.snapshot['scope_key']), [])

    def test_action_token_membership_and_bounded_reads_are_required(self):
        body = {'source': self.source, 'track_id': 'one', 'captured': 2, 'value': 5, 'edit_revision': '0'}
        self.assertEqual(self.client.post('/api/ratings', json=body).status_code, 403)
        self.assertEqual(self.save(track_id='absent').status_code, 400)
        with patch('inline_ratings.resolve') as resolve:
            response = self.client.get('/api/ratings', query_string=[('source', self.source), *[('track_id', str(i)) for i in range(101)]])
            self.assertEqual(response.status_code, 400); resolve.assert_not_called()

    def test_scopes_remain_separate_and_capture_files_are_unchanged(self):
        capture_id = 'a' * 32; folder = self.root / 'analyzers' / capture_id; folder.mkdir(parents=True)
        metadata = folder / 'metadata.json'; metadata.write_text(json.dumps(self.snapshot))
        report = folder / 'report.json'; report.write_text(json.dumps({'format': 'Synthetic', 'created': '2026-01-01'}))
        before = metadata.read_bytes(), report.read_bytes()
        self.assertEqual(self.save().status_code, 200)
        source = 'capture:' + capture_id
        state = self.rows(source, ids=('one',))
        self.assertFalse(state['rows'][0]['staged'])
        response = self.client.post('/api/ratings', json={'source': source, 'track_id': 'one', 'captured': 2, 'value': 5, 'edit_revision': state['edit_revision']}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual((metadata.read_bytes(), report.read_bytes()), before)
        self.assertEqual(self.rows(ids=('one',))['rows'][0]['value'], 4)

    def test_workspace_stars_need_no_capture_and_reject_old_workspace_revision(self):
        raw = {'rating': 2, 'track_id': 'one'}
        current = {'id': 'b' * 32, 'catalog': SimpleNamespace(tracks={'one': raw}),
                   'metadata': {}, 'decisions': {}, 'relocations': {}}
        application.sessions[current['id']] = current; application.active = current['id']
        source = 'session:' + current['id']; old = revision(current, self.root)
        before = deepcopy(raw); state = self.rows(source, ids=('one',))
        self.assertEqual(self.client.get('/api/ratings', query_string={'source': 'session:' + 'c' * 32, 'track_id': 'one'}).status_code, 409)
        response = self.client.post('/api/ratings', json={'source': source, 'track_id': 'one', 'captured': 2, 'value': 3, 'edit_revision': state['edit_revision']}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(raw, before); self.assertEqual(len(self.store.snapshots()), 1)
        stale = application.app.test_client().post('/api/ratings', json={'source': source, 'track_id': 'one', 'captured': 2, 'value': 5, 'edit_revision': response.json['edit_revision']}, headers={**self.headers, 'X-Workbench-Workspace': current['id'], 'X-Workbench-Revision': old})
        self.assertEqual(stale.status_code, 409)


if __name__ == '__main__':
    unittest.main()
