"""Explicit, source-scoped local audio mappings. Never rewrite captured/export paths."""
from hashlib import sha256
from itertools import islice
from pathlib import Path
import json
import os
import re
from urllib.parse import unquote, urlsplit

from flask import jsonify, request
from werkzeug.exceptions import Conflict
from workbench_store import Store

FIELDS = ('current_path', 'xml_location', 'original_path')


def recorded(value):
    if not isinstance(value, str) or not value or any(ord(c)<32 for c in value):
        return None
    if value.lower().startswith('file:'):
        try:parsed=urlsplit(value)
        except ValueError:return None
        if parsed.netloc.lower() not in ('','localhost') or parsed.query or parsed.fragment:
            return None
        value=unquote(parsed.path)
    value=value.replace('\\','/')
    if re.match(r'^/[A-Za-z]:/',value):value=value[1:]
    if any(ord(c)<32 for c in value) or value.startswith('//') or '..' in value.split('/'):
        return None
    windows=bool(re.match(r'^[A-Za-z]:/',value))
    if not windows and not value.startswith('/'):return None
    parts=[p for p in value.split('/') if p and p!='.']
    if len(parts)>64:return None
    if windows and any(':' in p for p in parts[1:]):return None
    return '/'.join(parts) if windows else '/'+ '/'.join(parts)


def signature(mappings):
    return sha256(json.dumps(mappings,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def mappings_for(store, snapshot):
    return store.setting('audio_paths:'+str(snapshot.get('scope_key','')),[])


def validate(mappings):
    if not isinstance(mappings,list) or len(mappings)>16:
        raise ValueError('Choose at most 16 local audio folders.')
    result=[];seen=set()
    for row in mappings:
        if not isinstance(row,dict):raise ValueError('Choose a recorded folder and a local folder.')
        prefix=recorded(row.get('recorded_root'))
        if prefix is None:raise ValueError('Enter an absolute recorded folder, such as D:/Music.')
        # Preserve drive roots as D:/; normalize only separators, not user spelling.
        if re.fullmatch('[A-Za-z]:',prefix):prefix+='/'
        raw=row.get('local_root')
        if not isinstance(raw,str) or not raw or any(ord(c)<32 for c in raw) or raw.startswith(('//','\\\\')):
            raise ValueError('Choose an existing local folder.')
        path=Path(raw).expanduser()
        if not path.is_absolute() or '..' in path.parts:
            raise ValueError('Choose an absolute local folder.')
        try:
            path=path.resolve(strict=True);stat=path.stat()
            if not path.is_dir():raise ValueError('The local audio folder must be a directory.')
        except OSError as error:raise ValueError('Connect the local audio folder before saving its mapping.') from error
        key=prefix.casefold() if re.match('^[A-Za-z]:',prefix) else prefix
        if key in seen:raise ValueError('A recorded folder can have only one local mapping.')
        seen.add(key)
        result.append({'recorded_root':prefix,'local_root':str(path),'device':stat.st_dev,'inode':stat.st_ino})
    return sorted(result,key=lambda row:(-len(row['recorded_root']),row['recorded_root']))


def mapped_path(value, mappings):
    value=recorded(value)
    if value is None:return None
    windows=bool(re.match('^[A-Za-z]:',value))
    compared=value.casefold() if windows else value
    for row in sorted(mappings or [],key=lambda r:-len(r.get('recorded_root',''))):
        prefix=row['recorded_root'].rstrip('/')
        match=prefix.casefold() if windows else prefix
        if compared!=match and not compared.startswith(match+'/'):continue
        root=Path(row['local_root'])
        try:
            stat=root.stat()
            # A disconnected/replaced mount must not be mistaken for the saved volume.
            if stat.st_dev!=row['device'] or stat.st_ino!=row['inode'] or not root.is_dir():return None
            path=root
            for part in value[len(prefix):].strip('/').split('/'):
                if not part:continue
                candidate=path/part
                if not candidate.exists() and windows and path.is_dir():
                    entries=list(islice(path.iterdir(),4097))
                    if len(entries)>4096:return None
                    matches=[p for p in entries if p.name.casefold()==part.casefold()]
                    if len(matches)>1:return None
                    if matches:candidate=matches[0]
                if candidate.is_symlink() or candidate.is_junction():return None
                path=candidate
            if not path.resolve().is_relative_to(root):return None
            return path
        except (OSError,RuntimeError,ValueError):
            return None
    return None


def inherit(store, old_scope, new_scope):
    rows=store.setting('audio_paths:'+old_scope,[])
    if rows:store.set_setting('audio_paths:'+new_scope,rows)


def register(owner):
    app=owner.app
    def store():return Store(owner.DATA/'workbench-sidecar.sqlite3')
    def snapshot(source):
        from collection_sources import resolve
        if isinstance(source,str) and source.startswith('session:'):
            session=owner.current()
            if source!='session:'+session['id']:raise Conflict('This workspace is no longer loaded.')
            source='workspace'
        return resolve(owner,source)
    def local():
        from file_health import local_request
        if not local_request():raise ValueError('Local audio mapping requires the local application.')
    def examples(s,rows):
        from track_playback import inspect_audio
        output=[]
        for track in s['tracks']:
            pairs=[(track.get(key),mapped_path(track.get(key),rows)) for key in FIELDS if track.get(key)]
            selected=next(((raw,path) for raw,path in pairs if path is not None),pairs[0] if pairs else None)
            if selected:
                output.append({'track_id':str(track['id']),'recorded':selected[0],
                               'local':str(selected[1]) if selected[1] is not None else None,
                               'status':inspect_audio(track,rows)[0]})
            if len(output)==8:break
        return output

    @app.get('/api/audio-paths')
    def get_paths():
        local();s=snapshot(request.args.get('source',''));saved=store();rows=mappings_for(saved,s)
        from discovery import mounted_roots
        mounts=mounted_roots()
        roots=[]
        for track in s['tracks'][:1000]:
            for key in FIELDS:
                value=recorded(track.get(key))
                if value and re.match('^[A-Za-z]:',value):
                    root=value[:2]+'/'
                    if root not in roots:roots.append(root)
        return jsonify(scope=s['scope_key'],mappings=rows,revision=signature(rows),
                       recorded_roots=roots,mounted_roots=mounts)

    @app.post('/api/audio-paths/preview')
    def preview_paths():
        local();b=request.get_json(silent=True) or {};s=snapshot(b.get('source',''))
        rows=validate(b.get('mappings'))
        return jsonify(examples=examples(s,rows),mappings=rows)

    @app.post('/api/audio-paths')
    def save_paths():
        local();b=request.get_json(silent=True) or {};s=snapshot(b.get('source',''));saved=store()
        rows=validate(b.get('mappings'))
        with owner.lock:
            if any(job.get('status')=='running' and job.get('file_health_scope')==s['scope_key'] for job in owner.tasks.values()):
                raise Conflict('Cancel or finish the File health scan before changing audio folders.')
            if b.get('revision')!=signature(mappings_for(saved,s)):
                raise Conflict('Audio folder mappings changed. Reload them before saving.')
            saved.set_setting('audio_paths:'+s['scope_key'],rows)
            with saved.connection() as db:
                sources=[s['scope_key'],*('snapshot:'+r[0] for r in db.execute('SELECT id FROM snapshots WHERE scope_key=?',(s['scope_key'],)))]
                for source in sources:
                    db.execute('DELETE FROM file_health_records WHERE source=?',(source,))
                    db.execute('DELETE FROM file_health_scans WHERE source=?',(source,))
                db.execute('DELETE FROM file_status_cache')
        return jsonify(scope=s['scope_key'],revision=signature(rows),mappings=rows,examples=examples(s,rows),
                       note='Local availability mappings saved. Re-scan File health and preview MusicBrainz again. Exported paths are unchanged.')
