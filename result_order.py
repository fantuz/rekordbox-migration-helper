"""Typed, stable ordering before pagination; missing values always come last."""
from math import isfinite

NUMERIC={'year','rating','bpm','duration','position','sequence','tracks','common_tracks','jaccard',
         'playlists','saved_sessions','saved_entries','bpm_delta','plays','same_saved_order'}
TRACK_FIELDS=('title','artist','album','genre','year','rating','bpm','duration','file_status')
STATUS={'playable':0,'missing':1,'inaccessible':2,'unverified':3}

def ordered(rows,field='',direction='asc',allowed=TRACK_FIELDS):
    if field not in ('',*allowed) or direction not in ('asc','desc'):
        raise ValueError('Choose a supported collection sort')
    if not field:return list(rows)
    def key(row):
        value=row.get(field)
        if field=='file_status':return STATUS.get(value)
        if field in NUMERIC:
            return value if isinstance(value,(int,float)) and isfinite(value) else None
        return str(value).casefold() if value not in (None,'') else None
    known=[];missing=[]
    for row in rows:
        value=key(row)
        (missing if value is None else known).append(row)
    return sorted(known,key=key,reverse=direction=='desc')+missing

def scan_statuses(store,snapshot):
    identity=snapshot.get('id','')
    source=identity if identity.startswith(('capture:','snapshot:')) else 'snapshot:'+identity
    with store.connection() as db:
        return {r['track_id']:r['status'] for r in db.execute(
            'SELECT track_id,status FROM file_health_records WHERE source=?',(source,))}

def with_status(rows,statuses,identity='id'):
    return [{**row,'file_status':statuses.get(str(row.get(identity,'')))} for row in rows]

def page_result(result,args,allowed,page_size=50,statuses=None,identity='track_id',full=False):
    rows=result['rows']
    if statuses is not None:rows=with_status(rows,statuses,identity)
    rows=ordered(rows,args.get('sort',''),args.get('direction','asc'),allowed)
    try:offset=max(0,int(args.get('offset',0)))
    except (TypeError,ValueError,OverflowError):raise ValueError('Choose a valid page offset') from None
    return {**result,'rows':rows if full else rows[offset:offset+page_size],
            'total':len(rows),'offset':offset,'sort':args.get('sort',''),
            'direction':args.get('direction','asc'),'sort_scope':'collection',
            'file_status_basis':'Last saved File health scan; unchecked tracks sort last'}
