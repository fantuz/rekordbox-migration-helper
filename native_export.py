"""Experimental native backup writer for isolated rekordbox restore testing."""
from contextlib import closing
from copy import copy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
import json
import os
import sqlite3
import struct
import zipfile
from xml.etree import ElementTree

from engine import decision_map, open_master, position


def mutable_copy(path):
    from sqlcipher3 import dbapi2 as cipher
    from pyrekordbox.masterdb.database import BLOB
    from pyrekordbox.utils import deobfuscate
    db=cipher.connect(str(path))
    key=deobfuscate(BLOB).replace("'","''")
    db.execute("PRAGMA key='"+key+"'")
    db.row_factory=__import__("sqlcipher3").Row
    return db


def copy_member_raw(source, target, info, end_offset):
    """Preserve compressed bytes, including Zip64 local headers and descriptors.

    zipfile has no public compressed-copy API. Only this helper uses its writer
    bookkeeping. Finalization by zipfile rebuilds the central directory offsets.
    """
    member=copy(info)
    target.fp.seek(target.start_dir)
    member.header_offset=target.fp.tell()
    source.fp.seek(info.header_offset)
    remaining=end_offset-info.header_offset
    if remaining<30:
        raise ValueError("Invalid ZIP member boundary")
    while remaining:
        chunk=source.fp.read(min(2*1024**2,remaining))
        if not chunk:
            raise ValueError("Truncated source ZIP member")
        target.fp.write(chunk)
        remaining-=len(chunk)
    target.filelist.append(member)
    target.NameToInfo[member.filename]=member
    target.start_dir=target.fp.tell()
    target._didModify=True


def rewrite_archive(source_path, destination, replacements, progress):
    temporary=destination.with_suffix(".partial")
    with zipfile.ZipFile(source_path) as source, zipfile.ZipFile(temporary,"w",allowZip64=True) as target:
        infos=sorted(source.infolist(),key=lambda i:i.header_offset)
        names=[i.filename for i in infos]
        if len(names)!=len(set(names)):
            raise ValueError("Backup contains repeated ZIP paths")
        for n,info in enumerate(infos):
            if info.filename in replacements:
                replacement=replacements[info.filename]
                member=copy(info)
                # Clear flags managed by zipfile for the newly compressed entry.
                member.flag_bits=0
                if isinstance(replacement,Path):
                    with replacement.open("rb") as src,target.open(member,"w",force_zip64=True) as dst:
                        while chunk:=src.read(2*1024**2):
                            dst.write(chunk)
                else:
                    target.writestr(member,replacement)
            else:
                end=infos[n+1].header_offset if n+1<len(infos) else source.start_dir
                copy_member_raw(source,target,info,end)
            if n%1500==0:
                progress(35+int(55*n/max(len(infos),1)),f"Writing backup member {n:,} / {len(infos):,}")
    with zipfile.ZipFile(temporary) as checked,zipfile.ZipFile(source_path) as original:
        if checked.namelist()!=[i.filename for i in sorted(original.infolist(),key=lambda i:i.header_offset)]:
            raise ValueError("Backup member list changed unexpectedly")
        for info in checked.infolist():
            if info.filename not in replacements:
                prior=original.getinfo(info.filename)
                if (info.CRC,info.file_size,info.compress_size)!=(prior.CRC,prior.file_size,prior.compress_size):
                    raise ValueError("An unrelated backup member changed")
        for name,replacement in replacements.items():
            expected=sha256()
            if isinstance(replacement,Path):
                with replacement.open("rb") as stream:
                    while chunk:=stream.read(2*1024**2):expected.update(chunk)
            else:
                expected.update(replacement)
            actual=sha256()
            with checked.open(name) as stream:
                while chunk:=stream.read(2*1024**2):actual.update(chunk)
            if actual.digest()!=expected.digest():
                raise ValueError("Replaced backup member failed verification")
    os.replace(temporary,destination)


def export_native(catalog,decisions,relocations,destination,progress):
    mapping,results=decision_map(catalog,decisions)
    folder=destination.parent
    master=folder/"native-master.db"
    backup=Path(catalog.metadata["zip_path"])
    with zipfile.ZipFile(backup) as archive:
        contents=archive.read("contents.xml")
        with archive.open("master.db") as src,master.open("wb") as dst:
            while chunk:=src.read(2*1024**2):dst.write(chunk)
    progress(5,"Applying decisions to an encrypted database copy")
    timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]+" +00:00"
    with closing(mutable_copy(master)) as db:
        tables={r[0]:{c[1] for c in db.execute('PRAGMA table_info("'+r[0]+'")')}
                for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        before=db.execute("SELECT count(*) FROM djmdContent WHERE rb_local_deleted=0").fetchone()[0]
        registry=db.execute("SELECT int_1 FROM agentRegistry WHERE registry_id='localUpdateCount'").fetchone()
        if registry is None:
            raise ValueError("Unsupported update registry; native export was stopped")
        usn=registry[0] or 0
        changed=0

        def update(table,where,params,values):
            nonlocal usn,changed
            count=db.execute('SELECT count(*) FROM "'+table+'" WHERE '+where,params).fetchone()[0]
            if not count:return
            usn+=1
            values=dict(values)
            if "rb_local_usn" in tables[table]:values["rb_local_usn"]=usn
            if "updated_at" in tables[table]:values["updated_at"]=timestamp
            if "rb_local_synced" in tables[table]:values["rb_local_synced"]=0
            fields=list(values)
            sql='UPDATE "'+table+'" SET '+",".join('"'+k+'"=?' for k in fields)+" WHERE "+where
            db.execute(sql,[values[k] for k in fields]+list(params))
            changed+=count

        with db:
            for donor,keeper in mapping.items():
                keep_uuid=db.execute("SELECT UUID FROM djmdContent WHERE ID=?",(keeper,)).fetchone()[0]
                # Retire registration/gain rows belonging to discarded source assets.
                for table,columns in tables.items():
                    if "ContentID" not in columns or table=="djmdCue":
                        continue
                    if table in ("contentFile","contentCue","djmdMixerParam"):
                        if "rb_local_deleted" not in columns:
                            raise ValueError("Unsupported relation "+table)
                        update(table,"ContentID=? AND rb_local_deleted=0",(donor,),{"rb_local_deleted":1})
                    else:
                        values={"ContentID":keeper}
                        if "ContentUUID" in columns:values["ContentUUID"]=keep_uuid
                        update(table,"ContentID=?"+(" AND rb_local_deleted=0" if "rb_local_deleted" in columns else ""),(donor,),values)
                for table,columns in tables.items():
                    for field in ("ContentID1","ContentID2"):
                        if field in columns:
                            update(table,'"'+field+'"=?',(donor,),{field:keeper})
                update("djmdContent","ID=?",(donor,),{"rb_local_deleted":1})

            final_cues={}
            for keeper,result in results.items():
                keep_uuid=db.execute("SELECT UUID FROM djmdContent WHERE ID=?",(keeper,)).fetchone()[0]
                donors=result.get("donors",[result["donor"]])
                selected_ids={c.get("ID") for c in result["cues"]}
                group_ids=[keeper,*donors]
                placeholders=",".join("?" for _ in group_ids)
                existing=list(db.execute("SELECT * FROM djmdCue WHERE ContentID IN ("+placeholders+") AND rb_local_deleted=0",group_ids))
                for c in existing:
                    if c["ID"] not in selected_ids:
                        update("djmdCue","ID=?",(c["ID"],),{"rb_local_deleted":1})
                for cue in result["cues"]:
                    row=db.execute("SELECT * FROM djmdCue WHERE ID=?",(cue.get("ID"),)).fetchone()
                    if row is None:
                        # A serialized-only cue can be reconstructed using its saved
                        # seek/frame fields. XML-only cues lack native seek metadata.
                        if cue.get("representation")=="xml":
                            raise ValueError("A staged XML-only cue needs native cue conversion validation")
                        source_cue=None
                        for cache in db.execute("SELECT Cues FROM contentCue WHERE ContentID IN ("+placeholders+")",group_ids):
                            source_cue=next((c for c in json.loads(cache[0] or "[]") if c.get("ID")==cue.get("ID")),None)
                            if source_cue:break
                        if not source_cue:
                            raise ValueError("Native cue metadata unavailable for "+str(cue.get("ID")))
                        values={k:v for k,v in source_cue.items() if k in tables["djmdCue"]}
                        values.update(ContentID=keeper,ContentUUID=keep_uuid,UUID=values.get("UUID") or str(uuid4()),
                                      created_at=values.get("created_at") or timestamp,updated_at=timestamp,rb_local_deleted=0)
                        usn+=1
                        values["rb_local_usn"]=usn
                        fields=list(values)
                        db.execute("INSERT INTO djmdCue ("+",".join('"'+f+'"' for f in fields)+") VALUES ("+",".join("?" for _ in fields)+")",[values[f] for f in fields])
                        changed+=1
                    values={k:v for k,v in cue.items() if k in tables["djmdCue"] and k not in ("ID","ContentUUID","UUID","ContentID","created_at","rb_local_usn","usn")}
                    values.update(ContentID=keeper,ContentUUID=keep_uuid,rb_local_deleted=0)
                    update("djmdCue","ID=?",(cue["ID"],),values)
                rows=[dict(c) for c in db.execute("SELECT * FROM djmdCue WHERE ContentID=? AND rb_local_deleted=0 ORDER BY Kind,InMsec",(keeper,))]
                final_cues[keeper]=rows
                mirrored=json.dumps(rows,ensure_ascii=False,separators=(",",":"))
                existing_cache=db.execute("SELECT ID FROM contentCue WHERE ContentID=? AND rb_local_deleted=0",(keeper,)).fetchone()
                if existing_cache:
                    update("contentCue","ID=?",(existing_cache[0],),{"Cues":mirrored,"rb_cue_count":len(rows)})
                else:
                    usn+=1
                    db.execute("""INSERT INTO contentCue
                        (ID,ContentID,Cues,rb_cue_count,UUID,rb_local_deleted,rb_local_usn,created_at,updated_at)
                        VALUES (?,?,?,?,?,0,?,?,?)""",(str(uuid4()),keeper,mirrored,len(rows),str(uuid4()),usn,timestamp,timestamp))
                update("djmdContent","ID=?",(keeper,),{"Rating":result["rating"],"CueUpdated":1})
            for track,uri in relocations.items():
                from urllib.parse import urlsplit,unquote
                parsed=urlsplit(uri,allow_fragments=False)
                if parsed.scheme!="file":
                    raise ValueError("Native relocation requires a file URI")
                path=unquote(parsed.path)
                if parsed.netloc.lower() not in ("","localhost"):path="//"+parsed.netloc+path
                elif len(path)>2 and path[0]=="/" and path[2]==":":path=path[1:]
                row=db.execute("SELECT ServiceID FROM djmdContent WHERE ID=?",(track,)).fetchone()
                if row is None:raise ValueError("Unknown native relocation track")
                if row[0] not in (0,None):
                    raise ValueError("Cloud-associated references need a verified cloud relocation workflow")
                if track in mapping:raise ValueError("Relocate the chosen keeper rather than a retired donor")
                update("djmdContent","ID=?",(track,),{"FolderPath":path.replace("\\","/")})
            db.execute("UPDATE agentRegistry SET int_1=?,updated_at=? WHERE registry_id='localUpdateCount'",(usn,timestamp))

            after=db.execute("SELECT count(*) FROM djmdContent WHERE rb_local_deleted=0").fetchone()[0]
            if after!=before-len(mapping):raise ValueError("Native track count validation failed")
            for table,columns in tables.items():
                if "ContentID" in columns:
                    deleted="r.rb_local_deleted=0 AND " if "rb_local_deleted" in columns else ""
                    dangling=db.execute('SELECT count(*) FROM "'+table+'''"
                        r LEFT JOIN djmdContent c ON c.ID=r.ContentID WHERE '''+deleted+"""r.ContentID IS NOT NULL
                        AND (c.ID IS NULL OR c.rb_local_deleted!=0)""").fetchone()[0]
                    if dangling:raise ValueError("Active native relation points at retired content in "+table)
            for keeper,result in results.items():
                actual={(c["Kind"],c["InMsec"],c["OutMsec"] if c["OutMsec"] is not None and c["OutMsec"]>=0 else -1) for c in final_cues[keeper]}
                expected={(c["Kind"],*position(c)) for c in result["cues"]}
                if actual!=expected:raise ValueError("Native cue verification failed")
            if [tuple(r) for r in db.execute("PRAGMA integrity_check")]!=[("ok",)]:
                raise ValueError("Native database integrity check failed")
        if db.execute("PRAGMA cipher_integrity_check").fetchone():
            raise ValueError("Encrypted page verification failed")
    root=ElementTree.fromstring(contents)
    for value in root.iter("VALUE"):
        if value.get("name")=="CONTENT_NUM":value.set("val",str(after))
    contents=ElementTree.tostring(root,encoding="utf-8",xml_declaration=True)
    progress(30,"Database validated; copying compressed backup data")
    rewrite_archive(backup,destination,{"master.db":master,"contents.xml":contents},progress)
    return {"active_tracks_before":before,"active_tracks_after":after,"merges":len(mapping),"changed_rows":changed,
            "relocations":len(relocations),"bytes":destination.stat().st_size,"local_update_count":usn,
            "format":"Experimental native rekordbox Backup Library ZIP",
            "restore_validation":"Verify in an isolated Windows library with Cloud Library Sync paused before replacing your working library."}
