"""Explicit current-workspace context for existing single-client API fixtures."""
from flask.testing import FlaskClient
from workspace_safety import revision

def workspace_client(owner):
    class WorkspaceClient(FlaskClient):
        def open(self, *args, **kwargs):
            headers = dict(kwargs.get('headers') or {})
            session = owner.sessions.get(owner.active)
            if session:
                headers.setdefault('X-Workbench-Workspace', session['id'])
                headers.setdefault('X-Workbench-Revision', revision(session))
            kwargs['headers'] = headers
            return super().open(*args, **kwargs)
    return WorkspaceClient(owner.app, owner.app.response_class)
