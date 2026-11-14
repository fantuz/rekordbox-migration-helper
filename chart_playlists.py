"""Opt-in public ListenBrainz charts; matching and playlist creation stay local."""
from collections import defaultdict,Counter
from copy import deepcopy
from difflib import SequenceMatcher
import json
import math
import re
import threading
import time
import unicodedata
from urllib.parse import urlencode,urlsplit,unquote
import urllib.request
import urllib.error

from musicbrainz_pilot import USER_AGENT
from workbench_store import now

CHART_URL='https://api.listenbrainz.org/1/stats/sitewide/recordings'
CHART_SOURCE='https://listenbrainz.org/charts/'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class ChartClient:
    def __init__(self,transport=None,clock=time.monotonic):
        self.transport=transport or urllib.request.build_opener(NoRedirect()).open
        self.clock=clock;self.lock=threading.Lock();self.cache={};self.next_request=0

    def fetch(self,period='week'):
        if period not in ('week','month','year'):raise ValueError('Choose a weekly, monthly or yearly chart')
        with self.lock:
            tick=self.clock()
            if period in self.cache and tick-self.cache[period][0]<3600:
                return {**deepcopy(self.cache[period][1]),'cached':True}
            if tick<self.next_request:raise ValueError('The chart service is cooling down. Try again later.')
            self.next_request=tick+1.1
            request=urllib.request.Request(CHART_URL+'?'+urlencode({'range':period,'count':100,'offset':0}),
                                           headers={'User-Agent':USER_AGENT,'Accept':'application/json'})
            def rate_headers(headers):
                try:
                    pause=float(headers.get('X-RateLimit-Reset-In',1.1)) if headers.get('X-RateLimit-Remaining')=='0' else 1.1
                    retry=float(headers.get('Retry-After',0))
                    if not math.isfinite(pause) or not math.isfinite(retry):raise ValueError()
                    self.next_request=max(self.next_request,self.clock()+max(1.1,pause,retry))
                except (ValueError,TypeError,OverflowError):self.next_request=max(self.next_request,self.clock()+60)
            try:
                with self.transport(request,timeout=15) as response:
                    rate_headers(response.headers)
                    if response.status==204:raise ValueError('This chart has not been calculated yet')
                    raw=response.read(2*1024**2+1)
            except urllib.error.HTTPError as error:
                rate_headers(error.headers or {})
                self.next_request=max(self.next_request,self.clock()+60)
                raise ValueError('ListenBrainz returned HTTP '+str(error.code)+'. Try again later.') from error
            except OSError as error:
                raise ValueError('The chart service could not be reached. Try again later.') from error
            if len(raw)>2*1024**2:raise ValueError('Chart response exceeded the size limit')
            try:payload=json.loads(raw)['payload'];recordings=payload['recordings']
            except (ValueError,KeyError,TypeError):raise ValueError('Unexpected chart response') from None
            if not isinstance(recordings,list) or any(not isinstance(r,dict) for r in recordings[:100]):
                raise ValueError('Unexpected chart recordings')
            rows=[{'rank':i+1,'title':str(r.get('track_name') or '')[:500],'artist':str(r.get('artist_name') or '')[:500],
                   'recording_mbid':str(r.get('recording_mbid') or '')[:36],
                   'listens':r.get('listen_count') if isinstance(r.get('listen_count'),int) and r['listen_count']>=0 else None}
                  for i,r in enumerate(recordings[:100])]
            result={'provider':'ListenBrainz','period':period,'rows':rows,'retrieved_at':now(),
                    'from_ts':payload.get('from_ts'),'to_ts':payload.get('to_ts'),'last_updated':payload.get('last_updated'),
                    'source_url':CHART_SOURCE,'cached':False,
                    'basis':'ListenBrainz community listening counts, not sales, DJ rankings or MusicBrainz ratings. Chart order is retained; recording matches require review.'}
            self.cache[period]=(self.clock(),deepcopy(result))
            return result


def identity_text(value):
    # Keep remix/version words and punctuation: do not collapse distinct recordings.
    return ' '.join(unicodedata.normalize('NFKC',str(value or '')).casefold().split())


def match_chart(snapshot,chart):
    exact=defaultdict(list);artists=defaultdict(list)
    for track in snapshot['tracks']:
        artist=identity_text(track.get('artist'));title=identity_text(track.get('title'))
        if artist and title:exact[(artist,title)].append(track);artists[artist].append(track)
    rows=[];totals=Counter()
    for entry in chart['rows']:
        artist,title=identity_text(entry['artist']),identity_text(entry['title'])
        matches=exact.get((artist,title),[])
        status='exact_tags' if len(matches)==1 else 'ambiguous' if matches else 'unmatched'
        if not matches and artist and title:
            scored=sorted(((SequenceMatcher(None,title,identity_text(t.get('title'))).ratio(),t)
                           for t in artists.get(artist,[])[:500]),key=lambda pair:-pair[0])
            matches=[t for score,t in scored[:5] if score>=.6]
            if matches:status='review_version'
        candidates=[{k:t.get(k) for k in ('id','title','artist','duration','album')} for t in matches[:10]]
        totals[status]+=1
        rows.append({**entry,'status':status,'candidates':candidates,'candidate_count':len(matches)})
    return {**chart,'rows':rows,'summary':dict(totals),'snapshot_id':snapshot['id']}


def local_audio_path(value):
    value=str(value or '')
    if value.lower().startswith('file:'):
        url=urlsplit(value)
        if url.scheme.lower()!='file' or url.netloc.lower() not in ('','localhost') or url.query or url.fragment:
            raise ValueError('Only local file paths can be exported')
        value=unquote(url.path)
        if re.match(r'^/[A-Za-z]:/',value):value=value[1:]
    if not value or any(ord(c)<32 for c in value) or value.startswith(('#','//','\\\\')):
        raise ValueError('A track has no safe local file path')
    if not (value.startswith('/') or re.match(r'^[A-Za-z]:[\\\\/]',value)):
        raise ValueError('A track needs an absolute local file path')
    if '..' in value.replace('\\','/').split('/'):raise ValueError('Parent traversal in a recorded file path is unsupported')
    return value


def chart_m3u(snapshot,report,selected):
    if not isinstance(selected,list) or not selected or len(selected)>100:raise ValueError('Select between 1 and 100 chart matches')
    if any(not isinstance(s,dict) for s in selected):raise ValueError('Invalid chart selection')
    choices={str(s.get('rank')):str(s.get('track_id','')) for s in selected}
    if len(choices)!=len(selected):raise ValueError('Choose one match per chart position')
    tracks={t['id']:t for t in snapshot['tracks']};lines=['#EXTM3U','#PLAYLIST:ListenBrainz chart'];seen=set();used=set()
    for row in report['rows']:
        rank=str(row['rank'])
        if rank not in choices:continue
        identity=choices[rank]
        if identity not in {t['id'] for t in row['candidates']} or identity not in tracks:
            raise ValueError('Choose only reviewed candidates from this chart')
        used.add(rank)
        if identity in seen:continue
        seen.add(identity);track=tracks[identity];path=local_audio_path(track.get('current_path'))
        label=' - '.join(str(track.get(k) or '') for k in ('artist','title'))
        label=' '.join(label.splitlines())
        lines.extend(['#EXTINF:-1,'+label,path])
    if used!=set(choices) or not seen:raise ValueError('No valid chart selections')
    return '\n'.join(lines)+'\n'
