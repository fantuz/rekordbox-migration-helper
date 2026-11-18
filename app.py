"""Run with .venv/bin/python app.py. Open http://127.0.0.1:8765."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import copy, deepcopy
from datetime import datetime, timezone
from pathlib import Path
from hashlib import sha256
from threading import RLock
from functools import wraps
from uuid import uuid4
from time import monotonic
import argparse
import json
import os
import secrets
import sqlite3
import sys

from report_files import save_json
from flask import Flask, g, has_request_context, jsonify, request, send_file, send_from_directory
from engine import Catalog, analyze, enrich_usage, decision_map, export_xml
from native_export import export_native
from media import scan as scan_media, verify_pair
from file_workflow import select_inputs, fingerprint_inputs, check_inputs, prepare_export, list_exports,pair_signature
from analyzer import analyze_folder, COMPATIBILITY, source_stamps
from platform_paths import default_data_directory, discover_cloud_roots, database_names
from discovery import suggestions as discover_locations,scan_roots as discover_scan
from storage_audit import scan_storage, verify_group
from metadata_export import capture_catalog, export_metadata, list_metadata_exports
from task_control import TaskControl, OperationCancelled
import localization
import documentation
from workspace_safety import transaction

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
DATA = Path(os.environ.get("LIBRARY_WORKBENCH_DATA_DIR",str(default_data_directory(ROOT)))).expanduser().resolve()
DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
from temporary_files import TemporaryWorkspace
from shutdown_cleanup import ShutdownController
TEMPORARY=TemporaryWorkspace(DATA)
INPUTS=DATA/"inputs"
INPUTS.mkdir(exist_ok=True)
app = Flask(__name__, static_folder="static")
app.config.update(MAX_CONTENT_LENGTH=48*1024**3, TRUSTED_HOSTS=["127.0.0.1","localhost"])
localization.register(app,ROOT/'static')
documentation.register(app)
TOKEN = secrets.token_urlsafe(32)
executor = ThreadPoolExecutor(max_workers=1)
lock = RLock()
sessions, tasks = {}, {}
task_controls = {}
active = None
MAX_COMPLETED_TASKS=256
TASK_RETENTION_SECONDS=3600


def prune_tasks():
    """Bound terminal results; active jobs and persisted reports stay available."""
    now=monotonic()
    with lock:
        completed=sorted((task.setdefault('_completed_at',now),identity)
                         for identity,task in tasks.items() if task['status']!='running' and identity not in task_controls)
        for index,(finished,identity) in enumerate(completed):
            if now-finished>TASK_RETENTION_SECONDS or index<len(completed)-MAX_COMPLETED_TASKS:
                tasks.pop(identity,None)


def clean_provider_cache():
    path=DATA/'workbench-sidecar.sqlite3'
    if path.is_file():
        with closing(sqlite3.connect(path,timeout=30)) as db:
            if not db.execute("SELECT 1 FROM sqlite_schema WHERE name='mb_cache'").fetchone():return
            db.execute('DELETE FROM mb_cache');db.commit();db.execute('VACUUM');db.execute('PRAGMA wal_checkpoint(TRUNCATE)')


shutdown=ShutdownController(TEMPORARY,lambda:cancel_lab_jobs(),clean_provider_cache,lambda:app.config['SHUTDOWN_CALLBACK']())
app.config['REQUEST_SHUTDOWN']=shutdown.request


def application_version():
    candidates=[ROOT/"VERSION",ROOT.parent/"VERSION"]
    if getattr(sys,"frozen",False):candidates.insert(0,Path(sys.executable).parent.parent/"Resources/VERSION")
    for path in candidates:
        if path.is_file():return path.read_text(encoding="utf-8").strip()
    return "development"


def persist(session):
    dest = DATA / session["id"] / "state.json"
    dest.parent.mkdir(parents=True,exist_ok=True)
    payload = {k:v for k,v in session.items() if k not in ("catalog","inventory","_state_commit")}
    temp = dest.with_suffix(".tmp")
    try:
        temp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
        os.replace(temp,dest)
        session['_state_commit']=uuid4().hex
    finally:
        try:temp.unlink(missing_ok=True)
        except OSError:pass


def log(session, text):
    with lock, transaction(session):
        session["events"].append({"time":datetime.now(timezone.utc).isoformat(),"text":text})
        persist(session)


def atomic_workspace(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        with lock:
            with transaction(current()):return view(*args,**kwargs)
    return wrapped


def task_progress(job, amount, text):
    if shutdown.requested.is_set():raise InterruptedError('Stopping: temporary analysis copies are being cleaned')
    task_controls[job].checkpoint(amount)
    with lock:
        tasks[job].update(progress=amount,message=text)


def launch(work, message, pool=None, on_finished=None, cancel_event=None):
    job = uuid4().hex
    with lock:
        if shutdown.requested.is_set():raise ValueError('The application is stopping')
        prune_tasks()
        tasks[job] = {"id":job,"status":"running","progress":0,"message":message}
        task_controls[job] = TaskControl()
        if cancel_event is not None:task_controls[job].event=cancel_event
    def run():
        try:
            task_controls[job].checkpoint()
            with TEMPORARY.operation():result=work(lambda n,s:task_progress(job,n,s))
            with lock:
                tasks[job].update(status="complete",progress=100,result=result,message="Complete")
        except OperationCancelled as error:
            with lock:
                tasks[job].update(status="cancelled",message=str(error))
        except Exception as error:
            with lock:
                tasks[job].update(status="error",message=str(error),progress=0)
        finally:
            try:
                # Also notify owners when cancellation happens before work starts.
                if on_finished:on_finished(tasks[job]['status'])
            finally:
                with lock:
                    task_controls.pop(job,None)
                    tasks[job]['_completed_at']=monotonic()
                    prune_tasks()
    try:(pool or executor).submit(run)
    except Exception:
        with lock:tasks.pop(job,None);task_controls.pop(job,None)
        raise
    return job


def load_session(metadata, sid, progress):
    global active
    metadata=deepcopy(metadata)
    metadata["input_fingerprints"]=check_inputs(metadata,content=True,progress=progress)
    catalog=Catalog(metadata["source"],metadata)
    session_dir=DATA/sid
    session_dir.mkdir(parents=True,exist_ok=True)
    enrich_usage(catalog,Path(metadata["zip_path"]),TEMPORARY.folder(sid),progress)
    if not metadata.get('pair_signature'):metadata['pair_signature']=pair_signature(Path(metadata['zip_path']),Path(metadata['xml_path']),metadata.get('xml_sha256'),TEMPORARY.folder(sid)/'master.db')
    state=session_dir/"state.json"
    saved=json.loads(state.read_text(encoding="utf-8")) if state.exists() else {}
    inventory=saved.get("inventory")
    if saved.get("inventory_path") and Path(saved["inventory_path"]).is_file():
        inventory=json.loads(Path(saved["inventory_path"]).read_text(encoding="utf-8"))
    catalog.policy=saved.get("policy","newest")
    catalog.refresh_counts()
    session={"id":sid,"_workspace_generation":uuid4().hex,"metadata":metadata,"catalog":catalog,"decisions":saved.get("decisions",{}),
             "export_target":saved.get("export_target","auto"),"relocations":saved.get("relocations",{}),"events":saved.get("events",[]),"policy":catalog.policy,"last_batch":saved.get("last_batch",[]),"batches":saved.get("batches",[]),"held_pairs":saved.get("held_pairs",{}),"inventory":inventory,"inventory_path":saved.get("inventory_path"),"name":saved.get("name",metadata["name"]),"media_verifications":saved.get("media_verifications",{}),"backup_acknowledged":saved.get("backup_acknowledged")}
    with lock:
        log(session,f"Loaded {len(catalog.tracks):,} tracks and {len(catalog.pairs):,} candidate pairs")
        sessions[sid]=session
        active=sid
    return {"session":sid}


def current():
    with lock:
        if not active or active not in sessions:
            raise ValueError("Load a backup and XML first")
        from workspace_safety import require
        return require(sys.modules[__name__], sessions[active])


def summary(session,metadata_state=None):
    decisions=session["decisions"]
    from workbench_store import Store
    if metadata_state is None:
        metadata_state=Store(DATA/'workbench-sidecar.sqlite3').edit_state('session:'+session['id']) if (DATA/'workbench-sidecar.sqlite3').is_file() else {'overrides':{},'edit_revision':'0'}
    fields=metadata_state['overrides']
    from workspace_safety import revision
    from export_references import target_info
    stamp=metadata_state['edit_revision']
    if has_request_context() and request.method!='GET' and getattr(g,'workspace_session',None) is session:
        stamp=g.workspace_edit_revision
    return {"id":session["id"],"revision":revision(session,DATA,stamp),"name":session.get("name",session["metadata"]["name"]),"metadata":session["metadata"],"counts":session["catalog"].counts,
            "export_reference":target_info(session["catalog"],session.get("export_target","auto")),
            "metadata_override_fields":sum(len(v) for v in fields.values()),
            "metadata_override_tracks":len(fields),"metadata_override_by_field":{f:sum(f in v for v in fields.values()) for f in {f for v in fields.values() for f in v}},
            "policy":session["policy"],"backup_acknowledged":session.get("backup_acknowledged"),"staged":sum(d["action"]=="merge" for d in decisions.values()),
            "skipped":sum(d["action"]=="skip" for d in decisions.values()),
            "relocations":len(session["relocations"]),"events":session["events"][-60:]}


def configured_example():
    path=Path(os.environ.get("LIBRARY_WORKBENCH_EXAMPLE",str(DATA/"example.json")))
    try:
        metadata=json.loads(path.read_text(encoding="utf-8"))
        if all(Path(metadata[key]).is_file() for key in ("source","zip_path","xml_path")):
            return {**metadata,"import_mode":"example"}
    except (OSError,ValueError,KeyError):pass
    return None


@app.before_request
def protect():
    if shutdown.requested.is_set() and request.path not in ('/api/cleanup','/api/desktop/stop','/api/status') and not request.path.startswith('/api/tasks/'):
        return jsonify(error='The app is stopping and cleaning its temporary copies'),503
    if request.method in ("POST","PUT","PATCH","DELETE") and request.headers.get("X-Workbench-Token")!=TOKEN:
        return jsonify(error="Reload the local page to authorize this action"),403


from workspace_safety import register as register_workspace_safety
register_workspace_safety(sys.modules[__name__])


from werkzeug.exceptions import HTTPException
@app.errorhandler(HTTPException)
def http_error(error):
    from workspace_safety import WorkspaceConflict
    return jsonify(error=error.description,conflict='workspace' if isinstance(error,WorkspaceConflict) else 'resource'),error.code


@app.errorhandler(ValueError)
def bad(error):
    return jsonify(error=str(error)),400


@app.get("/")
def home():
    return send_from_directory(ROOT/"static","index.html")


@app.get("/api/status")
def status():
    return jsonify(app_id="library-workbench",version=application_version(),token=TOKEN,desktop=bool(app.config.get("SHUTDOWN_CALLBACK")),example_available=bool(configured_example()),cleanup=shutdown.status(),session=summary(sessions[active]) if active in sessions and not shutdown.requested.is_set() else None)


@app.get('/api/cleanup')
def cleanup_info():return jsonify(shutdown.status(inventory=True))


@app.get("/api/workspace")
def workspace():
    files=[]
    for path in sorted(INPUTS.iterdir()):
        if path.suffix.lower() in (".zip",".xml") and path.is_file():
            files.append({"name":path.name,"path":str(path.resolve()),"kind":path.suffix.lower()[1:],"bytes":path.stat().st_size})
    session=sessions.get(active)
    return jsonify(root=str(DATA),inputs=str(INPUTS),temporary_root=str(TEMPORARY.path),exports_root=str(DATA/"exports"),files=files,
                   session_directory=str(DATA/session["id"]) if session else None,exports=list_exports(DATA/"exports"))


@app.get("/api/analyzer")
def analyzer_info():
    reports=[]
    for path in (DATA/"analyzers").glob("*/report.json"):
        try:
            record=json.loads(path.read_text(encoding="utf-8"))
            reports.append({**{key:record.get(key) for key in ("id","created","source","format","read_status")},
                            "track_paths_available":(path.parent/"track-paths.json").is_file(),
                            "metadata_available":(path.parent/"metadata.json").is_file()})
        except (OSError,ValueError):continue
    discovery=discover_locations()
    return jsonify(compatibility=COMPATIBILITY,suggestions=[row["path"] for row in discovery["found"]],discovery=discovery,
                   reports=sorted(reports,key=lambda row:row["created"],reverse=True)[:20],directory=str(DATA/"analyzers"))


@app.get('/api/discovery')
def discovery_suggestions():return jsonify(discover_locations())


@app.post('/api/discovery/scan')
def discovery_search():
    body=request.get_json() or {};roots=deepcopy(body.get('roots',[]));kind=body.get('kind','both');depth=body.get('depth',8)
    def work(progress):
        result=discover_scan(roots,progress,kind,depth)
        report_id=uuid4().hex;result['id']=report_id;result['created']=datetime.now(timezone.utc).isoformat()
        result['download']='/api/discovery/'+report_id+'/report'
        output=DATA/'discovery';output.mkdir(exist_ok=True)
        save_json(output/(report_id+'.json'),result)
        return result
    return jsonify(job=launch(work,'Searching selected folders for library databases and analysis trees'))


@app.get('/api/discovery/<identity>/report')
def discovery_report(identity):
    if not re_uuid(identity):return jsonify(error='Report not found'),404
    path=DATA/'discovery'/(identity+'.json')
    if not path.is_file():return jsonify(error='Report not found'),404
    return send_file(path,as_attachment=True,download_name='location-discovery.json')


@app.post("/api/analyzer")
def start_analyzer():
    body=request.get_json() or {}
    source=str(body.get("path","")).strip()
    version=str(body.get("version","")).strip()
    recursive=body.get('recursive_inventory',False)
    if not isinstance(recursive,bool):raise ValueError('Recursive inventory must be true or false')
    report_id=uuid4().hex
    return jsonify(job=launch(lambda progress:analyze_folder(source,DATA/"analyzers"/report_id,progress,version,snapshot_root=TEMPORARY.folder('analyzers',report_id),recursive_inventory=recursive),
                             "Capturing a read-only source-folder snapshot"),report_id=report_id)


@app.get("/api/analyzer/<report_id>/journal-status")
def analyzer_journal_status(report_id):
    """Metadata-only WAL/journal change detection on an already selected capture.

    Never open an active encrypted database connection, parse WAL frames, alter
    checkpoints or classify these stamps as committed transactions.
    """
    if not re_uuid(report_id):return jsonify(error="Report not found"),404
    path=DATA/"analyzers"/report_id/"report.json"
    if not path.is_file() or path.is_symlink():return jsonify(error="Report not found"),404
    report=json.loads(path.read_text(encoding="utf-8"))
    if report.get("format")!="Modern desktop master.db":
        return jsonify(supported=False,changed=False,message="Live monitoring requires a saved modern desktop database capture")
    root=Path(report["source"])
    if not root.is_dir() or root.is_symlink() or root.is_junction():
        return jsonify(supported=False,changed=False,message="The saved source directory is unavailable or is a link")
    names=[name for name in database_names(root) if name.casefold()=="master.db"]
    if len(names)!=1:
        return jsonify(supported=False,changed=False,message="Exactly one source master.db must be present")
    name=names[0]
    for suffix in ("","-wal","-journal"):
        if (root/(name+suffix)).is_symlink():
            return jsonify(supported=False,changed=False,message="Linked database or journal files cannot be monitored")
    current=source_stamps(root,name)
    if current['master.db'] is None:return jsonify(supported=False,changed=False,message='Source master.db is no longer available')
    baseline={row["name"]:{key:row.get(key) for key in ("bytes","mtime_ns","inode")} for row in report.get("source_files",[])}
    changed=any(current[key]!=baseline.get(key) for key in current)
    signature=sha256(json.dumps(current,sort_keys=True).encode()).hexdigest()
    return jsonify(supported=True,changed=changed,signature=signature,
                   wal_present=current.get("master.db-wal") is not None,
                   journal_present=current.get("master.db-journal") is not None,
                   message="File changes may include checkpoints or uncommitted writes; only a consistent private snapshot is presented")


@app.get("/api/analyzer/<report_id>")
@app.get("/api/analyzer/<report_id>/report")
def analyzer_report(report_id):
    if not re_uuid(report_id):return jsonify(error="Report not found"),404
    path=DATA/"analyzers"/report_id/"report.json"
    if not path.is_file():return jsonify(error="Report not found"),404
    if request.path.endswith("/report"):return send_file(path,as_attachment=True,download_name="read-only-library-report.json")
    return jsonify(json.loads(path.read_text(encoding="utf-8")))


@app.get("/api/quick-export")
def quick_export_info():
    from workbench_store import Store
    sources=[]
    for path in (DATA/"analyzers").glob("*/report.json"):
        if not (path.parent/"metadata.json").is_file():continue
        try:
            report=json.loads(path.read_text(encoding="utf-8"))
            counters=(report.get('database') or report.get('xml') or {}).get('counters',{})
            sources.append({"id":report["id"],"created":report["created"],"tracks":counters.get('tracks')})
        except (OSError,ValueError,KeyError,TypeError):continue
    return jsonify(directory=str(DATA/"quick-exports"),sources=sorted(sources,key=lambda r:r["created"],reverse=True)[:20],snapshots=Store(DATA/'workbench-sidecar.sqlite3').snapshots(),
                   exports=list_metadata_exports(DATA/"quick-exports"))


def quick_snapshot(body):
    """Freeze one explicit metadata state for preview and generation alike."""
    from workbench_store import Store
    if not isinstance(body,dict):raise ValueError('Provide an offline summary request')
    source=body.get('source','session');scope=body.get('scope','all')
    if source=='session':
        with lock:
            session=current();snapshot=capture_catalog(session['catalog'],scope)
            snapshot['scope_key']='session:'+str(session.get('id') or active or 'current')
    elif isinstance(source,str) and source.startswith('lab:'):
        snapshot=Store(DATA/'workbench-sidecar.sqlite3').snapshot(source[4:])
        if scope!='all':raise ValueError('Choose all captured tracks for a saved snapshot')
    else:
        if not isinstance(source,str) or not re_uuid(source):raise ValueError('Choose a loaded workspace or saved source snapshot')
        if scope!='all':raise ValueError('XML collection scope is available only for an imported XML/ZIP workspace')
        path=DATA/'analyzers'/source/'metadata.json'
        if not path.is_file():raise ValueError('This report has no metadata snapshot. Run Source analyzer again to enable quick export.')
        snapshot=json.loads(path.read_text(encoding='utf-8'))
        if isinstance(snapshot,dict):snapshot.setdefault('scope_key','capture:'+source)
    if not isinstance(snapshot,dict) or not isinstance(snapshot.get('tracks'),list) or any(
            not isinstance(track,dict) or not isinstance(track.get('id'),str) or
            not isinstance(track.get('playlists',[]),list) or any(not isinstance(name,str) for name in track.get('playlists',[]))
            for track in snapshot['tracks']):
        raise ValueError('This source has no usable metadata snapshot. Capture it again.')
    if body.get('working') is True:snapshot=Store(DATA/'workbench-sidecar.sqlite3').effective(snapshot)
    snapshot['data_state']='working' if body.get('working') is True else 'captured'
    return snapshot


def sharing_options(body):
    return {key:body[key] for key in ('preset','fields','track_ids','playlist') if key in body}


@app.post('/api/quick-export/preview')
def preview_quick_export():
    from metadata_export import disclosure
    body=request.get_json(silent=True)
    return jsonify(disclosure(quick_snapshot(body),include_paths=body.get('include_paths') is True,
                              allow_empty_selection=True,**sharing_options(body)))


@app.put('/api/quick-export/xml')
def quick_xml_upload():
    """XML-only metadata entry; no native backup is needed for a summary."""
    limit=4*1024**3
    if request.content_length and request.content_length>limit:raise ValueError('XML exceeds the 4 GB analysis limit')
    identity=uuid4().hex;folder=TEMPORARY.folder('xml-summaries',identity)
    partial=folder/'collection.part';final=folder/'collection.xml';done=0
    try:
        with TEMPORARY.operation(),partial.open('xb') as stream:
            while chunk:=request.stream.read(2*1024**2):
                if shutdown.requested.is_set():raise InterruptedError('Upload cancelled for temporary-file cleanup')
                done+=len(chunk)
                if done>limit:raise ValueError('XML exceeds the 4 GB analysis limit')
                stream.write(chunk)
        if not done:raise ValueError('File is empty')
        os.replace(partial,final)
    except Exception:
        partial.unlink(missing_ok=True);raise
    from xml_analysis import analyze_xml
    return jsonify(job=launch(lambda p:analyze_xml(final,DATA/'analyzers'/identity,p),'Reading XML metadata for an offline summary'),source=identity)


@app.post("/api/quick-export")
def quick_export():
    body=request.get_json(silent=True)
    snapshot=quick_snapshot(body)
    export_id=uuid4().hex
    title=body.get("title") or "My library"
    include_paths=body.get("include_paths") is True
    return jsonify(job=launch(lambda progress:export_metadata(snapshot,DATA/"quick-exports",export_id,ROOT/"static",progress,
                                                             title=title,include_paths=include_paths,temporary_root=TEMPORARY.folder('exports'),**sharing_options(body)),"Building your offline metadata explorer"))


@app.get("/api/quick-export/<export_id>/<kind>")
def quick_download(export_id,kind):
    if not re_uuid(export_id) or kind not in ("html","zip","report"):return jsonify(error="Offline export not found"),404
    folder=DATA/"quick-exports"/export_id
    if not (folder/"export.json").is_file():return jsonify(error="Offline export not found"),404
    path=folder/{"html":"library.html","zip":"metadata-explorer.zip","report":"export.json"}[kind]
    if not path.is_file():return jsonify(error="Offline export not found"),404
    return send_file(path,as_attachment=True)


def save_storage(audit):
    folder=DATA/"storage"/audit["id"]
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/"audit.json"
    temp=path.with_suffix(".tmp")
    temp.write_text(json.dumps(audit,ensure_ascii=False),encoding="utf-8")
    os.replace(temp,path)
    summary={key:audit[key] for key in ("id","created","policy_hint","file_locations","totals")}
    summary["source_report"]=audit.get("source_report")
    save_json(folder/"summary.json",summary)


def load_storage(audit_id):
    if not re_uuid(audit_id):raise ValueError("Unknown storage audit")
    path=DATA/"storage"/audit_id/"audit.json"
    if not path.is_file():raise ValueError("Storage audit is unavailable")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/storage")
def storage_info():
    reports=[]
    for path in (DATA/"storage").glob("*/summary.json"):
        try:reports.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError,ValueError):continue
    return jsonify(suggestions=discover_cloud_roots(),reports=sorted(reports,key=lambda row:row["created"],reverse=True)[:20])


@app.post("/api/storage/scan")
def start_storage():
    body=request.get_json() or {}
    roots=deepcopy(body.get("roots",[]))
    policy=body.get("policy","unknown")
    report_id=str(body.get("source_report") or "")
    if report_id and not re_uuid(report_id):raise ValueError("Unknown source report")
    audit_id=uuid4().hex
    def work(progress):
        paths=DATA/"analyzers"/report_id/"track-paths.json" if report_id else None
        if paths and not paths.is_file():raise ValueError("This source report has no track-path index. Capture it again, or choose folder comparison without a source report.")
        track_paths=json.loads(paths.read_text(encoding="utf-8")) if paths and paths.is_file() else []
        audit=scan_storage(roots,progress,policy,track_paths)
        audit.update(id=audit_id,source_report=report_id or None)
        if track_paths and not audit["matched_database_tracks"]:
            audit["warnings"].append("No database paths matched these folders. Set recorded-prefix mappings if this copy uses different drive paths.")
            audit["warning_count"]+=1
        save_storage(audit)
        return {"id":audit_id,"totals":audit["totals"]}
    return jsonify(job=launch(work,"Comparing local and cloud-visible folders without reading audio"))


@app.get("/api/storage/<audit_id>")
def storage_details(audit_id):
    audit=load_storage(audit_id)
    rows=audit["groups"]
    if request.args.get("scope")=="cloud_local":rows=[row for row in rows if row["cloud_local"]]
    offset=max(0,int(request.args.get("offset",0)))
    from result_order import ordered
    rows=ordered(rows,request.args.get('sort',''),request.args.get('direction','asc'),('physical_files','id'))
    return jsonify(sort_scope='collection',**{key:value for key,value in audit.items() if key!="groups"},groups=rows[offset:offset+30],group_total=len(rows),offset=offset)


@app.get("/api/storage/<audit_id>/report")
def storage_report(audit_id):
    if not re_uuid(audit_id):return jsonify(error="Report not found"),404
    path=DATA/"storage"/audit_id/"audit.json"
    if not path.is_file():return jsonify(error="Report not found"),404
    return send_file(path,as_attachment=True,download_name="cloud-local-storage-report.json")


@app.post("/api/storage/<audit_id>/verify")
def verify_storage(audit_id):
    if not re_uuid(audit_id):raise ValueError("Unknown storage audit")
    group=str((request.get_json() or {}).get("group",""))
    def work(progress):
        audit=load_storage(audit_id)
        result=verify_group(audit,group,progress)
        save_storage(audit)
        return result
    return jsonify(job=launch(work,"Verifying explicitly selected local file bytes"))


@app.post("/api/example")
def example():
    metadata=configured_example()
    if not metadata:
        raise ValueError("The example catalog is unavailable. Import a backup and XML.")
    return jsonify(job=launch(lambda p:load_session(metadata,"october",p),"Loading the configured local example"))


@app.get("/api/tasks/<job>")
def task(job):
    with lock:
        prune_tasks()
        if job not in tasks:
            return jsonify(error="Task not found or expired; completed reports and exports remain saved"),404
        return jsonify({k:v for k,v in tasks[job].items() if not k.startswith('_')})


@app.post('/api/tasks/<job>/cancel')
def cancel_task(job):
    with lock:
        prune_tasks()
        if job not in tasks:return jsonify(error='Task not found'),404
        control=task_controls.get(job)
        if control and tasks[job]['status']=='running':
            control.cancel()
            tasks[job]['cancel_requested']=True
        return jsonify(status=tasks[job]['status'],cancel_requested=tasks[job].get('cancel_requested',False),
                       message='Cancellation takes effect at the next safe checkpoint; completed outputs are kept')


def media_evidence(session,row):
    matches=(session.get("inventory") or {}).get("matches",{})
    check=session.get("media_verifications",{}).get(row["id"])
    return {**row,"evidence":{**row["evidence"],
            "files_found_both":all(matches.get(i,{}).get("status")=="found" for i in (row["a"],row["b"])),
            "content_hash_agrees":bool(check and check["same_file_bytes"]),
            "content_hash_differs":bool(check and not check["same_file_bytes"])}}


def duration_in_range(value,minimum,maximum):
    return minimum==0 and maximum==float('inf') if value is None else minimum<=value<=maximum


def in_scope(session,row,values,include_evidence=True):
    cat=session["catalog"]
    track=cat.tracks[row["keeper"]]
    try:
        minimum=float(values.get("min") or 0)*60
        maximum=float(values["max"])*60 if values.get("max") else float("inf")
    except ValueError:
        raise ValueError("Enter valid track lengths")
    if minimum<0 or maximum<minimum:raise ValueError("Invalid length range")
    if not duration_in_range(track["duration_seconds"],minimum,maximum):return False
    if values.get("cohort")=="xml" and not all(cat.tracks[i]["october_xml"] for i in (row["a"],row["b"])):return False
    cue=cat.cue_summary(track["track_id"])
    feature=values.get("feature","all")
    tests={"all":True,"only_auto":cue["total"]>0 and cue["other"]==0,"mixed":cue["other"]>0 and cue["auto"]>0,
           "full_manual":cue["other"]>0 and cue["auto"]==0,"rated":track["rating"]>0,
           "unplayed":cue["total"]==0 and (track["play_count"] or 0)==0}
    if feature not in tests:raise ValueError("Unknown cue selector")
    if not tests[feature]:return False
    for field in ("album","artist","genre","label"):
        value=str(values.get(field,"")).strip().casefold()
        if value and value not in str(track.get(field,"")).casefold():return False
    extension=str(values.get("format","")).lower()
    if extension and extension!=Path((track.get("current_path") or "").replace("\\","/")).suffix.lower().lstrip("."):return False
    for name,field,scale in (("bpm_min","bpm",1),("bpm_max","bpm",-1),("bitrate_min","bitrate",1)):
        value=values.get(name)
        if value not in (None,""):
            try:bound=float(value)
            except ValueError:raise ValueError("Enter numeric BPM and bitrate limits")
            actual=track.get(field)
            if actual is None or scale*actual<scale*bound:return False
    playlist=values.get("playlist")
    if playlist and playlist not in track.get("playlist_ids",[]):return False
    available=values.get("availability")
    if available:
        status=(session.get("inventory") or {}).get("matches",{}).get(track["track_id"],{}).get("status","unverified")
        if status!=available:return False
    requested=values.get("evidence","")
    requested=requested.split(",") if isinstance(requested,str) else requested
    if include_evidence and any(key and not row["evidence"].get(key,False) for key in requested):
        return False
    query=str(values.get("q","")).casefold()
    return not query or query in (row["title"]+" "+row["artist"]+" "+row["id"]).casefold()


@app.get("/api/pairs")
def pairs():
    from pair_query import page
    return jsonify(page(current(),request.args,in_scope,media_evidence))


@app.get("/api/pair/<pair_id>")
def detail(pair_id):
    session=current()
    if pair_id not in session["catalog"].pairs:
        return jsonify(error="Pair not found"),404
    value=session["catalog"].detail(pair_id)
    value["group_note"]=session.get("held_pairs",{}).get(pair_id)
    value["media_verification"]=session.get("media_verifications",{}).get(pair_id)
    return jsonify(**value,decision=session["decisions"].get(pair_id))


def stage(session,pair_id,choice,group_state=None):
    cat=session["catalog"]
    if pair_id not in cat.pairs:
        raise ValueError("Pair does not exist")
    if choice["action"] not in ("merge","skip","undo"):
        raise ValueError("Unknown decision")
    if choice["action"]=="undo":
        old=session["decisions"].pop(pair_id,None)
        # Re-evaluate the remaining group on the next staging action.
        return
    if choice["action"]=="merge":
        keeper=choice.get("keeper") or cat.preferred(cat.pairs[pair_id])[0]
        pair=cat.pairs[pair_id]
        if keeper not in (pair["a"],pair["b"]):raise ValueError("Unknown keeper")
        donor=pair["b"] if keeper==pair["a"] else pair["a"]
        if group_state is None:
            prior={i:d for i,d in session["decisions"].items() if i!=pair_id}
            mapping,results=decision_map(cat,prior)
        else:
            mapping,results=group_state
        if keeper in mapping or donor in mapping or donor in results:
            raise ValueError("This sibling already has another keeper. Undo the overlapping decision first.")
        result=cat.merge(pair,keeper,choice.get("prefer_auto",False),choice.get("prefer_rating",False),results.get(keeper))
        if result["conflicts"]:
            raise ValueError("Review the remaining cue or rating conflict before staging this merge")
        choice={**choice,"keeper":keeper}
        mapping[donor]=keeper
        result["donors"]=[*results.get(keeper,{}).get("donors",[]),donor]
        results[keeper]=result
    session["held_pairs"].pop(pair_id,None)
    session["decisions"][pair_id]=choice


@app.post("/api/decision")
@atomic_workspace
def decide():
    body=request.get_json()
    with lock:
        session=current()
        stage(session,body["pair"],body)
        log(session,body["action"].capitalize()+" · "+session["catalog"].descriptions[body["pair"]]["title"])
        return jsonify(session=summary(session))


@app.post("/api/bulk")
@atomic_workspace
def bulk():
    body=request.get_json()
    if body.get("mode") not in ("ready","auto"):
        raise ValueError("Choose ready pairs or automatic cue differences")
    with lock:
        session=current()
        count=blocked=covered=0
        batch_ids=[]
        previous_held=dict(session.get("held_pairs",{}))
        group_state=decision_map(session["catalog"],session["decisions"])
        field={"newest":"date_added","last_played":"last_played","play_count":"play_count"}[session["policy"]]
        def ranking(item):
            t=session["catalog"].tracks[item[1]["keeper"]]
            return (bool(session["catalog"].cue_summary(t["track_id"])["other"]),
                    (t.get(field) or 0) if field=="play_count" else str(t.get(field) or ""),
                    bool(t["october_xml"]),bool(t["rating"]),-int(t["track_id"]) if t["track_id"].isdigit() else 0)
        for i,r in sorted(session["catalog"].descriptions.items(),key=ranking,reverse=True):
            r=media_evidence(session,r)
            if r["category"]!=body["mode"] or i in session["decisions"] or not in_scope(session,r,body):
                continue
            mapping,_=group_state
            if mapping.get(r["a"],r["a"])==mapping.get(r["b"],r["b"]):
                covered+=1
                continue
            try:
                stage(session,i,{"action":"merge","keeper":r["keeper"],"prefer_auto":body["mode"]=="auto","prefer_rating":False},group_state)
                count+=1
                batch_ids.append(i)
            except ValueError as error:
                blocked+=1
                session["held_pairs"][i]=str(error)
        session["last_batch"]=batch_ids
        session.setdefault("batches",[]).append({"decisions":batch_ids,"previous_held":previous_held})
        log(session,f"Batch staged {count:,} {body['mode']} merges; {covered:,} comparisons already covered; {blocked:,} group choices held for review")
        return jsonify(session=summary(session),count=count,blocked=blocked,covered=covered)


@app.post("/api/bulk/undo")
@atomic_workspace
def undo_batch():
    with lock:
        session=current()
        count=0
        batch=session.get("batches",[]).pop() if session.get("batches") else session.get("last_batch",[])
        previous_decisions={}
        if isinstance(batch,dict):
            session["held_pairs"]=batch["previous_held"]
            previous_decisions=batch.get('previous_decisions',{})
            batch=batch["decisions"]
        for i in batch:
            if i in session["decisions"]:
                session["decisions"].pop(i)
                count+=1
        session['decisions'].update(previous_decisions)
        session["last_batch"]=session["batches"][-1]["decisions"] if session.get("batches") and isinstance(session["batches"][-1],dict) else []
        log(session,f"Undid the last batch of {count:,} decisions")
        return jsonify(session=summary(session),count=count)


@app.post("/api/policy")
def policy():
    value=request.get_json().get("policy")
    if value not in ("newest","last_played","play_count"):
        raise ValueError("Unknown keeper preference")
    session=current()
    def change(progress):
        with lock, transaction(session):
            session["policy"]=value
            session["catalog"].policy=value
            session["catalog"].refresh_counts()
            log(session,"Keeper tie-breaker changed to "+value)
        return {"session":session["id"]}
    return jsonify(job=launch(change,"Updating keeper suggestions"))



def reference_catalog(session):
    from workbench_store import Store
    catalog=copy(session["catalog"])
    catalog.metadata=deepcopy(catalog.metadata)
    catalog.metadata['export_target']=session.get('export_target','auto')
    catalog.metadata['_audio_access_mappings']=Store(DATA/'workbench-sidecar.sqlite3').setting('audio_paths:session:'+session['id'],[])
    return catalog


@app.post("/api/export-target")
@atomic_workspace
def export_target():
    from export_references import target_info
    session=current()
    body=request.get_json(silent=True)
    if not isinstance(body,dict):raise ValueError('Choose an export target.')
    selected=body.get('target')
    target_info(session['catalog'],selected)
    session['export_target']=selected
    log(session,'Export reference target: '+selected)
    return jsonify(session=summary(session))


@app.post("/api/relocation")
@atomic_workspace
def relocation():
    from urllib.parse import urlsplit
    body=request.get_json()
    i=body.get("track_id")
    uri=(body.get("uri") or "").strip()
    session=current()
    if i not in session["catalog"].tracks:
        raise ValueError("Unknown track")
    if uri and (urlsplit(uri).scheme!="file" or not urlsplit(uri).path):
        raise ValueError("Enter a file URI such as file://localhost/D:/Music/track.mp3")
    if uri:
        from export_references import validate_relocations
        validate_relocations(reference_catalog(session),{i:uri})
        session["relocations"][i]=uri
    else:
        session["relocations"].pop(i,None)
    log(session,("Staged reference for " if uri else "Cleared reference for ")+session["catalog"].tracks[i]["title"])
    return jsonify(session=summary(session))


@app.get("/api/report")
def report():
    session=current()
    mapping,results=decision_map(session["catalog"],session["decisions"])
    payload={**summary(session),"decisions":session["decisions"],"reference_edits":session["relocations"],
             "merge_map":mapping,"cue_changes":{i:r["changes"] for i,r in results.items()},
             "format":"Offline review plan v1","native_backup_writer":"Native ZIP export requires an isolated restore test on the selected Windows/macOS target"}
    return app.response_class(json.dumps(payload,ensure_ascii=False,indent=2),mimetype="application/json",
                              headers={"Content-Disposition":'attachment; filename="library-review-report.json"'})


@app.post("/api/export")
def export():
    kind=(request.get_json(silent=True) or {}).get("format","xml")
    if kind not in ("xml","zip","pair"):
        raise ValueError("Unknown export format")
    with lock:
        session=current()
        if not session.get("backup_acknowledged"):
            raise ValueError("Keep a separate, untouched rekordbox Backup Library backup before transforming files, then acknowledge it on Prepare export.")
        catalog=reference_catalog(session)
        if kind in ("zip","pair") and str(catalog.metadata.get("version","")).split(".")[0]!="7":
            raise ValueError("Native ZIP generation is currently available for v7 inputs only. Older libraries can be inspected with Source analyzer; native round-trip validation for v6 is pending.")
        check_inputs(catalog.metadata)
        from lab_routes import workspace_overrides
        from workbench_store import Store
        from workspace_safety import revision,WorkspaceConflict
        edits=Store(DATA/'workbench-sidecar.sqlite3').edit_state('session:'+session['id'],history=True)
        if request.headers.get('X-Workbench-Revision')!=revision(session,DATA,edits['edit_revision']):
            raise WorkspaceConflict('Staged metadata changed. Reload and review the export again.')
        catalog.metadata['field_overrides']=workspace_overrides(DATA,session,edits['overrides'])
        decisions=deepcopy(session["decisions"])
        relocations=dict(session["relocations"])
        from export_references import validate_export
        retired,_=decision_map(catalog,decisions)
        validate_export(catalog,relocations,kind,retired)
        snapshot=deepcopy(summary(session,edits))
        snapshot['metadata_overrides']=deepcopy(catalog.metadata['field_overrides'])
        snapshot['revision']=revision(session,DATA,edits['edit_revision'])
        snapshot['metadata_edit_revision']=edits['edit_revision']
        snapshot['metadata_override_evidence']=edits['overrides']
        snapshot['metadata_edit_history']=edits['history']
    export_id=uuid4().hex
    def work(progress):
        result=prepare_export(catalog,decisions,relocations,snapshot,DATA/"exports",export_id,kind,progress,temporary_root=TEMPORARY.folder('exports'))
        log(session,f"Exported {('XML + ZIP' if kind=='pair' else kind.upper())} with {result['merges']:,} staged merges")
        return result
    return jsonify(job=launch(work,"Preparing "+("matching XML + ZIP" if kind=="pair" else kind.upper())))


@app.post("/api/backup/acknowledge")
@atomic_workspace
def acknowledge_backup():
    session=current()
    confirmed=(request.get_json() or {}).get("confirmed") is True
    session["backup_acknowledged"]=datetime.now(timezone.utc).isoformat() if confirmed else None
    log(session,"Separate untouched backup acknowledged" if confirmed else "Backup acknowledgement cleared")
    return jsonify(session=summary(session))


@app.get("/api/download/<export_id>")
@app.get("/api/download/<export_id>/<kind>")
def download(export_id,kind="xml"):
    if not re_uuid(export_id) or kind not in ("xml","zip","report"):
        return jsonify(error="Export not found"),404
    file=DATA/"exports"/export_id/({"xml":"edited-collection.xml","zip":"edited-library.zip","report":"report.json"}[kind])
    return send_file(file,as_attachment=True)


def re_uuid(value):
    return len(value)==32 and all(c in "0123456789abcdef" for c in value)


@app.post("/api/import")
def start_import():
    body=request.get_json()
    if not isinstance(body,dict):raise ValueError('Choose one ZIP library backup and one XML collection')
    for key,ext in (("zip",".zip"),("xml",".xml")):
        if not str(body.get(key,"")).lower().endswith(ext):
            raise ValueError("Choose one ZIP library backup and one XML collection")
    target=str(body.get('resume_session') or '')
    if target:resume_state(target)
    import ntpath
    names={key:ntpath.basename(str(body[key]).replace('/','\\')) for key in ('zip','xml')}
    try:
        if any('\x00' in name for name in names.values()):raise UnicodeError()
        for name in names.values():name.encode('utf-8')
    except UnicodeError:raise ValueError('Filenames must contain valid Unicode without null characters') from None
    sid=uuid4().hex
    folder=TEMPORARY.folder(sid)
    # Upload bytes always use fixed session paths; these names are display metadata.
    info={**names,'resume_session':target}
    (folder/"upload.json").write_text(json.dumps(info,ensure_ascii=False),encoding="utf-8")
    return jsonify(session=sid)


@app.post("/api/import/local")
def import_local():
    body=request.get_json() or {};paths=select_inputs(body)
    target=str(body.get('resume_session') or '')
    if target:resume_state(target)
    sid=uuid4().hex
    folder=DATA/sid
    if not target:folder.mkdir(mode=0o700)
    inputs={"zip_path":str(paths["zip"]),"xml_path":str(paths["xml"])}
    inputs["input_fingerprints"]=fingerprint_inputs(inputs)
    def work(progress):
        check_inputs(inputs)
        if target:return reattach_inputs(target,paths,progress,'linked')
        inputs['input_fingerprints']=fingerprint_inputs(inputs,content=True,progress=progress)
        metadata=analyze(paths["zip"],paths["xml"],folder,progress,scratch=TEMPORARY.folder(sid))
        metadata.update(inputs,import_mode="linked")
        check_inputs(metadata)
        return load_session(metadata,sid,progress)
    return jsonify(job=launch(work,"Analyzing existing files without copying"),session=sid)


@app.put("/api/upload/<sid>/<kind>")
def upload(sid,kind):
    if not re_uuid(sid) or kind not in ("zip","xml"):
        raise ValueError("Unknown upload")
    from upload_recovery import receive
    done=receive(TEMPORARY,sid,kind,request.stream,request.content_length,shutdown.requested.is_set)
    return jsonify(bytes=done)


@app.get('/api/import/<sid>')
def upload_status(sid):
    if not re_uuid(sid):raise ValueError('Unknown import')
    folder=TEMPORARY.path/sid;path=folder/'upload.json'
    if folder.is_symlink() or folder.is_junction() or not path.is_file():
        raise ValueError('This upload session is unavailable. Start a new import.')
    info=json.loads(path.read_text(encoding='utf-8'))
    files={}
    for kind in ('zip','xml'):
        name=info.get(kind,'')
        if not name or '/' in name or '\\' in name:raise ValueError('Invalid upload session')
        candidate=folder/name
        files[kind]={'complete':candidate.is_file() and not candidate.is_symlink(),
                     'bytes':candidate.stat().st_size if candidate.is_file() else 0}
    return jsonify(session=sid,files=files)

@app.post("/api/import/<sid>/analyze")
def run_import(sid):
    if not re_uuid(sid):
        raise ValueError("Unknown import")
    folder=TEMPORARY.path/sid
    if folder.is_symlink() or folder.is_junction() or not (folder/'upload.json').is_file():
        raise ValueError('This upload session is unavailable. Start a new import.')
    info=json.loads((folder/"upload.json").read_text(encoding="utf-8"))
    backup,xml=folder/info["zip"],folder/info["xml"]
    if not backup.exists() or not xml.exists():
        raise ValueError("Finish uploading both files first")
    def work(progress):
        if info.get('resume_session'):return reattach_inputs(info['resume_session'],{'zip':backup,'xml':xml},progress,'uploaded')
        stamps=fingerprint_inputs({"zip_path":str(backup),"xml_path":str(xml)},content=True,progress=progress)
        saved=DATA/sid;saved.mkdir(parents=True,exist_ok=True)
        metadata=analyze(backup,xml,saved,progress,scratch=TEMPORARY.folder(sid))
        metadata.update(input_fingerprints=stamps,import_mode="uploaded")
        check_inputs(metadata)
        return load_session(metadata,sid,progress)
    with lock:
        for task in tasks.values():
            if task.get('import_session')==sid and task['status'] in ('running','complete'):
                if task['status']=='complete' and active!=(task.get('result') or {}).get('session'):
                    raise ValueError('This import already completed. Resume it from Saved workspaces to make it active again.')
                return jsonify(job=task['id'])
        job=launch(work,"Analyzing the imported pair")
        tasks[job]['import_session']=sid
    return jsonify(job=job)


def resume_state(sid):
    if sid!='october' and not re_uuid(sid):raise ValueError('Choose a saved workspace')
    path=DATA/sid/'state.json'
    if not path.is_file():raise ValueError('Saved workspace not found')
    return json.loads(path.read_text(encoding='utf-8'))


def reattach_inputs(sid,paths,progress,mode):
    saved=resume_state(sid);metadata=deepcopy(saved['metadata'])
    if not metadata.get('pair_signature'):raise ValueError('This older workspace has no input identity. Restore its recorded paths once to upgrade it, or start a new workspace.')
    if not Path(metadata['source']).is_file():raise ValueError('Saved review metadata is unavailable; import as a new workspace')
    inputs={'zip_path':str(paths['zip']),'xml_path':str(paths['xml'])};inputs['input_fingerprints']=fingerprint_inputs(inputs,content=True,progress=progress)
    progress(5,'Verifying the selected originals before restoring saved decisions')
    identity=pair_signature(paths['zip'],paths['xml'])
    check_inputs(inputs)
    if identity!=metadata['pair_signature']:raise ValueError('These files differ from the saved workspace. Select the matching original XML/ZIP pair; saved decisions were kept unchanged.')
    for kind,stamp in metadata.get('input_fingerprints',{}).items():
        if stamp.get('sha256') and stamp['sha256']!=inputs['input_fingerprints'][kind]['sha256']:
            raise ValueError('These original file bytes differ from the saved workspace. Saved decisions were kept unchanged.')
    metadata.update(inputs,import_mode=mode)
    return load_session(metadata,sid,progress)


@app.get("/api/statistics")
def statistics():
    session=current()
    try:
        minimum=float(request.args.get("min","0"))*60
        maximum=float(request.args["max"])*60 if request.args.get("max") else float("inf")
    except ValueError:
        raise ValueError("Enter track lengths in minutes")
    if minimum<0 or maximum<minimum:
        raise ValueError("Maximum length must be at least the minimum")
    cohort=request.args.get("cohort","all")
    if cohort not in ("all","xml"):
        raise ValueError("Unknown statistics scope")
    tracks=[t for t in session["catalog"].tracks.values()
            if duration_in_range(t["duration_seconds"],minimum,maximum) and (cohort=="all" or t["october_xml"])]
    counters={"total":len(tracks),"analysed":0,"rated":0,"full_manual":0,"mixed":0,"only_auto":0,"no_cues_no_plays":0,"no_cues":0}
    bins=[(30,"< 30 sec"),(60,"30–60 sec"),(180,"1–3 min"),(300,"3–5 min"),(600,"5–10 min"),
          (1800,"10–30 min"),(3600,"30–60 min"),(float("inf"),"> 60 min")]
    hist=[0]*len(bins)
    for t in tracks:
        cues=session["catalog"].cue_summary(t["track_id"])
        counters["analysed"]+=bool(t.get("analysed",t["grid_sha256"]))
        counters["rated"]+=t["rating"]>0
        counters["full_manual"]+=cues["other"]>0 and cues["auto"]==0
        counters["mixed"]+=cues["other"]>0 and cues["auto"]>0
        counters["only_auto"]+=cues["total"]>0 and cues["other"]==0
        counters["no_cues"]+=cues["total"]==0
        counters["no_cues_no_plays"]+=cues["total"]==0 and (t["play_count"] or 0)==0
        if t['duration_seconds'] is None:continue
        for n,(limit,_) in enumerate(bins):
            if t["duration_seconds"]<limit:
                hist[n]+=1
                break
    selected_ids={t["track_id"] for t in tracks}
    counters.update(albums=len({t.get("album","").strip().casefold() for t in tracks if t.get("album","").strip()}),
                    authors=len({t["artist"].strip().casefold() for t in tracks if t["artist"].strip()}),
                    composers=len({t.get("composer","").strip().casefold() for t in tracks if t.get("composer","").strip()}),
                    playlists=len({p for t in tracks for p in t.get("playlist_ids",[])}),
                    total_playlists=session["metadata"].get("playlist_total",0),
                    broken_xml_targets=sum(i in selected_ids for i in session["metadata"].get("broken_xml_targets",[])),
                    broken_database_links=session["metadata"].get("broken_database_links",0),
                    orphan_analysis_folders=session["metadata"].get("orphan_analysis_folders",0),
                    missing_media=None,orphan_media=None)
    from history_browser import added_years
    return jsonify(counters=counters,unknown_duration=sum(t['duration_seconds'] is None for t in tracks),histogram=[{"label":label,"count":count} for (_,label),count in zip(bins,hist)],
                   addition_dates=added_years(tracks),
                   scope=cohort,min_minutes=minimum/60,max_minutes=maximum/60 if maximum!=float("inf") else None,
                   note="Manual categories mean cues without CUE(Auto) or 1.1Bars labels. Zero play count is the saved count.")


@app.get("/api/group/details")
def group_details():
    ids=request.args.get("ids","").split(",")
    session=current()
    cat=session["catalog"]
    if not 1<=len(ids)<=100 or any(i not in cat.tracks for i in ids):
        raise ValueError("Unknown recording group")
    keeper=ids[0]
    for i in ids[1:]:keeper=cat.preferred({"a":keeper,"b":i})[0]
    return jsonify(keeper=keeper,tracks=[{**cat.tracks[i],"cue_summary":cat.cue_summary(i)} for i in ids])


@app.post("/api/inventory/scan")
def inventory_scan():
    from file_health import local_request
    if not local_request():raise ValueError('Media searches require the local application')
    body=request.get_json(silent=True)
    if not isinstance(body,dict):raise ValueError('Provide a media search request')
    mappings=body.get("roots",[])
    advanced=body.get('advanced',False)
    if not isinstance(advanced,bool):raise ValueError('Choose a supported search mode')
    session=current()
    if body.get('workspace')!=session['id']:raise ValueError('This workspace is no longer loaded')
    def work(progress):
        if advanced:
            from media_recovery import scan
            result=scan(session['catalog'].tracks,mappings,progress)
        else:
            result=scan_media(session["catalog"].tracks,mappings,progress)
            result['scan_id']=uuid4().hex
        progress(99,'Saving the media search results')
        inventory_path=DATA/session["id"]/('inventory-'+uuid4().hex+'.json')
        temporary=inventory_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result,ensure_ascii=False),encoding="utf-8")
        os.replace(temporary,inventory_path)
        try:
            with lock, transaction(session):
                session["inventory"]=result
                session["media_verifications"]={}
                session["inventory_path"]=str(inventory_path)
                log(session,f"Indexed {result['file_count']:,} media files in selected roots")
        except Exception:
            inventory_path.unlink(missing_ok=True)
            raise
        return {"counts":result["counts"],"files":result["file_count"],"warnings":result["warnings"]}
    with lock:
        for job in tasks.values():
            if job.get('inventory_workspace')==session['id'] and job['status']=='running':
                return jsonify(job=job['id'])
        job=launch(work,"Scanning the selected media roots")
        tasks[job]['inventory_workspace']=session['id']
    return jsonify(job=job)


@app.get("/api/inventory")
def inventory_items():
    from media_recovery import UNRESOLVED
    session=current()
    inventory=session.get("inventory")
    if not inventory:return jsonify(counts={},rows=[],total=0,file_count=0)
    status=request.args.get("status","all")
    query=request.args.get("q","").casefold()
    offset=max(0,int(request.args.get("offset",0)))
    rows=[]
    for i,match in inventory["matches"].items():
        track=session["catalog"].tracks[i]
        if status=='unresolved':
            if match['status'] not in UNRESOLVED:continue
        elif status!="all" and match["status"]!=status:continue
        if query and query not in (track["title"]+" "+track["artist"]+" "+i).casefold():continue
        rows.append({"track_id":i,"title":track["title"],"artist":track["artist"],
                     'staged_uri':session['relocations'].get(i),**match})
    from result_order import ordered
    rows=ordered(rows,request.args.get('sort',''),request.args.get('direction','asc'),('title','artist','status','candidate_count'))
    return jsonify(sort_scope='collection',counts=inventory["counts"],file_count=inventory["file_count"],roots=inventory["roots"],
                   scan_id=inventory.get('scan_id'),advanced=inventory.get('advanced',False),
                   complete=inventory.get('complete'),note=inventory.get('note'),
                   warnings=inventory["warnings"],total=len(rows),rows=rows[offset:offset+50])


@app.get('/api/inventory/report')
def inventory_report():
    from media_recovery import recovery_report
    with lock:
        payload=recovery_report(current())
    return app.response_class(json.dumps(payload,ensure_ascii=False,indent=2),mimetype='application/json',
                              headers={'Content-Disposition':'attachment; filename="recovery-review.json"'})


@app.post("/api/inventory/verify")
def verify_media():
    session=current()
    pair=(request.get_json() or {}).get("pair")
    if not session.get("inventory"):raise ValueError("Scan the media roots first")
    def work(progress):
        result=verify_pair(session["catalog"],session["inventory"],pair,progress)
        with lock, transaction(session):
            session.setdefault("media_verifications",{})[pair]=result
            log(session,"Media hash verification "+("agreed" if result["same_file_bytes"] else "differed")+" for "+pair)
        return result
    return jsonify(job=launch(work,"Verifying local media bytes"))


@app.post("/api/inventory/stage")
@atomic_workspace
def stage_inventory_reference():
    from file_health import local_request
    from media_recovery import stage_candidate
    if not local_request():raise ValueError('Relocation requires the local application')
    body=request.get_json(silent=True)
    if not isinstance(body,dict):raise ValueError('Provide a relocation request')
    with lock:
        session=current()
        inventory=session.get('inventory') or {}
        if body.get('workspace')!=session['id']:raise ValueError('This workspace is no longer loaded')
        if not inventory.get('scan_id') or body.get('scan_id')!=inventory['scan_id']:
            raise ValueError('The search results changed; reload and review the candidate')
        i=body.get('track_id')
        match=inventory.get('matches',{}).get(i,{})
        if body.get('undo') is True:
            candidates=match.get('candidates',[])
            if not candidates or session['relocations'].get(i)!=candidates[0].get('export_uri'):
                raise ValueError('The staged reference changed; review it in File references')
            session['relocations'].pop(i)
            log(session,'Cleared inventory reference for '+session['catalog'].tracks[i]['title'])
            return jsonify(session=summary(session))
        uri=stage_candidate(inventory,match)
        from export_references import validate_relocations
        validate_relocations(reference_catalog(session),{i:uri})
        session['relocations'][i]=uri
        log(session,'Staged inventory reference for '+session['catalog'].tracks[i]['title'])
        return jsonify(session=summary(session))


@app.get("/api/sessions")
def saved_sessions():
    entries=[]
    for state in DATA.glob("*/state.json"):
        try:
            value=json.loads(state.read_text(encoding="utf-8"))
            meta=value["metadata"]
            entries.append({"id":value["id"],"name":value.get("name",meta["name"]),
                            "updated":state.stat().st_mtime,"staged":sum(d["action"]=="merge" for d in value.get("decisions",{}).values()),
                            "available":all(Path(meta[k]).is_file() for k in ("source","zip_path","xml_path"))})
        except (ValueError,KeyError,OSError):
            continue
    return jsonify(sessions=sorted(entries,key=lambda r:r["updated"],reverse=True))


@app.post("/api/sessions/<sid>/resume")
def resume_session(sid):
    if sid!="october" and not re_uuid(sid):raise ValueError("Unknown saved session")
    state=DATA/sid/"state.json"
    if not state.is_file():raise ValueError("Saved session is unavailable")
    saved=json.loads(state.read_text(encoding="utf-8"))
    metadata=saved["metadata"]
    if not all(Path(metadata[k]).is_file() for k in ("source","zip_path","xml_path")):
        raise ValueError("The temporary inputs were cleaned or originals moved. Use Reattach originals for this saved workspace.")
    check_inputs(metadata)
    return jsonify(job=launch(lambda p:load_session(metadata,sid,p),"Resuming the saved workspace"))


@app.post("/api/session/name")
@atomic_workspace
def rename_session():
    name=str((request.get_json() or {}).get("name","")).strip()
    if not 1<=len(name)<=100:raise ValueError("Use a name of 1 to 100 characters")
    session=current()
    session["name"]=name
    log(session,"Workspace renamed to "+name)
    return jsonify(session=summary(session))


@app.route("/api/presets",methods=["GET","POST"])
def filter_presets():
    path=DATA/"filter-presets.json"
    with lock:
        saved=json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if request.method=="POST":
            body=request.get_json()
            name=str(body.get("name","")).strip()
            if not 1<=len(name)<=60:raise ValueError("Use a preset name of 1 to 60 characters")
            allowed={"min","max","cohort","feature","q","evidence","album","artist","genre","label","format",
                     "bpm_min","bpm_max","bitrate_min","playlist","availability"}
            saved[name]={k:v for k,v in body.get("criteria",{}).items() if k in allowed}
            temp=path.with_suffix(".tmp")
            temp.write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding="utf-8")
            os.replace(temp,path)
    return jsonify(presets=saved)


def recording_group_plan(session,body):
    """Run the actual staging rules on separate decision dictionaries first."""
    ids=body.get("track_ids",[])
    keeper=body.get("keeper")
    if not isinstance(ids,list) or not 1<=len(ids)<=100 or any(not isinstance(i,str) for i in ids):
        raise ValueError("Choose between 1 and 100 known group members")
    if len(set(ids))!=len(ids) or keeper not in ids:raise ValueError("Choose a keeper in this recording group")
    excluded=body.get('excluded',[])
    if not isinstance(excluded,list) or any(not isinstance(i,str) or i not in ids or i==keeper for i in excluded):
        raise ValueError("Exclude only donor members of this group")
    if any(i not in session["catalog"].tracks for i in ids):raise ValueError("Unknown group member")
    shadow={**session,'decisions':dict(session['decisions']),'held_pairs':dict(session['held_pairs'])}
    state=decision_map(session['catalog'],session['decisions'])
    rows=[];staged=[];held={}
    for donor in ids:
        row={'track_id':donor,'status':'keeper','reason':''}
        rows.append(row)
        if donor==keeper:continue
        if state[0].get(donor)==keeper:
            row['status']='already_staged';continue
        if donor in excluded:
            row['status']='excluded';continue
        pair_id='~'.join(sorted((donor,keeper)))
        if pair_id not in session['catalog'].pairs:
            row.update(status='held',reason='No direct match to this keeper; inspect the supporting pair first')
            held[donor]=row['reason'];continue
        try:
            stage(shadow,pair_id,{'action':'merge','keeper':keeper,'prefer_auto':bool(body.get('prefer_auto')),
                                 'prefer_rating':bool(body.get('prefer_rating'))},state)
            row['status']='ready';staged.append(pair_id)
        except ValueError as error:
            row.update(status='held',reason=str(error));held[donor]=str(error)
            shadow['held_pairs'][pair_id]=str(error)
    counts={name:sum(r['status']==name for r in rows) for name in ('ready','held','excluded','already_staged')}
    return {'keeper':keeper,'rows':rows,'counts':counts,'decisions':staged,'held':held},shadow


@app.post('/api/group/preview')
def preview_recording_group():
    with lock:
        plan,_=recording_group_plan(current(),request.get_json() or {})
    return jsonify(**plan)


@app.post("/api/group/stage")
@atomic_workspace
def stage_recording_group():
    session=current()
    with lock:
        previous_held=dict(session["held_pairs"])
        plan,shadow=recording_group_plan(session,request.get_json() or {})
        staged=plan['decisions'];held=plan['held']
        previous_decisions={i:session['decisions'][i] for i in staged if i in session['decisions']}
        session['decisions']=shadow['decisions'];session['held_pairs']=shadow['held_pairs']
        session["batches"].append({"decisions":staged,"previous_held":previous_held,'previous_decisions':previous_decisions})
        session["last_batch"]=staged
        log(session,f"Recording group staged {len(staged)} merges; {len(held)} siblings held for review; {plan['counts']['excluded']} excluded")
    return jsonify(session=summary(session),count=len(staged),held=held)


@app.post("/api/desktop/stop")
def stop_desktop():
    callback=app.config.get("SHUTDOWN_CALLBACK")
    if not callback:raise ValueError("Stop the command-line server from its terminal")
    return jsonify(shutdown.request((request.get_json() or {}).get('acknowledged') is True))


from lab_routes import register as register_lab
register_lab(sys.modules[__name__])
from insights_routes import register as register_insights
register_insights(sys.modules[__name__])
from track_playback import register as register_playback
register_playback(sys.modules[__name__])
from intelligence_routes import register as register_intelligence
register_intelligence(sys.modules[__name__])
from collection_views import register as register_collection_views
register_collection_views(sys.modules[__name__])
from investigations import register as register_investigations
register_investigations(sys.modules[__name__])
from journeys_routes import register as register_journeys
register_journeys(sys.modules[__name__])
from audio_paths import register as register_audio_paths
register_audio_paths(sys.modules[__name__])
from file_health import register as register_file_health
register_file_health(sys.modules[__name__])
from library_preparation import register as register_library_preparation
register_library_preparation(sys.modules[__name__])


if __name__=="__main__":
    parser=argparse.ArgumentParser(description="Local rekordbox preparation workbench")
    parser.add_argument("--port",type=int,default=8765)
    args=parser.parse_args()
    from desktop_launcher import serve_application
    serve_application(app,args.port,True)
