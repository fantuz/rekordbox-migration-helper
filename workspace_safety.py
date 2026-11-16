"""Bind workspace requests to the collection and working state actually reviewed."""
from hashlib import sha256
import json
from uuid import uuid4
from contextlib import contextmanager
from copy import deepcopy
from flask import g, has_request_context, request
from werkzeug.exceptions import Conflict

class WorkspaceConflict(Conflict):
    """Distinguish stale workspace actions from scoped provider/scan conflicts."""


FIELDS = ('decisions', 'relocations', 'policy', 'backup_acknowledged', 'name',
          'held_pairs', 'batches', 'media_verifications', 'export_target')


def revision(session, data=None, edit_revision=None):
    # A fresh load is a new review context, even if it uses the same saved ID.
    generation = session.setdefault('_workspace_generation', uuid4().hex)
    state = {key: session.get(key) for key in FIELDS}
    state.update(generation=generation, scan=(session.get('inventory') or {}).get('scan_id'),
                 inputs=session.get('metadata', {}).get('pair_signature'))
    if edit_revision is None:
        from metadata_concurrency import saved_revision
        edit_revision=saved_revision(data/'workbench-sidecar.sqlite3','session:'+session['id']) if data is not None else '0'
    state['metadata_edits']=edit_revision
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
        raise WorkspaceConflict('The active workspace changed. Reload and review this action again.')
    identity = request.headers.get('X-Workbench-Workspace') or request.args.get('workspace')
    stamp = request.headers.get('X-Workbench-Revision')
    mutation = request.method in ('POST', 'PUT', 'PATCH', 'DELETE')
    if (mutation and not identity) or (identity and identity != session['id']):
        raise WorkspaceConflict('This action belongs to another workspace. Reload and review it again.')
    from metadata_concurrency import saved_revision
    edits=saved_revision(owner.DATA/'workbench-sidecar.sqlite3','session:'+session['id'])
    if mutation and (not stamp or stamp != revision(session,owner.DATA,edits)):
        raise WorkspaceConflict('The workspace changed since you reviewed it. Reload before applying this action.')
    g.workspace_session = session
    g.workspace_edit_revision = edits
    return session


def register(owner):
    @owner.app.after_request
    def workspace_response(response):
        session = getattr(g, 'workspace_session', None)
        if session is not None:
            response.headers['X-Workbench-Workspace'] = session['id']
            response.headers['X-Workbench-Revision'] = revision(session,owner.DATA,g.workspace_edit_revision)
        return response

    @owner.app.teardown_request
    def release_workspace_lock(error):
        if getattr(g, 'workspace_lock_held', False):
            g.workspace_lock_held = False
            owner.lock.release()


@contextmanager
def transaction(session):
    """Restore working state on failure; callers hold the workspace lock throughout."""
    before={key:value if key in ('catalog','inventory') else deepcopy(value) for key,value in session.items()}
    catalog=session.get('catalog')
    # Policy changes replace derived counts/descriptions. Preserve their original objects.
    derived=vars(catalog).copy() if catalog is not None else None
    try:
        yield
    except Exception:
        # A response-rendering error after a successful save must not undo RAM only.
        if session.get('_state_commit')!=before.get('_state_commit'):
            raise
        session.clear();session.update(before)
        if derived is not None:
            vars(catalog).clear();vars(catalog).update(derived)
        raise
