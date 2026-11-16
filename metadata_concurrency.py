"""Persistent revisions for staged metadata, including resets and provider edits."""
from contextlib import closing
import sqlite3
from werkzeug.exceptions import Conflict


def revision(db, scope):
    row = db.execute('SELECT revision FROM override_revisions WHERE scope_key=?', (scope,)).fetchone()
    return str(row[0]) if row else '0'


def require_revision(db, scope, expected):
    if not isinstance(expected, str) or expected != revision(db, scope):
        raise Conflict('Staged metadata changed. Reload and review the current edits before saving or resetting them.')


def saved_revision(path, scope):
    # Reading workspace status must not create a sidecar just to obtain revision zero.
    if not path.is_file():
        return '0'
    with closing(sqlite3.connect(path, timeout=30)) as db:
        if not db.execute("SELECT 1 FROM sqlite_schema WHERE name='override_revisions'").fetchone():
            return '0'
        return revision(db, scope)
