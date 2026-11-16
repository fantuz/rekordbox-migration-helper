"""Current review context for single-client fixtures; stale-client tests use raw clients."""
from flask.testing import FlaskClient
from workspace_safety import revision

def workspace_client(owner):
    class WorkspaceClient(FlaskClient):
        def open(self, *args, **kwargs):
            headers = dict(kwargs.get('headers') or {})
            session = owner.sessions.get(owner.active)
            if session:
                headers.setdefault('X-Workbench-Workspace', session['id'])
                headers.setdefault('X-Workbench-Revision', revision(session,owner.DATA))
            kwargs['headers'] = headers
            path=str(args[0]) if args else str(kwargs.get('path',''))
            body=kwargs.get('json')
            if isinstance(body,dict) and (path in ('/api/lab/overrides','/api/lab/normalize') or
                    path.startswith('/api/lab/musicbrainz/') and path.rsplit('/',1)[-1] in ('stage','review','release','candidate')):
                from workbench_store import Store
                saved=Store(owner.DATA/'workbench-sidecar.sqlite3')
                identity=body.get('snapshot')
                if not identity:
                    with saved.connection() as db:
                        row=db.execute('SELECT snapshot_id FROM mb_batches WHERE id=?',(path.split('/')[4],)).fetchone()
                        identity=row[0] if row else None
                if identity:
                    scope=saved.snapshot(identity)['scope_key']
                    kwargs['json']={**body,'edit_revision':body.get('edit_revision',saved.edit_state(scope)['edit_revision'])}
            return super().open(*args, **kwargs)
    return WorkspaceClient(owner.app, owner.app.response_class)
