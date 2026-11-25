"""Preview one native grid change and download analysis copies from a paired desktop backup."""
from contextlib import closing
from hashlib import md5, sha256
from hmac import compare_digest
import json
import re
import stat
import tempfile
import zipfile
import zlib

from flask import jsonify, request, send_file
from werkzeug.exceptions import Conflict

from backup_manifest import analysis_member
from engine import open_master
from file_health import local_request
from file_workflow import archive_index_digest, check_inputs
from native_grid import MAX_FILE_BYTES, MAX_SET_BYTES, plan_grid_nudge
from workspace_safety import WorkspaceConflict

EXTENSIONS = {'DAT', 'EXT', '2EX', '3EX'}
DAT_NAME = re.compile(r'ANLZ[0-9A-F]{4}\.DAT', re.ASCII | re.IGNORECASE)
PAGE_SIZE = 50


def _read_siblings(archive, reference):
    directory, dat_name = reference.rsplit('/', 1)
    stem = dat_name[:-4]
    # Compare complete anchored paths. Every track can have a file named ANLZ0000.DAT.
    members = {}
    physical_dir = None
    total = 0
    for info in archive.infolist():
        path = info.filename.replace('\\', '/')
        folder, _, name = path.rstrip('/').rpartition('/')
        if not name.casefold().startswith(stem + '.'):
            continue
        folded = folder.casefold()
        if folded != directory and not folded.endswith('/' + directory):
            continue
        if ((physical_dir is not None and folder != physical_dir)
                or info.orig_filename.replace('\\', '/') != path or ':' in path
                or any(part in ('', '.', '..') for part in path.split('/'))
                or stat.S_ISLNK(info.external_attr >> 16)):
            raise ValueError('Ambiguous, linked or unsafe analysis companion path in the backup')
        # The desktop importer accepts archives with wrapper directories before PIONEER.
        if folded != directory and not ('/' + folded).endswith('/pioneer/' + directory):
            raise ValueError('Unrecognized analysis directory prefix in this backup')
        physical_dir = folder
        suffix = name[len(stem) + 1:].upper()
        if suffix not in EXTENSIONS or suffix in members:
            raise ValueError('Unknown or duplicate same-name analysis companion in the backup')
        total += info.file_size
        if info.file_size > MAX_FILE_BYTES or total > MAX_SET_BYTES:
            raise ValueError('Analysis file set exceeds the size limit')
        members[suffix] = info
    if 'DAT' not in members:
        raise ValueError('The backup does not contain the selected track’s DAT')
    files = {}
    for suffix, info in members.items():
        with archive.open(info) as stream:
            data = stream.read(info.file_size + 1)
        if len(data) != info.file_size:
            raise ValueError('The analysis member size differs from the ZIP directory')
        files[suffix] = data
    return files


def _registration_proof(master, track_id, reference, files):
    """Check the private import DB. Never follow a native registered local filesystem path."""
    if not master.is_file():
        raise ValueError('Reopen the paired workspace to restore its temporary database copy')
    with closing(open_master(master.resolve())) as db:
        paths = db.execute('SELECT AnalysisDataPath FROM djmdContent WHERE ID=? AND rb_local_deleted=0',
                           (track_id,)).fetchall()
        if len(paths) != 1 or analysis_member(paths[0][0]) != reference:
            raise ValueError('Native track ownership no longer matches the selected catalog track')
        columns = {r[1].casefold() for r in db.execute('PRAGMA table_info(contentFile)')}
        if not columns:
            return None
        if not {'contentid', 'path', 'hash', 'size', 'rb_local_deleted'} <= columns:
            raise ValueError('The native file registration schema cannot establish analysis-file ownership')

        # Include registrations by other tracks with the same anchored native path, also when
        # a prefix, backslash or case differs. Do not transfer the entire registry into Python.
        stem = reference[:-4]
        rows = db.execute("""SELECT ContentID,Path,Size,Hash FROM contentFile
            WHERE rb_local_deleted=0 AND (ContentID=? OR
            instr('/' || lower(replace(Path,char(92),'/')),?)>0)""", (track_id, '/' + stem + '.'))
        registered = set()
        for owner, path, size, checksum in rows:
            normalized = analysis_member(path)
            if normalized is None or normalized.rsplit('.', 1)[0] != stem:
                # Adjacent audio/artwork registrations are unrelated to this analysis set.
                if str(owner) == track_id and '/usbanlz/' in ('/' + str(path).replace('\\', '/').casefold()):
                    raise ValueError('A native analysis registration is outside the recognized sibling set')
                continue
            suffix = normalized.rsplit('.', 1)[1].upper()
            if str(owner) != track_id or suffix in registered:
                raise ValueError('More than one native file registration claims an analysis companion')
            if suffix not in files:
                raise ValueError('A registered analysis companion is missing from the backup')
            data = files[suffix]
            if size != len(data) or str(checksum).lower() != md5(data, usedforsecurity=False).hexdigest():
                raise ValueError('Analysis bytes differ from their registered size or checksum')
            registered.add(suffix)
    return sha256(files['3EX']).hexdigest() if '3EX' in registered else None


def _plan(owner, session, body):
    offset = body.get('offset_ms')
    if type(offset) is not int or offset not in (-1, 1):
        raise ValueError('Choose a whole-grid nudge of −1 or +1 ms')
    track_id = body.get('track_id')
    tracks = session['catalog'].tracks
    if not isinstance(track_id, str) or track_id not in tracks:
        raise ValueError('Select a track from the active paired workspace')
    track = tracks[track_id]
    reference = analysis_member(track.get('analysis_path'))
    if not reference or not DAT_NAME.fullmatch(reference.rsplit('/', 1)[-1]):
        raise ValueError('This track has no recognized native DAT reference')
    if any(other_id != track_id and analysis_member(other.get('analysis_path')) == reference
           for other_id, other in tracks.items()):
        raise ValueError('Multiple catalog tracks claim this analysis file')

    metadata = session['metadata']
    captured_index = (metadata.get('pair_signature') or {}).get('archive_index_sha256')
    if not captured_index:
        raise ValueError('Reopen the paired workspace to verify its source backup')
    check_inputs(metadata)
    try:
        with zipfile.ZipFile(metadata['zip_path']) as archive:
            if archive_index_digest(archive) != captured_index:
                raise ValueError('The backup directory changed since import. Reimport the pair.')
            files = _read_siblings(archive, reference)
    except (zipfile.BadZipFile, EOFError, RuntimeError, OSError, zlib.error) as exc:
        raise ValueError('Could not verify the selected analysis files in the backup') from exc
    master = owner.TEMPORARY.path / session['id'] / 'master.db'
    from sqlcipher3 import dbapi2 as cipher
    try:
        registration = _registration_proof(master, track_id, reference, files)
    except cipher.DatabaseError as exc:
        raise ValueError('Could not verify analysis ownership in the temporary database. Reopen the paired workspace.') from exc
    changes, facts = plan_grid_nudge(files, offset, track_id=track_id, registered_embedding_sha256=registration)
    check_inputs(metadata)
    stem = reference.rsplit('/', 1)[-1][:-4].upper()
    outputs = {stem + '.' + suffix: changes.get(suffix, files[suffix]) for suffix in sorted(files)}
    manifest = []
    digests = []
    for suffix in sorted(files):
        name = stem + '.' + suffix
        manifest.append(dict(name=name, before_bytes=len(files[suffix]), after_bytes=len(outputs[name]),
                             changed=suffix in changes))
        before = sha256(files[suffix]).hexdigest()
        after = sha256(outputs[name]).hexdigest() if suffix in changes else before
        digests.append((name, before, after))
    identity = [session['id'], session.get('_workspace_generation'), captured_index, track_id, reference, offset, digests]
    proof = sha256(json.dumps(identity, separators=(',', ':')).encode()).hexdigest()
    return dict(session_id=session['id'], track_id=track_id, title=track.get('title') or '',
                offset_ms=offset, proof=proof, files=manifest, **facts), outputs


def register(owner):
    def context(values):
        if not local_request():
            raise ValueError('Use the local application to review a grid nudge')
        session = owner.current()
        if not isinstance(values, dict) or values.get('session_id') != session['id']:
            raise WorkspaceConflict('Select the current paired workspace before reviewing its grid')
        return session

    @owner.app.get('/api/lab/grid-nudge/tracks')
    def grid_nudge_tracks():
        session = context(request.args.to_dict())
        query = request.args.get('q', '').strip().casefold()
        if len(query) > 200:
            raise ValueError('Use a search of at most 200 characters')
        rows = []
        for identity, track in session['catalog'].tracks.items():
            path = (track.get('analysis_path') or '').replace('\\', '/')
            if not DAT_NAME.fullmatch(path.rsplit('/', 1)[-1]):
                continue
            row = dict(id=identity, title=track.get('title') or '', artist=track.get('artist') or '')
            if any(query in value.casefold() for value in row.values()):
                rows.append(row)
            if len(rows) > PAGE_SIZE:
                break
        return jsonify(session_id=session['id'], tracks=rows[:PAGE_SIZE], has_more=len(rows) > PAGE_SIZE)

    @owner.app.post('/api/lab/grid-nudge/preview')
    def grid_nudge_preview():
        body = request.get_json(silent=True)
        summary, _ = _plan(owner, context(body), body)
        return jsonify(summary)

    @owner.app.post('/api/lab/grid-nudge/download')
    def grid_nudge_download():
        body = request.get_json(silent=True)
        session = context(body)
        proof = body.get('proof')
        if not isinstance(proof, str) or not re.fullmatch('[a-f0-9]{64}', proof):
            raise ValueError('Preview this grid nudge before downloading it')
        summary, outputs = _plan(owner, session, body)
        if not compare_digest(summary['proof'], proof):
            raise Conflict('The track, nudge or source bytes changed. Preview the grid nudge again.')
        # Large sets spill to a temporary file. The response closes it when streaming ends.
        output = tempfile.SpooledTemporaryFile(max_size=4 * 1024**2)
        try:
            with zipfile.ZipFile(output, 'w') as archive:
                for name, data in outputs.items():
                    archive.writestr(name, data)
            output.seek(0)
            return send_file(output, mimetype='application/zip', as_attachment=True,
                             download_name='analysis-grid-nudge.zip')
        except Exception:
            output.close()
            raise
