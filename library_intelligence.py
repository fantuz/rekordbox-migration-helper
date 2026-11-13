"""Bounded, explainable collection insights from captured metadata only."""
from collections import Counter
from math import isfinite
from library_checks import match_tracks


def distributions(tracks, fields=('genre','artist')):
    return {field:Counter(str(t.get(field) or '') for t in tracks) for field in fields}


def distribution_changes(before, after, limit=30):
    left,right=distributions(before),distributions(after)
    return {field:[{'name':key,'before':left[field][key],'after':right[field][key],
                    'delta':right[field][key]-left[field][key]}
                   for key in sorted(left[field].keys()|right[field].keys(),
                                     key=lambda k:(-abs(right[field][k]-left[field][k]),k.casefold()))
                   if left[field][key]!=right[field][key]][:limit] for field in left}


def duplicate_impact(snapshot, removed):
    removed=set(removed);tracks=snapshot['tracks'];kept=[t for t in tracks if t['id'] not in removed]
    return {'before_records':len(tracks),'retained_records':len(kept),'removed_records':len(tracks)-len(kept),
            'distributions':distribution_changes(tracks,kept),
            'basis':'Captured record counts after excluding donors from validated staged merges. This is not a count of distinct recordings or freed audio bytes.',
            'data_state':'captured metadata; donor exclusion only','audio_files_removed':False}


def playlists(snapshot):
    if snapshot.get('playlists'):
        return [{'id':str(p['id']),'name':p.get('name',''),'tracks':list(p.get('tracks',[])),
                 'order_available':bool(snapshot.get('capabilities',{}).get('playlist_order')),
                 'smart':bool(p.get('smart'))} for p in snapshot['playlists'] if not p.get('folder')]
    # XML/workspace summaries retain names rather than stable playlist identities.
    names={}
    for track in snapshot['tracks']:
        for name in track.get('playlists',[]):names.setdefault(name,[]).append(track['id'])
    return [{'id':'name:'+name,'name':name,'tracks':ids,'order_available':False,'smart':False} for name,ids in sorted(names.items())]


def page_offset(value):
    if isinstance(value,bool):raise ValueError('Choose a valid page offset')
    try:result=int(value)
    except (TypeError,ValueError,OverflowError):raise ValueError('Choose a valid page offset') from None
    return max(0,result)


def playlist_overlap(snapshot, identity, minimum=.5, offset=0):
    try:minimum=float(minimum)
    except (TypeError,ValueError,OverflowError):raise ValueError('Choose an overlap threshold from 0 to 1') from None
    offset=page_offset(offset)
    if not isfinite(minimum) or not 0<=minimum<=1:raise ValueError('Choose an overlap threshold from 0 to 1')
    lists=playlists(snapshot);source=next((p for p in lists if p['id']==identity),None)
    if source is None:raise ValueError('Choose a captured playlist')
    selected=set(source['tracks']);rows=[]
    for other in lists:
        if other['id']==identity:continue
        ids=set(other['tracks']);common=len(selected&ids);union=len(selected|ids)
        similarity=common/union if union else 0
        if not common or similarity<minimum:continue
        rows.append({'id':other['id'],'name':other['name'],'common_tracks':common,'tracks':len(ids),
                     'jaccard':round(similarity,4),'identical_membership':selected==ids,
                     'contains_selected':selected<=ids,'selected_contains_other':ids<=selected,
                     'same_saved_order':source['tracks']==other['tracks'] if source['order_available'] and other['order_available'] else None,
                     'smart':other['smart']})
    rows.sort(key=lambda r:(-r['jaccard'],-r['common_tracks'],r['name'].casefold()))
    return {'playlist':{'id':identity,'name':source['name'],'entries':len(source['tracks']),'distinct_tracks':len(selected)},
            'rows':rows[offset:offset+50],'total':len(rows),'offset':offset,
            'basis':'Shared captured track IDs / union of IDs. Intentional playlist overlap is not an error. Name-only captures can combine playlists with the same name; saved order is unavailable there.'}


def session_progression(snapshot, identity, offset=0):
    caps=snapshot.get('capabilities',{})
    if not caps.get('history_details') or not caps.get('history_order'):
        raise ValueError('Saved native history order is required for session progression')
    history=next((h for h in snapshot.get('histories',[]) if h['id']==identity and not h.get('folder')),None)
    if history is None:raise ValueError('Choose a captured history session')
    tracks={t['id']:t for t in snapshot['tracks']};offset=page_offset(offset);rows=[]
    entries=history['entries']
    def bpm(t):
        value=t.get('bpm')
        return value if isinstance(value,(int,float)) and isfinite(value) and value>0 else None
    for index in range(offset,min(offset+50,len(entries))):
        entry=entries[index];track=tracks.get(entry['track_id'],{});previous=tracks.get(entries[index-1]['track_id'],{}) if index else {}
        current_bpm,prior_bpm=bpm(track),bpm(previous)
        rows.append({'sequence':index+1,'position':entry.get('position'),'track_id':entry['track_id'],
                     **{f:track.get(f,entry.get(f) if f in ('title','artist') else None) for f in ('title','artist','bpm','tonality','color_name','color_hex')},
                     'missing_metadata':not bool(track),'bpm_delta':round(current_bpm-prior_bpm,2) if current_bpm is not None and prior_bpm is not None else None})
    return {'session':{f:history.get(f) for f in ('id','name','date')},'rows':rows,'total':len(entries),'offset':offset,
            'basis':'Saved session order with tags from this capture. BPM differences describe stored tags, not measured transitions. No individual play times, energy or gig duration is inferred.'}


def evolution(before, after):
    old,new,mapping,evidence=match_tracks(before,after)
    fields=('artist','album','genre','year','bpm','rating','tonality','color_name','analysed','play_count')
    changes=Counter();unavailable=Counter()
    for a,b in mapping.items():
        for field in fields:
            left,right=old[a].get(field),new[b].get(field)
            if left is None or right is None:unavailable[field]+=1
            elif left!=right:changes[field]+=1
    return {'before_records':len(old),'after_records':len(new),'matched_records':len(mapping),
            'unmatched_before':len(old)-len(mapping),'unmatched_after':len(new)-len(mapping),
            'match_evidence':dict(Counter(evidence.values())),'changed_fields':dict(changes),
            'unavailable_field_comparisons':dict(unavailable),
            'distributions':distribution_changes(list(old.values()),list(new.values())),
            'before_captured':before.get('source_captured') or before.get('captured'),
            'after_captured':after.get('source_captured') or after.get('captured'),
            'basis':'Unique UUID, compatible ID, ISRC or recorded-path matches. Unmatched records may be new, removed or ambiguous; no deletion is inferred. Distributions count records, including duplicates.'}
