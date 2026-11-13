"""Run with .venv/bin/python app.py. Open http://127.0.0.1:8765."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import copy, deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4
import argparse
import json
import os
import secrets
import sqlite3
import sys

from flask import Flask, jsonify, request, send_file, send_from_directory
from engine import Catalog, analyze, enrich_usage, decision_map, export_xml
from native_export import export_native
from media import scan as scan_media, verify_pair
from file_workflow import select_inputs, fingerprint_inputs, check_inputs, prepare_export, list_exports,pair_signature
from analyzer import analyze_folder, COMPATIBILITY
from platform_paths import default_data_directory, discover_cloud_roots
from discovery import suggestions as discover_locations,scan_roots as discover_scan
from storage_audit import scan_storage, verify_group
from metadata_export import capture_catalog, export_metadata, list_metadata_exports
import localization
import documentation

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
active = None


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
    payload = {k:v for k,v in session.items() if k not in ("catalog","inventory")}
    temp = dest.with_suffix(".tmp")
    temp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    os.replace(temp,dest)


def log(session, text):
    with lock:
        session["events"].append({"time":datetime.now(timezone.utc).isoformat(),"text":text})
        persist(session)


def task_progress(job, amount, text):
    if shutdown.requested.is_set():raise InterruptedError('Stopping: temporary analysis copies are being cleaned')
    with lock:
        tasks[job].update(progress=amount,message=text)


def launch(work, message, pool=None):
    if shutdown.requested.is_set():raise ValueError('The application is stopping')
    job = uuid4().hex
    tasks[job] = {"id":job,"status":"running","progress":0,"message":message}
    def run():
        try:
            with TEMPORARY.operation():result=work(lambda n,s:task_progress(job,n,s))
            with lock:
                tasks[job].update(status="complete",progress=100,result=result,message="Complete")
        except Exception as error:
            with lock:
                tasks[job].update(status="error",message=str(error),progress=0)
    (pool or executor).submit(run)
    return job


def load_session(metadata, sid, progress):
    global active
    metadata=deepcopy(metadata)
    metadata["input_fingerprints"]=check_inputs(metadata)
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
    session={"id":sid,"metadata":metadata,"catalog":catalog,"decisions":saved.get("decisions",{}),
             "relocations":saved.get("relocations",{}),"events":saved.get("events",[]),"policy":catalog.policy,"last_batch":saved.get("last_batch",[]),"batches":saved.get("batches",[]),"held_pairs":saved.get("held_pairs",{}),"inventory":inventory,"inventory_path":saved.get("inventory_path"),"name":saved.get("name",metadata["name"]),"media_verifications":saved.get("media_verifications",{}),"backup_acknowledged":saved.get("backup_acknowledged")}
    with lock:
        sessions[sid]=session
        active=sid
        log(session,f"Loaded {len(catalog.tracks):,} tracks and {len(catalog.pairs):,} candidate pairs")
    return {"session":sid}


def current():
    if not active or active not in sessions:
        raise ValueError("Load a backup and XML first")
    return sessions[active]


def summary(session):
    decisions=session["decisions"]
    from workbench_store import Store
    fields=Store(DATA/'workbench-sidecar.sqlite3').overrides('session:'+session['id']) if (DATA/'workbench-sidecar.sqlite3').is_file() else {}
    return {"id":session["id"],"name":session.get("name",session["metadata"]["name"]),"metadata":session["metadata"],"counts":session["catalog"].counts,
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
    if request.method in ("POST","PUT","DELETE") and request.headers.get("X-Workbench-Token")!=TOKEN:
        return jsonify(error="Reload the local page to authorize this action"),403


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
        (output/(report_id+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
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
    report_id=uuid4().hex
    return jsonify(job=launch(lambda progress:analyze_folder(source,DATA/"analyzers"/report_id,progress,version,snapshot_root=TEMPORARY.folder('analyzers',report_id)),
                             "Capturing a read-only source-folder snapshot"),report_id=report_id)


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
    sources=[]
    for path in (DATA/"analyzers").glob("*/report.json"):
        if not (path.parent/"metadata.json").is_file():continue
        try:
            report=json.loads(path.read_text(encoding="utf-8"))
            counters=(report.get('database') or report.get('xml') or {}).get('counters',{})
            sources.append({"id":report["id"],"created":report["created"],"tracks":counters.get('tracks')})
        except (OSError,ValueError,KeyError,TypeError):continue
    return jsonify(directory=str(DATA/"quick-exports"),sources=sorted(sources,key=lambda r:r["created"],reverse=True)[:20],
                   exports=list_metadata_exports(DATA/"quick-exports"))


@app.post("/api/quick-export")
def quick_export():
    body=request.get_json() or {}
    source=body.get("source","session")
    scope=body.get("scope","all")
    if source=="session":
        with lock:snapshot=capture_catalog(current()["catalog"],scope)
    else:
        if not isinstance(source,str) or not re_uuid(source):raise ValueError("Choose a loaded workspace or saved source snapshot")
        if scope!="all":raise ValueError("XML collection scope is available only for an imported XML/ZIP workspace")
        path=DATA/"analyzers"/source/"metadata.json"
        if not path.is_file():raise ValueError("This report has no metadata snapshot. Run Source analyzer again to enable quick export.")
        snapshot=json.loads(path.read_text(encoding="utf-8"))
    export_id=uuid4().hex
    title=body.get("title") or "My library"
    include_paths=body.get("include_paths") is True
    return jsonify(job=launch(lambda progress:export_metadata(snapshot,DATA/"quick-exports",export_id,ROOT/"static",progress,
                                                             title=title,include_paths=include_paths,temporary_root=TEMPORARY.folder('exports')),"Building your offline metadata explorer"))


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
    (folder/"summary.json").write_text(json.dumps(summary),encoding="utf-8")


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
    return jsonify(**{key:value for key,value in audit.items() if key!="groups"},groups=rows[offset:offset+30],group_total=len(rows),offset=offset)


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
    if job not in tasks:
        return jsonify(error="Task not found"),404
    return jsonify(tasks[job])


def media_evidence(session,row):
    matches=(session.get("inventory") or {}).get("matches",{})
    check=session.get("media_verifications",{}).get(row["id"])
    return {**row,"evidence":{**row["evidence"],
            "files_found_both":all(matches.get(i,{}).get("status")=="found" for i in (row["a"],row["b"])),
            "content_hash_agrees":bool(check and check["same_file_bytes"]),
            "content_hash_differs":bool(check and not check["same_file_bytes"])}}


def in_scope(session,row,values,include_evidence=True):
    cat=session["catalog"]
    track=cat.tracks[row["keeper"]]
    try:
        minimum=float(values.get("min") or 0)*60
        maximum=float(values["max"])*60 if values.get("max") else float("inf")
    except ValueError:
        raise ValueError("Enter valid track lengths")
    if minimum<0 or maximum<minimum:raise ValueError("Invalid length range")
    if not minimum<=track["duration_seconds"]<=maximum:return False
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
    session=current()
    cat=session["catalog"]
    mode=request.args.get("filter","all")
    query=request.args.get("q","").casefold()
    offset=max(0,int(request.args.get("offset",0)))
    rows=[]
    facets={}
    for i,r in cat.descriptions.items():
        r=media_evidence(session,r)
        if i in session.get("held_pairs",{}):
            r={**r,"category":"review"}
        choice=session["decisions"].get(i)
        if mode=="staged" and (not choice or choice["action"]!="merge"):
            continue
        if mode in ("ready","auto","review") and (r["category"]!=mode or choice):
            continue
        if not in_scope(session,r,request.args,include_evidence=False):
            continue
        for key,value in r["evidence"].items():
            facets[key]=facets.get(key,0)+int(value)
        if not in_scope(session,r,request.args):
            continue
        rows.append({**r,"decision":choice})
    rows.sort(key=lambda r:(r["category"]=="review",r["title"].casefold(),r["id"]))
    parent={}
    def root(i):
        parent.setdefault(i,i)
        while parent[i]!=i:
            parent[i]=parent[parent[i]]
            i=parent[i]
        return i
    for r in rows:
        parent[root(r["a"])]=root(r["b"])
    review_parent={}
    def review_root(i):
        review_parent.setdefault(i,i)
        while review_parent[i]!=i:
            review_parent[i]=review_parent[review_parent[i]]
            i=review_parent[i]
        return i
    for r in rows:
        if r["category"]=="review":
            review_parent[review_root(r["a"])]=review_root(r["b"])
    groups=len({root(i) for i in parent})
    if request.args.get("view")=="groups":
        grouped={}
        for r in rows:
            key=root(r["a"])
            group=grouped.setdefault(key,{"id":key,"pairs":[],"tracks":set()})
            group["pairs"].append(r)
            group["tracks"].update((r["a"],r["b"]))
        group_rows=[]
        for group in grouped.values():
            options=group["pairs"]
            rep=next((r for r in options if r["category"]=="review"),options[0])
            group_rows.append({"id":group["id"],"representative":rep["id"],"title":rep["title"],"artist":rep["artist"],
                               "track_ids":sorted(group["tracks"]),"pair_ids":[r["id"] for r in options],
                               "track_count":len(group["tracks"]),"pair_count":len(options),
                               "category":"review" if any(r["category"]=="review" for r in options) else
                                          "auto" if any(r["category"]=="auto" for r in options) else "ready"})
        group_rows.sort(key=lambda r:(r["category"]=="review",r["title"].casefold(),r["id"]))
        return jsonify(total=groups,groups=groups,tracks=len(parent),pair_count=len(rows),
                       potential_reduction=len(parent)-groups,review_groups=len({review_root(i) for i in review_parent}),
                       review_tracks=len(review_parent),facets=facets,offset=offset,rows=group_rows[offset:offset+40],view="groups")
    return jsonify(total=len(rows),groups=groups,tracks=len(parent),potential_reduction=len(parent)-groups,
                   review_groups=len({review_root(i) for i in review_parent}),review_tracks=len(review_parent),
                   facets=facets,offset=offset,rows=rows[offset:offset+40])


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
def decide():
    body=request.get_json()
    with lock:
        session=current()
        stage(session,body["pair"],body)
        log(session,body["action"].capitalize()+" · "+session["catalog"].descriptions[body["pair"]]["title"])
        return jsonify(session=summary(session))


@app.post("/api/bulk")
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
def undo_batch():
    with lock:
        session=current()
        count=0
        batch=session.get("batches",[]).pop() if session.get("batches") else session.get("last_batch",[])
        if isinstance(batch,dict):
            session["held_pairs"]=batch["previous_held"]
            batch=batch["decisions"]
        for i in batch:
            if i in session["decisions"]:
                session["decisions"].pop(i)
                count+=1
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
        with lock:
            session["policy"]=value
            session["catalog"].policy=value
            session["catalog"].refresh_counts()
            log(session,"Keeper tie-breaker changed to "+value)
        return {"session":session["id"]}
    return jsonify(job=launch(change,"Updating keeper suggestions"))


@app.post("/api/relocation")
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
             "format":"Offline review plan v1","native_backup_writer":"Experimental ZIP export; isolated Windows restore test required"}
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
        catalog=copy(session["catalog"])
        catalog.metadata=deepcopy(catalog.metadata)
        if kind in ("zip","pair") and str(catalog.metadata.get("version","")).split(".")[0]!="7":
            raise ValueError("Native ZIP generation is currently available for v7 inputs only. Older libraries can be inspected with Source analyzer; native round-trip validation for v6 is pending.")
        check_inputs(catalog.metadata)
        from lab_routes import workspace_overrides
        catalog.metadata['field_overrides']=workspace_overrides(DATA,session)
        decisions=deepcopy(session["decisions"])
        relocations=dict(session["relocations"])
        snapshot=deepcopy(summary(session))
        snapshot['metadata_overrides']=deepcopy(catalog.metadata['field_overrides'])
        from workbench_store import Store
        snapshot['metadata_override_evidence']=Store(DATA/'workbench-sidecar.sqlite3').overrides('session:'+session['id'])
        snapshot['metadata_edit_history']=Store(DATA/'workbench-sidecar.sqlite3').override_history('session:'+session['id'])
    export_id=uuid4().hex
    def work(progress):
        result=prepare_export(catalog,decisions,relocations,snapshot,DATA/"exports",export_id,kind,progress,temporary_root=TEMPORARY.folder('exports'))
        log(session,f"Exported {('XML + ZIP' if kind=='pair' else kind.upper())} with {result['merges']:,} staged merges")
        return result
    return jsonify(job=launch(work,"Preparing "+("matching XML + ZIP" if kind=="pair" else kind.upper())))


@app.post("/api/backup/acknowledge")
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
        metadata=analyze(paths["zip"],paths["xml"],folder,progress,scratch=TEMPORARY.folder(sid))
        metadata.update(inputs,import_mode="linked")
        check_inputs(metadata)
        return load_session(metadata,sid,progress)
    return jsonify(job=launch(work,"Analyzing existing files without copying"),session=sid)


@app.put("/api/upload/<sid>/<kind>")
def upload(sid,kind):
    if not re_uuid(sid) or kind not in ("zip","xml"):
        raise ValueError("Unknown upload")
    folder=TEMPORARY.folder(sid)
    info=json.loads((folder/"upload.json").read_text(encoding="utf-8"))
    final=folder/info[kind]
    if final.exists():
        raise ValueError("File has already been uploaded")
    temp=folder/(kind+".part")
    done=0
    with TEMPORARY.operation(),temp.open("xb") as stream:
        while chunk:=request.stream.read(2*1024*1024):
            if shutdown.requested.is_set():raise InterruptedError('Upload cancelled for temporary-file cleanup')
            done+=len(chunk)
            stream.write(chunk)
    if done==0:
        temp.unlink()
        raise ValueError("File is empty")
    os.replace(temp,final)
    return jsonify(bytes=done)


@app.post("/api/import/<sid>/analyze")
def run_import(sid):
    if not re_uuid(sid):
        raise ValueError("Unknown import")
    folder=TEMPORARY.folder(sid)
    info=json.loads((folder/"upload.json").read_text(encoding="utf-8"))
    backup,xml=folder/info["zip"],folder/info["xml"]
    if not backup.exists() or not xml.exists():
        raise ValueError("Finish uploading both files first")
    def work(progress):
        if info.get('resume_session'):return reattach_inputs(info['resume_session'],{'zip':backup,'xml':xml},progress,'uploaded')
        stamps=fingerprint_inputs({"zip_path":str(backup),"xml_path":str(xml)})
        saved=DATA/sid;saved.mkdir(parents=True,exist_ok=True)
        metadata=analyze(backup,xml,saved,progress,scratch=TEMPORARY.folder(sid))
        metadata.update(input_fingerprints=stamps,import_mode="uploaded")
        check_inputs(metadata)
        return load_session(metadata,sid,progress)
    return jsonify(job=launch(work,"Analyzing the imported pair"))


def resume_state(sid):
    if sid!='october' and not re_uuid(sid):raise ValueError('Choose a saved workspace')
    path=DATA/sid/'state.json'
    if not path.is_file():raise ValueError('Saved workspace not found')
    return json.loads(path.read_text(encoding='utf-8'))


def reattach_inputs(sid,paths,progress,mode):
    saved=resume_state(sid);metadata=deepcopy(saved['metadata'])
    if not metadata.get('pair_signature'):raise ValueError('This older workspace has no input identity. Restore its recorded paths once to upgrade it, or start a new workspace.')
    if not Path(metadata['source']).is_file():raise ValueError('Saved review metadata is unavailable; import as a new workspace')
    inputs={'zip_path':str(paths['zip']),'xml_path':str(paths['xml'])};inputs['input_fingerprints']=fingerprint_inputs(inputs)
    progress(5,'Verifying the selected originals before restoring saved decisions')
    identity=pair_signature(paths['zip'],paths['xml'])
    check_inputs(inputs)
    if identity!=metadata['pair_signature']:raise ValueError('These files differ from the saved workspace. Select the matching original XML/ZIP pair; saved decisions were kept unchanged.')
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
            if minimum<=t["duration_seconds"]<=maximum and (cohort=="all" or t["october_xml"])]
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
    return jsonify(counters=counters,histogram=[{"label":label,"count":count} for (_,label),count in zip(bins,hist)],
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
    mappings=(request.get_json() or {}).get("roots",[])
    session=current()
    def work(progress):
        result=scan_media(session["catalog"].tracks,mappings,progress)
        inventory_path=DATA/session["id"]/"inventory.json"
        temporary=inventory_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result,ensure_ascii=False),encoding="utf-8")
        os.replace(temporary,inventory_path)
        with lock:
            session["inventory"]=result
            session["media_verifications"]={}
            session["inventory_path"]=str(inventory_path)
            log(session,f"Indexed {result['file_count']:,} media files in selected roots")
        return {"counts":result["counts"],"files":result["file_count"],"warnings":result["warnings"]}
    return jsonify(job=launch(work,"Scanning the selected media roots"))


@app.get("/api/inventory")
def inventory_items():
    session=current()
    inventory=session.get("inventory")
    if not inventory:return jsonify(counts={},rows=[],total=0,file_count=0)
    status=request.args.get("status","all")
    query=request.args.get("q","").casefold()
    offset=max(0,int(request.args.get("offset",0)))
    rows=[]
    for i,match in inventory["matches"].items():
        track=session["catalog"].tracks[i]
        if status!="all" and match["status"]!=status:continue
        if query and query not in (track["title"]+" "+track["artist"]+" "+i).casefold():continue
        rows.append({"track_id":i,"title":track["title"],"artist":track["artist"],**match})
    return jsonify(counts=inventory["counts"],file_count=inventory["file_count"],roots=inventory["roots"],
                   warnings=inventory["warnings"],total=len(rows),rows=rows[offset:offset+50])


@app.post("/api/inventory/verify")
def verify_media():
    session=current()
    pair=(request.get_json() or {}).get("pair")
    if not session.get("inventory"):raise ValueError("Scan the media roots first")
    def work(progress):
        result=verify_pair(session["catalog"],session["inventory"],pair,progress)
        with lock:
            session.setdefault("media_verifications",{})[pair]=result
            log(session,"Media hash verification "+("agreed" if result["same_file_bytes"] else "differed")+" for "+pair)
        return result
    return jsonify(job=launch(work,"Verifying local media bytes"))


@app.post("/api/inventory/stage")
def stage_inventory_reference():
    session=current()
    i=(request.get_json() or {}).get("track_id")
    match=(session.get("inventory") or {}).get("matches",{}).get(i,{})
    if match.get("status")!="found" or len(match.get("candidates",[]))!=1:
        raise ValueError("Choose a reference with exactly one local candidate")
    uri=match["candidates"][0].get("export_uri")
    if not uri:raise ValueError("Set an export root URI in the mapping and scan again")
    session["relocations"][i]=uri
    log(session,"Staged inventory reference for "+session["catalog"].tracks[i]["title"])
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


@app.post("/api/group/stage")
def stage_recording_group():
    body=request.get_json()
    ids=body.get("track_ids",[])
    keeper=body.get("keeper")
    if not ids or len(ids)>100 or keeper not in ids:raise ValueError("Choose a keeper in this recording group")
    session=current()
    if any(i not in session["catalog"].tracks for i in ids):raise ValueError("Unknown group member")
    with lock:
        previous_held=dict(session["held_pairs"])
        state=decision_map(session["catalog"],session["decisions"])
        staged=[]
        held={}
        for donor in ids:
            if donor==keeper or state[0].get(donor)==keeper:continue
            pair_id="~".join(sorted((donor,keeper)))
            if pair_id not in session["catalog"].pairs:
                held[donor]="No direct match to this keeper; review the supporting pair first"
                continue
            try:
                stage(session,pair_id,{"action":"merge","keeper":keeper,"prefer_auto":bool(body.get("prefer_auto")),
                                     "prefer_rating":bool(body.get("prefer_rating"))},state)
                staged.append(pair_id)
            except ValueError as error:
                held[donor]=str(error)
                session["held_pairs"][pair_id]=str(error)
        session["batches"].append({"decisions":staged,"previous_held":previous_held})
        session["last_batch"]=staged
        log(session,f"Recording group staged {len(staged)} merges; {len(held)} siblings held for review")
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


if __name__=="__main__":
    parser=argparse.ArgumentParser(description="Local rekordbox preparation workbench")
    parser.add_argument("--port",type=int,default=8765)
    args=parser.parse_args()
    from desktop_launcher import serve_application
    serve_application(app,args.port,True)
