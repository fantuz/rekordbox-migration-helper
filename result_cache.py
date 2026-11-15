"""Bounded derived JSON cache; original libraries and live scans are never cached."""
from functools import wraps
from hashlib import sha256
import json
import re
import time
from flask import request,make_response
from workbench_store import Store,encoded

MAX_BYTES=16*1024**2
MAX_ENTRIES=64
SCHEMA='collection-results-v1'


def file_stamp(path):
    if not path.is_file() or path.is_symlink():return None
    s=path.stat()
    return (path.name,s.st_size,s.st_mtime_ns,s.st_ino)


def signature(owner,source):
    try:
        saved=Store(owner.DATA/'workbench-sidecar.sqlite3')
        if source.startswith('snapshot:'):
            with saved.connection() as db:
                row=db.execute("SELECT digest,json_extract(payload,'$.source_capture') FROM snapshots WHERE id=?",(source[9:],)).fetchone()
            if row is None:return None
            report=file_stamp(owner.DATA/'analyzers'/row[1]/'report.json') if isinstance(row[1],str) and re.fullmatch('[a-f0-9]{32}',row[1]) else None
            return [row[0],report]
        if re.fullmatch(r'capture:[a-f0-9]{32}',source):
            root=owner.DATA/'analyzers'/source[8:]
            if root.is_symlink() or root.is_junction():return None
            files=[root/'comparison.json' if (root/'comparison.json').is_file() else root/'metadata.json',root/'report.json']
            stamps=[file_stamp(p) for p in files]
            return stamps if all(stamps) else None
    except OSError:
        # Let the normal source reader report unavailable or changing evidence.
        return None
    return None


def connection(owner):
    saved=Store(owner.DATA/'workbench-sidecar.sqlite3')
    with saved.connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS result_cache(key TEXT PRIMARY KEY,created REAL,payload TEXT)')
    return saved.connection()


def cached_collection(owner):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args,**kwargs):
            source=request.args.get('source','');stamp=signature(owner,source)
            if stamp is None:return fn(*args,**kwargs)
            saved=Store(owner.DATA/'workbench-sidecar.sqlite3')
            decisions=saved.setting('duplicate_reviews:'+source,{}) if '/duplicates' in request.path else None
            key=sha256(encoded([SCHEMA,request.path,sorted(request.args.items(multi=True)),stamp,decisions]).encode()).hexdigest()
            now=time.time()
            with connection(owner) as db:row=db.execute('SELECT payload FROM result_cache WHERE key=? AND created>?',(key,now-7*86400)).fetchone()
            if row:
                response=owner.app.response_class(row[0],mimetype='application/json');response.headers['X-Workbench-Cache']='hit';return response
            response=make_response(fn(*args,**kwargs))
            if response.status_code==200 and response.mimetype=='application/json' and signature(owner,source)==stamp and (decisions is None or saved.setting('duplicate_reviews:'+source,{})==decisions):
                raw=response.get_data(as_text=True)
                if len(raw.encode())<=MAX_BYTES:
                    with connection(owner) as db:
                        db.execute('INSERT OR REPLACE INTO result_cache VALUES (?,?,?)',(key,now,raw))
                        db.execute('DELETE FROM result_cache WHERE created<?',(now-7*86400,))
                        rows=db.execute('SELECT key,length(CAST(payload AS BLOB)) AS size FROM result_cache ORDER BY created DESC').fetchall()
                        used=0
                        for n,row in enumerate(rows):
                            used+=row['size']
                            if n>=MAX_ENTRIES or used>MAX_BYTES:db.execute('DELETE FROM result_cache WHERE key=?',(row['key'],))
            response.headers['X-Workbench-Cache']='miss';return response
        return wrapped
    return decorate


def clear(owner,providers=False):
    with connection(owner) as db:
        db.execute('DELETE FROM result_cache')
        db.execute('DELETE FROM file_status_cache')
        if providers:db.execute('DELETE FROM mb_cache')
    for name in ('clear_insight_cache','clear_chart_cache'):
        callback=getattr(owner,name,None)
        if callback:callback()
