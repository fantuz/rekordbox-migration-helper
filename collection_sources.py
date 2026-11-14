"""Resolve captured collections without opening a user's original database."""
import json
import re

from research_capture import capture_workspace
from workbench_store import Store


def resolve(owner, source):
    if source == 'workspace':
        session = owner.current()
        result = capture_workspace(session['catalog'], 'session:' + session['id'])
        result.update(label=session['name'], captured=None)
        return result
    if isinstance(source, str) and source.startswith('snapshot:'):
        return Store(owner.DATA / 'workbench-sidecar.sqlite3').snapshot(source[9:])
    if isinstance(source, str) and re.fullmatch(r'capture:[a-f0-9]{32}', source):
        folder = owner.DATA / 'analyzers' / source[8:]
        if folder.is_symlink():
            raise ValueError('Choose an ordinary saved capture')
        path = folder / 'comparison.json'
        if not path.is_file():
            path = folder / 'metadata.json'
        report_path = folder / 'report.json'
        if path.is_file() and report_path.is_file() and not path.is_symlink() and not report_path.is_symlink():
            result = json.loads(path.read_text(encoding='utf-8'))
            report = json.loads(report_path.read_text(encoding='utf-8'))
            result.update(scope_key=source, source_capture=source[8:], captured=report.get('created'),
                          label=report.get('format', 'Saved source capture'))
            return result
    raise ValueError('Choose a loaded workspace or saved collection snapshot')


def history_source(owner, values):
    source = values.get('source')
    if not source:
        identity = values.get('snapshot', '')
        source = identity if str(identity).startswith('capture:') else 'snapshot:' + str(identity)
    return resolve(owner, source)


def source_report(owner, snapshot):
    identity = str(snapshot.get('source_capture') or '')
    if re.fullmatch('[a-f0-9]{32}', identity):
        path = owner.DATA / 'analyzers' / identity / 'report.json'
        if path.is_file() and not path.is_symlink():
            return json.loads(path.read_text(encoding='utf-8'))
    return {}
