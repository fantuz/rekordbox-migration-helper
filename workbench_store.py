"""Private SQLite working state. Never connects to the rekordbox database."""
from contextlib import contextmanager, closing
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from uuid import uuid4
from metadata_overrides import validate


def now():return datetime.now(timezone.utc).isoformat()
def encoded(value):return json.dumps(value,ensure_ascii=False,separators=(",",":"),allow_nan=False)


class Store:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connection() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY,label TEXT,created TEXT,source_kind TEXT,scope_key TEXT,digest TEXT,payload TEXT);
              CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY,kind TEXT,created TEXT,sources TEXT,summary TEXT);
              CREATE TABLE IF NOT EXISTS report_rows(report_id TEXT,ordinal INTEGER,section TEXT,severity TEXT,track_id TEXT,search_text TEXT,payload TEXT,PRIMARY KEY(report_id,ordinal));
              CREATE INDEX IF NOT EXISTS report_sections ON report_rows(report_id,section,ordinal);
              CREATE TABLE IF NOT EXISTS overrides(scope_key TEXT,track_id TEXT,field TEXT,value TEXT,baseline TEXT,origin TEXT,updated TEXT,PRIMARY KEY(scope_key,track_id,field));
              CREATE TABLE IF NOT EXISTS override_history(id TEXT PRIMARY KEY,scope_key TEXT,track_id TEXT,field TEXT,previous TEXT,current TEXT,created TEXT);
              CREATE TABLE IF NOT EXISTS settings(name TEXT PRIMARY KEY,value TEXT);
              CREATE TABLE IF NOT EXISTS mb_batches(id TEXT PRIMARY KEY,snapshot_id TEXT,created TEXT,status TEXT,summary TEXT,sample TEXT);
              CREATE TABLE IF NOT EXISTS mb_results(batch_id TEXT,track_id TEXT,status TEXT,payload TEXT,PRIMARY KEY(batch_id,track_id));
              CREATE TABLE IF NOT EXISTS mb_cache(key TEXT PRIMARY KEY,created REAL,expires REAL,payload TEXT);
            ''')

    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.path,timeout=30)) as db:
            db.row_factory=sqlite3.Row;db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA busy_timeout=30000')
            with db:yield db

    def snapshots(self):
        with self.connection() as db:return [dict(r) for r in db.execute('SELECT id,label,created,source_kind,scope_key,digest FROM snapshots ORDER BY created DESC LIMIT 100')]

    def save_snapshot(self,payload,label):
        payload=deepcopy(payload);identity=uuid4().hex;created=now()
        payload.update(id=identity,label=str(label).strip()[:160] or 'Library snapshot')
        raw=encoded(payload);digest=sha256(raw.encode()).hexdigest()
        with self.connection() as db:db.execute('INSERT INTO snapshots VALUES (?,?,?,?,?,?,?)',(identity,payload['label'],created,payload.get('source_kind'),payload.get('scope_key',identity),digest,raw))
        return {"id":identity,"label":payload['label'],"created":created,"tracks":len(payload['tracks']),"digest":digest}

    def snapshot(self,identity):
        with self.connection() as db:r=db.execute('SELECT payload FROM snapshots WHERE id=?',(identity,)).fetchone()
        if not r:raise ValueError('Choose a saved Library lab snapshot')
        return json.loads(r[0])

    def save_report(self,kind,sources,summary,rows):
        identity=uuid4().hex;created=now()
        with self.connection() as db:
            db.execute('INSERT INTO reports VALUES (?,?,?,?,?)',(identity,kind,created,encoded(sources),encoded(summary)))
            db.executemany('INSERT INTO report_rows VALUES (?,?,?,?,?,?,?)',[(identity,n,r.get('section','info'),r.get('severity','info'),str(r.get('track_id','')),str(r).casefold(),encoded(r)) for n,r in enumerate(rows)])
        return {"id":identity,"kind":kind,"created":created,"summary":summary,"rows":len(rows)}

    def reports(self):
        with self.connection() as db:return [{**dict(r),'summary':json.loads(r['summary']),'sources':json.loads(r['sources'])} for r in db.execute('SELECT * FROM reports ORDER BY created DESC LIMIT 50')]

    def report(self,identity,offset=0,section='',query='',all_rows=False):
        with self.connection() as db:
            report=db.execute('SELECT * FROM reports WHERE id=?',(identity,)).fetchone()
            if not report:raise ValueError('Report not found')
            where='report_id=?';params=[identity]
            if section:where+=' AND section=?';params.append(section)
            if query:where+=' AND instr(search_text,?)>0';params.append(query.casefold())
            count=db.execute('SELECT count(*) FROM report_rows WHERE '+where,params).fetchone()[0]
            sql='SELECT payload FROM report_rows WHERE '+where+' ORDER BY ordinal'
            if not all_rows:sql+=' LIMIT 50 OFFSET ?';params.append(max(0,int(offset)))
            rows=[json.loads(r[0]) for r in db.execute(sql,params)]
            facets=[dict(r) for r in db.execute('SELECT section,count(*) AS count FROM report_rows WHERE report_id=? GROUP BY section',(identity,))]
        return {**dict(report),'summary':json.loads(report['summary']),'sources':json.loads(report['sources']),'rows':rows,'total':count,'offset':max(0,int(offset)),'sections':facets}

    def overrides(self,scope):
        result={}
        with self.connection() as db:
            for row in db.execute('SELECT * FROM overrides WHERE scope_key=?',(scope,)):
                result.setdefault(row['track_id'],{})[row['field']]={'value':json.loads(row['value']),'baseline':json.loads(row['baseline']),'origin':row['origin'],'updated':row['updated']}
        return result

    def save_override(self,scope,track_id,field,value,baseline,origin='manual'):
        value=validate(field,value)
        with self.connection() as db:
            old=db.execute('SELECT value FROM overrides WHERE scope_key=? AND track_id=? AND field=?',(scope,track_id,field)).fetchone()
            db.execute('INSERT INTO override_history VALUES (?,?,?,?,?,?,?)',(uuid4().hex,scope,track_id,field,old[0] if old else None,encoded(value),now()))
            db.execute('INSERT OR REPLACE INTO overrides VALUES (?,?,?,?,?,?,?)',(scope,track_id,field,encoded(value),encoded(baseline),str(origin)[:120],now()))
        return value

    def save_bulk(self,snapshot,track_ids,field,value):
        value=validate(field,value);tracks={t['id']:t for t in snapshot['tracks']}
        if not 1<=len(track_ids)<=10000 or any(i not in tracks for i in track_ids):raise ValueError('Choose between 1 and 10,000 tracks in this snapshot')
        scope=snapshot['scope_key'];created=now()
        with self.connection() as db:
            for identity in set(track_ids):
                old=db.execute('SELECT value FROM overrides WHERE scope_key=? AND track_id=? AND field=?',(scope,identity,field)).fetchone()
                db.execute('INSERT INTO override_history VALUES (?,?,?,?,?,?,?)',(uuid4().hex,scope,identity,field,old[0] if old else None,encoded(value),created))
                db.execute('INSERT OR REPLACE INTO overrides VALUES (?,?,?,?,?,?,?)',(scope,identity,field,encoded(value),encoded(tracks[identity].get(field)),'manual normalization',created))
        return len(set(track_ids))

    def clear_override(self,scope,track_id,field):
        with self.connection() as db:
            old=db.execute('SELECT value FROM overrides WHERE scope_key=? AND track_id=? AND field=?',(scope,track_id,field)).fetchone()
            if old:db.execute('INSERT INTO override_history VALUES (?,?,?,?,?,?,?)',(uuid4().hex,scope,track_id,field,old[0],None,now()))
            db.execute('DELETE FROM overrides WHERE scope_key=? AND track_id=? AND field=?',(scope,track_id,field))

    def setting(self,name,default=None):
        with self.connection() as db:r=db.execute('SELECT value FROM settings WHERE name=?',(name,)).fetchone()
        return json.loads(r[0]) if r else default

    def set_setting(self,name,value):
        with self.connection() as db:db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(name,encoded(value)))

    def effective(self,snapshot):
        result=deepcopy(snapshot);overrides=self.overrides(snapshot['scope_key']);count=0
        for track in result['tracks']:
            for field,edit in overrides.get(track['id'],{}).items():track[field]=edit['value'];count+=1
        result['metadata_overrides_applied']=count
        return result
