"""Read-only, metadata-first comparison of local and cloud-visible music roots."""
from collections import defaultdict
from datetime import datetime,timezone
from hashlib import sha256
import os
from pathlib import Path

from engine import path_key
from media import AUDIO,cloud_placeholder,file_record


def allocation(path,stat):
    if hasattr(stat,"st_blocks"):return stat.st_blocks*512
    if os.name=="nt":
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL("kernel32",use_last_error=True)
        get_size=kernel.GetCompressedFileSizeW
        get_size.argtypes=(wintypes.LPCWSTR,ctypes.POINTER(wintypes.DWORD))
        get_size.restype=wintypes.DWORD
        high=wintypes.DWORD()
        ctypes.set_last_error(0)
        value=str(path)
        if not value.startswith('\\\\?\\'):
            value='\\\\?\\UNC\\'+value[2:] if value.startswith('\\\\') else '\\\\?\\'+value
        low=get_size(value,ctypes.byref(high))
        if low==0xFFFFFFFF and ctypes.get_last_error():return None
        return (high.value<<32)|low
    return None


def totals(audit):
    groups=audit["groups"]
    copies=[g for g in groups if g["physical_files"]>1]
    verified=[g for g in copies if g.get("verification")]
    return {"candidate_groups":len(copies),"cloud_local_candidate_groups":sum(g["cloud_local"] for g in copies),
            "potential_extra_logical_bytes":sum(g["potential_extra_logical_bytes"] for g in copies),
            "link_alias_groups":sum(len(g["files"])>g["physical_files"] for g in groups),
            "database_reference_groups":sum(len(g["track_ids"])>1 for g in groups),
            "last_verified_identical_groups":sum(g["verification"]["same_file_bytes"] for g in verified),
            "last_verified_extra_logical_bytes":sum(g["verification"]["extra_identical_logical_bytes"] for g in verified)}


def scan_storage(mappings,progress,policy="unknown",track_paths=None):
    if policy not in ("copy","move","unknown"):raise ValueError("Choose Copy, Move or Unknown as your upload-policy hint")
    if not 1<=len(mappings)<=20:raise ValueError("Choose between one and twenty music folders")
    validated=[];warnings=[]
    for mapping in mappings:
        kind=mapping.get("kind","local")
        if kind not in ("local","dropbox","google_drive"):raise ValueError("Choose Local, Dropbox or Google Drive for each folder")
        raw=str(mapping.get("root","")).strip().strip('"')
        root=Path(raw).expanduser()
        if not raw or not root.is_absolute():raise ValueError("Enter a full path for each music folder")
        if not root.is_dir():warnings.append("Folder unavailable: "+str(root));continue
        root=root.resolve()
        if root==Path(root.anchor):raise ValueError("Choose a music folder rather than an entire system drive")
        if any(row["root"]==str(root) for row in validated):raise ValueError("The same folder was selected more than once")
        validated.append({"root":str(root),"kind":kind,"recorded_prefix":str(mapping.get("recorded_prefix","")).strip()})
    records=[];seen_paths=set();allocated_inodes=set();index=defaultdict(list)
    # More specific roots get first attribution when selected folders overlap.
    for mapping in sorted(validated,key=lambda row:len(Path(row["root"]).parts),reverse=True):
        root=Path(mapping["root"])
        def unreadable(error):warnings.append(str(error))
        for folder,dirs,names in os.walk(root,followlinks=False,onerror=unreadable):
            dirs[:]=[name for name in dirs if not (Path(folder)/name).is_symlink() and not (Path(folder)/name).is_junction()]
            for name in names:
                path=Path(folder)/name
                if path.suffix.casefold() not in AUDIO or path.is_symlink():continue
                identity_path=os.path.normcase(str(path.resolve()))
                if identity_path in seen_paths:continue
                try:
                    stat=path.stat()
                    physical=str(stat.st_dev)+":"+str(stat.st_ino) if stat.st_ino else identity_path
                    used=allocation(path,stat)
                except OSError as error:warnings.append(str(error));continue
                seen_paths.add(identity_path)
                counted=physical not in allocated_inodes
                allocated_inodes.add(physical)
                record={"id":len(records),"path":str(path),"name":name,"kind":mapping["kind"],
                        "root":mapping["root"],"size":stat.st_size,"mtime_ns":stat.st_mtime_ns,
                        "physical_id":physical,"cloud_only":cloud_placeholder(stat),"allocated_bytes":used if counted else 0,
                        "allocation_counted":counted,"track_ids":[],"evidence":[]}
                records.append(record)
                index[path_key(str(path)),stat.st_size].append(record["id"])
                if mapping["recorded_prefix"]:
                    recorded=mapping["recorded_prefix"].rstrip("/\\")+"/"+path.relative_to(root).as_posix()
                    index[path_key(recorded),stat.st_size].append(record["id"])
                if len(records)%1000==0:progress(25,f"Indexed {len(records):,} audio file locations without reading content")
    parent=list(range(len(records)))
    def find(value):
        while parent[value]!=value:parent[value]=parent[parent[value]];value=parent[value]
        return value
    def combine(ids,evidence):
        ids=list(set(ids))
        if len(ids)<2:return
        for value in ids:
            parent[find(value)]=find(ids[0])
            records[value]["evidence"].append(evidence)
    dimensions=defaultdict(list)
    for record in records:
        if record["size"]:dimensions[record["name"].casefold(),record["size"]].append(record["id"])
    for ids in dimensions.values():combine(ids,"filename_and_size")
    matched_tracks=0
    for track in track_paths or []:
        ids=set()
        for field in ("current_path","original_path"):
            if track.get(field):ids.update(index.get((path_key(track[field]),track.get("size")),[]))
        if ids:matched_tracks+=1
        for value in ids:records[value]["track_ids"].append(str(track["id"]))
        combine(ids,"database_paths_and_size")
    grouped=defaultdict(list)
    for record in records:grouped[find(record["id"])].append(record)
    groups=[]
    for members in grouped.values():
        track_ids=sorted({i for record in members for i in record["track_ids"]})
        if len(members)<2 and len(track_ids)<2:continue
        physical={record["physical_id"] for record in members}
        kinds={record["kind"] for record in members}
        groups.append({"id":sha256("\0".join(sorted(record["path"] for record in members)).encode()).hexdigest()[:24],
                       "files":members,"physical_files":len(physical),"track_ids":track_ids,
                       "cloud_local":"local" in kinds and bool(kinds & {"dropbox","google_drive"}),
                       "evidence":sorted({e for record in members for e in record["evidence"]}),
                       "potential_extra_logical_bytes":members[0]["size"]*max(0,len(physical)-1),"verification":None})
    locations=[]
    for kind in ("local","dropbox","google_drive"):
        selected=[r for r in records if r["kind"]==kind]
        locations.append({"kind":kind,"files":len(selected),"logical_bytes":sum(r["size"] for r in selected),
                          "known_allocated_bytes":sum(r["allocated_bytes"] or 0 for r in selected),
                          "unknown_allocation_files":sum(r["allocated_bytes"] is None for r in selected),
                          "cloud_placeholders":sum(r["cloud_only"] for r in selected)})
    result={"created":datetime.now(timezone.utc).isoformat(),"policy_hint":policy,"roots":validated,
            "file_locations":len(records),"physical_files":len(allocated_inodes),"locations":locations,
            "matched_database_tracks":matched_tracks,"groups":sorted(groups,key=lambda g:(not g["cloud_local"],-g["potential_extra_logical_bytes"])),
            "warnings":warnings[:100],"warning_count":len(warnings),"source_writes":False,
            "notes":["Copy/Move is a user-supplied hint. This audit reports observed files, not the historical rekordbox setting.",
                     "Cloud logical bytes describe files visible in the selected cloud folders, not account quota usage or a complete remote inventory.",
                     "Cloud folders can occupy local disk space. Known disk allocation is a filesystem measurement and may differ from logical file size.",
                     "Overlapping roots and hard-link aliases are counted once for physical allocation. Shared filesystem clone extents may still affect estimates.",
                     "Filename/size and database-path matches identify candidates. Explicit SHA-256 verification is needed to confirm identical content.",
                     "Not found means outside the selected folders or unavailable here. Offline mounts and hidden remote files may still contain other copies."]}
    result["totals"]=totals(result)
    progress(100,"Cloud/local storage comparison complete")
    return result


def verify_group(audit,group_id,progress):
    group=next((row for row in audit["groups"] if row["id"]==group_id),None)
    if group is None:raise ValueError("Unknown storage candidate group")
    records={record["physical_id"]:record for record in group["files"]}
    if len(records)<2:raise ValueError("This group refers to only one physical file")
    if len(records)>30:raise ValueError("This group is too large for one hash request; narrow the selected roots")
    for record in records.values():
        actual=file_record(Path(record["path"]))
        if actual["cloud_only"]:raise ValueError("Download cloud-only audio explicitly before hash verification")
        if (actual["size"],actual["mtime_ns"])!=(record["size"],record["mtime_ns"]):raise ValueError("A file changed since the audit. Scan again before verification.")
    hashes={};done=0;size=sum(record["size"] for record in records.values())
    for record in records.values():
        path=Path(record["path"]);digest=sha256()
        with path.open("rb") as stream:
            while chunk:=stream.read(2*1024**2):
                digest.update(chunk);done+=len(chunk);progress(95*done/max(1,size),"Reading explicitly selected local files for SHA-256")
        actual=file_record(path)
        if actual["cloud_only"] or (actual["size"],actual["mtime_ns"])!=(record["size"],record["mtime_ns"]):raise ValueError("A file changed during verification. Scan again.")
        hashes[record["path"]]=digest.hexdigest()
    partitions=defaultdict(list)
    for record in records.values():partitions[hashes[record["path"]]].append(record)
    group["verification"]={"created":datetime.now(timezone.utc).isoformat(),"same_file_bytes":len(partitions)==1,"sha256":hashes,
                           "extra_identical_logical_bytes":sum(rows[0]["size"]*(len(rows)-1) for rows in partitions.values())}
    audit["totals"]=totals(audit)
    return group["verification"]
