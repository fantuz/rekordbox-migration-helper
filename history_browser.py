"""Saved history membership and addition dates, independent of live rekordbox."""
from collections import Counter
import re


def year_of(value):
    match=re.match(r'^([1-9]\d{3})(?:\D|\d{4}|$)',str(value or ''))
    return match[1] if match else None


def added_years(tracks):
    counts=Counter(year_of(t.get('date_added')) for t in tracks)
    return {'years':[{'year':year,'tracks':count} for year,count in sorted(((k,v) for k,v in counts.items() if k),reverse=True)],
            'unknown':counts.get(None,0),'tracks':sum(counts.values()),'basis':'Recorded date added to the library, separate from release year'}


def list_history(snapshot,query='',year='',offset=0):
    available=snapshot.get('capabilities',{}).get('history_details',False)
    histories=[h for h in snapshot.get('histories',[]) if not h.get('folder')]
    query=str(query).casefold().strip();counts=Counter(year_of(h.get('date')) for h in histories)
    selected=[h for h in histories if (not year or year_of(h.get('date'))==year or year=='unknown' and year_of(h.get('date')) is None)
              and (not query or query in str(h.get('name','')).casefold() or query in str(h.get('date','')).casefold())]
    selected.sort(key=lambda h:(h.get('date') or '',h.get('name') or ''),reverse=True);offset=max(0,int(offset))
    return {'available':available,'order_available':snapshot.get('capabilities',{}).get('history_order',False),
            'sessions_total':len(histories),'entries_total':sum(len(h['entries']) for h in histories),
            'years':[{'year':key,'sessions':value} for key,value in sorted(((k,v) for k,v in counts.items() if k),reverse=True)],
            'unknown_dates':counts.get(None,0),'rows':[{k:h.get(k) for k in ('id','name','date','parent')}|{'tracks':len(h['entries'])} for h in selected[offset:offset+30]],
            'total':len(selected),'offset':offset,'addition_dates':added_years(snapshot['tracks']),
            'note':'Saved membership and order, with tags from the captured collection. Individual play timestamps, actual performance duration and session purpose are not inferred.'}


def history_session(snapshot,identity,query='',offset=0,all_rows=False):
    if not snapshot.get('capabilities',{}).get('history_details'):raise ValueError('This snapshot has no decoded native play history. Capture a native ZIP workspace or source-folder snapshot again.')
    h=next((h for h in snapshot.get('histories',[]) if h['id']==identity and not h.get('folder')),None)
    if h is None:raise ValueError('Choose a saved history session')
    tracks={t['id']:t for t in snapshot['tracks']};rows=[];query=str(query).casefold().strip()
    for entry in h['entries']:
        t=tracks.get(entry['track_id']);missing=t is None
        values=t or entry
        item={field:values.get(field) for field in ('title','artist','album','genre','bpm','rating','duration','date_added')}
        item.update(track_id=entry['track_id'],position=entry.get('position'),missing_from_active_collection=missing)
        if not item['title']:item['title']='Track metadata unavailable'
        if not query or query in ' '.join(str(v or '') for v in item.values()).casefold():rows.append(item)
    offset=max(0,int(offset))
    return {'session':{k:h.get(k) for k in ('id','name','date')},'rows':rows if all_rows else rows[offset:offset+50],
            'total':len(rows),'recorded_entries':len(h['entries']),'offset':offset,'order_available':snapshot['capabilities'].get('history_order',False),
            'track_duration_sum':sum((tracks.get(e['track_id']) or {}).get('duration') or 0 for e in h['entries']),
            'missing_track_metadata':sum(e['track_id'] not in tracks for e in h['entries']),
            'note':'Track duration sum is not gig duration. Session dates and saved track order are shown as recorded; track tags come from the captured collection.'}
