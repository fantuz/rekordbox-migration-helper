"""Opt-in MusicBrainz proof of concept. GET only, bounded samples, paced requests."""
from collections import Counter,defaultdict
from math import isfinite
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from difflib import SequenceMatcher
from hashlib import sha256
import json
import re
import threading
import time
from urllib.parse import urlencode
import urllib.request
import urllib.error
from uuid import UUID,uuid4

from library_checks import normalized
from workbench_store import encoded,now

BASE='https://musicbrainz.org/ws/2/'
USER_AGENT='LibraryWorkbench/1.0 (https://github.com/fantuz/rekordbox-migration-helper)'
LICENSE='CC BY-NC-SA 3.0; MusicBrainz supplementary data'
LICENSE_URL='https://musicbrainz.org/doc/About/Data_License'
SPEEDS={'gentle':3.0,'balanced':2.0,'fast':1.1}


def unknown_genre(value):return normalized(value) in ('','unknown','unknown genre','unclassified','uncategorized')


TARGETS=('balanced','random','genre','album','year','playlist','missing_genre','missing_year','missing_album')


def target_options(snapshot):
    """Bounded, local-only choices; never transmit these tags until consent."""
    tracks=snapshot['tracks']
    def listed(field,limit=45):
        counts=Counter(str(t.get(field) or '').strip() for t in tracks if str(t.get(field) or '').strip())
        return [{'value':name,'label':name,'tracks':count} for name,count in
                sorted(counts.items(),key=lambda x:(-x[1],x[0].casefold()))[:limit]]
    genres=[row for row in listed('genre') if not unknown_genre(row['value'])]
    albums=listed('album')
    years=Counter(str(t.get('year')) for t in tracks
                  if re.fullmatch(r'\d{4}',str(t.get('year') or '')))
    year_choices=[{'value':name,'label':name,'tracks':count} for name,count in
                  sorted(years.items(),key=lambda x:-int(x[0]))[:80]]
    playlists=[]
    structured=snapshot.get('playlists') or []
    if structured:
        for entry in structured:
            if entry.get('folder'):continue
            playlists.append({'value':str(entry['id']),'label':str(entry.get('name') or entry['id']),
                              'tracks':len(entry.get('tracks') or [])})
    else:
        counts=Counter(name for t in tracks for name in set(t.get('playlists') or []))
        playlists=[{'value':'name:'+str(name),'label':str(name),'tracks':count}
                   for name,count in counts.items()]
    playlists.sort(key=lambda row:(-row['tracks'],row['label'].casefold(),row['value']))
    return {'genres':genres,'albums':albums,'years':year_choices,'playlists':playlists[:100],
            'total_tracks':len(tracks)}


def target_selection(snapshot,target,value):
    if target not in TARGETS:raise ValueError('Choose a supported enrichment target')
    if not isinstance(value,str) or len(value)>200:raise ValueError('Choose a supported target value')
    tracks=snapshot['tracks']
    if target in ('balanced','random'):return tracks
    if target=='missing_genre':return [t for t in tracks if unknown_genre(t.get('genre'))]
    if target=='missing_album':return [t for t in tracks if not str(t.get('album') or '').strip()]
    if target=='missing_year':return [t for t in tracks if not re.fullmatch(r'\d{4}',str(t.get('year') or ''))]
    options=target_options(snapshot)
    category={'genre':'genres','album':'albums','year':'years','playlist':'playlists'}[target]
    if not value or value not in {row['value'] for row in options[category]}:
        raise ValueError('Choose an available '+target+' target from this snapshot')
    if target in ('genre','album'):
        return [t for t in tracks if str(t.get(target) or '').strip()==value]
    if target=='year':
        return [t for t in tracks if str(t.get('year') or '')==value]
    structured=snapshot.get('playlists') or []
    if structured:
        ids=set(next((p.get('tracks') or [] for p in structured if str(p['id'])==value),[]))
        return [t for t in tracks if t['id'] in ids]
    label=value.removeprefix('name:')
    return [t for t in tracks if label in (t.get('playlists') or [])]


def sample_genres(snapshot,top=5,seed='preview',sample_size=None,target='balanced',target_value=''):
    top=int(top)
    if not 3<=top<=12:raise ValueError('Choose between 3 and 12 populated genres')
    if sample_size is not None:
        if isinstance(sample_size,bool) or str(sample_size) not in ('150','300','1000'):
            raise ValueError('Choose a pilot size of 150, 300 or 1000 tracks')
        sample_size=int(sample_size)
    if target!='balanced':
        candidates=target_selection(snapshot,target,target_value)
        candidates=sorted(candidates,key=lambda t:sha256((str(seed)+'\\0'+str(t['id'])).encode()).hexdigest())
        selected=[];seen=set()
        for t in candidates:
            identity=(normalized(t.get('artist')),normalized(t.get('title')),round(t.get('duration') or 0))
            if identity in seen:continue
            seen.add(identity);selected.append(t)
            if len(selected)>= (sample_size or 300):break
        return selected,[{'genre':target+((' · '+target_value) if target_value else ''),
                          'library_tracks':len(candidates),'sampled':len(selected),'requested':sample_size}]
    counts=Counter(t.get('genre') for t in snapshot['tracks'] if not unknown_genre(t.get('genre')))
    names=[name for name,_ in counts.most_common(top)];groups=defaultdict(list)
    for t in snapshot['tracks']:
        key='Unknown genre' if unknown_genre(t.get('genre')) else t.get('genre')
        if key in names or key=='Unknown genre':groups[key].append(t)
    if sample_size is not None:
        # Round-robin strata prevent a large genre from consuming the whole sample.
        queues={name:iter(sorted(groups[name],key=lambda t:sha256((str(seed)+'\\0'+t['id']).encode()).hexdigest()))
                for name in [*names,'Unknown genre']}
        selected=[];seen=set();picked=Counter();active=list(queues)
        while active and len(selected)<sample_size:
            for name in active[:]:
                for t in queues[name]:
                    identity=(normalized(t.get('artist')),normalized(t.get('title')),round(t.get('duration') or 0))
                    if identity in seen:continue
                    seen.add(identity);selected.append(t);picked[name]+=1;break
                else:active.remove(name)
                if len(selected)>=sample_size:break
        return selected,[{'genre':name,'library_tracks':len(groups[name]),'sampled':picked[name],'requested':None}
                         for name in queues]
    selected=[];seen=set();summary=[]
    for name in [*names,'Unknown genre']:
        maximum=50 if name=='Unknown genre' else 20
        candidates=sorted(groups[name],key=lambda t:sha256((str(seed)+'\0'+t['id']).encode()).hexdigest())
        picked=0
        for t in candidates:
            identity=(normalized(t.get('artist')),normalized(t.get('title')),round(t.get('duration') or 0))
            if identity in seen:continue
            seen.add(identity);selected.append(t);picked+=1
            if picked==maximum:break
        summary.append({'genre':name,'library_tracks':len(groups[name]),'sampled':picked,'requested':maximum})
    return selected[:300],summary


def quote_query(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"')[:350]+'"'


def public_query(track):
    isrc=re.sub('[^A-Za-z0-9]','',track.get('isrc') or '').upper()
    if re.fullmatch('[A-Z]{2}[A-Z0-9]{3}[0-9]{7}',isrc):return {'isrc':isrc,'query':'isrc:'+isrc}
    title=str(track.get('title') or '').strip();artist=str(track.get('artist') or '').strip()
    if any(re.search(r'(?:^[A-Za-z]:[\\/]|^/|^file:|\\\\|https?://)',v,re.I) for v in (title,artist)):
        raise ValueError('Path-like tags are withheld; review local tags first')
    if not title or len(title)<2 or re.fullmatch('[0-9a-fA-F]{12,}',title):raise ValueError('No usable title or public identifier; review local tags first')
    query='recording:'+quote_query(title)
    if artist:query+=' AND artist:'+quote_query(artist)
    return {'title':title[:350],'artist':artist[:350],'duration':track.get('duration'),'query':query}



def search_strategies(track, prepared):
    """Bounded tag-only alternatives; a candidate still requires human approval."""
    queries=[('exact',prepared['query'])]
    if prepared.get('isrc'):return queries
    title=prepared['title'];artist=prepared.get('artist') or ''
    base=re.sub(r'\s*[\[(][^\])]{0,100}\b(?:remix|mix|edit|version|extended|radio|live|feat|ft)\b[^\])]{0,100}[\])]\s*$', '', title, flags=re.I).strip()
    if len(base)>=2 and base!=title:
        queries.append(('base_title','recording:'+quote_query(base)+(' AND artist:'+quote_query(artist) if artist else '')))
    if artist:queries.append(('title_only','recording:'+quote_query(title)))
    return queries[:3]

def artist_credit(record):return ''.join(c.get('name') or c.get('artist',{}).get('name','') for c in record.get('artist-credit',[]) if isinstance(c,dict))


def candidates_for(track,records):
    result=[]
    for record in records[:20]:
        try:identity=str(UUID(record['id']))
        except (KeyError,ValueError,TypeError):continue
        title=record.get('title') or '';artist=artist_credit(record)
        title_score=max(SequenceMatcher(None,normalized(track.get('title')),normalized(v)).ratio() for v in (title,title+' '+(record.get('disambiguation') or '')))
        artist_score=SequenceMatcher(None,normalized(track.get('artist')),normalized(artist)).ratio() if track.get('artist') else 0
        duration_delta=abs(track['duration']-record['length']/1000) if track.get('duration') is not None and record.get('length') else None
        isrc_exact=bool(track.get('isrc') and track['isrc'].upper() in record.get('isrcs',[]))
        source_versions=set(re.findall(r'\b(?:remix|edit|live|instrumental|dub|extended|radio)\b',normalized(track.get('title'))))
        version_text=normalized(title+' '+(record.get('disambiguation') or ''))
        version_hold=bool(source_versions and not all(v in version_text.split() for v in source_versions))
        score=round(.60*title_score+.30*artist_score+.10*(1 if duration_delta is not None and duration_delta<=2 else 0),3)
        if isrc_exact:score=max(score,.95)
        result.append({'mbid':identity,'title':title,'artist':artist,'disambiguation':record.get('disambiguation'),
                       'title_similarity':round(title_score,3),'artist_similarity':round(artist_score,3),'duration_delta':duration_delta,
                       'isrc_exact':isrc_exact,'confidence':score,'version_needs_review':version_hold,'match_approved':False})
    return sorted(result,key=lambda c:(not c['version_needs_review'],c['confidence']),reverse=True)


def proposals(detail):
    rating=detail.get('rating') or {};votes=rating.get('votes-count') or 0;score=None
    try:
        if int(votes)>0 and rating.get('value') is not None and 0<=float(rating['value'])<=5:score=float(rating['value'])
    except (TypeError,ValueError,OverflowError):votes=0
    votes=max(0,int(votes))
    dates=[detail.get('first-release-date') or '']+[r.get('date','') for r in detail.get('releases',[])]
    years=[int(d[:4]) for d in dates if re.match(r'^\d{4}',d)]
    genres=sorted([g for g in detail.get('genres',[]) if g.get('name') and (g.get('count') or 0)>0],key=lambda g:-(g.get('count') or 0))
    tags=sorted([{'name':str(g['name'])[:200],'count':g.get('count',0)} for g in detail.get('tags',[])
                 if isinstance(g,dict) and g.get('name') and isinstance(g.get('count'),(int,float))
                 and isfinite(g['count']) and g['count']>0],key=lambda g:(-g['count'],g['name']))[:20]
    releases=[{'title':r.get('title'),'date':r.get('date'),'mbid':r.get('id'),
               'country':r.get('country'),'status':r.get('status'),'disambiguation':r.get('disambiguation')}
              for r in detail.get('releases',[])[:100] if isinstance(r,dict) and r.get('id') and r.get('title')]
    return {'community_score':score,'votes':int(votes),'scale_max':5,'year':min(years) if years else None,
            'year_basis':'First known release year for this recording; may differ from this file release',
            'genre':genres[0]['name'] if genres else None,'genre_votes':genres,'tags':tags,'possible_albums':releases,
            'license':LICENSE,'license_url':LICENSE_URL,'source_url':'https://musicbrainz.org/recording/'+str(detail.get('id','')),
            'retrieved_at':now(),'personal_rating_changed':False}


class RateGate:
    def __init__(self):self.lock=threading.Lock();self.last=0.0
    def wait(self,delay,cancel):
        with self.lock:
            pause=max(0,max(1.1,float(delay))-(time.monotonic()-self.last))
            if cancel.wait(pause):raise InterruptedError('Pilot cancelled')
            self.last=time.monotonic()


class MusicBrainzClient:
    def __init__(self,store,gate,enabled,delay=2.0,cancel=None,transport=None):
        delay=float(delay)
        if not 1.1<=delay<=60:raise ValueError('Lookup spacing must be between 1.1 and 60 seconds')
        self.store=store;self.gate=gate;self.enabled=enabled;self.delay=delay;self.cancel=cancel or threading.Event()
        self.transport=transport or urllib.request.urlopen;self.requests=0;self.cache_hits=0

    def get(self,endpoint,params):
        if not re.fullmatch(r'recording/(?:[0-9a-f-]{36})?',endpoint):raise ValueError('Unsupported provider endpoint')
        if not self.enabled():raise InterruptedError('MusicBrainz proof of concept is disabled')
        if self.cancel.is_set():raise InterruptedError('Pilot cancelled')
        url=BASE+endpoint+'?'+urlencode({**params,'fmt':'json'});key=sha256(url.encode()).hexdigest()
        with self.store.connection() as db:r=db.execute('SELECT payload FROM mb_cache WHERE key=? AND expires>?',(key,time.time())).fetchone()
        if r:self.cache_hits+=1;return json.loads(r[0])
        for attempt in range(2):
            self.gate.wait(self.delay,self.cancel)
            if not self.enabled():raise InterruptedError('MusicBrainz proof of concept is disabled')
            req=urllib.request.Request(url,headers={'User-Agent':USER_AGENT,'Accept':'application/json'})
            self.requests+=1
            try:
                with self.transport(req,timeout=15) as response:data=response.read(4*1024**2+1)
                if len(data)>4*1024**2:raise ValueError('Provider response exceeded the pilot size limit')
                result=json.loads(data)
                if not isinstance(result,dict):raise ValueError('Unexpected provider response')
                with self.store.connection() as db:db.execute('INSERT OR REPLACE INTO mb_cache VALUES (?,?,?,?)',(key,time.time(),time.time()+30*86400,encoded(result)))
                return result
            except urllib.error.HTTPError as error:
                if error.code==404:return {}
                if error.code not in (429,500,502,503,504) or attempt:raise
                retry=error.headers.get('Retry-After','5')
                try:pause=max(3,float(retry))
                except ValueError:
                    try:pause=max(3,(parsedate_to_datetime(retry)-datetime.now(timezone.utc)).total_seconds())
                    except (TypeError,ValueError,OverflowError):pause=5
                if pause>120:raise OSError('Provider asked for a longer pause; retry this batch later') from error
                if self.cancel.wait(pause):raise InterruptedError('Pilot cancelled')
        raise RuntimeError('Provider request failed')


def create_batch(store,snapshot,top=5,seed='preview',delay=2.0,sample_size=None,target='balanced',target_value='',playable_only=True,excluded_unplayable=0):
    delay=float(delay)
    if not 1.1<=delay<=60:raise ValueError('Lookup spacing must be between 1.1 and 60 seconds')
    selected,groups=sample_genres(snapshot,top,seed,sample_size,target,target_value)
    identity=uuid4().hex
    sample=[{k:t.get(k) for k in ('id','title','artist','album','genre','year','rating','duration','isrc','metadata_origin')} for t in selected]
    summary={'groups':groups,'target':target,'target_value':target_value,'requested_tracks':sample_size,'estimated_uncached_seconds':round(2*len(sample)*delay),'tracks':len(sample),'seconds_per_request':float(delay),'requests':0,'cache_hits':0,'done':0,
             'rating_available':0,'genre_available':0,'year_available':0,'experimental':True,'queries_include_audio':False,'queries_include_paths':False,
             'playable_only':playable_only,'excluded_unplayable':excluded_unplayable,
             'audio_mapping_revision':snapshot.get('audio_mapping_revision')}
    with store.connection() as db:db.execute('INSERT INTO mb_batches VALUES (?,?,?,?,?,?)',(identity,snapshot['id'],now(),'preview',encoded(summary),encoded(sample)))
    return {'id':identity,'summary':summary,'sample':sample,'status':'preview'}


BATCH_SORT_FIELDS=('sample','title','artist','genre','status','confidence','year',
                   'candidate','community','file_status')
BATCH_FILE_STATUS_ORDER={'playable':0,'missing':1,'inaccessible':2,'unverified':3}


def batch_record(store,identity,offset=0,sort='sample',direction='asc'):
    """Sort saved evidence across the full batch, then return a 50-row page.

    File status is the last explicit File Health scan for this snapshot.
    Playback probes do not alter this evidence or the resulting order.
    Missing values and unscanned files stay last in either direction.
    """
    if sort=='original':sort='sample'  # Accept the original PR #52 API spelling.
    if sort not in BATCH_SORT_FIELDS or direction not in ('asc','desc'):
        raise ValueError('Choose a supported MusicBrainz column and direction')
    try:offset=int(offset)
    except (ValueError,TypeError):raise ValueError('Choose a valid results page offset') from None
    if not 0<=offset<=1000000:raise ValueError('Choose a valid results page offset')
    with store.connection() as db:
        db.execute('BEGIN')
        r=db.execute('SELECT * FROM mb_batches WHERE id=?',(identity,)).fetchone()
        if not r:raise ValueError('Pilot batch not found')
        from metadata_concurrency import revision as edit_stamp
        source=db.execute('SELECT scope_key FROM snapshots WHERE id=?',(r['snapshot_id'],)).fetchone()
        edit_revision=edit_stamp(db,source[0]) if source else None
        results={x['track_id']:json.loads(x['payload']) for x in db.execute('SELECT track_id,payload FROM mb_results WHERE batch_id=?',(identity,))}
        scanned={x['track_id']:x for x in db.execute(
            'SELECT track_id,status,checked_at FROM file_health_records WHERE source=?',
            ('snapshot:'+r['snapshot_id'],))}
    from musicbrainz_review import revision,selected_candidate
    sample=json.loads(r['sample'])
    rows=[]
    for track in sample:
        evidence=scanned.get(track['id'])
        status=evidence['status'] if evidence and evidence['status'] in BATCH_FILE_STATUS_ORDER else 'unchecked'
        rows.append({**track,**results.get(track['id'],{'status':'not_requested'}),
                     'review_revision':revision(results.get(track['id'],{})),'edit_revision':edit_revision,
                     'selected_mbid':selected_candidate(results.get(track['id'],{})).get('mbid'),
                     'file_status':status,
                     'file_status_checked_at':evidence['checked_at'] if evidence and status!='unchecked' else None})
    if sort!='sample':
        def value(row):
            if sort in ('confidence','candidate'):
                candidate=selected_candidate(row)
                raw=candidate.get('confidence' if sort=='confidence' else 'title')
            elif sort=='year':
                raw=(row.get('proposal') or {}).get('year') or row.get('year')
            elif sort=='community':
                raw=(row.get('proposal') or {}).get('community_score')
            elif sort=='file_status':
                return BATCH_FILE_STATUS_ORDER.get(row['file_status'])
            else:
                raw=row.get(sort)
            if raw is None or isinstance(raw,str) and not raw.strip():return None
            if sort in ('confidence','year','community'):
                if isinstance(raw,bool):return None
                try:
                    number=float(raw)
                    return number if isfinite(number) else None
                except (TypeError,ValueError):return None
            return str(raw).casefold()
        # Stable ties retain original captured order, including descending sorts.
        known=[(value(row),row) for row in rows]
        present=[(key,row) for key,row in known if key is not None]
        absent=[row for key,row in known if key is None]
        present.sort(key=lambda item:item[0],reverse=direction=='desc')
        rows=[row for _,row in present]+absent
    return {'id':identity,'snapshot_id':r['snapshot_id'],'created':r['created'],'status':r['status'],'summary':json.loads(r['summary']),
            'total':len(rows),'offset':offset,'sort':sort,'direction':direction,
            'file_status_basis':'last_explicit_scan','rows':rows[offset:offset+50]}


def run_batch(store,identity,client,progress):
    with store.connection() as db:
        r=db.execute('SELECT * FROM mb_batches WHERE id=?',(identity,)).fetchone()
        if not r:raise ValueError('Pilot batch not found')
        sample=json.loads(r['sample']);summary=json.loads(r['summary'])
        previous={r['track_id']:json.loads(r['payload']) for r in db.execute('SELECT track_id,payload FROM mb_results WHERE batch_id=?',(identity,))}
        db.execute('UPDATE mb_batches SET status=? WHERE id=?',('running',identity))
    prior_requests=summary.get('requests',0);prior_hits=summary.get('cache_hits',0)
    from audio_paths import mappings_for,signature
    source_snapshot=store.snapshot(r['snapshot_id']) if summary.get('playable_only') or summary.get('audio_mapping_revision') else {}
    mappings=mappings_for(store,source_snapshot)
    local_tracks={t['id']:t for t in source_snapshot['tracks']} if summary.get('playable_only') else {}
    consecutive_errors=0;status='complete';totals=Counter(rating_available=0,genre_available=0,tags_available=0,year_available=0,service_errors=0,needs_local_tags=0,candidate_matches=0,no_match=0,skipped_unplayable=0)
    summary.update(done=0,**totals);summary.pop('message',None)
    for n,t in enumerate(sample):
        reused=False
        try:
            if getattr(client,'cancel',None) and client.cancel.is_set():raise InterruptedError('Pilot cancelled')
            if summary.get('audio_mapping_revision') and summary['audio_mapping_revision']!=signature(mappings_for(store,source_snapshot)):
                raise InterruptedError('Audio folder mappings changed. Preview a new batch before continuing.')
            from track_playback import inspect_audio
            if t['id'] in previous and previous[t['id']]['status'] not in ('service_error','not_playable'):result=previous[t['id']];reused=True
            elif summary.get('playable_only') and inspect_audio(local_tracks.get(t['id'],{}),mappings)[0]!='playable':
                result={'status':'not_playable','error':'Audio unavailable at lookup time; no provider request sent'}
            else:
                try:query=public_query(t)
                except ValueError as error:query=None;result={'status':'needs_local_tags','error':str(error)}
                if query is not None:
                    candidates=[];strategy='exact';attempts=0
                    for name,expression in search_strategies(t,query):
                        search=client.get('recording/',{'query':expression,'limit':20})
                        attempts+=1
                        candidates=candidates_for(t,search.get('recordings',[]))
                        if candidates:
                            strategy=name
                            break
                    proposal=None
                    if candidates:
                        detail=client.get('recording/'+candidates[0]['mbid'],{'inc':'ratings+genres+tags+releases+isrcs+artist-credits'})
                        if detail.get('id')!=candidates[0]['mbid']:raise ValueError('Candidate details do not match the requested recording; retry later')
                        proposal=proposals(detail)
                    result={'status':'candidate_needs_review' if candidates else 'no_match','query':query,'candidates':candidates,'proposal':proposal,
                            'selected_mbid':candidates[0]['mbid'] if candidates else None,'search_strategy':strategy if candidates else 'exhausted','search_attempts':attempts,'match_approved':False}
            consecutive_errors=0
        except InterruptedError as error:status='cancelled';summary['message']=str(error);break
        except Exception as error:
            consecutive_errors+=1;result={'status':'service_error','error':type(error).__name__+': '+str(error)[:200]}
        totals[{'service_error':'service_errors','candidate_needs_review':'candidate_matches','not_playable':'skipped_unplayable'}.get(result['status'],result['status'])]+=1
        proposal=result.get('proposal') or {}
        totals['rating_available']+=proposal.get('community_score') is not None
        totals['tags_available']+=bool(proposal.get('tags'))
        totals['genre_available']+=bool(proposal.get('genre'));totals['year_available']+=proposal.get('year') is not None
        with store.connection() as db:
            if not reused:db.execute('INSERT OR REPLACE INTO mb_results VALUES (?,?,?,?)',(identity,t['id'],result['status'],encoded(result)))
            summary.update(done=n+1,requests=prior_requests+client.requests,cache_hits=prior_hits+client.cache_hits,**totals)
            db.execute('UPDATE mb_batches SET summary=? WHERE id=?',(encoded(summary),identity))
        progress(100*(n+1)/max(1,len(sample)),f"MusicBrainz {n+1}/{len(sample)} · {client.requests} requests · {client.cache_hits} cached")
        if consecutive_errors>=5:status='service_paused';summary['message']='Stopped after five consecutive service errors; partial results retained';break
    if status=='complete' and totals['service_errors']:status='complete_with_errors'
    if status=='complete' and totals['skipped_unplayable']:status='complete_with_skips'
    summary.update(requests=prior_requests+client.requests,cache_hits=prior_hits+client.cache_hits,**totals)
    with store.connection() as db:db.execute('UPDATE mb_batches SET status=?,summary=? WHERE id=?',(status,encoded(summary),identity))
    return {'batch_id':identity,'status':status,'summary':summary}
