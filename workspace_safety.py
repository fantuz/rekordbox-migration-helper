"""Bind workspace requests to the collection and working state actually reviewed."""
from hashlib import sha256
import json
from uuid import uuid4
from flask import g, has_request_context, request
from werkzeug.exceptions import Conflict

FIELDS = ('decisions', 'relocations', 'policy', 'backup_acknowledged', 'name',
          'held_pairs', 'batches', 'media_verifications')


def revision(session):
    # A fresh load is a new review context, even if it uses the same saved ID.
    generation = session.setdefault('_workspace_generation', uuid4().hex)
    state = {key: session.get(key) for key in FIELDS}
    state.update(generation=generation, scan=(session.get('inventory') or {}).get('scan_id'),
                 inputs=session.get('metadata', {}).get('pair_signature'))
    return sha256(json.dumps(state, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':'), default=str).encode()).hexdigest()


def require(owner, session):
    if not has_request_context():
        return session
    if not getattr(g, 'workspace_lock_held', False):
        owner.lock.acquire()
        g.workspace_lock_held = True
    # Validate after taking the lock, not against a pre-lock global selection.
    if owner.active != session['id'] or owner.sessions.get(owner.active) is not session:
        raise Conflict('The active workspace changed. Reload and review this action again.')
    identity = request.headers.get('X-Workbench-Workspace') or request.args.get('workspace')
    stamp = request.headers.get('X-Workbench-Revision')
    mutation = request.method in ('POST', 'PUT', 'PATCH', 'DELETE')
    if (mutation and not identity) or (identity and identity != session['id']):
        raise Conflict('This action belongs to another workspace. Reload and review it again.')
    if mutation and (not stamp or stamp != revision(session)):
        raise Conflict('The workspace changed since you reviewed it. Reload before applying this action.')
    g.workspace_session = session
    return session


def register(owner):
    @owner.app.after_request
    def workspace_response(response):
        session = getattr(g, 'workspace_session', None)
        if session is not None:
            response.headers['X-Workbench-Workspace'] = session['id']
            response.headers['X-Workbench-Revision'] = revision(session)
        return response

    @owner.app.teardown_request
    def release_workspace_lock(error):
        if getattr(g, 'workspace_lock_held', False):
            g.workspace_lock_held = False
            owner.lock.release()
