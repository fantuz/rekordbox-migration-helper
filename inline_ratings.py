"""Bounded personal-star edits in the existing private metadata sidecar.

Only captured metadata is read. No cloud request, audio access, library mutation
or implicit snapshot creation is needed to edit the stars in a displayed row.
"""
from flask import jsonify, request
from werkzeug.exceptions import Conflict

from collection_sources import resolve
from metadata_export import track
from metadata_overrides import comparable
from workbench_store import Store


def register(owner):
    def selected(source, identities):
        if not isinstance(source, str):
            raise ValueError('Choose a loaded workspace or saved collection snapshot')
        if source == 'workspace' or source.startswith('session:'):
            session = owner.current()
            if source not in ('workspace', 'session:' + session['id']):
                raise Conflict('This action belongs to another workspace. Reload and review it again.')
            # Select only displayed IDs; do not recapture all cues/playlists.
            rows = {identity: track({'id': identity, 'rating': session['catalog'].tracks[identity].get('rating')})
                    for identity in identities if identity in session['catalog'].tracks}
            scope = 'session:' + session['id']
        else:
            snapshot = resolve(owner, source)
            scope = snapshot['scope_key']
            rows = {str(row['id']): row for row in snapshot['tracks'] if str(row['id']) in identities}
        if any(identity not in rows for identity in identities):
            raise ValueError('Choose a track in this collection')
        return scope, rows

    def describe(identity, row, state):
        edit = state['overrides'].get(identity, {}).get('rating')
        return {'track_id': identity, 'captured': row.get('rating'),
                'value': edit['value'] if edit else row.get('rating'), 'staged': edit is not None}

    @owner.app.get('/api/ratings')
    def ratings():
        identities = list(dict.fromkeys(request.args.getlist('track_id')))
        if not 1 <= len(identities) <= 100:
            raise ValueError('Choose between 1 and 100 displayed tracks')
        scope, rows = selected(request.args.get('source', ''), identities)
        state = Store(owner.DATA / 'workbench-sidecar.sqlite3').edit_state(scope)
        return jsonify(scope=scope, edit_revision=state['edit_revision'],
                       rows=[describe(identity, rows[identity], state) for identity in identities])

    @owner.app.route('/api/ratings', methods=['POST', 'DELETE'])
    def rating_edit():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValueError('Provide a JSON object')
        identity = str(body.get('track_id', ''))
        scope, rows = selected(body.get('source', ''), [identity])
        original = rows[identity].get('rating')
        if 'captured' not in body or comparable('rating', body['captured']) != comparable('rating', original):
            raise Conflict('Metadata baseline changed; reload this collection before editing stars.')
        saved = Store(owner.DATA / 'workbench-sidecar.sqlite3')
        if request.method == 'DELETE':
            state = saved.clear_override(scope, identity, 'rating', expected_revision=body.get('edit_revision'))
        else:
            state = saved.save_override(scope, identity, 'rating', body.get('value'), original,
                                        expected_revision=body.get('edit_revision'))
        return jsonify(scope=scope, edit_revision=state['edit_revision'], **describe(identity, rows[identity], state))
