"""Inspect a desktop library through private database copies, never source SQL."""
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3

from engine import is_auto
from media import cloud_placeholder
from metadata_export import capture_database


COMPATIBILITY=[
    {"version":"5 and earlier","format":"DeviceSQL · datafile.edb","status":"Detection and file inventory only",
     "detail":"Legacy records are not decoded. Convert a copy with rekordbox if you need modern database analysis."},
    {"version":"6","format":"SQLCipher SQLite · master.db","status":"Schema-based read-only checks",
     "detail":"The reader targets this format family. Validation against a genuine v6 sample is pending."},
    {"version":"7","format":"SQLCipher SQLite · master.db","status":"Reader checked with v7.2.19 backup data",
     "detail":"Source-folder checks run on a private copy. A restore and live-library check in Windows rekordbox remain pending."},
    {"version":"USB / device export","format":"export.pdb or exportLibrary.db","status":"Detected separately",
     "detail":"Classic Device Library and OneLibrary (formerly Device Library Plus) are device formats. Their records are not decoded here."},
]


def quoted(name):
    return '"'+name.replace('"','""')+'"'


def file_stamp(path):
    try:
        value=path.stat()
        return {"bytes":value.st_size,"mtime_ns":value.st_mtime_ns,"inode":value.st_ino}
    except FileNotFoundError:
        return None


def source_stamps(root):
    return {name:file_stamp(root/name) for name in ("master.db","master.db-wal","master.db-journal")}


def snapshot_database(root,destination,progress):
    before=source_stamps(root)
    if not before["master.db"]:raise ValueError("The source master.db is unavailable")
    destination.mkdir(parents=True,exist_ok=True)
    copied=[]
    for name,stamp in before.items():
        if not stamp:continue
        if cloud_placeholder((root/name).stat()):
            raise ValueError("A source database or journal file is online-only. Make it available locally before capturing a snapshot.")
        digest=sha256()
        with (root/name).open("rb") as src,(destination/name).open("xb") as out:
            while chunk:=src.read(2*1024**2):
                out.write(chunk)
                digest.update(chunk)
        copied.append({"name":name,**stamp,"sha256":digest.hexdigest()})
        progress(15,"Copied "+name+" into the private analysis workspace")
    if source_stamps(root)!=before:
        raise ValueError("The source database changed during capture. Close rekordbox, pause library sync and try again.")
    return copied,before


def analysis_folder(path):
    value=str(path or "").replace("\\","/").casefold()
    marker="usbanlz/"
    return marker+value.split(marker,1)[1].rsplit("/",1)[0] if marker in value else None


def footprint(root,progress):
    totals=defaultdict(lambda:{"files":0,"bytes":0})
    directories=set()
    warnings=[]
    files=total=0
    cloud=0
    def unreadable(error):warnings.append(str(error))
    for folder,children,names in os.walk(root,followlinks=False,onerror=unreadable):
        children[:]=[name for name in children if not (Path(folder)/name).is_symlink() and not (Path(folder)/name).is_junction()]
        for name in names:
            path=Path(folder)/name
            if path.is_symlink():continue
            try:
                stat=path.stat()
            except OSError as error:
                warnings.append(str(error));continue
            extension=path.suffix.lower() or "(no extension)"
            totals[extension]["files"]+=1
            totals[extension]["bytes"]+=stat.st_size
            files+=1;total+=stat.st_size
            if cloud_placeholder(stat):cloud+=1
            key=analysis_folder(path.relative_to(root))
            if key:directories.add(key)
            if files%5000==0:progress(40,f"Counted {files:,} files in the selected source folder")
    return {"files":files,"bytes":total,"cloud_placeholders":cloud,
            "extensions":[{"extension":extension,**values} for extension,values in sorted(totals.items(),key=lambda row:row[1]["bytes"],reverse=True)],
            "warnings":warnings[:20],"unreadable_entries":len(warnings)},directories


def inspect_database(path,asset_folders):
    with path.open("rb") as stream:plaintext=stream.read(16)==b"SQLite format 3\x00"
    if plaintext:
        db=sqlite3.connect(path)
    else:
        from native_export import mutable_copy
        db=mutable_copy(path)
    with closing(db):
        # Opening the private copy permits its own journal recovery. No database
        # connection is ever made to the selected source path.
        db.execute("SELECT count(*) FROM sqlite_schema").fetchone()
        db.execute("PRAGMA query_only=ON")
        integrity=[row[0] for row in db.execute("PRAGMA integrity_check(20)")]
        tables={row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        columns={name:{row[1] for row in db.execute("PRAGMA table_info("+quoted(name)+")")} for name in tables}
        schema_digest=sha256(json.dumps({name:sorted(cols) for name,cols in sorted(columns.items())},sort_keys=True).encode()).hexdigest()
        result={"encryption":"Unencrypted SQLite" if plaintext else "SQLCipher SQLite",
                "integrity":integrity,"integrity_ok":integrity==["ok"],"table_count":len(tables),
                "schema_sha256":schema_digest,"sqlite_user_version":db.execute("PRAGMA user_version").fetchone()[0],
                "tables":sorted(tables),"missing_core_columns":[],"counters":{},"health":{},"notes":[]}
        for field in ("ID","Title","FolderPath"):
            if field not in columns.get("djmdContent",set()):result["missing_core_columns"].append("djmdContent."+field)
        if result["missing_core_columns"]:
            result["notes"].append("This database does not expose the desktop track schema required for detailed checks.")
            return result

        def active(table,alias=""):
            return "coalesce("+(alias+"." if alias else "")+"rb_local_deleted,0)=0" if "rb_local_deleted" in columns[table] else "1=1"

        def rows(table,wanted):
            if table not in tables:return []
            fields=','.join(quoted(name) if name in columns[table] else "NULL AS "+quoted(name) for name in wanted)
            return [dict(zip(wanted,row)) for row in db.execute("SELECT "+fields+" FROM "+quoted(table)+" WHERE "+active(table))]

        tracks=rows("djmdContent",["ID","Title","FolderPath","OrgFolderPath","FileSize","Length","Rating","DJPlayCount","Analysed","AnalysisDataPath","ArtistID","AlbumID"])
        ids={t["ID"] for t in tracks}
        cues=rows("djmdCue",["ContentID","Comment"])
        cue_groups=defaultdict(list)
        for cue in cues:
            if cue["ContentID"] in ids:cue_groups[cue["ContentID"]].append(cue)
        counters={"tracks":len(tracks),"rated":sum(bool(t["Rating"]) for t in tracks) if "Rating" in columns["djmdContent"] else None,
                  "analysed":sum(bool(t["Analysed"]) for t in tracks) if "Analysed" in columns["djmdContent"] else None,
                  "cue_rows":len(cues) if "djmdCue" in tables else None,"full_manual":None,"mixed":None,"only_auto":None,"no_cues":None,"no_cues_no_plays":None}
        if {"ContentID","Comment"}<=columns.get("djmdCue",set()):
            for name in ("full_manual","mixed","only_auto","no_cues","no_cues_no_plays"):counters[name]=0
            if "DJPlayCount" not in columns["djmdContent"]:counters["no_cues_no_plays"]=None
            for track in tracks:
                saved=cue_groups[track["ID"]]
                automated=sum(is_auto(cue) for cue in saved)
                other=len(saved)-automated
                counters["full_manual"]+=other>0 and automated==0
                counters["mixed"]+=other>0 and automated>0
                counters["only_auto"]+=automated>0 and other==0
                counters["no_cues"]+=not saved
                if counters["no_cues_no_plays"] is not None:counters["no_cues_no_plays"]+=not saved and not track["DJPlayCount"]
        metadata_records={}
        for name,table,field in (("artists","djmdArtist","ArtistID"),("albums","djmdAlbum","AlbumID")):
            records=rows(table,["ID","Name"])
            used={t[field] for t in tracks if t[field]}
            counters[name]=len({str(r["Name"]).strip().casefold() for r in records if r["ID"] in used and r["Name"] and str(r["Name"]).strip()}) if {"ID","Name"}<=columns.get(table,set()) else None
            metadata_records[name+"_rows"]=len(records) if table in tables else None
        playlists=rows("djmdPlaylist",["ID","Attribute"])
        counters["playlists"]=sum((p["Attribute"] or 0)!=1 for p in playlists) if "Attribute" in columns.get("djmdPlaylist",set()) else None
        links={}
        for table in tables:
            if "ContentID" not in columns[table]:continue
            count=db.execute("SELECT count(*) FROM "+quoted(table)+" r LEFT JOIN djmdContent c ON c.ID=r.ContentID WHERE "+active(table,"r")+" AND r.ContentID IS NOT NULL AND (c.ID IS NULL OR NOT ("+active("djmdContent","c")+"))").fetchone()[0]
            if count:links[table]=count
        paths=Counter(str(t["FolderPath"] or "").replace("\\","/").casefold() for t in tracks if t["FolderPath"])
        owners={key for t in tracks if (key:=analysis_folder(t["AnalysisDataPath"]))}
        owners|={key for row in rows("contentFile",["Path"]) if (key:=analysis_folder(row["Path"]))}
        health={"broken_track_links":sum(links.values()),"broken_links_by_table":links,
                "duplicate_recorded_path_groups":sum(count>1 for count in paths.values()),
                "tracks_in_duplicate_paths":sum(count for count in paths.values() if count>1),
                "analysis_folders_found":len(asset_folders),"unlinked_analysis_folders":len(asset_folders-owners) if "AnalysisDataPath" in columns["djmdContent"] else None,
                "analysis_folders_not_found_here":len(owners-asset_folders) if "AnalysisDataPath" in columns["djmdContent"] else None,"audio_availability":None}
        result.update(counters=counters,health=health,metadata_records=metadata_records)
        result["track_paths"]=[{"id":t["ID"],"current_path":t["FolderPath"],"original_path":t["OrgFolderPath"],"size":t["FileSize"]} for t in tracks]
        result["health"]["different_original_paths"]=sum(bool(t["OrgFolderPath"] and str(t["OrgFolderPath"]).replace("\\","/").casefold()!=str(t["FolderPath"] or "").replace("\\","/").casefold()) for t in tracks)
        result["cloud_related_columns_present"]=sorted(columns["djmdContent"] & {"CloudID","ServiceID","DeviceID","OrgFolderPath","FileID","MasterDBID"})
        if any(value is None for value in counters.values()):result["notes"].append("Some optional tables or columns are absent. Their statistics are shown as unavailable rather than zero.")
        result["notes"].extend(["Cue origin is inferred from CUE(Auto) and 1.1Bars labels; labels can be edited.",
            "Cue counters use active djmdCue rows. Mirrored cue JSON is not counted a second time.",
            "Album and artist counters count distinct names referenced by active tracks, not unused metadata rows.",
            "Repeated recorded paths are review candidates, not proof that files are identical.",
            "Analysis-folder absence is scoped to the selected folder; the analysis data may be stored elsewhere.",
            "Music-file existence and cloud download state are not established by database records."])
        if result["integrity_ok"]:
            result["metadata_snapshot"] = capture_database(db, columns)
        return result


def analyze_folder(source,output,progress,version_hint=""):
    root=Path(str(source).strip().strip('"')).expanduser()
    if not root.is_absolute() or not root.is_dir():raise ValueError("Choose the full path of the rekordbox data folder")
    root=root.resolve()
    output=Path(output).resolve()
    if output.is_relative_to(root):raise ValueError("Choose the rekordbox data folder, not a parent of this application's workspace")
    if version_hint and not re.fullmatch(r"\d{1,2}(?:\.\d+){0,3}",version_hint):raise ValueError("Enter a version such as 7.2.19, or leave it blank")
    modern=(root/"master.db").is_file()
    legacy=[path for path in root.iterdir() if path.suffix.lower()==".edb" and path.is_file()]
    device=any((root/name).is_file() for name in ("export.pdb","exportLibrary.db","PIONEER/rekordbox/export.pdb","PIONEER/rekordbox/exportLibrary.db"))
    if not modern and not legacy and not device:raise ValueError("No master.db, legacy .edb or device export database was found. Select the folder containing the database.")
    output.mkdir(parents=True,exist_ok=True)
    result={"id":output.name,"created":datetime.now(timezone.utc).isoformat(),"source":str(root),"version_hint":version_hint or None,
            "mode":"Read-only source-folder analysis","source_writes":False,"compatibility_matrix":COMPATIBILITY,
            "format":"Modern desktop master.db" if modern else "Legacy .edb candidate" if legacy else "USB / device export",
            "source_files":[],"database":None,"messages":[],"directory":str(output)}
    stamps=None
    if modern:
        result["source_files"],stamps=snapshot_database(root,output/"snapshot",progress)
        if stamps.get("master.db-wal") or stamps.get("master.db-journal"):
            result["messages"].append({"level":"info","text":"Database journal files were captured with the private copy. Close rekordbox and pause sync before capture for a stable snapshot."})
        if legacy:result["messages"].append({"level":"info","text":"Legacy .edb files are also present. This report inspects master.db; older files were not converted or merged."})
    inventory,assets=footprint(root,progress)
    result["footprint"]=inventory
    if modern:
        progress(60,"Checking database integrity and library relationships on the private copy")
        try:
            result["database"]=inspect_database(output/"snapshot/master.db",assets)
            db=result["database"]
            metadata=db.pop("metadata_snapshot",None)
            result["metadata_available"]=metadata is not None
            if metadata is not None:
                metadata["version"]=version_hint or None
                (output/"metadata.json").write_text(json.dumps(metadata,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
            paths=db.pop("track_paths",[])
            result["track_paths_available"]=bool(paths)
            if paths:(output/"track-paths.json").write_text(json.dumps(paths,ensure_ascii=False),encoding="utf-8")
            result["read_status"]="checked" if db["integrity_ok"] and not db["missing_core_columns"] else "needs_review"
            if not db["integrity_ok"]:result["messages"].append({"level":"warning","text":"The private database copy failed its integrity check. Review the report before attempting any conversion or restore."})
            if db["missing_core_columns"]:result["messages"].append({"level":"warning","text":"The schema differs from the recognized desktop format. Detailed library counters are unavailable."})
        except Exception as error:
            result["read_status"]="unsupported"
            result["messages"].append({"level":"warning","text":"The private database copy could not be read with the available database reader: "+str(error)})
        if version_hint.startswith("6"):
            result["messages"].append({"level":"info","text":"Version 6 was supplied by the user. This tool has not yet been validated against a genuine v6 library sample."})
        elif version_hint.startswith("5"):
            result["messages"].append({"level":"warning","text":"The supplied v5 version conflicts with the modern master.db format. Check which library folder is selected."})
        else:
            result["messages"].append({"level":"info","text":"master.db identifies the v6/v7 format family, not the exact application version. A restore or live-library check in Windows rekordbox remains to be validated."})
        if source_stamps(root)!=stamps:
            raise ValueError("The source database changed while the report was running. Close rekordbox, pause sync and capture again.")
        result["source_unchanged"]=True
    else:
        result["read_status"]="inventory_only"
        result["messages"].append({"level":"warning","text":"Legacy/device database records are not decoded in this version. This report provides format detection and file footprint only; no conversion was performed."})
    if inventory["unreadable_entries"]:result["messages"].append({"level":"warning","text":"Some source-folder entries could not be inspected. Footprint counts are partial."})
    (output/"report.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    progress(100,"Read-only report saved")
    return result
