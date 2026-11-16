"""Bounded, opt-in recovery suggestions; never modifies media or a live library."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import math
import ntpath
import os
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from engine import path_key
from media import AUDIO, export_uri, file_record
from track_playback import inspect_audio

MAX_ENTRIES = 200000
MAX_FILES = 50000
MAX_SECONDS = 120
UNRESOLVED = {'not_found', 'unverified', 'ambiguous', 'cloud_only', 'review'}


def normalized(value):
    # Keep version/remix words and digits; do not conflate edits of a recording.
    return ' '.join(re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', str(value or '')).casefold()))


def duration(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else 0
    except (ValueError, TypeError):
        return 0


def read_tags(path):
    from tinytag import TinyTag
    tag = TinyTag.get(str(path), image=False)
    return {'title': tag.title or '', 'artist': tag.artist or '', 'duration': duration(tag.duration)}


def valid_export_uri(uri):
    try:
        parsed = urlsplit(uri)
        return (parsed.scheme == 'file' and parsed.netloc.lower() in ('', 'localhost')
                and parsed.path.startswith('/') and not parsed.query and not parsed.fragment
                and not any(ord(c) < 32 for c in unquote(uri))
                and '..' not in unquote(parsed.path).split('/'))
    except (ValueError, TypeError):
        return False


def ordinary_path(path):
    """Reject links/junctions in any component, including swapped scan roots."""
    return not any(p.is_symlink() or p.is_junction() for p in (path, *path.parents))


def scan(tracks, mappings, progress):
    if not isinstance(mappings, list) or not 1 <= len(mappings) <= 20:
        raise ValueError('Choose between one and twenty media roots')
    if len(tracks) > 250000:
        raise ValueError('This library exceeds the recovery scan limit')
    started = time.monotonic()
    warnings, roots, files = [], [], {}
    warning_count = 0

    def warn(message):
        nonlocal warning_count
        warning_count += 1
        if len(warnings) < 100:
            warnings.append(str(message))

    for mapping in mappings:
        if not isinstance(mapping, dict) or not isinstance(mapping.get('root'), str):
            raise ValueError('Choose an absolute local media folder')
        root = Path(mapping['root']).expanduser()
        if (not root.is_absolute() or str(root).startswith(('\\\\', '//'))
                or root == Path(root.anchor) or '..' in root.parts):
            raise ValueError('Choose an absolute local media folder, not an entire drive')
        uri = mapping.get('export_uri', '')
        if uri and not valid_export_uri(uri):
            raise ValueError('Export root must be a local file URI')
        if not isinstance(mapping.get('recorded_prefix', ''), str):
            raise ValueError('Provide a recorded path prefix')
        roots.append({**mapping, 'root': str(root.absolute())})
    visited = 0
    stopped = False
    for mapping in roots:
        root = Path(mapping['root'])
        if not ordinary_path(root) or not root.is_dir():
            warn('Root unavailable or linked: ' + str(root))
            continue
        for directory, dirs, names in os.walk(root, followlinks=False, onerror=warn):
            # A skipped subtree is explicitly incomplete evidence.
            for name in list(dirs):
                child = Path(directory, name)
                if child.is_symlink() or child.is_junction():
                    dirs.remove(name)
                    warn('Linked folder skipped: ' + str(child))
            directory_names = set(dirs)
            for name in [*dirs, *names]:
                visited += 1
                if visited % 100 == 0:
                    progress(10, f'Searching selected folders: {len(files):,} audio files')
                if visited > MAX_ENTRIES or len(files) >= MAX_FILES or time.monotonic() - started > MAX_SECONDS:
                    warn('Search limit reached; choose smaller folders and scan again')
                    stopped = True
                    break
                path = Path(directory, name)
                if path.suffix.casefold() not in AUDIO or name in directory_names:
                    continue
                if path.is_symlink() or path.is_junction():
                    warn('Linked file skipped: ' + str(path))
                    continue
                try:
                    record = file_record(path)
                    record['export_uri'] = export_uri(mapping, path.relative_to(root))
                    record['mapped_paths'] = []
                    if mapping.get('recorded_prefix'):
                        record['mapped_paths'].append(path_key(mapping['recorded_prefix'].rstrip('/\\') + '/' + path.relative_to(root).as_posix()))
                    key = os.path.normcase(str(path))
                    if key in files:
                        prior = files[key]
                        if prior['export_uri'] != record['export_uri']:
                            warn('Conflicting export roots for: ' + str(path))
                        prior['mapped_paths'].extend(record['mapped_paths'])
                        continue
                    if not record['cloud_only']:
                        try:
                            record['tags'] = read_tags(path)
                            if not duration(record['tags'].get('duration')):
                                raise ValueError('Audio duration could not be read')
                            after = file_record(path)
                            if (after['size'], after['mtime_ns']) != (record['size'], record['mtime_ns']):
                                raise ValueError('File changed during tag reading')
                        except Exception as error:
                            # A failed decoder is not evidence that no renamed match exists.
                            warn(str(path) + ': ' + str(error)[:160])
                            record.pop('tags', None)
                    else:
                        warn('Cloud placeholder not read: ' + str(path))
                    files[key] = record
                except OSError as error:
                    warn(error)
            if stopped:
                break
        if stopped:
            break

    names, mapped, tags = defaultdict(list), defaultdict(list), defaultdict(list)
    for record in files.values():
        names[normalized(Path(record['path']).name), record['size']].append(record)
        for value in record['mapped_paths']:
            mapped[value, record['size']].append(record)
        tag = record.get('tags', {})
        seconds = duration(tag.get('duration'))
        if normalized(tag.get('title')) and normalized(tag.get('artist')) and seconds:
            tags[normalized(tag['title']), normalized(tag['artist']), int(seconds)].append(record)
    complete = not warning_count
    matches, referenced = {}, set()
    matching_stopped = False
    for n, (identity, track) in enumerate(tracks.items()):
        if n % 100 == 0:
            progress(40 + 55 * n / max(1, len(tracks)), f'Checking recovery evidence: {n:,} / {len(tracks):,}')
        if time.monotonic() - started > MAX_SECONDS:
            if not matching_stopped:
                warn('Search time limit reached; choose smaller folders and scan again')
            matching_stopped = True
            matches[identity] = {'status': 'unverified', 'recorded_status': 'unverified',
                                 'evidence': None, 'candidates': [], 'candidate_count': 0}
            continue
        state, current = inspect_audio(track)
        candidates = {}

        def add(records, evidence, rank):
            for record in records:
                path = record['path']
                if path not in candidates:
                    candidates[path] = {k: v for k, v in record.items() if k != 'mapped_paths'}
                    candidates[path].update(evidence=[], rank=rank)
                candidates[path]['rank'] = max(rank, candidates[path]['rank'])
                if evidence not in candidates[path]['evidence']:
                    candidates[path]['evidence'].append(evidence)

        recorded = [track.get(k) for k in ('current_path', 'original_path', 'xml_location') if track.get(k)]
        size = track.get('size_bytes') or 0
        if size > 0:
            for value in recorded:
                add(mapped.get((path_key(value), size), []), 'mapped_path_and_size', 3)
                add(names.get((normalized(ntpath.basename(path_key(value))), size), []), 'filename_and_size', 2)
        seconds = duration(track.get('duration_seconds'))
        title, artist = normalized(track.get('title')), normalized(track.get('artist'))
        if title and artist and seconds:
            for bucket in range(max(0, int(seconds) - 2), int(seconds) + 3):
                add([r for r in tags.get((title, artist, bucket), [])
                     if abs(r['tags']['duration'] - seconds) <= 2], 'tags_and_duration', 1)
        rows = sorted(candidates.values(), key=lambda r: (-r['rank'], r['path']))
        for row in rows:
            observed=row.get('tags',{})
            conflicts=[key for key in ('title','artist') if normalized(track.get(key))
                       and normalized(observed.get(key)) and normalized(track[key])!=normalized(observed[key])]
            if seconds and duration(observed.get('duration')) and abs(seconds-observed['duration'])>2:
                conflicts.append('duration')
            row['metadata_conflicts']=conflicts
        referenced.update(candidates)
        if current:
            referenced.add(str(current))
            status = 'available'
        elif len(rows) > 1:
            status = 'ambiguous'
        elif rows:
            status = 'cloud_only' if rows[0]['cloud_only'] else 'found' if complete and not rows[0]['metadata_conflicts'] else 'review'
        else:
            status = 'not_found' if complete else 'unverified'
        matches[identity] = {'status': status, 'recorded_status': state,
                             'evidence': rows[0]['evidence'][0] if rows else None,
                             'candidates': rows[:20], 'candidate_count': len(rows)}
    complete = not warning_count
    if not complete:
        for match in matches.values():
            if match['status'] == 'found':match['status'] = 'review'
            elif match['status'] == 'not_found':match['status'] = 'unverified'
    return {'scan_id': uuid4().hex, 'advanced': True, 'complete': complete,
            'created': datetime.now(timezone.utc).isoformat(), 'roots': roots,
            'file_count': len(files), 'visited_entries': visited, 'warnings': warnings,
            'warning_count': warning_count, 'matches': matches,
            'orphans': [r for r in files.values() if r['path'] not in referenced],
            'counts': dict(Counter(r['status'] for r in matches.values())),
            'note': 'Suggestions describe only the selected folders. A unique candidate is not proof of audio identity. No result means gone forever.'}


def stage_candidate(inventory, match):
    if match.get('status') != 'found' or len(match.get('candidates', [])) != 1:
        raise ValueError('Choose a reference with exactly one local candidate')
    if inventory.get('advanced') and not inventory.get('complete'):
        raise ValueError('Finish a complete recovery scan before staging')
    record = match['candidates'][0]
    uri = record.get('export_uri')
    if not uri or not valid_export_uri(uri):
        raise ValueError('Set the Windows or macOS export root URI in the mapping and scan again')
    path = Path(record['path'])
    try:
        if not ordinary_path(path) or not os.access(path, os.R_OK):
            raise ValueError('Candidate unavailable or linked; scan again')
        current = file_record(path)
    except OSError as error:
        raise ValueError('Candidate unavailable; scan again') from error
    if current['cloud_only'] or (current['size'], current['mtime_ns']) != (record['size'], record['mtime_ns']):
        raise ValueError('Candidate changed since the scan; scan again')
    return uri


def recovery_report(session):
    inventory = session.get('inventory')
    if not inventory:
        raise ValueError('Scan the media roots first')
    return {'schema': 1, 'kind': 'Recovery review report; not a library or audio backup',
            'workspace': session['id'], 'created': datetime.now(timezone.utc).isoformat(),
            'scan': {k: v for k, v in inventory.items() if k not in ('matches', 'orphans')},
            'input_fingerprints': session.get('metadata', {}).get('input_fingerprints', {}),
            'tracks': [{'track_id': i, 'metadata': session['catalog'].tracks[i], **match,
                        'staged_uri': session['relocations'].get(i)} for i, match in inventory['matches'].items()],
            'backup_plan': [
                'Reconnect all drives and download cloud audio before another search.',
                'Keep an untouched Rekordbox Backup Library ZIP and matching collection XML on separate storage.',
                'Back up available music separately; a report or XML cannot recover missing audio.',
                'Test restoring the backup in a separate library before removing any entries.',
                'Review unresolved track IDs and playlists in Rekordbox. Remove only individually confirmed unwanted entries there.'],
            'library_entries_removed': 0, 'audio_files_modified': False}
