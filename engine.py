"""Offline rekordbox review, with streaming inputs and reversible decisions."""
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.parsers import expat
import json
import ntpath
import re
import sqlite3
import struct
import zipfile

AUTO_LABELS = {"cue(auto)", "1.1bars"}
HOT_NUMBERS = dict(zip((1, 2, 3, 5, *range(6, 18)), range(16)))


def is_auto(cue):
    return (cue.get("Comment") or "").strip().casefold() in AUTO_LABELS


def position(cue):
    end = cue.get("OutMsec")
    return cue.get("InMsec"), end if end is not None and end >= 0 else -1


def path_key(value):
    if not value:
        return ""
    if value.startswith("file:"):
        uri = urlsplit(value, allow_fragments=False)
        value = unquote(uri.path)
        if uri.netloc.lower() not in ("", "localhost"):
            value = "//" + uri.netloc + value
        elif re.match(r"^/[a-z]:", value, re.I):
            value = value[1:]
    return ntpath.normpath(value.replace("/", "\\")).casefold()


def asset_key(value):
    value = (value or "").replace("\\", "/").casefold().lstrip("/")
    i = value.rfind("/pioneer/")
    return value[i + 1:] if i >= 0 else value


def norm(value):
    return " ".join((value or "").split()).casefold()


def read_tags(archive, member):
    data = archive.read(member)
    if len(data) < 12 or data[:4] != b"PMAI":
        return {}
    offset, total = struct.unpack_from(">II", data, 4)
    if total != len(data) or offset < 12:
        return {}
    tags = {}
    while offset + 12 <= total:
        tag, header, length = struct.unpack_from(">4sII", data, offset)
        if not 12 <= header <= length or offset + length > total:
            return {}
        tags[tag] = data[offset + header:offset + length]
        offset += length
    return tags


def primary_cues_equal(a, b):
    return a["Kind"] == b["Kind"] and position(a) == position(b)


class Catalog:
    def __init__(self, source, metadata):
        self.source = Path(source)
        self.metadata = metadata
        self.policy = "newest"
        self.tracks = {}
        self.cues = defaultdict(list)
        self.pairs = {}
        self.source_cue_conflicts = defaultdict(list)
        with closing(sqlite3.connect(self.source)) as db:
            db.row_factory = sqlite3.Row
            for r in db.execute("SELECT * FROM source_track"):
                t = dict(r)
                t["xml_marks"] = json.loads(t.get("xml_marks_json") or "[]")
                t.update(date_added=None,last_played=None)
                self.tracks[t["track_id"]] = t
            for r in db.execute("SELECT source_track_id,cue_json FROM source_cue"):
                self.cues[r[0]].append(json.loads(r[1]))
            for r in db.execute("SELECT donor_id,candidate_id,evidence_rank FROM match_candidate"):
                if r[2] <= 2:
                    self.add_pair(r[0], r[1], r[2])
            try:
                for r in db.execute("SELECT track_a,track_b,evidence FROM same_cohort_review"):
                    self.add_pair(r[0], r[1], 1 if r[2].startswith("same_path") else 2)
            except sqlite3.OperationalError:
                pass
        inverse = {number:kind for kind,number in HOT_NUMBERS.items()}
        for i,t in self.tracks.items():
            for mark in t["xml_marks"]:
                number=int(mark.get("Num",-1))
                kind=0 if number==-1 else inverse.get(number)
                if kind is None:
                    self.source_cue_conflicts[i].append({"type":"unsupported_xml_cue","auto":False})
                    continue
                cue={"ID":"xml:"+i+":"+str(number)+":"+mark["Start"],"ContentID":i,"Kind":kind,
                     "InMsec":round(float(mark["Start"])*1000),
                     "OutMsec":round(float(mark["End"])*1000) if "End" in mark else -1,
                     "Comment":mark.get("Name") or "", "representation":"xml"}
                slots=[c for c in self.cues[i] if c["Kind"]==kind]
                same=any(c["Kind"]==kind and c["InMsec"]==cue["InMsec"] and position(c)[1]==cue["OutMsec"] for c in slots)
                if same:
                    continue
                if slots and kind!=0:
                    self.source_cue_conflicts[i].append({"type":"input_cue_versions","kind":kind,
                        "auto":is_auto(cue) and all(is_auto(c) for c in slots),
                        "xml_time":position(cue),"native_times":[position(c) for c in slots]})
                else:
                    self.cues[i].append(cue)
        self.counts = {}
        self.refresh_counts()

    def add_pair(self, a, b, rank):
        if a == b or a not in self.tracks or b not in self.tracks:
            return
        key = "~".join(sorted((a, b)))
        if key not in self.pairs or rank < self.pairs[key]["rank"]:
            self.pairs[key] = {"id": key, "a": a, "b": b, "rank": rank}

    def cue_summary(self, track_id):
        cues = self.cues[track_id]
        auto = sum(is_auto(c) for c in cues)
        return {"total": len(cues), "auto": auto, "other": len(cues) - auto}

    def preferred(self, pair):
        a, b = pair["a"], pair["b"]
        ca, cb = self.cue_summary(a), self.cue_summary(b)
        if bool(ca["other"]) != bool(cb["other"]):
            return (a if ca["other"] else b), "Contains cues without automatic labels"
        ta, tb = self.tracks[a], self.tracks[b]
        field = {"newest":"date_added","last_played":"last_played","play_count":"play_count"}[self.policy]
        va,vb = ta.get(field),tb.get(field)
        if va != vb and (va or vb):
            if field == "play_count":
                selected = a if (va or 0) > (vb or 0) else b
            else:
                selected = a if str(va or "") > str(vb or "") else b
            return selected, {"newest":"Most recently added","last_played":"Most recent saved play history","play_count":"Higher recorded play count"}[self.policy]
        if ta["october_xml"] != tb["october_xml"]:
            return (a if ta["october_xml"] else b), "Present in the supplied XML"
        if bool(ta["rating"]) != bool(tb["rating"]):
            return (a if ta["rating"] else b), "Has a saved rating"
        return min(a, b), "Stable selection; review the playable file"

    def merge(self, pair, keeper=None, prefer_auto=False, prefer_rating=False, accumulated=None):
        keeper = keeper or self.preferred(pair)[0]
        if keeper not in (pair["a"], pair["b"]):
            raise ValueError("Keeper must belong to this pair")
        donor = pair["b"] if keeper == pair["a"] else pair["a"]
        out = [dict(c) for c in (accumulated["cues"] if accumulated else self.cues[keeper])]
        conflicts = [c for i in (keeper,donor) for c in self.source_cue_conflicts[i] if not (prefer_auto and c["auto"])]
        changes = []
        for cue in self.cues[donor]:
            slots = [c for c in out if c["Kind"] == cue["Kind"]]
            same = next((c for c in slots if primary_cues_equal(c, cue)), None)
            if same is not None:
                # A custom label takes precedence over an automatic placeholder.
                a, b = same.get("Comment") or "", cue.get("Comment") or ""
                if is_auto(same) and not is_auto(cue):
                    same.update({k: v for k, v in cue.items() if k in ("Comment", "Color", "ColorTableIndex") and v is not None})
                    changes.append({"type": "cue_label_recovered", "kind": cue["Kind"]})
                elif a and b and a != b and not is_auto(same) and not is_auto(cue):
                    conflicts.append({"type": "cue_label", "kind": cue["Kind"], "keeper": a, "donor": b})
                elif not a and b and not is_auto(cue):
                    same["Comment"] = b
                continue
            if slots and cue["Kind"] != 0:
                conflict = {"type": "cue_slot", "kind": cue["Kind"], "slot": HOT_NUMBERS.get(cue["Kind"]),
                            "keeper_times": [position(c) for c in slots], "donor_time": position(cue),
                            "auto": is_auto(cue), "label": cue.get("Comment") or ""}
                if is_auto(cue) and prefer_auto:
                    changes.append({**conflict, "type": "older_auto_cue_retired"})
                elif not is_auto(cue) and all(is_auto(c) for c in slots):
                    for existing in slots:
                        out.remove(existing)
                    out.append(dict(cue))
                    changes.append({"type": "other_cue_replaces_auto", "kind": cue["Kind"]})
                else:
                    conflicts.append(conflict)
            else:
                out.append(dict(cue))
                changes.append({"type": "cue_added", "kind": cue["Kind"]})
        ka, db = (accumulated["rating"] if accumulated else self.tracks[keeper]["rating"]), self.tracks[donor]["rating"]
        if ka and db and ka != db and not prefer_rating:
            conflicts.append({"type": "rating", "keeper": ka, "donor": db})
        return {"keeper": keeper, "donor": donor, "cues": out, "rating": ka or db,
                "conflicts": conflicts, "changes": changes}

    def describe(self, pair):
        keeper, reason = self.preferred(pair)
        plain = self.merge(pair, keeper)
        auto = self.merge(pair, keeper, prefer_auto=True)
        conflicts = plain["conflicts"]
        category = "ready" if not conflicts else "auto" if not auto["conflicts"] else "review"
        ta, tb = self.tracks[pair["a"]], self.tracks[pair["b"]]
        signature = lambda i: sorted((c["Kind"], *position(c)) for c in self.cues[i])
        equal = bool(self.cues[pair["a"]]) and signature(pair["a"]) == signature(pair["b"])
        pa={path_key(ta[k]) for k in ("current_path","original_path","xml_location") if ta.get(k)}
        pb={path_key(tb[k]) for k in ("current_path","original_path","xml_location") if tb.get(k)}
        ca,cb=self.cue_summary(pair["a"]),self.cue_summary(pair["b"])
        evidence={
            "preview_agrees":bool(ta["preview_sha256"]) and ta["preview_sha256"]==tb["preview_sha256"],
            "current_path_agrees":bool(ta["current_path"]) and path_key(ta["current_path"])==path_key(tb["current_path"]),
            "recorded_path_agrees":bool(pa & pb),
            "metadata_agrees":bool(ta["title"] and ta["artist"]) and norm(ta["title"])==norm(tb["title"]) and norm(ta["artist"])==norm(tb["artist"]),
            "cue_set_agrees":equal,"no_cues_both":ca["total"]==cb["total"]==0,
            "auto_only_both":ca["total"]>0 and cb["total"]>0 and ca["other"]==cb["other"]==0,
            "manual_present":bool(ca["other"] or cb["other"]),
            "grid_agrees":bool(ta["grid_sha256"]) and ta["grid_sha256"]==tb["grid_sha256"],
            "grid_differs":bool(ta["grid_sha256"] and tb["grid_sha256"]) and ta["grid_sha256"]!=tb["grid_sha256"],
            "rated":bool(ta["rating"] or tb["rating"]),
            "rating_conflict":bool(ta["rating"] and tb["rating"]) and ta["rating"]!=tb["rating"],
            "played":bool(ta["play_count"] or tb["play_count"]),
            "history":bool(ta.get("last_played") or tb.get("last_played")),
            "both_in_xml":bool(ta["october_xml"] and tb["october_xml"]),
            "input_mismatch":bool(self.source_cue_conflicts[pair["a"]] or self.source_cue_conflicts[pair["b"]]),
            "recency_differs":bool(ta.get("date_added") and tb.get("date_added")) and ta["date_added"]!=tb["date_added"]}
        return {**pair, "evidence":evidence, "keeper": keeper, "keeper_reason": reason, "category": category,
                "title": self.tracks[keeper]["title"], "artist": self.tracks[keeper]["artist"],
                "cue_equal": equal, "rating": self.tracks[keeper]["rating"],
                "cue_a": self.cue_summary(pair["a"]), "cue_b": self.cue_summary(pair["b"]),
                "conflicts": conflicts, "grid_differs": ta["grid_sha256"] != tb["grid_sha256"]}

    def refresh_counts(self):
        rows = [self.describe(p) for p in self.pairs.values()]
        self.descriptions = {r["id"]: r for r in rows}
        categories = Counter(r["category"] for r in rows)
        labels = Counter((c.get("Comment") or "") for cs in self.cues.values() for c in cs)
        parent={}
        def root(i):
            parent.setdefault(i,i)
            while parent[i]!=i:
                parent[i]=parent[parent[i]]
                i=parent[i]
            return i
        for r in rows:
            if r["category"]=="review":
                parent[root(r["a"])]=root(r["b"])
        manual_groups=len({root(i) for i in parent})
        self.counts = {"manual_groups":manual_groups,"manual_tracks":len(parent),"tracks": len(self.tracks), "xml_tracks": sum(bool(t["october_xml"]) for t in self.tracks.values()),
                       "pairs": len(rows), "identical_cues": sum(r["cue_equal"] for r in rows),
                       "manual_preferred": sum(self.preferred(p)[1].startswith("Contains") for p in self.pairs.values()),
                       "ready": categories["ready"], "auto": categories["auto"], "review": categories["review"],
                       "auto_labels": dict(labels.most_common(8))}

    def detail(self, pair_id):
        p = self.pairs[pair_id]
        return {**self.descriptions[pair_id], "tracks": [
            {**self.tracks[i], "cues": self.cues[i], "cue_summary": self.cue_summary(i)} for i in (p["a"], p["b"])
        ]}


def open_master(path):
    from sqlcipher3 import dbapi2 as cipher
    from pyrekordbox.masterdb.database import BLOB
    from pyrekordbox.utils import deobfuscate
    db = cipher.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    key = deobfuscate(BLOB).replace("'", "''")
    db.execute("PRAGMA key='" + key + "'")
    db.execute("PRAGMA query_only=ON")
    return db


def parse_xml(path, progress):
    tracks, playlists = {}, []
    parser = expat.ParserCreate()
    section = ""
    current = None
    depth = 0
    version = ""
    def start(name, attrs):
        nonlocal section, current, depth, version
        depth += 1
        if depth == 2:
            section = name
        if name == "PRODUCT":
            version = attrs.get("Version", "")
        if section == "COLLECTION":
            if name == "TRACK":
                current = attrs["TrackID"]
                if current in tracks:
                    raise ValueError("XML contains repeated TrackID values")
                tracks[current] = {"attrs": attrs, "marks": [], "tempo": 0}
            elif name == "POSITION_MARK":
                tracks[current]["marks"].append(attrs)
            elif name == "TEMPO":
                tracks[current]["tempo"] += 1
        elif section == "PLAYLISTS" and name == "TRACK":
            playlists.append(attrs["Key"])
    def end(name):
        nonlocal depth
        depth -= 1
    def reject(*args):
        raise ValueError("XML declarations with DTD or entities are unsupported")
    parser.StartElementHandler, parser.EndElementHandler = start, end
    parser.StartDoctypeDeclHandler = reject
    parser.EntityDeclHandler = reject
    digest = sha256()
    total, done = path.stat().st_size, 0
    with path.open("rb") as stream:
        while chunk := stream.read(2 * 1024 * 1024):
            parser.Parse(chunk, False)
            digest.update(chunk)
            done += len(chunk)
            if done % (32 * 1024 * 1024) == 0:
                progress(15 + int(20 * done / max(total, 1)), "Reading XML track and cue records")
        parser.Parse(b"", True)
    if not tracks:
        raise ValueError("XML has no Collection tracks")
    return tracks, playlists, version, digest.hexdigest()


def analyze(backup, xml, folder, progress, scratch=None):
    progress(5, "Reading backup directory")
    scratch=Path(scratch or folder);scratch.mkdir(parents=True,exist_ok=True)
    master = scratch / "master.db"
    with zipfile.ZipFile(backup) as archive:
        infos = archive.infolist()
        names = {i.filename for i in infos}
        if "master.db" not in names:
            if any(name.lower().endswith(".edb") for name in names):
                raise ValueError("This appears to contain a legacy rekordbox v5-or-earlier database. Legacy records are not decoded by this importer. Source analyzer can identify the folder and measure its footprint; convert a separate copy with rekordbox for modern database analysis.")
            if any(name.lower().endswith(("export.pdb","exportlibrary.db")) for name in names):
                raise ValueError("This is a USB/device export, not a desktop Backup Library ZIP. Select the backup produced by rekordbox Library > Backup Library.")
            raise ValueError("Backup must contain master.db at its root")
        if any(n in names for n in ("master.db-wal", "master.db-journal")):
            raise ValueError("Backup has an active database journal. Create a fresh Backup Library ZIP.")
        if archive.getinfo("master.db").file_size > 4 * 1024**3:
            raise ValueError("Database exceeds the 4 GB prototype limit")
        with archive.open("master.db") as src, master.open("wb") as dst:
            while chunk := src.read(2 * 1024 * 1024):
                dst.write(chunk)
        progress(10, "Checking database integrity")
        with closing(open_master(master.resolve())) as native:
            if native.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("Database integrity check failed")
            xml_tracks, playlists, version, xml_hash = parse_xml(xml, progress)
            native.row_factory = __import__("sqlcipher3").Row
            rows = [dict(r) for r in native.execute("""SELECT c.*,a.Name AS artist_name FROM djmdContent c
                LEFT JOIN djmdArtist a ON a.ID=c.ArtistID WHERE c.rb_local_deleted=0""")]
            by_id = {r["ID"]: r for r in rows}
            missing = set(xml_tracks) - by_id.keys()
            if missing:
                raise ValueError(f"{len(missing)} XML track IDs are absent from the backup. Select a matching pair.")
            mismatches = sum(int(x["attrs"].get("Size", "0")) != (by_id[i]["FileSize"] or 0) for i, x in xml_tracks.items())
            if mismatches:
                raise ValueError(f"{mismatches} XML file lengths differ from the backup. Select a matching pair.")
            progress(40, "Fingerprinting saved preview waveforms")
            assets = {}
            dats = [i for i in infos if "/USBANLZ/" in i.filename and i.filename.lower().endswith(".dat")]
            for n, member in enumerate(dats):
                if member.file_size > 20 * 1024**2:
                    continue
                tags = read_tags(archive, member)
                a, b, g = (tags.get(k) for k in (b"PWAV", b"PWV2", b"PQTZ"))
                signal = sha256(a + b).hexdigest() if a and b and len(set(a)) > 1 else None
                grid = sha256(g).hexdigest() if g else None
                assets[asset_key(member.filename)] = signal, grid
                if n % 1000 == 0:
                    progress(40 + int(35*n/max(len(dats), 1)), f"Fingerprinting analysis {n:,} / {len(dats):,}")
            output = folder / "catalog.sqlite3"
            with closing(sqlite3.connect(output)) as db:
                db.executescript("""
                    CREATE TABLE source_track(track_id TEXT PRIMARY KEY,title TEXT,artist TEXT,october_xml INTEGER,
                        size_bytes INTEGER,duration_seconds INTEGER,rating INTEGER,comment TEXT,device_id TEXT,service_id INTEGER,
                        current_path TEXT,original_path TEXT,xml_location TEXT,analysis_path TEXT,image_path TEXT,
                        preview_sha256 TEXT,grid_sha256 TEXT,xml_tempo_entries INTEGER,xml_marks_json TEXT,play_count INTEGER);
                    CREATE TABLE source_cue(cue_id TEXT PRIMARY KEY,source_track_id TEXT,source_representation TEXT,cue_json TEXT);
                    CREATE TABLE match_candidate(donor_id TEXT,candidate_id TEXT,evidence_rank INTEGER,
                        PRIMARY KEY(donor_id,candidate_id));
                    CREATE TABLE same_cohort_review(track_a TEXT,track_b TEXT,evidence TEXT,PRIMARY KEY(track_a,track_b));
                """)
                for r in rows:
                    x = xml_tracks.get(r["ID"])
                    signal, grid = assets.get(asset_key(r["AnalysisDataPath"]), (None, None))
                    db.execute("INSERT INTO source_track VALUES (" + ",".join("?"*20) + ")", (
                        r["ID"],r["Title"] or "",r["artist_name"] or "",bool(x),r["FileSize"] or 0,r["Length"] or 0,
                        r["Rating"] or 0,r["Commnt"] or "",r["DeviceID"],r["ServiceID"],r["FolderPath"],r["OrgFolderPath"],
                        x["attrs"]["Location"] if x else None,r["AnalysisDataPath"],r["ImagePath"],signal,grid,
                        x["tempo"] if x else None,json.dumps(x["marks"] if x else []),r["DJPlayCount"]))
                seen = set()
                for r in native.execute("SELECT * FROM djmdCue WHERE rb_local_deleted=0"):
                    c = dict(r)
                    if c["ContentID"] not in by_id:
                        continue
                    c["representation"] = "native"
                    seen.add(c["ID"])
                    db.execute("INSERT INTO source_cue VALUES (?,?,?,?)", (c["ID"],c["ContentID"],"native",json.dumps(c)))
                for r in native.execute("SELECT ContentID,Cues FROM contentCue WHERE rb_local_deleted=0"):
                    if r["ContentID"] not in by_id:
                        continue
                    for c in json.loads(r["Cues"] or "[]"):
                        if c["ID"] in seen:
                            continue
                        seen.add(c["ID"])
                        c["representation"] = "serialized_only"
                        db.execute("INSERT INTO source_cue VALUES (?,?,?,?)", (c["ID"],r["ContentID"],"serialized_only",json.dumps(c)))
                db.commit()
            progress(80, "Matching file dimensions and waveform fingerprints")
    # Match within and across device cohorts. Cue similarity is supporting evidence only.
    catalog = Catalog(output, {})
    signals = defaultdict(list)
    for t in catalog.tracks.values():
        if t["preview_sha256"] and t["size_bytes"] > 0 and t["duration_seconds"] > 0:
            signals[t["size_bytes"],t["duration_seconds"],t["preview_sha256"]].append(t["track_id"])
    with closing(sqlite3.connect(output)) as db:
        for ids in signals.values():
            if len(ids) > 50:
                continue
            for n, a in enumerate(sorted(ids)):
                for b in sorted(ids)[n+1:]:
                    ta,tb = catalog.tracks[a],catalog.tracks[b]
                    pa={path_key(ta[k]) for k in ("current_path","original_path","xml_location") if ta[k]}
                    pb={path_key(tb[k]) for k in ("current_path","original_path","xml_location") if tb[k]}
                    shared=bool(pa & pb)
                    if not shared and not (norm(ta["title"])==norm(tb["title"]) and norm(ta["artist"])==norm(tb["artist"]) and ta["title"] and ta["artist"]):
                        continue
                    db.execute("INSERT INTO match_candidate VALUES (?,?,?)",(a,b,1 if shared else 2))
        db.commit()
    from file_workflow import pair_signature
    return {"name": backup.name, "zip_path": str(backup), "xml_path": str(xml), "source": str(output),
            "pair_signature":pair_signature(backup,xml,xml_hash,master),
            "version": version, "xml_sha256": xml_hash, "zip_bytes": backup.stat().st_size,
            "unpacked_bytes": sum(i.file_size for i in infos), "file_count": len(infos),
            "input_check": "XML IDs and declared file sizes match the backup",
            "missing_xml_playlist_tracks": sum(i not in xml_tracks for i in playlists),"xml_playlist_ids":playlists}


def enrich_usage(catalog, backup, working, progress):
    master = working / "master.db"
    if not master.exists():
        progress(15, "Reading saved usage dates")
        with zipfile.ZipFile(backup) as archive, archive.open("master.db") as src, master.open("wb") as dst:
            while chunk := src.read(2 * 1024 * 1024):
                dst.write(chunk)
    with closing(open_master(master.resolve())) as db:
        for i, stock, created, play_count, analysed in db.execute("SELECT ID,StockDate,created_at,DJPlayCount,Analysed FROM djmdContent"):
            if i in catalog.tracks:
                catalog.tracks[i]["date_added"] = stock or created
                catalog.tracks[i]["play_count"] = play_count or 0
                catalog.tracks[i]["analysed"] = bool(analysed)
        # Use the date of an actual saved history. Database update time is unrelated.
        for i, date in db.execute("""SELECT s.ContentID,max(h.DateCreated) FROM djmdSongHistory s
            JOIN djmdHistory h ON h.ID=s.HistoryID
            WHERE s.rb_local_deleted=0 AND h.rb_local_deleted=0 GROUP BY s.ContentID"""):
            if i in catalog.tracks:
                catalog.tracks[i]["last_played"] = date or None
    with closing(open_master(master.resolve())) as db:
        for i,bitrate,sample,depth,bpm,year in db.execute("SELECT ID,BitRate,SampleRate,BitDepth,BPM,ReleaseYear FROM djmdContent"):
            if i in catalog.tracks:
                catalog.tracks[i].update(bitrate=bitrate,sample_rate=sample,bit_depth=depth,bpm=(bpm or 0)/100,year=year)
        catalog.metadata["playlist_options"]=[{"id":i,"name":name} for i,name in db.execute("SELECT ID,Name FROM djmdPlaylist WHERE rb_local_deleted=0 AND coalesce(Attribute,0)!=1 ORDER BY Name")]
        for i,album,composer,genre,label in db.execute("""SELECT c.ID,al.Name,co.Name,g.Name,l.Name
            FROM djmdContent c LEFT JOIN djmdAlbum al ON al.ID=c.AlbumID LEFT JOIN djmdArtist co ON co.ID=c.ComposerID
            LEFT JOIN djmdGenre g ON g.ID=c.GenreID LEFT JOIN djmdLabel l ON l.ID=c.LabelID"""):
            if i in catalog.tracks:
                catalog.tracks[i].update(album=album or "",composer=composer or "",genre=genre or "",label=label or "",playlist_ids=[])
        for i,playlist in db.execute("SELECT ContentID,PlaylistID FROM djmdSongPlaylist WHERE rb_local_deleted=0"):
            if i in catalog.tracks:catalog.tracks[i]["playlist_ids"].append(playlist)
        catalog.metadata["playlist_total"]=db.execute("SELECT count(*) FROM djmdPlaylist WHERE rb_local_deleted=0 AND coalesce(Attribute,0)!=1").fetchone()[0]
        owners={asset_key(t["analysis_path"]).rsplit("/",1)[0] for t in catalog.tracks.values() if t["analysis_path"]}
        for path, in db.execute("SELECT Path FROM contentFile WHERE rb_local_deleted=0"):
            path=asset_key(path)
            if "/usbanlz/" in path:owners.add(path.rsplit("/",1)[0])
        broken=0
        for table, in db.execute("SELECT name FROM sqlite_schema WHERE type='table'"):
            columns={c[1] for c in db.execute('PRAGMA table_info("'+table+'")')}
            if "ContentID" not in columns:continue
            active="r.rb_local_deleted=0 AND " if "rb_local_deleted" in columns else ""
            broken+=db.execute('SELECT count(*) FROM "'+table+'" r LEFT JOIN djmdContent c ON c.ID=r.ContentID WHERE '+active+'r.ContentID IS NOT NULL AND (c.ID IS NULL OR c.rb_local_deleted!=0)').fetchone()[0]
        catalog.metadata["broken_database_links"]=broken
    with zipfile.ZipFile(backup) as archive:
        directories={asset_key(i.filename).rsplit("/",1)[0] for i in archive.infolist() if "/USBANLZ/" in i.filename and not i.is_dir()}
    catalog.metadata["orphan_analysis_folders"]=len(directories-owners)
    refs=catalog.metadata.get("xml_playlist_ids")
    if refs is None:
        try:
            with closing(sqlite3.connect(catalog.source)) as review:
                refs=[r[0] for r in review.execute("SELECT source_track_id FROM projected_xml_playlist_item")]
        except sqlite3.OperationalError:
            refs=[]
    catalog.metadata["broken_xml_targets"]=sorted({i for i in refs if i not in catalog.tracks or not catalog.tracks[i]["october_xml"]})
    catalog.refresh_counts()


def decision_map(catalog, decisions):
    mapping, results = {}, {}
    keepers=set()
    for pair_id, choice in decisions.items():
        if choice["action"] != "merge":
            continue
        pair=catalog.pairs[pair_id]
        keeper=choice["keeper"]
        donor=pair["b"] if keeper==pair["a"] else pair["a"]
        if keeper in mapping or donor in mapping or donor in keepers:
            raise ValueError("A staged group has conflicting keeper choices")
        result=catalog.merge(pair,keeper,choice.get("prefer_auto",False),choice.get("prefer_rating",False),results.get(keeper))
        if result["conflicts"]:
            raise ValueError("A staged group still has cue or rating conflicts")
        previous=results.get(keeper,{}).get("donors",[])
        result["donors"]=[*previous,donor]
        results[keeper]=result
        keepers.add(keeper)
        mapping[donor]=keeper
    return mapping, results


def export_xml(catalog, decisions, relocations, destination, progress):
    """Export supported XML metadata while keeping the source archive as evidence."""
    from lxml import etree
    from xml.sax.saxutils import quoteattr
    from metadata_overrides import plan as override_plan,apply_xml
    xml = Path(catalog.metadata["xml_path"])
    backup = Path(catalog.metadata["zip_path"])
    mapping, results = decision_map(catalog, decisions)
    field_edits=override_plan(catalog,mapping)
    in_xml = {i for i,t in catalog.tracks.items() if t["october_xml"]}
    result_ids = {mapping.get(i,i) for i in in_xml}
    replacements = {donor:keeper for donor,keeper in mapping.items() if donor in in_xml and keeper not in in_xml}
    # Preserve references to native rows already present in the source XML playlists.
    needed = set()
    scan = expat.ParserCreate()
    section = ""
    def inspect(name, attrs):
        nonlocal section
        if name in ("COLLECTION","PLAYLISTS"):
            section = name
        elif section == "PLAYLISTS" and name == "TRACK":
            i = mapping.get(attrs["Key"], attrs["Key"])
            if i not in result_ids:
                if i not in catalog.tracks:
                    raise ValueError("Playlist references a track missing from both inputs")
                needed.add(i)
    scan.StartElementHandler = inspect
    scan.StartDoctypeDeclHandler = lambda *a: (_ for _ in ()).throw(ValueError("DTD is unsupported"))
    with xml.open("rb") as stream:
        while chunk := stream.read(2*1024*1024):
            scan.Parse(chunk,False)
        scan.Parse(b"",True)
    result_ids |= needed
    for i,value in relocations.items():
        if i not in catalog.tracks or not value.lower().startswith("file:"):
            raise ValueError("Relocation needs a file URI and a known track ID")
    namespace = lambda tag,attrs: "<" + tag + "".join(" "+k+"="+quoteattr(str(v)) for k,v in attrs.items()) + ">"
    staged_native = set(results) | needed
    working = destination.parent
    master = working / "export-master.db"
    with zipfile.ZipFile(backup) as archive:
        member_index = {asset_key(i.filename):i for i in archive.infolist()}
        with archive.open("master.db") as src, master.open("wb") as dst:
            while chunk := src.read(2*1024*1024):
                dst.write(chunk)
        with closing(open_master(master.resolve())) as native:
            native.row_factory=__import__("sqlcipher3").Row
            def native_element(i):
                row=dict(native.execute("""SELECT c.*,a.Name AS Artist,al.Name AS Album,g.Name AS Genre,k.ScaleName AS Tonality
                    FROM djmdContent c LEFT JOIN djmdArtist a ON a.ID=c.ArtistID
                    LEFT JOIN djmdAlbum al ON al.ID=c.AlbumID LEFT JOIN djmdGenre g ON g.ID=c.GenreID
                    LEFT JOIN djmdKey k ON k.ID=c.KeyID WHERE c.ID=?""",(i,)).fetchone())
                t=catalog.tracks[i]
                location=relocations.get(i) or t["xml_location"]
                if not location:
                    path=t["original_path"] or t["current_path"]
                    if not path or not re.match(r"^[A-Za-z]:[\\/]|^/",path):
                        raise ValueError("A restored playlist track needs a usable media path")
                    from urllib.parse import quote
                    location="file://localhost/"+quote(path.replace("\\","/").lstrip("/"),safe="/:")
                attrs=dict(TrackID=i,Name=row["Title"] or "",Artist=row["Artist"] or "",Album=row["Album"] or "",
                           Genre=row["Genre"] or "",Size=row["FileSize"] or 0,TotalTime=row["Length"] or 0,
                           AverageBpm=f'{(row["BPM"] or 0)/100:.2f}',Rating=(row["Rating"] or 0)*51,
                           DateAdded=(row["StockDate"] or "")[:10],Location=location,Comments=row["Commnt"] or "",
                           PlayCount=row["DJPlayCount"] or 0,SampleRate=row["SampleRate"] or 0,BitRate=row["BitRate"] or 0,
                           Tonality=row["Tonality"] or "")
                element=etree.Element("TRACK",{k:str(v) for k,v in attrs.items()})
                if row.get('ReleaseYear'):element.set('Year',str(row['ReleaseYear']))
                member=member_index.get(asset_key(t["analysis_path"]))
                if member:
                    grid=read_tags(archive,member).get(b"PQTZ",b"")
                    for offset in range(0,len(grid)-7,8):
                        beat,bpm,ms=struct.unpack_from(">HHI",grid,offset)
                        if beat not in (1,2,3,4) or bpm==0:
                            raise ValueError("A saved grid has an unsupported beat entry")
                        etree.SubElement(element,"TEMPO",Inizio=f"{ms/1000:.3f}",Bpm=f"{bpm/100:.2f}",Metro="4/4",Battito=str(beat))
                apply_cues(element, results.get(i,{"cues":catalog.cues[i],"rating":row["Rating"] or 0}))
                apply_xml(element,field_edits.get(i,{}))
                return element

            def apply_cues(element,result):
                element.set("Rating",str(result["rating"]*51))
                for old in list(element.findall("POSITION_MARK")):
                    element.remove(old)
                for cue in result["cues"]:
                    kind=cue["Kind"]
                    if kind not in HOT_NUMBERS and kind!=0:
                        raise ValueError("An unsupported cue kind needs native format review")
                    start,end=position(cue)
                    if start is None:
                        raise ValueError("Cue has no timestamp")
                    attrs=dict(Name=cue.get("Comment") or "",Type="4" if end>=0 else "0",
                               Start=f"{start/1000:.3f}",Num=str(HOT_NUMBERS.get(kind,-1)))
                    if end>=0:
                        attrs["End"]=f"{end/1000:.3f}"
                    color=cue.get("Color")
                    if color is not None and color>=0:
                        attrs.update(Red=str((color>>16)&255),Green=str((color>>8)&255),Blue=str(color&255))
                    etree.SubElement(element,"POSITION_MARK",**attrs)

            progress(15,"Writing edited XML and preserving track grids")
            # Stream one collection track or top-level playlist at a time.
            with destination.open("wb") as stream:
                stream.write(b'<?xml version="1.0" encoding="UTF-8"?>\n<DJ_PLAYLISTS Version="1.0.0">\n')
                stream.write(b'<PRODUCT Name="rekordbox" Version="'+catalog.metadata.get("version","7.2.19").encode()+b'" Company="AlphaTheta"/>\n')
                stream.write(namespace("COLLECTION",{"Entries":len(result_ids)}).encode())
                emitted=set()
                for event,e in etree.iterparse(str(xml),events=("end",),resolve_entities=False,no_network=True,huge_tree=True):
                    parent=e.getparent()
                    if e.tag=="TRACK" and parent is not None and parent.tag=="COLLECTION":
                        original=e.get("TrackID")
                        i=mapping.get(original,original)
                        if i not in emitted and i in result_ids and (original not in mapping or i not in in_xml):
                            if original in replacements:
                                element=native_element(i)
                            else:
                                element=e
                                if i in results:
                                    apply_cues(element,results[i])
                            if i in relocations:
                                element.set("Location",relocations[i])
                            apply_xml(element,field_edits.get(i,{}))
                            stream.write(etree.tostring(element,encoding="UTF-8"))
                            emitted.add(i)
                        e.clear()
                        while e.getprevious() is not None:
                            del parent[0]
                    elif e.tag=="COLLECTION":
                        for i in sorted(result_ids-emitted):
                            stream.write(etree.tostring(native_element(i),encoding="UTF-8"))
                            emitted.add(i)
                        stream.write(b"</COLLECTION>\n")
                        e.clear()
                    elif e.tag=="PLAYLISTS":
                        for ref in e.iter("TRACK"):
                            ref.set("Key",mapping.get(ref.get("Key"),ref.get("Key")))
                        stream.write(etree.tostring(e,encoding="UTF-8"))
                        e.clear()
                stream.write(b"\n</DJ_PLAYLISTS>")
    progress(85,"Validating exported XML IDs and playlist references")
    checked,playlists,_,digest=parse_xml(destination,lambda *_:None)
    if set(checked)!=result_ids or any(i not in checked for i in playlists):
        raise ValueError("Export failed track or playlist validation")
    for identity,fields in field_edits.items():
        if identity not in checked:continue
        expected=etree.Element('TRACK');apply_xml(expected,fields)
        for field in fields:
            from metadata_overrides import XML_FIELDS
            key=XML_FIELDS[field]
            if checked[identity]['attrs'].get(key)!=expected.get(key):raise ValueError('XML metadata verification failed: '+identity+' / '+field)
    return {"track_count":len(result_ids),"merges":len(mapping),"playlist_tracks_recovered":len(needed),
            "metadata_fields":sum(len(fields) for i,fields in field_edits.items() if i in result_ids),
            "metadata_tracks_outside_xml":len(field_edits.keys()-result_ids),
            "relocations":len(relocations),"sha256":digest,"native_backup_status":"Windows restore validation required"}
