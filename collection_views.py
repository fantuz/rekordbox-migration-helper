"""Read-only statistics, candidate groups and references for saved collections."""
from collections import defaultdict
from hashlib import sha256
import math
import ntpath
import re
import unicodedata

from result_cache import cached_collection
from flask import jsonify, request

from collection_sources import resolve, source_report
from history_browser import added_years
from workbench_store import Store
from chart_views import collection_charts,hide_unknown
import cloud_analysis


def normalized(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split())


def path_key(value):
    value = str(value or '').replace('\\', '/')
    # Case is significant on POSIX. Windows drive/UNC paths compare case-insensitively.
    return ntpath.normpath(value).casefold() if re.match(r'^[A-Za-z]:/', value) or value.startswith('//') else value


def statistics(snapshot, minimum=0, maximum=math.inf, report=None, hide=False, provider="all", cloud_context=None):
    hide=hide_unknown(hide)
    if not math.isfinite(minimum) or minimum < 0 or maximum < minimum or math.isnan(maximum):
        raise ValueError('Enter a finite, non-negative length range')
    tracks = [t for t in snapshot['tracks'] if
              (t.get('duration') is None and minimum == 0 and maximum == math.inf) or
              (t.get('duration') is not None and minimum <= t['duration'] <= maximum)]
    tracks,cloud=cloud_analysis.select(tracks,provider,cloud_context)
    def count(fields, predicate):
        return None if any(any(t.get(f) is None for f in fields) for t in tracks) else sum(predicate(t) for t in tracks)
    counters = {'total': len(tracks), 'dropbox_paths':cloud['selected_counts']['dropbox'],
                'google_drive_paths':cloud['selected_counts']['google_drive'],
                'analysed': count(['analysed'], lambda t: bool(t['analysed'])),
                'rated': count(['rating'], lambda t: t['rating'] > 0),
                'full_manual': count(['manual_cues', 'auto_cues'], lambda t: t['manual_cues'] > 0 and t['auto_cues'] == 0),
                'mixed': count(['manual_cues', 'auto_cues'], lambda t: t['manual_cues'] > 0 and t['auto_cues'] > 0),
                'only_auto': count(['manual_cues', 'auto_cues'], lambda t: t['manual_cues'] == 0 and t['auto_cues'] > 0),
                'no_cues': count(['manual_cues', 'auto_cues'], lambda t: t['manual_cues'] + t['auto_cues'] == 0),
                'no_cues_no_plays': count(['manual_cues', 'auto_cues', 'play_count'], lambda t: t['manual_cues'] + t['auto_cues'] == 0 and t['play_count'] == 0)}
    for name, field in [('albums', 'album'), ('authors', 'artist'), ('composers', 'composer')]:
        counters[name] = len({str(t.get(field) or '').strip().casefold() for t in tracks if str(t.get(field) or '').strip()})
    playlists = [p for p in snapshot.get('playlists', []) if not p.get('folder')]
    ids = {t['id'] for t in tracks}
    capabilities=snapshot.get('capabilities', {})
    known_playlists = capabilities.get('playlist_membership', capabilities.get('playlist_order', False)) is True
    counters.update(total_playlists=len(playlists) if known_playlists else None,
                    playlists=sum(bool(ids.intersection(p['tracks'])) for p in playlists) if known_playlists else None,
                    broken_xml_targets=None, broken_database_links=None, orphan_analysis_folders=None,
                    missing_media=None, orphan_media=None)
    health = (report or {}).get('database', {}).get('health', {})
    counters['broken_database_links'] = health.get('broken_track_links')
    counters['orphan_analysis_folders'] = health.get('unlinked_analysis_folders')
    bins = [(30, '< 30 sec'), (60, '30–60 sec'), (180, '1–3 min'), (300, '3–5 min'),
            (600, '5–10 min'), (1800, '10–30 min'), (3600, '30–60 min'), (math.inf, '> 60 min')]
    counts = [0] * len(bins)
    for t in tracks:
        if t.get('duration') is None:
            continue
        for n, (limit, _) in enumerate(bins):
            if t['duration'] < limit:
                counts[n] += 1
                break
    histogram=[{'label': label, 'count': n} for (_, label), n in zip(bins, counts)]
    additions=added_years(tracks)
    return {'counters': counters, 'cloud':cloud,'histogram':histogram,
            'addition_dates':additions,'charts':collection_charts(tracks,histogram,additions,hide),'hide_unknown':hide,
            'unknown_duration': sum(t.get('duration') is None for t in tracks),
            'scope': 'captured', 'note': 'Captured metadata; unknown fields stay unverified. Relationship counts cover the full source. Audio availability requires a local scan.'}


def duplicate_groups(snapshot, basis='path'):
    if basis not in ('path', 'metadata'):
        raise ValueError('Choose recorded paths or artist and title')
    buckets = defaultdict(list)
    for t in snapshot['tracks']:
        key = path_key(t.get('current_path')) if basis == 'path' else (normalized(t.get('artist')), normalized(t.get('title')))
        if (basis == 'path' and key) or (basis == 'metadata' and all(key)):
            buckets[key].append(t)
    result = []
    for members in buckets.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda t: t['id'])
        identity = sha256((basis + '\0' + '\0'.join(t['id'] for t in members)).encode()).hexdigest()[:32]
        durations = [t['duration'] for t in members if t.get('duration') is not None]
        result.append({'id': identity, 'basis': basis, 'tracks': members, 'count': len(members),
                       'duration_spread': max(durations) - min(durations) if durations else None})
    return sorted(result, key=lambda g: (-g['count'], g['id']))


def sort_collection_rows(rows, view, field, direction):
    """Sort the complete filtered result before taking a 50-row page."""
    allowed = {'duplicates': {'title', 'count', 'duration_spread', 'review'},
               'references': {'title', 'current_path', 'original_path', 'analysis_path'}}
    if field not in allowed[view] or direction not in ('asc', 'desc'):
        raise ValueError('Choose a supported collection sort column and direction')
    # Stable tie-breaker makes consecutive pages repeatable across requests.
    ordered = sorted(rows, key=lambda row: str(row.get('id') or ''))
    present, unknown = [], []
    for row in ordered:
        value = row.get(field)
        (unknown if value is None or isinstance(value, str) and not value.strip() else present).append(row)
    if field in ('count', 'duration_spread'):
        key = lambda row: row[field]
    elif field == 'review':
        rank = {'unreviewed': 0, 'candidate': 1, 'keep_separate': 2}
        key = lambda row: rank.get(row[field], 99)
    else:
        key = lambda row: normalized(row[field])
    present.sort(key=key, reverse=direction == 'desc')
    return present + unknown


def register(owner):
    app = owner.app
    def source():
        value = request.args.get('source', '')
        return value, resolve(owner, value)
    def page(rows):
        offset = max(0, int(request.args.get('offset', 0)))
        return {'rows': rows[offset:offset + 50], 'total': len(rows), 'offset': offset}
    def matches(track):
        query = normalized(request.args.get('q', ''))
        return not query or query in normalized(' '.join(str(track.get(f) or '') for f in
                                                        ('id', 'title', 'artist', 'current_path', 'original_path', 'analysis_path')))
    def reviews(key):
        return Store(owner.DATA / 'workbench-sidecar.sqlite3').setting('duplicate_reviews:' + key, {})

    def cloud_context():return cloud_analysis.context(owner,request.args.get('source',''))
    def cloud_signature():return cloud_analysis.signature(cloud_context())

    @app.get('/api/collection/statistics')
    @cached_collection(owner,vary=cloud_signature)
    def collection_statistics():
        key, snapshot = source()
        minimum = float(request.args.get('min') or 0) * 60
        maximum = float(request.args['max']) * 60 if request.args.get('max') else math.inf
        if request.args.get('max') and not math.isfinite(maximum):
            raise ValueError('Enter a finite maximum length')
        return jsonify(source=key, **statistics(snapshot, minimum, maximum, source_report(owner, snapshot),request.args.get('hide_unknown',False),request.args.get('provider','all'),cloud_context()))

    @app.get('/api/collection/duplicates')
    @cached_collection(owner,vary=cloud_signature)
    def collection_duplicates():
        from track_flags import flags,checked_flag,FLAGS
        flag=checked_flag(request.args.get('flag',''))
        key, snapshot = source()
        groups = duplicate_groups(snapshot, request.args.get('basis', 'path'))
        provider=cloud_analysis.checked_provider(request.args.get('provider','all'));configuration=cloud_context()
        def provider_match(track):return cloud_analysis.matches(cloud_analysis.classify(track,configuration),provider)
        saved = reviews(key)
        rows = [{'id': g['id'], 'basis': g['basis'], 'count': g['count'], 'duration_spread': g['duration_spread'],
                 'title': g['tracks'][0].get('title'), 'artist': g['tracks'][0].get('artist'),
                 'review': saved.get(g['id'], 'unreviewed'), 'flags': sorted({f for t in g['tracks'] for f in flags(t)})} for g in groups if any(matches(t) for t in g['tracks']) and any(provider_match(t) for t in g['tracks'])]
        flag_counts={key:sum(key in r['flags'] for r in rows) for key in FLAGS}
        if flag:rows=[r for r in rows if flag in r['flags']]
        sorting = request.args.get('sort', 'count')
        direction = request.args.get('direction', 'desc')
        rows = sort_collection_rows(rows, 'duplicates', sorting, direction)
        return jsonify(source=key, **page(rows), sort=sorting, direction=direction, flag=flag,flag_counts=flag_counts,
                       groups=len(rows), tracks=sum(r['count'] for r in rows),source_groups=len(groups),
                       source_tracks=sum(g['count'] for g in groups),provider=provider,cloud_note=cloud_analysis.NOTE,
                       note='Candidates only. Paths and matching tags do not prove identical audio; versions, durations and cues need review. No merge or source write is performed.')

    @app.get('/api/collection/duplicates/<identity>')
    @cached_collection(owner,vary=cloud_signature)
    def collection_duplicate(identity):
        key, snapshot = source()
        group = next((g for g in duplicate_groups(snapshot, request.args.get('basis', 'path')) if g['id'] == identity), None)
        if group is None:
            raise ValueError('This candidate group is no longer available')
        from track_flags import flags
        return jsonify(source=key, id=identity, count=group['count'], review=reviews(key).get(identity, 'unreviewed'), **page([{**t,'flags':flags(t)} for t in group['tracks']]))

    @app.post('/api/collection/duplicates/<identity>/review')
    def review_duplicate(identity):
        b = request.get_json(silent=True)
        if not isinstance(b, dict):
            raise ValueError('Supply a JSON object')
        key = b.get('source', '')
        status = b.get('status')
        if status not in ('unreviewed', 'keep_separate', 'candidate'):
            raise ValueError('Choose a supported review status')
        snapshot = resolve(owner, key)
        if not any(g['id'] == identity for g in duplicate_groups(snapshot, b.get('basis', 'path'))):
            raise ValueError('This candidate group is no longer available')
        with owner.lock:
            saved = reviews(key)
            saved[identity] = status
            Store(owner.DATA / 'workbench-sidecar.sqlite3').set_setting('duplicate_reviews:' + key, saved)
        return jsonify(saved=True, source_writes=False)

    @app.get('/api/collection/references')
    @cached_collection(owner,vary=cloud_signature)
    def collection_references():
        key, snapshot = source()
        mode = request.args.get('mode', 'all')
        if mode not in ('all', 'changed', 'missing_path'):
            raise ValueError('Choose a reference filter')
        def changed(t):
            return bool(t.get('original_path')) and path_key(t['original_path']) != path_key(t.get('current_path'))
        tracks = snapshot['tracks']
        matching=[t for t in tracks if matches(t) and (mode == 'all' or mode == 'changed' and changed(t) or mode == 'missing_path' and not t.get('current_path'))]
        selected,cloud=cloud_analysis.select(matching,request.args.get('provider','all'),cloud_context())
        rows = [{f: t.get(f) for f in ('id', 'title', 'artist', 'current_path', 'original_path', 'analysis_path', 'size')}
                for t in selected]
        sorting = request.args.get('sort', 'title')
        direction = request.args.get('direction', 'asc')
        rows = sort_collection_rows(rows, 'references', sorting, direction)
        return jsonify(source=key, **page(rows), sort=sorting, direction=direction,
                       tracks=len(selected),source_tracks=len(tracks),cloud=cloud, changed=sum(changed(t) for t in selected),
                       missing_path=sum(not t.get('current_path') for t in selected),
                       note='Recorded current, original and analysis paths. An empty path is not proof of a missing audio file. Playback checks availability on this computer only.')
