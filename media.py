"""Inventory only user-selected media roots; content hashes are explicit."""
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from urllib.parse import quote
import os
import ntpath
import stat as stat_constants

from engine import path_key

AUDIO = {".mp3",".flac",".wav",".aiff",".aif",".m4a",".aac",".ogg",".opus",".mp4",".avi",".alac"}
CLOUD_FLAGS = 0x1000 | 0x40000 | 0x400000


def cloud_placeholder(stat):
    return bool(getattr(stat,"st_file_attributes",0) & CLOUD_FLAGS or
                getattr(stat,"st_flags",0) & getattr(stat_constants,"SF_DATALESS",0x40000000))


def file_record(path):
    stat=path.stat()
    return {"path":str(path),"size":stat.st_size,"mtime_ns":stat.st_mtime_ns,
            "cloud_only":cloud_placeholder(stat)}


def export_uri(mapping,relative):
    root=mapping.get("export_uri","").rstrip("/")
    if not root:
        return None
    if not root.lower().startswith("file:"):
        raise ValueError("Export root must be a file URI")
    return root+"/"+quote(relative.as_posix(),safe="/")


def scan(tracks,mappings,progress):
    if not 1<=len(mappings)<=20:
        raise ValueError("Choose between one and twenty media roots")
    files=[]
    warnings=[]
    indexes=defaultdict(list)
    exact=defaultdict(list)
    validated=[]
    for mapping in mappings:
        root=Path(mapping.get("root","")).expanduser().resolve()
        if not root.is_dir():
            warnings.append("Root unavailable: "+str(root))
            continue
        if root==Path(root.anchor):
            raise ValueError("Select a media folder rather than the entire system drive")
        mapping={**mapping,"root":str(root)}
        validated.append(mapping)
        if mapping.get("export_uri") and not mapping["export_uri"].lower().startswith("file:"):
            raise ValueError("Export root must be a file URI")
        def on_error(error):
            warnings.append(str(error))
        for directory,dirs,names in os.walk(root,followlinks=False,onerror=on_error):
            dirs[:]=[d for d in dirs if not Path(directory,d).is_symlink() and not Path(directory,d).is_junction()]
            for name in names:
                path=Path(directory,name)
                if path.suffix.casefold() not in AUDIO or path.is_symlink():
                    continue
                try:
                    record=file_record(path)
                except OSError as error:
                    warnings.append(str(error))
                    continue
                relative=path.relative_to(root)
                record["export_uri"]=export_uri(mapping,relative)
                files.append(record)
                indexes[name.casefold(),record["size"]].append(record)
                if mapping.get("recorded_prefix"):
                    recorded=mapping["recorded_prefix"].rstrip("/\\")+"/"+relative.as_posix()
                    exact[path_key(recorded),record["size"]].append(record)
                if len(files)%500==0:
                    progress(10,f"Indexed {len(files):,} media files")
    matches={}
    for n,(i,track) in enumerate(tracks.items()):
        recorded=[track.get(k) for k in ("current_path","original_path","xml_location") if track.get(k)]
        candidates=[]
        evidence=""
        for value in recorded:
            records=exact.get((path_key(value),track["size_bytes"]))
            if records:
                candidates.extend(records)
                evidence="mapped_path_and_size"
        if not candidates:
            for value in recorded:
                name=ntpath.basename(path_key(value))
                candidates.extend(indexes.get((name,track["size_bytes"]),[]))
            evidence="filename_and_size"
        unique={r["path"]:r for r in candidates}
        candidates=list(unique.values())
        if len(candidates)==1:
            record=candidates[0]
            status="cloud_only" if record["cloud_only"] else "found"
        elif candidates:
            status="ambiguous"
        else:
            status="not_found" if not warnings and validated else "unverified"
        matches[i]={"status":status,"evidence":evidence if candidates else None,"candidates":candidates[:20],
                    "candidate_count":len(candidates)}
        if n%3000==0:
            progress(30+int(65*n/max(len(tracks),1)),f"Checked {n:,} / {len(tracks):,} library references")
    from collections import Counter
    return {"roots":validated,"file_count":len(files),"warnings":warnings[:100],"matches":matches,
            "counts":dict(Counter(r["status"] for r in matches.values())),
            "note":"Not found means absent from these scanned roots. Other drives and cloud sources may still contain the audio."}


def verify_pair(catalog,inventory,pair_id,progress):
    if pair_id not in catalog.pairs:
        raise ValueError("Unknown duplicate pair")
    records=[]
    for i in (catalog.pairs[pair_id]["a"],catalog.pairs[pair_id]["b"]):
        match=inventory.get("matches",{}).get(i,{})
        if match.get("status")!="found" or len(match.get("candidates",[]))!=1:
            raise ValueError("Both siblings need one local candidate before content verification")
        records.append(match["candidates"][0])
    hashes={}
    total=sum(r["size"] for r in {r["path"]:r for r in records}.values())
    done=0
    for record in records:
        path=Path(record["path"])
        before=file_record(path)
        if before["cloud_only"]:
            raise ValueError("Cloud-only content is held for explicit download outside this scan")
        if (before["size"],before["mtime_ns"])!=(record["size"],record["mtime_ns"]):
            raise ValueError("A file changed since the inventory. Scan the root again.")
        if record["path"] not in hashes:
            digest=sha256()
            with path.open("rb") as stream:
                while chunk:=stream.read(2*1024**2):
                    digest.update(chunk)
                    done+=len(chunk)
                    progress(int(95*done/max(total,1)),"Reading local media for SHA-256 verification")
            after=file_record(path)
            if (before["size"],before["mtime_ns"])!=(after["size"],after["mtime_ns"]):
                raise ValueError("A media file changed during hashing")
            hashes[record["path"]]=digest.hexdigest()
    return {"pair_id":pair_id,"same_file_bytes":len(set(hashes.values()))==1,
            "paths":[r["path"] for r in records],"sha256":hashes}
