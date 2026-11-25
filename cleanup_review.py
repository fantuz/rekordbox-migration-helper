"""Plan an immutable Workbench collection snapshot using recorded references and fresh local evidence."""
from collections import Counter, defaultdict
from hashlib import sha256
import json

from cleanup_paths import PathInspector
from export_references import decoded_path
from metadata_sidecars import leaf_name

HASH_BUDGET = 8 * 1024 ** 3
PATH_FIELDS = ('current_path', 'xml_location', 'original_path')
LOCATION_REASONS = {
    'cloud': 'cloud_reference', 'external': 'external_volume', 'foreign': 'foreign_os',
    'outside': 'outside_music', 'unclassified': 'unknown_path', 'unavailable': 'unavailable_folder',
    'sidecar': 'metadata_sidecar',
}


def _token(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def location_evidence(finding):
    """Fingerprint the filesystem observation separately for a final metadata-only recheck."""
    return _token(finding)


def _path_key(value):
    try:
        return decoded_path(value)
    except ValueError:
        return value


def _present(value):
    return value not in (None, '', 0, '0', False)


def _preparation(track, playlist_members, history_members):
    reasons = set(track.get('cleanup_links') or ())
    identity = str(track.get('id', ''))
    if track.get('cues') or _present(track.get('manual_cues')) or _present(track.get('auto_cues')):
        reasons.add('cues')
    if track.get('playlists') or identity in playlist_members:
        reasons.add('playlist')
    if _present(track.get('play_count')) or track.get('last_played') or identity in history_members:
        reasons.add('play_history')
    if any(track.get(k) for k in ('analysis_path','analysed','grid_bpms','tempo_markers')):
        reasons.add('analysis')
    if _present(track.get('rating')) or _present((track.get('raw_tags') or {}).get('rating')):
        reasons.add('rating')
    if track.get('comment') or track.get('color_status') == 'assigned':
        reasons.add('saved_metadata')
    if not isinstance(track.get('size'), int) or isinstance(track.get('size'), bool) or track['size'] <= 0:
        reasons.add('unknown_metadata')
    return reasons


def build_report(snapshot, *, inspector=None, compare_bytes=False, protected_ids=(), cloud_ids=(),
                 extra_cloud_roots=(), progress=None, scope_ids=None, review_only=False):
    """Read-only review. Scoped rereads must include both the selection and its original keepers."""
    inspector = inspector or PathInspector.current(extra_cloud_roots=extra_cloud_roots)
    tracks = snapshot['tracks']
    coverage = snapshot.get('cleanup_coverage') or {}
    gates = []
    if not inspector.can_apply:
        gates.append('host_review_only' if inspector.host not in ('Windows', 'macOS') else 'unavailable_folder')
    if review_only:
        gates.append('save_snapshot')
    if snapshot.get('cleanup_lineage') or str(snapshot.get('scope_key', '')).startswith('cleanup:'):
        gates.append('derived_snapshot')
    if coverage.get('version') != 1 or coverage.get('scope') not in ('xml', 'native') or coverage.get('complete') is not True:
        gates.append('incomplete_capture')
    track_ids = Counter(str(t.get('id') or '') for t in tracks)
    if '' in track_ids or any(count != 1 for count in track_ids.values()):
        gates.append('ambiguous_identity')
    if scope_ids is not None:
        scope_ids = set(scope_ids)
        if not scope_ids.issubset(track_ids):
            raise ValueError('A selected reference or its keeper is missing from this snapshot.')
    playlist_members = {str(t) for p in snapshot.get('playlists', []) for t in p.get('tracks', [])}
    history_members = {str(e.get('track_id')) for h in snapshot.get('histories', []) for e in h.get('entries', [])}
    findings = []
    rows = []
    name_sizes = Counter()
    cloud_ids = set(cloud_ids)
    for i, track in enumerate(tracks):
        identity = str(track.get('id') or '')
        if scope_ids is not None and identity not in scope_ids:
            continue
        if progress and i % 250 == 0:
            progress(5 + 60 * i // max(1,len(tracks)), 'Checking recorded collection paths')
        reasons = _preparation(track, playlist_members, history_members)
        if identity in protected_ids:
            reasons.update(protected_ids[identity] if isinstance(protected_ids, dict) else ('metadata_edit',))
        reasons.update(gates)
        service = (track.get('source_evidence') or {}).get('service_id')
        cloud_hint = identity in cloud_ids or _present(service) or 'cloud_reference' in reasons
        paths = list(dict.fromkeys(p for k in PATH_FIELDS if isinstance((p := track.get(k)), str) and p))
        path = paths[0] if paths else ''
        finding = inspector.inspect(path, cloud_hint=cloud_hint)
        status = finding['status']
        if status == 'missing' and (track.get('tonality') or _present(track.get('bpm'))):
            # Tag-derived BPM/key can match across duplicates, but have no keeper on a missing row.
            reasons.add('saved_metadata')
        if status in LOCATION_REASONS:
            reasons.add(LOCATION_REASONS[status])
        if not track.get('current_path') and not track.get('xml_location'):
            reasons.add('unknown_path')  # The original path alone cannot establish the current file.
        for alternate in paths[1:]:
            alt = inspector.inspect(alternate, cloud_hint=cloud_hint)
            if finding == alt and _path_key(alternate) == _path_key(path):
                continue
            if alt['status'] in LOCATION_REASONS:
                reasons.add(LOCATION_REASONS[alt['status']])
            if not (finding.get('identity') and finding['identity'] == alt.get('identity')):
                reasons.add('alternate_reference')
        if status == 'present' and finding['size'] != track.get('size'):
            reasons.add('size_conflict')
        metadata = _token({k:v for k,v in track.items() if k not in (*PATH_FIELDS, 'id', 'uuid')})
        size = track.get('size')
        hint = (leaf_name(path) or '').casefold(), (size if type(size) is int and size > 0 else None)
        if hint[0] and hint[1] is not None:
            name_sizes[hint] += 1
        rows.append(dict(id=identity, title=track.get('title',''), artist=track.get('artist',''), path=path,
                         os=finding['os'], volume=finding['volume'], status=status, reasons=sorted(reasons),
                         protected=bool(reasons), candidate=None, keeper_id=None, keeper_path=None,
                         proof=None, signals=[]))
        findings.append((finding, metadata, hint))

    by_size = defaultdict(list)
    for index, (finding, metadata, _) in enumerate(findings):
        if not rows[index]['protected'] and finding['status'] == 'present' and finding['identity']:
            by_size[finding['size']].append(index)
    digests = {}
    used = skipped = 0
    if compare_bytes and not gates:
        for size, indices in sorted(by_size.items()):
            if len(indices) < 2:
                continue
            for i in indices:
                if progress:
                    progress(65 + 30 * used // HASH_BUDGET, 'Comparing eligible local audio files')
                if size > HASH_BUDGET - used:
                    skipped += 1
                    continue
                def on_bytes(consumed):
                    progress(65 + 30 * (used + consumed) // HASH_BUDGET, 'Comparing eligible local audio files')
                digest, consumed = inspector.digest(rows[i]['path'], findings[i][0], HASH_BUDGET - used,
                                                    on_bytes if progress else None)
                used += consumed
                if digest:
                    digests[i] = digest
                else:
                    skipped += 1
    # Positive file identity covers aliases without reading bytes. A content comparison
    # also covers distinct local files. Never merge different captured catalog metadata.
    groups = defaultdict(list)
    for indices in by_size.values():
        for i in indices:
            finding = findings[i][0]
            group = ('sha256', digests[i]) if i in digests else ('same_file', tuple(finding['identity']))
            groups[group].append(i)
    for (proof, _), indices in groups.items():
        if len(indices) < 2:
            continue
        by_metadata = defaultdict(list)
        for i in indices:
            by_metadata[findings[i][1]].append(i)
        for matching in by_metadata.values():
            keeper = min(matching, key=lambda j: rows[j]['id'])
            for i in matching:
                if len(by_metadata) > 1:
                    rows[i]['signals'].append('distinct_metadata')
                if i != keeper:
                    # File identity remains the same proof when a scoped recheck has more byte budget.
                    same_file = findings[i][0]['identity'] == findings[keeper][0]['identity']
                    rows[i].update(candidate='duplicate', keeper_id=rows[keeper]['id'],
                                   keeper_path=rows[keeper]['path'], proof='same_file' if same_file else proof)
    volumes = {}
    statuses, reasons, signals = Counter(), Counter(), Counter()
    counts = dict(total=len(rows), protected=0, eligible=0, missing=0, duplicate=0)
    for i, row in enumerate(rows):
        finding, metadata, hint = findings[i]
        if name_sizes[hint] > 1:
            row['signals'].append('same_name_size')
        if not row['protected'] and row['status'] == 'missing':
            row.update(candidate='missing', proof='absent')
        row['location_evidence'] = location_evidence(finding)
        digest = digests[i] if row['proof'] == 'sha256' else None
        row['evidence'] = _token([row['id'], row['path'], metadata, finding, row['reasons'], digest])
        statuses[row['status']] += 1
        reasons.update(row['reasons'])
        signals.update(row['signals'])
        v = volumes.setdefault((row['os'],row['volume']), dict(os=row['os'],volume=row['volume'],total=0,
                                                               present=0,missing=0,protected=0,eligible=0))
        v['total'] += 1
        if row['status'] in ('present','missing'):
            v[row['status']] += 1
        counts['protected'] += int(row['protected'])
        v['protected'] += int(row['protected'])
        if row['candidate']:
            counts['eligible'] += 1
            counts[row['candidate']] += 1
            v['eligible'] += 1
    return dict(host=inspector.host, can_apply=not gates, gates=gates, rows=rows, counts=counts,
                coverage_gaps=coverage.get('gaps', [] if coverage else ['older_capture']),
                parent_snapshot_id=(snapshot.get('cleanup_lineage') or {}).get('parent_snapshot_id'),
                statuses=dict(statuses), reasons=dict(reasons), signals=dict(signals),
                volumes=[volumes[k] for k in sorted(volumes)], compare_bytes=compare_bytes,
                hash_bytes=used, hashed_files=len(digests), hash_skipped=skipped, hash_budget=HASH_BUDGET)
