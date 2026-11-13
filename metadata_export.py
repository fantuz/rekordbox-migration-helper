"""Portable, offline metadata snapshots. No audio, database or network operations."""
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import html
import json
import math
from pathlib import Path
import shutil
import zipfile

from engine import is_auto


FIELDS = ("id", "title", "artist", "album", "genre", "year", "bpm", "rating",
          "duration", "format", "label", "composer", "play_count", "date_added",
          "last_played", "analysed", "manual_cues", "auto_cues", "bitrate",
          "sample_rate", "bit_depth", "playlists")
PATH_FIELDS = ("current_path", "original_path")
PAGES = {"index": "Overview", "tracks": "Tracks", "genres": "Genres", "years": "Release years", "added": "Added by year",
         "artists": "Artists", "albums": "Albums", "bpm": "BPM ranges", "ratings": "Ratings",
         "duration": "Duration", "formats": "Formats", "playlists": "Playlists"}


def number(value, minimum=0, maximum=None):
    try:
        result = float(value)
        if not math.isfinite(result) or result < minimum or (maximum is not None and result > maximum):
            return None
        return int(result) if result.is_integer() else result
    except (ValueError, TypeError, OverflowError):
        return None


def clean(value):
    return str(value or "").strip()


def track(values):
    """Keep a bounded metadata allowlist; unavailable values stay unknown."""
    text = ("id", "title", "artist", "album", "genre", "label", "composer", "date_added", "last_played", *PATH_FIELDS)
    result = {field: clean(values.get(field)) for field in text}
    for field in ("duration", "play_count", "manual_cues", "auto_cues", "bitrate", "sample_rate", "bit_depth"):
        result[field] = number(values.get(field))
    result["year"] = number(values.get("year"), 1000, 2999)
    result["bpm"] = number(values.get("bpm"), .001)
    result["rating"] = number(values.get("rating"), 0, 5)
    result["analysed"] = None if values.get("analysed") is None else bool(values["analysed"])
    path = result["current_path"].replace("\\", "/")
    result["format"] = clean(values.get("format") or Path(path).suffix.lstrip(".")).upper()
    result["playlists"] = sorted({clean(p) for p in values.get("playlists", []) if clean(p)}, key=str.casefold)
    return result


def capture_catalog(catalog, scope="all"):
    if scope not in ("all", "xml"):
        raise ValueError("Choose the full loaded library or the XML collection")
    names = {p["id"]: p["name"] for p in catalog.metadata.get("playlist_options", [])}
    tracks = []
    for source in catalog.tracks.values():
        if scope == "xml" and not source.get("october_xml"):
            continue
        cues = catalog.cue_summary(source["track_id"])
        tracks.append(track({**source, "id": source["track_id"], "duration": source.get("duration_seconds"),
                             "manual_cues": cues["other"], "auto_cues": cues["auto"],
                             "playlists": [names.get(p, str(p)) for p in source.get("playlist_ids", [])]}))
    return {"tracks": tracks, "source_kind": "Loaded XML + ZIP", "scope": scope,
            "version": catalog.metadata.get("version"), "captured": datetime.now(timezone.utc).isoformat(),
            "cue_basis": "Combined XML/native cue metadata; automatic origin is inferred from editable labels."}


def capture_database(db, columns):
    """Called only on the analyzer's already-open, query-only private copy."""
    def rows(table, wanted):
        if table not in columns:
            return []
        fields = ",".join('"'+field+'"' if field in columns[table] else 'NULL AS "'+field+'"' for field in wanted)
        where = " WHERE coalesce(rb_local_deleted,0)=0" if "rb_local_deleted" in columns[table] else ""
        return [dict(zip(wanted, row)) for row in db.execute('SELECT '+fields+' FROM "'+table+'"'+where)]

    lookups = {name: {str(row["ID"]): row["Name"] for row in rows(name, ("ID", "Name"))}
               for name in ("djmdArtist", "djmdAlbum", "djmdGenre", "djmdLabel")}
    playlist_names = {str(p["ID"]): p["Name"] for p in rows("djmdPlaylist", ("ID", "Name", "Attribute"))
                      if (p["Attribute"] or 0) != 1}
    playlists = defaultdict(list)
    for row in rows("djmdSongPlaylist", ("ContentID", "PlaylistID")):
        if str(row["PlaylistID"]) in playlist_names:
            playlists[str(row["ContentID"])].append(playlist_names[str(row["PlaylistID"])])
    cues = defaultdict(list)
    for row in rows("djmdCue", ("ContentID", "Comment")):
        cues[str(row["ContentID"])].append(row)
    cue_known = {"ContentID", "Comment"} <= columns.get("djmdCue", set())
    source_fields = ("ID", "Title", "ArtistID", "AlbumID", "GenreID", "LabelID", "ComposerID", "ReleaseYear",
                     "BPM", "Rating", "Length", "DJPlayCount", "StockDate", "Analysed", "BitRate", "SampleRate",
                     "BitDepth", "FolderPath", "OrgFolderPath")
    tracks = []
    for row in rows("djmdContent", source_fields):
        identity = str(row["ID"])
        automated = sum(is_auto(cue) for cue in cues[identity])
        saved_bpm = number(row["BPM"])
        values = {"id": identity, "title": row["Title"], "year": row["ReleaseYear"],
                  "bpm": None if saved_bpm is None else saved_bpm/100,
                  "rating": row["Rating"], "duration": row["Length"], "play_count": row["DJPlayCount"],
                  "date_added": row["StockDate"], "analysed": row["Analysed"], "bitrate": row["BitRate"],
                  "sample_rate": row["SampleRate"], "bit_depth": row["BitDepth"], "current_path": row["FolderPath"],
                  "original_path": row["OrgFolderPath"], "playlists": playlists[identity],
                  "manual_cues": len(cues[identity])-automated if cue_known else None,
                  "auto_cues": automated if cue_known else None}
        for target, table, field in (("artist", "djmdArtist", "ArtistID"), ("composer", "djmdArtist", "ComposerID"),
                                     ("album", "djmdAlbum", "AlbumID"), ("genre", "djmdGenre", "GenreID"),
                                     ("label", "djmdLabel", "LabelID")):
            values[target] = lookups[table].get(str(row[field]), "")
        tracks.append(track(values))
    return {"tracks": tracks, "source_kind": "Read-only source snapshot", "scope": "all",
            "captured": datetime.now(timezone.utc).isoformat(),
            "cue_basis": "Active native djmdCue rows; automatic origin is inferred from editable labels."}


def payload(snapshot, title, include_paths=False):
    fields = [*FIELDS, *(PATH_FIELDS if include_paths else ())]
    return {"schema": 1, "title": clean(title)[:160] or "My library", "created": datetime.now(timezone.utc).isoformat(),
            "captured": snapshot.get("captured"), "source_kind": snapshot.get("source_kind", "Metadata snapshot"),
            "scope": snapshot.get("scope", "all"), "version": snapshot.get("version"),
            "cue_basis": snapshot.get("cue_basis", ""), "includes_paths": include_paths,
            "staged_changes_applied": False, "metadata_overrides_applied":snapshot.get('metadata_overrides_applied',0), "columns": fields,
            "rows": [[t.get(field) for field in fields] for t in snapshot["tracks"]]}


def script_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def export_metadata(snapshot, root, export_id, assets, progress, title="My library", include_paths=False,temporary_root=None):
    root, assets = Path(root), Path(assets)
    root.mkdir(parents=True,exist_ok=True)
    pending, final = Path(temporary_root or root)/(".pending-"+export_id), root/export_id
    pending.mkdir(parents=True)
    try:
        data = payload(snapshot, title, include_paths)
        serialized = script_json(data)
        css, js = (assets/"explorer.css").read_text(encoding="utf-8"), (assets/"explorer.js").read_text(encoding="utf-8")
        template = (assets/"explorer.html").read_text(encoding="utf-8")
        def page(view, single):
            return (template.replace("@@TITLE@@", html.escape(data["title"]))
                    .replace("@@VIEW@@", view).replace("@@MODE@@", "single" if single else "multi")
                    .replace("@@STYLES@@", "<style>"+css+"</style>" if single else '<link rel="stylesheet" href="explorer.css">')
                    .replace("@@DATA@@", "<script>window.METADATA_SNAPSHOT="+serialized+";</script>" if single else '<script src="library-data.js"></script>')
                    .replace("@@APP@@", "<script>"+js+"</script>" if single else '<script src="explorer.js"></script>'))
        progress(20, "Writing standalone HTML with metadata only")
        standalone = page("index", True).encode("utf-8")
        (pending/"library.html").write_bytes(standalone)
        progress(55, "Building the offline category pages")
        with zipfile.ZipFile(pending/"metadata-explorer.zip", "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for view in PAGES:
                archive.writestr(view+".html", page(view, False).encode("utf-8"))
            archive.writestr("explorer.css", css.encode("utf-8"))
            archive.writestr("explorer.js", js.encode("utf-8"))
            archive.writestr("library-data.js", ("window.METADATA_SNAPSHOT="+serialized+";").encode("utf-8"))
            archive.writestr("START HERE.txt", "Extract the entire ZIP, then open index.html in a browser.\nNo server, application, internet connection or installation is required.\nThis is a captured metadata explorer, not a rekordbox backup or editable library.\nStaged cleanup decisions are not applied. No audio, artwork, waveforms or native database is included.\n"+("Recorded file paths were included by your explicit choice.\n" if include_paths else "Recorded file paths are excluded.\n"))
        with zipfile.ZipFile(pending/"metadata-explorer.zip") as checked:
            if checked.testzip() is not None:
                raise ValueError("The offline explorer ZIP did not validate")
        files = [{"kind": kind, "name": name, "bytes": (pending/name).stat().st_size,
                  "sha256": sha256((pending/name).read_bytes()).hexdigest(),
                  "download": "/api/quick-export/"+export_id+"/"+kind}
                 for kind, name in (("html", "library.html"), ("zip", "metadata-explorer.zip"))]
        record = {"id": export_id, "created": data["created"], "title": data["title"], "tracks": len(data["rows"]),
                  "status": "complete", "source_kind": data["source_kind"], "scope": data["scope"],
                  "source_captured": data["captured"], "includes_paths": include_paths, "staged_changes_applied": False,
                  "metadata_overrides_applied":data.get('metadata_overrides_applied',0),
                  "pages": list(PAGES.values()), "files": files, "directory": str(final.resolve())}
        (pending/"export.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        pending.rename(final)
    except Exception:
        shutil.rmtree(pending, ignore_errors=True)
        raise
    progress(100, "Offline HTML and minisite saved")
    return record


def list_metadata_exports(root):
    records = []
    for path in Path(root).glob("*/export.json"):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            if item["status"] == "complete" and all((path.parent/f["name"]).is_file() for f in item["files"]):
                records.append(item)
        except (OSError, ValueError, KeyError):
            continue
    return sorted(records, key=lambda item: item["created"], reverse=True)[:20]
