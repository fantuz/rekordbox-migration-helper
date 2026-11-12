"""Local input references and publication of validated XML/ZIP export sets."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil


def select_inputs(values):
    paths={}
    for kind in ("zip","xml"):
        value=str(values.get(kind,"")).strip().strip('"')
        path=Path(value).expanduser()
        if not value or not path.is_absolute() or path.suffix.lower()!="."+kind:
            raise ValueError("Choose a full path to a ."+kind+" file on this computer")
        try:
            path=path.resolve(strict=True)
            if not path.is_file() or path.stat().st_size==0:raise OSError()
        except OSError:
            raise ValueError("The selected "+kind.upper()+" file is missing, empty or unreadable") from None
        paths[kind]=path
    return paths


def fingerprint_inputs(metadata):
    result={}
    for kind in ("zip","xml"):
        path=Path(metadata[kind+"_path"])
        try:
            stat=path.stat()
            if not path.is_file():raise OSError()
        except OSError:
            raise ValueError("The source "+kind.upper()+" file has moved or is unavailable. Restore its recorded location.") from None
        result[kind]={"path":str(path.resolve()),"bytes":stat.st_size,"mtime_ns":stat.st_mtime_ns}
    return result


def check_inputs(metadata):
    actual=fingerprint_inputs(metadata)
    expected=metadata.get("input_fingerprints")
    if expected and actual!=expected:
        raise ValueError("An input file has changed since this workspace was analyzed. Import the pair as a new workspace.")
    return actual


def prepare_export(catalog,decisions,relocations,snapshot,root,export_id,kind,progress,
                   xml_writer=None,native_writer=None):
    """Expose a completed set only after every requested writer has validated it."""
    if kind not in ("xml","zip","pair"):raise ValueError("Unknown export format")
    if xml_writer is None:
        from engine import export_xml
        xml_writer=export_xml
    if native_writer is None:
        from native_export import export_native
        native_writer=export_native
    decisions,relocations,snapshot=deepcopy((decisions,relocations,snapshot))
    expected=check_inputs(catalog.metadata)
    metadata={**catalog.metadata,"input_fingerprints":expected}
    root=Path(root)
    pending=root/(".pending-"+export_id)
    final=root/export_id
    pending.mkdir(parents=True)
    requested=("xml","zip") if kind=="pair" else (kind,)
    validations={}
    try:
        for index,format_name in enumerate(requested):
            check_inputs(metadata)
            destination=pending/("edited-collection.xml" if format_name=="xml" else "edited-library.zip")
            def update(amount,message,index=index,format_name=format_name):
                progress((index*100+min(99,max(0,amount)))/len(requested),format_name.upper()+" · "+message)
            writer=xml_writer if format_name=="xml" else native_writer
            validations[format_name]=writer(catalog,deepcopy(decisions),dict(relocations),destination,update)
            if not destination.is_file() or not destination.stat().st_size:
                raise ValueError(format_name.upper()+" export did not produce a file")
            check_inputs(metadata)
        if kind=="pair" and validations["xml"]["merges"]!=validations["zip"]["merges"]:
            raise ValueError("The XML and ZIP writers reported different merge plans")
        for name in ("export-master.db","native-master.db"):
            (pending/name).unlink(missing_ok=True)
        created=datetime.now(timezone.utc).isoformat()
        review={"session":snapshot,"decisions":decisions,"reference_edits":relocations,"inputs":expected,
                "metadata_overrides":deepcopy(catalog.metadata.get('field_overrides',{}))}
        digest=sha256(json.dumps(review,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        report={**review,"review_sha256":digest,"export_id":export_id,"created":created,"format":kind,"validation":validations}
        (pending/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        files=[]
        for name in (*requested,"report"):
            filename={"xml":"edited-collection.xml","zip":"edited-library.zip","report":"report.json"}[name]
            files.append({"kind":name,"name":filename,"bytes":(pending/filename).stat().st_size,
                          "download":"/api/download/"+export_id+"/"+name})
        record={"id":export_id,"status":"complete","format":kind,"created":created,"session_id":snapshot["id"],
                "session_name":snapshot.get("name",snapshot["id"]),"directory":str(final.resolve()),
                "review_sha256":digest,"merges":next(iter(validations.values()))["merges"],"files":files}
        (pending/"export.json").write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
        pending.rename(final)
    except Exception:
        shutil.rmtree(pending,ignore_errors=True)
        raise
    return {**record,"validation":validations if kind=="pair" else validations[kind],
            "download":files[0]["download"],"report":"/api/download/"+export_id+"/report"}


def list_exports(root):
    records=[]
    root=Path(root)
    if not root.is_dir():return records
    for manifest in root.glob("*/export.json"):
        try:
            record=json.loads(manifest.read_text(encoding="utf-8"))
            if record.get("status")=="complete" and all((manifest.parent/f["name"]).is_file() for f in record["files"]):
                records.append(record)
        except (OSError,ValueError,KeyError):
            continue
    return sorted(records,key=lambda r:r["created"],reverse=True)[:20]
