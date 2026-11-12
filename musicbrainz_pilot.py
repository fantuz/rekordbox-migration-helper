"""Opt-in MusicBrainz proof of concept. GET only, bounded samples, paced requests."""
from collections import Counter,defaultdict
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
USER_AGENT='LibraryWorkbench/0.5.0 (https://github.com/fantuz/rekordbox-migration-helper)'
LICENSE='CC BY-NC-SA 3.0; MusicBrainz supplementary data'
LICENSE_URL='https://musicbrainz.org/doc/About/Data_License'
SPEEDS={'gentle':3.0,'balanced':2.0,'fast':1.1}


def unknown_genre(value):return normalized(value) in ('','unknown','unknown genre','unclassified','uncategorized')


def sample_genres(snapshot,top=5,seed='preview'):
    top=int(top)
    if not 3<=top<=12:raise ValueError('Choose between 3 and 12 populated genres; the sample is capped at 300 tracks')
    counts=Counter(t.get('genre') for t in snapshot['tracks'] if not unknown_genre(t.get('genre')))
    names=[name for name,_ in counts.most_common(top)];groups=defaultdict(list)
    for t in snapshot['tracks']:
        key='Unknown genre' if unknown_genre(t.get('genre')) else t.get('genre')
        if key in names or key=='Unknown genre':groups[key].append(t)
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


def artist_credit(record):return ''.join(c.get('name') or c.get('artist',{}).get('name','') for c in record.get('artist-credit',[]) if isinstance(c,dict))


def candidates_for(track,records):
    result=[]
    for record in records[:10]:
        try:identity=str(UUID(record['id']))
        except (KeyError,ValueError,TypeError):continue
        title=record.get('title') or '';artist=artist_credit(record)
        title_score=SequenceMatcher(None,normalized(track.get('title')),normalized(title+' '+(record.get('disambiguation') or ''))).ratio()
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
    except (TypeError,ValueError):votes=0
    dates=[detail.get('first-release-date') or '']+[r.get('date','') for r in detail.get('releases',[])]
    years=[int(d[:4]) for d in dates if re.match(r'^\d{4}',d)]
    genres=sorted([g for g in detail.get('genres',[]) if g.get('name') and (g.get('count') or 0)>0],key=lambda g:-(g.get('count') or 0))
    releases=[{'title':r.get('title'),'date':r.get('date'),'mbid':r.get('id')} for r in detail.get('releases',[])[:20]]
    return {'community_score':score,'votes':int(votes),'scale_max':5,'year':min(years) if years else None,
            'year_basis':'First known release year for this recording; may differ from this file release',
            'genre':genres[0]['name'] if genres else None,'genre_votes':genres,'possible_albums':releases,
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


def create_batch(store,snapshot,top=5,seed='preview',delay=2.0):
    delay=float(delay)
    if not 1.1<=delay<=60:raise ValueError('Lookup spacing must be between 1.1 and 60 seconds')
    selected,groups=sample_genres(snapshot,top,seed)
    identity=uuid4().hex
    sample=[{k:t.get(k) for k in ('id','title','artist','album','genre','year','rating','duration','isrc','metadata_origin')} for t in selected]
    summary={'groups':groups,'tracks':len(sample),'seconds_per_request':float(delay),'requests':0,'cache_hits':0,'done':0,
             'rating_available':0,'genre_available':0,'year_available':0,'experimental':True,'queries_include_audio':False,'queries_include_paths':False}
    with store.connection() as db:db.execute('INSERT INTO mb_batches VALUES (?,?,?,?,?,?)',(identity,snapshot['id'],now(),'preview',encoded(summary),encoded(sample)))
    return {'id':identity,'summary':summary,'sample':sample,'status':'preview'}


def batch_record(store,identity,offset=0):
    with store.connection() as db:
        r=db.execute('SELECT * FROM mb_batches WHERE id=?',(identity,)).fetchone()
        if not r:raise ValueError('Pilot batch not found')
        results={x['track_id']:json.loads(x['payload']) for x in db.execute('SELECT * FROM mb_results WHERE batch_id=?',(identity,))}
    sample=json.loads(r['sample'])
    return {'id':identity,'snapshot_id':r['snapshot_id'],'created':r['created'],'status':r['status'],'summary':json.loads(r['summary']),
            'total':len(sample),'offset':int(offset),'rows':[{**t,**results.get(t['id'],{'status':'not_requested'})} for t in sample[int(offset):int(offset)+50]]}


def run_batch(store,identity,client,progress):
    with store.connection() as db:
        r=db.execute('SELECT * FROM mb_batches WHERE id=?',(identity,)).fetchone()
        if not r:raise ValueError('Pilot batch not found')
        sample=json.loads(r['sample']);summary=json.loads(r['summary'])
        db.execute('UPDATE mb_batches SET status=? WHERE id=?',('running',identity))
    consecutive_errors=0;status='complete';totals=Counter(rating_available=0,genre_available=0,year_available=0)
    summary.update(done=0,**totals);summary.pop('message',None)
    for n,t in enumerate(sample):
        try:
            try:query=public_query(t)
            except ValueError as error:
                result={'status':'needs_local_tags','error':str(error)}
                query=None
            if query is None:
                with store.connection() as db:db.execute('INSERT OR REPLACE INTO mb_results VALUES (?,?,?,?)',(identity,t['id'],result['status'],encoded(result)))
                summary['done']=n+1
                continue
            search=client.get('recording/',{'query':query['query'],'limit':5})
            candidates=candidates_for(t,search.get('recordings',[]));proposal=None
            if candidates:
                detail=client.get('recording/'+candidates[0]['mbid'],{'inc':'ratings+genres+releases+isrcs+artist-credits'})
                proposal=proposals(detail);totals['rating_available']+=proposal['community_score'] is not None
                totals['genre_available']+=bool(proposal['genre']);totals['year_available']+=proposal['year'] is not None
            result={'status':'candidate_needs_review' if candidates else 'no_match','query':query,'candidates':candidates,'proposal':proposal,'match_approved':False}
            consecutive_errors=0
        except InterruptedError as error:status='cancelled';summary['message']=str(error);break
        except Exception as error:
            consecutive_errors+=1;result={'status':'service_error','error':type(error).__name__+': '+str(error)[:200]}
        with store.connection() as db:
            db.execute('INSERT OR REPLACE INTO mb_results VALUES (?,?,?,?)',(identity,t['id'],result['status'],encoded(result)))
            summary.update(done=n+1,requests=client.requests,cache_hits=client.cache_hits,**totals)
            db.execute('UPDATE mb_batches SET summary=? WHERE id=?',(encoded(summary),identity))
        progress(100*(n+1)/max(1,len(sample)),f"MusicBrainz {n+1}/{len(sample)} · {client.requests} requests · {client.cache_hits} cached")
        if consecutive_errors>=5:status='service_paused';summary['message']='Stopped after five consecutive service errors; partial results retained';break
    summary.update(requests=client.requests,cache_hits=client.cache_hits)
    with store.connection() as db:db.execute('UPDATE mb_batches SET status=?,summary=? WHERE id=?',(status,encoded(summary),identity))
    return {'batch_id':identity,'status':status,'summary':summary}
