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
from duplicate_evidence import EVIDENCE_KEYS, isrc_key, recorded_comparisons
from history_browser import added_years
from workbench_store import Store
from chart_views import collection_charts,hide_unknown
import cloud_analysis
import collection_storage
import metadata_sidecars


def normalized(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split())


def path_key(value):
    value = str(value or '').replace('\\', '/')
    # Case is significant on POSIX. Windows drive/UNC paths compare case-insensitively.
    return ntpath.normpath(value).casefold() if re.match(r'^[A-Za-z]:/', value) or value.startswith('//') else value


def statistics(snapshot, minimum=0, maximum=math.inf, report=None, hide=False, provider="all",
               cloud_context=None, hide_sidecars=False, *, owner=None, source=''):
    hide=hide_unknown(hide)
    if not math.isfinite(minimum) or minimum < 0 or maximum < minimum or math.isnan(maximum):
        raise ValueError('Enter a finite, non-negative length range')
    tracks = [t for t in snapshot['tracks'] if
              (t.get('duration') is None and minimum == 0 and maximum == math.inf) or
              (t.get('duration') is not None and minimum <= t['duration'] <= maximum)]
    tracks,sidecars=metadata_sidecars.select(tracks,hide_sidecars)
    selected,cloud=cloud_analysis.select_with_evidence(tracks,provider,cloud_context)
    tracks = [track for track, _ in selected]
    storage = collection_storage.recorded_storage(selected)
    storage['observed'] = collection_storage.observed_storage(
        owner, source, tracks, (cloud_context or {}).get('mappings', []))
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
    return {'counters': counters, 'sidecars':sidecars,'cloud':cloud,'storage':storage,'histogram':histogram,
            'addition_dates':additions,'charts':collection_charts(tracks,histogram,additions,hide),'hide_unknown':hide,
            'unknown_duration': sum(t.get('duration') is None for t in tracks),
            'scope': 'captured', 'note': 'Captured metadata; unknown fields stay unverified. Relationship counts cover the full source. Audio availability requires a local scan.'}


DUPLICATE_BASES = ('path', 'metadata', 'isrc')
DUPLICATE_REVIEW_STATES = ('unreviewed', 'keep_separate', 'candidate')


def duplicate_groups(snapshot, basis='path'):
    if basis not in DUPLICATE_BASES:
        raise ValueError('Choose a supported duplicate grouping basis')
    buckets = defaultdict(list)
    for t in snapshot['tracks']:
        if basis == 'path':
            key = path_key(t.get('current_path'))
        elif basis == 'isrc':
            key = isrc_key(t.get('isrc'))
        else:
            fields = (normalized(t.get('artist')), normalized(t.get('title')))
            key = fields if all(fields) else None
        if key:
            buckets[key].append(t)
    result = []
    for members in buckets.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda t: t['id'])
        identity = sha256((basis + '\0' + '\0'.join(t['id'] for t in members)).encode()).hexdigest()[:32]
        result.append({'id': identity, 'basis': basis, 'tracks': members, 'count': len(members),
                       **recorded_comparisons(members)})
    return sorted(result, key=lambda g: (-g['count'], g['id']))


def duplicate_review_keys(source, scope):
    """Workspace decisions used one shared key before review ownership was captured."""
    keys = ['duplicate_reviews:' + source]
    if source == 'workspace' and scope.startswith('session:'):
        keys.append('duplicate_reviews:' + scope)
    return keys


def sidecar_groups(groups, hide=False):
    """Retain candidate identities/review notes while hiding sidecar members."""
    hiding=metadata_sidecars.enabled(hide)
    members=[t for group in groups for t in group['tracks']]
    _,summary=metadata_sidecars.select(members,hiding)
    if not hiding:return groups,summary
    result=[]
    for group in groups:
        tracks=[t for t in group['tracks'] if not metadata_sidecars.is_sidecar(t)]
        if len(tracks)<2:continue
        result.append({**group, 'tracks':tracks, 'count':len(tracks), **recorded_comparisons(tracks)})
    return result,summary


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
    def reviews(key,snapshot):
        saved = Store(owner.DATA / 'workbench-sidecar.sqlite3')
        values = {}
        for name in duplicate_review_keys(key,snapshot.get('scope_key','')):
            values.update(saved.setting(name, {}))
        return values

    def cloud_context():return cloud_analysis.context(owner,request.args.get('source',''))
    def cloud_signature():return cloud_analysis.signature(cloud_context())
    def statistics_signature():
        return [cloud_signature(), collection_storage.observation_signature(owner, request.args.get('source',''))]

    @app.get('/api/collection/statistics')
    @cached_collection(owner,vary=statistics_signature)
    def collection_statistics():
        key, snapshot = source()
        minimum = float(request.args.get('min') or 0) * 60
        maximum = float(request.args['max']) * 60 if request.args.get('max') else math.inf
        if request.args.get('max') and not math.isfinite(maximum):
            raise ValueError('Enter a finite maximum length')
        return jsonify(source=key, **statistics(
            snapshot, minimum, maximum, source_report(owner, snapshot),
            request.args.get('hide_unknown',False), request.args.get('provider','all'),
            cloud_context(), request.args.get('hide_metadata_sidecars',False), owner=owner, source=key))

    @app.get('/api/collection/duplicates')
    @cached_collection(owner,vary=cloud_signature)
    def collection_duplicates():
        from track_flags import flags,checked_flag,FLAGS
        flag = checked_flag(request.args.get('flag', ''))
        criterion = request.args.get('criterion', '')
        review_filter = request.args.get('review_status', '')
        if criterion and criterion not in EVIDENCE_KEYS:
            raise ValueError('Choose a supported duplicate evidence criterion')
        if review_filter and review_filter not in DUPLICATE_REVIEW_STATES:
            raise ValueError('Choose a supported review status')
        key, snapshot = source()
        original_groups = duplicate_groups(snapshot, request.args.get('basis', 'path'))
        groups,sidecars = sidecar_groups(original_groups,request.args.get('hide_metadata_sidecars',False))
        provider=cloud_analysis.checked_provider(request.args.get('provider','all'));configuration=cloud_context()
        def provider_match(track):return cloud_analysis.matches(cloud_analysis.classify(track,configuration),provider)
        query = normalized(request.args.get('q', ''))
        identifier = isrc_key(query)
        def matches(track):
            return (not query or bool(identifier and identifier == isrc_key(track.get('isrc')))
                    or query in normalized(' '.join(str(track.get(field) or '') for field in (
                        'id', 'title', 'artist', 'album', 'isrc', 'current_path', 'original_path', 'analysis_path'))))
        saved = reviews(key,snapshot)
        rows = []
        for group in groups:
            review = saved.get(group['id'], 'unreviewed')
            tracks = group['tracks']
            if review_filter and review != review_filter or criterion and not group['evidence'][criterion]:
                continue
            if not any(matches(t) for t in tracks) or not any(provider_match(t) for t in tracks):
                continue
            rows.append({'id': group['id'], 'basis': group['basis'], 'count': group['count'],
                         'duration_spread': group['duration_spread'], 'evidence': group['evidence'],
                         'title': tracks[0].get('title'), 'artist': tracks[0].get('artist'),
                         'review': review, 'flags': sorted({f for t in tracks for f in flags(t)})})
        flag_counts={key:sum(key in r['flags'] for r in rows) for key in FLAGS}
        if flag:rows=[r for r in rows if flag in r['flags']]
        sorting = request.args.get('sort', 'count')
        direction = request.args.get('direction', 'desc')
        rows = sort_collection_rows(rows, 'duplicates', sorting, direction)
        return jsonify(source=key, **page(rows), sidecars=sidecars,sort=sorting, direction=direction, flag=flag,flag_counts=flag_counts,
                       criterion=criterion, review_status=review_filter,
                       groups=len(rows), tracks=sum(r['count'] for r in rows),source_groups=len(original_groups),
                       source_tracks=sum(g['count'] for g in original_groups),provider=provider,cloud_note=cloud_analysis.NOTE,
                       note='Candidates only. Paths and matching tags do not prove identical audio; versions, durations and cues need review. No merge or source write is performed.')

    @app.get('/api/collection/duplicates/<identity>')
    @cached_collection(owner,vary=cloud_signature)
    def collection_duplicate(identity):
        key, snapshot = source()
        groups,sidecars=sidecar_groups(duplicate_groups(snapshot,request.args.get('basis','path')),request.args.get('hide_metadata_sidecars',False))
        group = next((g for g in groups if g['id'] == identity), None)
        if group is None:
            raise ValueError('This candidate group is no longer available')
        from track_flags import flags
        return jsonify(source=key, sidecars=sidecars,id=identity, count=group['count'], review=reviews(key,snapshot).get(identity, 'unreviewed'), **page([{**t,'flags':flags(t)} for t in group['tracks']]))

    @app.post('/api/collection/duplicates/<identity>/review')
    def review_duplicate(identity):
        b = request.get_json(silent=True)
        if not isinstance(b, dict):
            raise ValueError('Supply a JSON object')
        key = b.get('source', '')
        status = b.get('status')
        if status not in DUPLICATE_REVIEW_STATES:
            raise ValueError('Choose a supported review status')
        snapshot = resolve(owner, key)
        if not any(g['id'] == identity for g in duplicate_groups(snapshot, b.get('basis', 'path'))):
            raise ValueError('This candidate group is no longer available')
        with owner.lock:
            store = Store(owner.DATA / 'workbench-sidecar.sqlite3')
            name = duplicate_review_keys(key,snapshot.get('scope_key',''))[-1]
            saved = store.setting(name,{})
            saved[identity] = status
            store.set_setting(name,saved)
        return jsonify(saved=True, source_writes=False)

    @app.get('/api/collection/references')
    @cached_collection(owner, vary=lambda: ['reference-groups-v1', cloud_signature()])
    def collection_references():
        from reference_views import group_references, reference_rows

        key, snapshot = source()
        mode = request.args.get('mode', 'all')
        grouping = request.args.get('group_by', 'none')
        query = normalized(request.args.get('q', '')).replace('\\', '/')
        fields = ('id', 'title', 'artist', 'current_path', 'original_path', 'analysis_path', 'xml_location')

        def search(track):
            return not query or query in normalized(' '.join(str(track.get(field) or '') for field in fields)).replace('\\', '/')

        rows, counts, sidecars, cloud = reference_rows(
            snapshot, search, mode, grouping, request.args.get('provider', 'all'),
            cloud_context(), request.args.get('hide_metadata_sidecars', False)
        )
        sorting = request.args.get('sort', 'title')
        direction = request.args.get('direction', 'asc')
        rows = group_references(sort_collection_rows(rows, 'references', sorting, direction), grouping)
        return jsonify(source=key, **page(rows), sidecars=sidecars, sort=sorting, direction=direction,
                       mode=mode, group_by=grouping, counts=counts, tracks=len(rows),
                       source_tracks=len(snapshot['tracks']), cloud=cloud,
                       changed=sum('changed' in row['flags'] for row in rows),
                       missing_path=sum('missing_path' in row['flags'] for row in rows),
                       note='Recorded current, original and analysis paths. An empty path is not proof of a missing audio file. Playback checks availability on this computer only.')
