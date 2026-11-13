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
from localization import browser_catalogues

from engine import is_auto
from track_tags import native_colour,rgb,editable_colour,native_colour_support


FIELDS = ("id", "title", "artist", "album", "genre", "year", "bpm", "rating",
          "duration", "format", "label", "composer", "play_count", "date_added",
          "last_played", "analysed", "manual_cues", "auto_cues", "bitrate",
          "sample_rate", "bit_depth", "playlists", "tonality", "color_name", "color_hex", "color_status")
PATH_FIELDS = ("current_path", "original_path")
SHARE_FIELDS = ("title", "artist", "album", "genre", "year", "bpm", "duration", "format")
PUBLIC_DIMENSIONS = {"genres": "genre", "years": "year", "artists": "artist", "albums": "album",
                     "bpm": "bpm", "duration": "duration", "formats": "format", "tonality": "tonality",
                     "colours": "color_name"}
PAGES = {"index": "Overview", "tracks": "Tracks", "genres": "Genres", "years": "Release years", "added": "Added by year",
         "artists": "Artists", "albums": "Albums", "bpm": "BPM ranges", "ratings": "Ratings",
         "duration": "Duration", "formats": "Formats", "playlists": "Playlists", "tonality": "Tonality", "colours": "Track colours"}
PAGE_FIELDS = {"genres": "genre", "years": "year", "added": "date_added", "artists": "artist", "albums": "album",
               "bpm": "bpm", "ratings": "rating", "duration": "duration", "formats": "format", "playlists": "playlists",
               "tonality": "tonality", "colours": "color_status"}


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
    text = ("id", "title", "artist", "album", "genre", "label", "composer", "date_added", "last_played", "tonality", *PATH_FIELDS)
    result = {field: str(values.get(field) or '') for field in text}
    result['comment']=None if values.get('comment') is None else str(values['comment'])
    result.update({field:clean(values.get(field)) for field in ('color_name','color_key','color_basis')})
    result['color_status']=values.get('color_status') if values.get('color_status') in ('assigned','unassigned','unknown') else 'unknown'
    result['color_hex']=rgb(values.get('color_hex'))
    result['colour']=editable_colour(result)
    for field in ("duration", "play_count", "manual_cues", "auto_cues", "bitrate", "sample_rate", "bit_depth"):
        result[field] = number(values.get(field))
    result["year"] = number(values.get("year"), 1000, 2999)
    result["bpm"] = number(values.get("bpm"), .001)
    result["rating"] = number(values.get("rating"), 0, 5)
    result["analysed"] = None if values.get("analysed") is None else bool(values["analysed"])
    path = result["current_path"].replace("\\", "/")
    result["format"] = clean(values.get("format") or Path(path).suffix.lstrip(".")).upper()
    result["playlists"] = sorted({str(p) for p in values.get("playlists", []) if clean(p)}, key=str.casefold)
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
            "colour_edit_support":catalog.metadata.get("colour_edit_support"),
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
    keys={str(r['ID']):r['ScaleName'] for r in rows('djmdKey',('ID','ScaleName'))}
    colours={str(r['ID']):r for r in rows('djmdColor',('ID','ColorCode','SortKey','Commnt'))}
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
                     "BitDepth", "FolderPath", "OrgFolderPath", "Commnt", "KeyID", "ColorID")
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
                  'comment':row['Commnt'],'tonality':keys.get(str(row['KeyID']),''),
                  **native_colour(row['ColorID'],colours.get(str(row['ColorID'])),'ColorID' in columns.get('djmdContent',set())),
                  "manual_cues": len(cues[identity])-automated if cue_known else None,
                  "auto_cues": automated if cue_known else None}
        for target, table, field in (("artist", "djmdArtist", "ArtistID"), ("composer", "djmdArtist", "ComposerID"),
                                     ("album", "djmdAlbum", "AlbumID"), ("genre", "djmdGenre", "GenreID"),
                                     ("label", "djmdLabel", "LabelID")):
            values[target] = lookups[table].get(str(row[field]), "")
        tracks.append(track(values))
    return {"tracks": tracks, "source_kind": "Read-only source snapshot", "scope": "all",
            "captured": datetime.now(timezone.utc).isoformat(),
            "colour_edit_support":native_colour_support(db,columns,list(colours.values())),
            "cue_basis": "Active native djmdCue rows; automatic origin is inferred from editable labels."}


def _selection(snapshot, preset="private", fields=None, track_ids=None, playlist=None, include_paths=False,
               allow_empty_selection=False):
    if preset not in ("public", "selected", "private"):
        raise ValueError("Choose public summary, selected list or private explorer")
    if fields is not None and (not isinstance(fields, list) or any(not isinstance(f, str) or f not in (*FIELDS, *PATH_FIELDS) for f in fields)):
        raise ValueError("Choose supported metadata fields")
    if track_ids is not None and (not isinstance(track_ids, list) or any(not isinstance(t, str) for t in track_ids) or len(track_ids)>200000):
        raise ValueError("Choose track IDs from the selected source")
    if playlist is not None and not isinstance(playlist, str):
        raise ValueError("Choose a playlist from the selected source")
    tracks = snapshot["tracks"]
    if preset == "selected":
        wanted = set(track_ids or ())
        if not wanted and not playlist and not allow_empty_selection:
            raise ValueError("Choose at least one track ID or a playlist for the selected list")
        tracks = [t for t in tracks if str(t.get("id")) in wanted or (playlist and playlist in t.get("playlists", []))]
        if not tracks and not allow_empty_selection:
            raise ValueError("No selected tracks were found in this source")
    if preset == "public":
        selected_fields = []
    else:
        requested = fields if fields is not None else (list(SHARE_FIELDS) if preset == "selected" else list(FIELDS))
        selected_fields = list(dict.fromkeys(f for f in requested if f not in PATH_FIELDS or include_paths))
        if include_paths:
            selected_fields.extend(f for f in PATH_FIELDS if f not in selected_fields)
        if not selected_fields:
            raise ValueError("Choose at least one metadata field")
    return tracks, selected_fields


def disclosure(snapshot, preset="private", fields=None, track_ids=None, playlist=None, include_paths=False,
               allow_empty_selection=True):
    """Describe the exact serialized selection without returning track values or paths."""
    tracks, selected_fields = _selection(snapshot, preset, fields, track_ids, playlist, include_paths, allow_empty_selection)
    return {"preset": preset, "track_count": len(tracks), "aggregates_only": preset == "public",
            "fields": (["Category labels", "Category counts", "Category duration totals", "Category mean BPM"]
                       if preset == "public" else selected_fields),
            "available_fields": list(FIELDS),
            "available_playlists": sorted({str(p) for t in snapshot["tracks"] for p in t.get("playlists", [])}, key=str.casefold),
            "includes_paths": any(f in PATH_FIELDS for f in selected_fields),
            "data_state": (snapshot.get("data_state") if snapshot.get("data_state") in ("working", "captured") else "working" if snapshot.get("metadata_overrides_applied") else "captured"),
            "metadata_overrides_applied": snapshot.get("metadata_overrides_applied", 0),
            "staged_changes_applied": False,
            "omitted": (["Individual tracks", "Track IDs", "Playlists", "Dates", "Play counts", "Personal stars", "Cues", "File paths"]
                        if preset == "public" else [f for f in (*FIELDS, *PATH_FIELDS) if f not in selected_fields])}


def _bucket(value, bins):
    n = number(value)
    return None if n is None else next(label for limit, label in bins if n < limit)


def public_aggregates(tracks):
    """Only labels and aggregates survive; personal usage, IDs and track rows never enter this object."""
    result = {}
    bpm_bins = [(80,"Under 80"),(100,"80–99.99"),(120,"100–119.99"),(130,"120–129.99"),(140,"130–139.99"),
                (160,"140–159.99"),(180,"160–179.99"),(math.inf,"180+")]
    duration_bins = [(60,"Under 1 min"),(180,"1–2.99 min"),(360,"3–5.99 min"),(600,"6–9.99 min"),
                     (1800,"10–29.99 min"),(math.inf,"30 min+")]
    for page, field in PUBLIC_DIMENSIONS.items():
        grouped = {}
        for t in tracks:
            value = (_bucket(t.get(field), bpm_bins) if page == "bpm" else _bucket(t.get(field), duration_bins)
                     if page == "duration" else t.get(field))
            if page == "colours":
                value = (t.get("color_name") or t.get("color_hex") or "Assigned colour") if t.get("color_status") == "assigned" else "No assigned colour" if t.get("color_status") == "unassigned" else None
            # Category labels are captured metadata, not UI prose. Preserve
            # Unicode and meaningful spacing instead of silently normalizing tags.
            key = str(value) if value is not None and str(value).strip() else None
            if key not in grouped:
                grouped[key] = {"label": key, "count": 0, "duration": 0, "duration_known": 0, "bpm_total": 0, "bpm_count": 0}
            g = grouped[key]; g["count"] += 1
            duration_value, bpm_value = number(t.get("duration")), number(t.get("bpm"), .001)
            if duration_value is not None:g["duration"] += duration_value; g["duration_known"] += 1
            if bpm_value is not None:g["bpm_total"] += bpm_value; g["bpm_count"] += 1
        result[page] = []
        for g in sorted(grouped.values(), key=lambda g: (-g["count"], str(g["label"]).casefold())):
            total = g.pop("bpm_total"); count = g.pop("bpm_count")
            g["average_bpm"] = round(total/count, 1) if count else None
            result[page].append(g)
    durations = [number(t.get("duration")) for t in tracks]
    bpms = [number(t.get("bpm"), .001) for t in tracks]
    known_bpms = [n for n in bpms if n is not None]
    return {"tracks": len(tracks), "duration": sum(n for n in durations if n is not None),
            "duration_known": sum(n is not None for n in durations), "bpm_known": len(known_bpms),
            "average_bpm": round(sum(known_bpms)/len(known_bpms), 1) if known_bpms else None,
            "categories": result}


def payload(snapshot, title, include_paths=False, preset="private", fields=None, track_ids=None, playlist=None):
    tracks, fields = _selection(snapshot, preset, fields, track_ids, playlist, include_paths)
    info = disclosure(snapshot, preset, fields, track_ids, playlist, include_paths)
    return {"schema": 1, "title": clean(title)[:160] or "My library", "created": datetime.now(timezone.utc).isoformat(),
            "captured": None if preset == "public" else snapshot.get("captured"), "source_kind": "Public collection summary" if preset == "public" else snapshot.get("source_kind", "Metadata snapshot"),
            "scope": snapshot.get("scope", "all"), "version": snapshot.get("version"),
            "cue_basis": snapshot.get("cue_basis", "") if any(f in fields for f in ("manual_cues", "auto_cues")) else "", "includes_paths": info["includes_paths"],
            "staged_changes_applied": False, "metadata_overrides_applied":snapshot.get('metadata_overrides_applied',0), "columns": fields,
            "preset": preset, "data_state": info["data_state"], "track_count": len(tracks),
            "disclosure": {k:info[k] for k in ("fields", "omitted", "aggregates_only")},
            "aggregates": public_aggregates(tracks) if preset == "public" else None,
            "rows": [] if preset == "public" else [[t.get(field) for field in fields] for t in tracks]}


def script_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def export_metadata(snapshot, root, export_id, assets, progress, title="My library", include_paths=False,temporary_root=None,
                    preset="private", fields=None, track_ids=None, playlist=None):
    root, assets = Path(root), Path(assets)
    root.mkdir(parents=True,exist_ok=True)
    pending, final = Path(temporary_root or root)/(".pending-"+export_id), root/export_id
    pending.mkdir(parents=True)
    try:
        data = payload(snapshot, title, include_paths, preset, fields, track_ids, playlist)
        exported_pages = {key: name for key, name in PAGES.items()
                          if key == "index" or (key in PUBLIC_DIMENSIONS if preset == "public" else
                                                key == "tracks" or PAGE_FIELDS.get(key) in data['columns'])}
        serialized = script_json(data)
        css, js = (assets/"explorer.css").read_text(encoding="utf-8"), (assets/"explorer.js").read_text(encoding="utf-8")
        translations=browser_catalogues(assets)+'\n'+(assets/'i18n.js').read_text(encoding='utf-8')
        template = (assets/"explorer.html").read_text(encoding="utf-8")
        def page(view, single):
            return (template.replace("@@TITLE@@", html.escape(data["title"]))
                    .replace("@@VIEW@@", view).replace("@@MODE@@", "single" if single else "multi")
                    .replace("@@STYLES@@", "<style>"+css+"</style>" if single else '<link rel="stylesheet" href="explorer.css">')
                    .replace("@@DATA@@", "<script>window.METADATA_SNAPSHOT="+serialized+";</script>" if single else '<script src="library-data.js"></script>')
                    .replace("@@APP@@", "<script>"+translations+'\n'+js+"</script>" if single else '<script src="translations.js"></script><script src="explorer.js"></script>'))
        progress(20, "Writing standalone HTML with metadata only")
        standalone = page("index", True).encode("utf-8")
        (pending/"library.html").write_bytes(standalone)
        progress(55, "Building the offline category pages")
        with zipfile.ZipFile(pending/"metadata-explorer.zip", "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for view in exported_pages:
                archive.writestr(view+".html", page(view, False).encode("utf-8"))
            archive.writestr("explorer.css", css.encode("utf-8"))
            archive.writestr("explorer.js", js.encode("utf-8"))
            archive.writestr('translations.js',translations.encode('utf-8'))
            archive.writestr("library-data.js", ("window.METADATA_SNAPSHOT="+serialized+";").encode("utf-8"))
            archive.writestr("START HERE.txt", "Extract the entire ZIP, then open index.html in a browser.\nNo server, application, internet connection or installation is required.\nThis is a metadata explorer, not a rekordbox backup or editable library.\nMerge and relocation decisions are not applied. No audio, artwork, waveforms or native database is included.\nPreset: "+data['preset']+". Metadata state: "+data['data_state']+".\n"+("Recorded file paths were included by your explicit choice.\n" if data['includes_paths'] else "Recorded file paths are excluded.\n")+"Included fields: "+", ".join(data['disclosure']['fields'])+".\n")
        with zipfile.ZipFile(pending/"metadata-explorer.zip") as checked:
            if checked.testzip() is not None:
                raise ValueError("The offline explorer ZIP did not validate")
        files = [{"kind": kind, "name": name, "bytes": (pending/name).stat().st_size,
                  "sha256": sha256((pending/name).read_bytes()).hexdigest(),
                  "download": "/api/quick-export/"+export_id+"/"+kind}
                 for kind, name in (("html", "library.html"), ("zip", "metadata-explorer.zip"))]
        record = {"id": export_id, "created": data["created"], "title": data["title"], "tracks": data["track_count"],
                  "status": "complete", "source_kind": data["source_kind"], "scope": data["scope"],
                  "source_captured": data["captured"], "includes_paths": data['includes_paths'], "staged_changes_applied": False,
                  "preset": data['preset'], "data_state": data['data_state'], "disclosure": data['disclosure'],
                  "metadata_overrides_applied":data.get('metadata_overrides_applied',0),
                  "pages": list(exported_pages.values()), "files": files, "directory": str(final.resolve())}
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
