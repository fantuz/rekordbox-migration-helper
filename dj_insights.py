"""Local, explainable usage/discovery views over immutable metadata snapshots."""
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta
from hashlib import sha256
import re
import unicodedata
from statistics import median

from metadata_export import number
from track_tags import rgb


PERSPECTIVES={
    'most':'Most played','least':'Least played · positive counts','zero':'No recorded plays',
    'ready':'Prepared, no recorded plays','gems':'Highly rated, underplayed','rediscover':'Rediscover past rotation',
    'recent':'Recently added','last_used':'Recently used','preparation':'Preparation opportunities','random':'Random discovery','all':'All matching tracks'}
DIMENSIONS={'family':'Genre family','genre':'Saved genre tag','year':'Release year','added':'Addition year',
            'initial':'Artist initial','artist':'Artist','bpm':'BPM band','rating':'Personal stars',
            'usage':'Recorded usage','preparation':'Cue preparation','format':'Format','tone':'Saved tonality','colour':'Saved track colour','tracks':'Tracks'}
BASES={'saved':'Saved play count','history':'Captured history entries','sessions':'Distinct captured sessions'}
METRICS={'tracks':'Tracks','plays':'Recorded plays / selected evidence','duration':'Full track duration (seconds)'}
RULES=(
    ('Drum & bass',('drum and bass','drum n bass','drum bass','dnb','d and b','jungle','neurofunk')),
    ('House',('house',)),('Techno',('techno','tekno')),('Trance',('trance','psytrance')),
    ('Breaks',('breaks','breakbeat','breakbeats','big beat','bigbeat')),
    ('Dubstep & bass',('dubstep','riddim','future bass','bass music')),
    ('Hard dance',('hardcore','gabber','hardstyle','speedcore','hard dance','hardtek')),
    ('Disco & funk',('disco','funk','funky')),('Hip-hop',('hip hop','hiphop','rap','trap')),
    ('R&B & soul',('r and b','rnb','soul')),('Pop',('pop',)),('Rock & metal',('rock','metal','punk')),
    ('Ambient & downtempo',('ambient','downtempo','chillout','chill out','trip hop','lounge')),
    ('Jazz',('jazz',)),('Reggae & dub',('reggae','dancehall','ska')),
    ('Latin',('latin','salsa','bachata','reggaeton','cumbia','bossa nova')),
    ('Classical',('classical','orchestral','opera')))
UNKNOWN={'','unknown','unknown genre','unclassified','no genre','none','n a','na','not set','?'}
PREPARATION={'manual':'Manual cues','mixed':'Mixed manual / auto cues','auto':'Only automatic cues','none':'No cues','unknown':'Cue status unknown'}
TRACK_FIELDS=('id','title','artist','album','genre','year','bpm','rating','duration','format','play_count',
              'manual_cues','auto_cues','analysed','date_added','last_played','tonality','color_key','color_name','color_hex','color_status','color_basis')
NOTE=('Recorded usage is evidence, not a measure of liking. Zero counts do not prove a track was never played. '
      'History dates belong to sessions, not individual play events. Cue origin is inferred from editable labels. '
      'Counts describe library entries; duplicate recordings can appear more than once. Originals and audio stay unchanged.')


def folded(value):
    value=unicodedata.normalize('NFKC',str(value or '')).casefold().replace('&',' and ')
    return ' '.join(re.sub(r'[^\w]+',' ',value).split())


def genre_family(value):
    tag=folded(value)
    if tag in UNKNOWN:return 'Unknown genre'
    hits=[name for name,aliases in RULES if any(re.search(r'(?<!\w)'+re.escape(alias)+r'(?!\w)',tag) for alias in aliases)]
    if tag=='dub':hits.append('Reggae & dub')
    if len(hits)>1:return 'Mixed families'
    if hits:return hits[0]
    if any(re.search(r'(?<!\w)'+alias+r'(?!\w)',tag) for alias in ('electronic','electronica','edm','electro','minimal','experimental')):return 'Electronic · unspecific'
    return 'Other / unmapped'


def saved_date(value):
    text=str(value or '').strip()
    try:
        if re.fullmatch(r'\d{8}',text):return datetime.strptime(text,'%Y%m%d').date()
        if not re.match(r'^\d{4}-\d{2}-\d{2}(?:$|[ T])',text):return None
        return date.fromisoformat(text[:10])
    except ValueError:return None


def initial(value):
    text=unicodedata.normalize('NFKD',str(value or '').strip())
    text=''.join(c for c in text if not unicodedata.combining(c))
    if not text:return ''
    first=text[0].upper()
    return '0–9' if first.isdigit() else first if first.isalpha() else '#'


def preparation(t):
    manual,auto=t.get('manual_cues'),t.get('auto_cues')
    if manual is None or auto is None:return 'unknown'
    return 'mixed' if manual and auto else 'manual' if manual else 'auto' if auto else 'none'


class InsightIndex:
    """Compact projection: no paths, cue payloads, database handles or audio."""
    def __init__(self,snapshot):
        self.rows=[];self.history=bool(snapshot.get('capabilities',{}).get('history_details'))
        self.sessions=[];self.unresolved=0;self.undated_entries=0
        self.reference=saved_date(snapshot.get('captured')) or saved_date(snapshot.get('source_captured'))
        self.info={k:snapshot.get(k) for k in ('id','label','captured','source_kind')}
        identities=set();families={};initials={}
        for source in snapshot.get('tracks',[]):
            t={k:source.get(k) for k in TRACK_FIELDS};t['id']=str(t['id'])
            if t['id'] in identities:raise ValueError('Snapshot track IDs are not unique')
            identities.add(t['id'])
            for field in ('title','artist','album','genre','format','tonality'):t[field]=str(t.get(field) or '')
            t['color_hex']=rgb(t['color_hex']);t['color_status']=t['color_status'] if t['color_status'] in ('assigned','unassigned') else 'unknown'
            t['color_key']=str(t['color_key'] or ('rgb:'+t['color_hex'] if t['color_hex'] and t['color_status']=='assigned' else t['color_status']))
            t['color_name']=str(t['color_name'] or {'unassigned':'No assigned colour','unknown':'Colour not captured','assigned':'Assigned colour'}[t['color_status']])
            for field in ('play_count','manual_cues','auto_cues'):t[field]=number(t[field],0,2**53-1)
            for field in ('bpm','duration'):t[field]=number(t[field],.001 if field=='bpm' else 0,2**53-1)
            t['rating']=number(t['rating'],0,5);t['year']=number(t['year'],1000,2999)
            if t['genre'] not in families:families[t['genre']]=genre_family(t['genre'])
            if t['artist'] not in initials:initials[t['artist']]=initial(t['artist'])
            t['family']=families[t['genre']];t['initial']=initials[t['artist']];t['preparation']=preparation(t)
            t['_added']=saved_date(t['date_added']);t['_last']=saved_date(t['last_played'])
            t['_search']=[folded(t[k]) for k in ('title','artist','album','genre')]
            self.rows.append(t)
        if self.history:
            for h in snapshot.get('histories',[]):
                if h.get('folder'):continue
                stamp=saved_date(h.get('date'));counts=Counter(str(e.get('track_id')) for e in h.get('entries',[]))
                self.unresolved+=sum(n for key,n in counts.items() if key not in identities)
                counts={key:n for key,n in counts.items() if key in identities}
                if stamp is None:self.undated_entries+=sum(counts.values())
                self.sessions.append((stamp,counts))
        if self.reference is None:
            self.reference=max((stamp for stamp,_ in self.sessions if stamp),default=None)
        self.family_counts=Counter(t['family'] for t in self.rows)
        self.color_labels={t['color_key']:t['color_name'] for t in self.rows}

    def options(self):
        colours=Counter(t['color_key'] for t in self.rows);representatives={t['color_key']:t for t in self.rows}
        return {'snapshot':self.info,'entries':len(self.rows),'reference_date':self.reference.isoformat() if self.reference else None,
                'history_available':self.history,'history_sessions':len(self.sessions),
                'history_unresolved_entries':self.unresolved,'history_undated_entries':self.undated_entries,
                'families':[{'key':k,'tracks':n} for k,n in self.family_counts.most_common()],
                'genres':sorted({t['genre'] for t in self.rows},key=str.casefold),
                'tonalities':sorted({t['tonality'] for t in self.rows},key=str.casefold),
                'colours':[{'key':k,'label':representatives[k]['color_name'],'hex':representatives[k]['color_hex'],
                            'status':representatives[k]['color_status'],'tracks':n} for k,n in colours.most_common()],
                'perspectives':PERSPECTIVES,'dimensions':DIMENSIONS,'bases':BASES,'metrics':METRICS,'preparation':PREPARATION,
                'genre_rules':{'version':1,'method':'Tag text only; explicit word/phrase aliases, no audio or internet inference',
                               'families':[{'family':name,'aliases':list(aliases)} for name,aliases in RULES],
                               'fallback':'Multiple matched families → Mixed families; ambiguous specific tags remain unmapped; generic electronic tags stay unspecific.'},'note':NOTE}

    def scope(self,args):
        basis=args.get('basis','saved')
        if basis not in BASES:raise ValueError('Choose a supported usage evidence source')
        if basis!='saved' and not self.history:raise ValueError('This snapshot has no decoded session history; choose saved play counts or capture a native library')
        start,end=None,None
        for field in ('from','to'):
            if args.get(field):
                stamp=saved_date(args[field])
                if stamp is None:raise ValueError('Use YYYY-MM-DD for session date filters')
                if field=='from':start=stamp
                else:end=stamp
        if start and end and start>end:raise ValueError('The session end date must be at least the start date')
        if basis=='saved' and (start or end):raise ValueError('Session date filters require captured history evidence')
        counts=Counter();reach=Counter();last={};selected_sessions=0
        if basis!='saved':
            for stamp,entries in self.sessions:
                if (start or end) and (not stamp or start and stamp<start or end and stamp>end):continue
                selected_sessions+=1;counts.update(entries);reach.update(entries.keys())
                if stamp:
                    for key in entries:last[key]=max(stamp,last.get(key,stamp))
        search=folded(args.get('q',''));family=str(args.get('family',''));genre=args.get('genre')
        prep=args.get('preparation','');bounds={}
        usage=args.get('usage_filter','')
        if usage not in ('','zero','low','played','unknown'):raise ValueError('Choose a supported usage filter')
        if prep and prep not in (*PREPARATION,'analysed'):raise ValueError('Choose a supported preparation filter')
        for field,maximum in (('bpm_min',10000),('bpm_max',10000),('min',1e7),('max',1e7),('rating_min',5)):
            raw=args.get(field)
            if raw not in (None,''):
                value=number(raw,0,maximum)
                if value is None:raise ValueError('Use a valid non-negative '+field.replace('_',' '))
                bounds[field]=value
        for low,high in (('bpm_min','bpm_max'),('min','max')):
            if low in bounds and high in bounds and bounds[low]>bounds[high]:raise ValueError('A filter minimum exceeds its maximum')
        result=[]
        for source in self.rows:
            if args.get('track_id') is not None and source['id']!=str(args['track_id']):continue
            if search and not any(search in value for value in source['_search']):continue
            if family and source['family']!=family:continue
            if genre is not None and source['genre']!=genre:continue
            if args.get('tone') is not None and source['tonality']!=args['tone']:continue
            if args.get('colour') is not None and source['color_key']!=args['colour']:continue
            if prep and (source['analysed'] is not True if prep=='analysed' else source['preparation']!=prep):continue
            if any(source.get(field) is None or (source[field]<value if lower else source[field]>value)
                   for name,field,lower,scale in (('bpm_min','bpm',True,1),('bpm_max','bpm',False,1),('min','duration',True,60),('max','duration',False,60),('rating_min','rating',True,1))
                   if name in bounds for value in (bounds[name]*scale,)):continue
            t={**source,'plays':source['play_count'] if basis=='saved' else counts[source['id']] if basis=='history' else reach[source['id']],
               '_evidence_last':source['_last'] if basis=='saved' else last.get(source['id'])}
            t['evidence_date_after_snapshot']=bool(self.reference and t['_evidence_last'] and t['_evidence_last']>self.reference)
            if usage and not {'zero':t['plays']==0,'low':t['plays'] is not None and 0<t['plays']<=3,
                              'played':t['plays'] is not None and t['plays']>0,'unknown':t['plays'] is None}[usage]:continue
            result.append(t)
        path=args.get('path',[])
        if not isinstance(path,list) or len(path)>8:raise ValueError('Choose up to eight valid bubble branches')
        used=set();breadcrumbs=[]
        for item in path:
            if not isinstance(item,dict) or item.get('dimension') not in DIMENSIONS or not isinstance(item.get('key'),str):raise ValueError('Invalid bubble branch')
            dim=item['dimension'];key=item['key']
            if dim in used:raise ValueError('A bubble dimension cannot repeat in one branch')
            used.add(dim);result=[t for t in result if self.key(t,dim)==key]
            breadcrumbs.append({'dimension':dim,'key':key,'label':self.label(key,dim)})
        context={'basis':basis,'basis_label':BASES[basis],'selected_sessions':selected_sessions if basis!='saved' else None,
                 'from':start.isoformat() if start else None,'to':end.isoformat() if end else None,
                 'reference_date':self.reference.isoformat() if self.reference else None,'breadcrumbs':breadcrumbs,
                 'history_unresolved_entries':self.unresolved,'history_undated_entries':self.undated_entries,'note':NOTE}
        return result,context

    @staticmethod
    def key(t,dimension):
        if dimension in ('family','genre','initial','artist','format'):return t[dimension]
        if dimension=='tone':return t['tonality']
        if dimension=='colour':return t['color_key']
        if dimension=='tracks':return t['id']
        if dimension=='year':return str(int(t['year'])) if t['year'] is not None else ''
        if dimension=='added':return str(t['_added'].year) if t['_added'] else ''
        if dimension=='bpm':return str(int(t['bpm']//10)*10) if t['bpm'] is not None else ''
        if dimension=='rating':return str(t['rating']) if t['rating'] is not None else ''
        if dimension=='preparation':return t['preparation']
        plays=t['plays']
        return '' if plays is None else '0' if plays==0 else '1–3' if plays<=3 else '4–10' if plays<=10 else '11–30' if plays<=30 else '31+'

    def label(self,key,dimension):
        if dimension=='colour':return self.color_labels.get(key,'Colour not captured')
        if key=='':return {'genre':'Blank genre tag','artist':'Artist unavailable','initial':'Artist unavailable','usage':'Usage unknown'}.get(dimension,'Unknown / not captured')
        if dimension=='preparation':return PREPARATION.get(key,key)
        if dimension=='rating':return 'Unrated' if key=='0' else key+' stars'
        if dimension=='bpm':return key+'–'+str(int(key)+9.99)+' BPM'
        if dimension=='usage':return 'No recorded plays' if key=='0' else key+' recorded plays'
        return key


def statistics(rows):
    known=[t['plays'] for t in rows if t['plays'] is not None];total=sum(known)
    tempos=[t['bpm'] for t in rows if t['bpm'] is not None];lengths=[t['duration'] for t in rows if t['duration'] is not None]
    return {'entries':len(rows),'known_usage':len(known),'unknown_usage':len(rows)-len(known),'recorded_plays':total,
            'zero_usage':sum(v==0 for v in known),'known_usage_percent':round(100*len(known)/len(rows),1) if rows else None,
            'top_ten_play_share':round(100*sum(sorted(known,reverse=True)[:10])/total,1) if total else None,
            'rated':sum(t['rating'] is not None and t['rating']>0 for t in rows),
            'manual_cues':sum(t['manual_cues'] is not None and t['manual_cues']>0 for t in rows),
            'genre_families':len({t['family'] for t in rows}),'full_track_seconds':sum(t['duration'] or 0 for t in rows),
            'duration_unknown':sum(t['duration'] is None for t in rows),
            'bpm_known':len(tempos),'bpm_unknown':len(rows)-len(tempos),'bpm_mean':sum(tempos)/len(tempos) if tempos else None,
            'bpm_median':median(tempos) if tempos else None,'bpm_min':min(tempos) if tempos else None,'bpm_max':max(tempos) if tempos else None,
            'duration_mean':sum(lengths)/len(lengths) if lengths else None,'duration_median':median(lengths) if lengths else None,
            'tonality_known':sum(bool(t['tonality']) for t in rows),'tonality_unknown':sum(not t['tonality'] for t in rows),
            'coloured':sum(t['color_status']=='assigned' for t in rows),'colour_unassigned':sum(t['color_status']=='unassigned' for t in rows),
            'colour_unknown':sum(t['color_status']=='unknown' for t in rows)}


def public_track(t,reason=''):
    return {k:t.get(k) for k in TRACK_FIELDS}|{'family':t['family'],'preparation':t['preparation'],'plays':t['plays'],
                                            'evidence_last_date':t['_evidence_last'].isoformat() if t['_evidence_last'] else None,
                                            'evidence_date_after_snapshot':t['evidence_date_after_snapshot'],'reason':reason}


def ranking(index,args,all_rows=False,limit=50):
    rows,context=index.scope(args);scope=statistics(rows);mode=args.get('perspective','most')
    if mode not in PERSPECTIVES:raise ValueError('Choose a supported insight perspective')
    def setting(name,default,minimum,maximum):
        value=number(default if args.get(name) in (None,'') else args[name],minimum,maximum)
        if value is None:raise ValueError('Invalid '+name.replace('_',' '))
        return value
    max_plays=setting('max_plays',3,0,1e9);stars=setting('stars',3,0,5);days=setting('days',180,1,36500)
    sample_size=int(setting('sample',20,1,100));seed=str(args.get('seed','discovery'))[:100]
    if args.get('random_mode','balanced') not in ('balanced','uniform'):raise ValueError('Choose balanced or uniform random sampling')
    cutoff=index.reference-timedelta(days=days) if index.reference else None
    known=lambda t:t['plays'] is not None
    prepared=lambda t:t['analysed'] is True and t['manual_cues'] is not None and t['manual_cues']>0
    predicates={'most':lambda t:known(t) and t['plays']>0,'least':lambda t:known(t) and t['plays']>0,
                'zero':lambda t:known(t) and t['plays']==0,'ready':lambda t:known(t) and t['plays']==0 and prepared(t),
                'gems':lambda t:known(t) and t['plays']<=max_plays and t['rating'] is not None and t['rating']>=stars and t['rating']>0,
                'rediscover':lambda t:known(t) and t['plays']>0 and t['_evidence_last'] is not None and cutoff is not None and t['_evidence_last']<=cutoff,
                'recent':lambda t:t['_added'] is not None,
                'last_used':lambda t:known(t) and t['plays']>0 and t['_evidence_last'] is not None and not t['evidence_date_after_snapshot'],
                'preparation':lambda t:t['analysed'] is False or t['preparation'] in ('auto','none'),
                'random':lambda t:True,'all':lambda t:True}
    selected=[t for t in rows if predicates[mode](t)];eligible=len(selected)
    if mode=='random':
        random_key=lambda t:sha256((seed+'\0'+t['id']).encode()).digest()
        selected.sort(key=random_key)
        if args.get('random_mode','balanced')=='balanced':
            buckets=defaultdict(list)
            for t in selected:buckets[t['family']].append(t)
            names=sorted(buckets,key=lambda k:sha256((seed+'\0'+k).encode()).digest())
            selected=[]
            for n in range(sample_size):
                if len(selected)>=sample_size:break
                for key in names:
                    if n<len(buckets[key]):selected.append(buckets[key][n])
                    if len(selected)>=sample_size:break
        selected=selected[:sample_size]
    else:
        if mode=='most':order=lambda t:(-t['plays'],t['title'].casefold(),t['id'])
        elif mode=='least':order=lambda t:(t['plays'],t['title'].casefold(),t['id'])
        elif mode=='gems':order=lambda t:(-t['rating'],t['plays'],t['title'].casefold(),t['id'])
        elif mode=='rediscover':order=lambda t:(t['_evidence_last'] or date.max,t['title'].casefold(),t['id'])
        elif mode=='recent':order=lambda t:(-(t['_added'] or date.min).toordinal(),t['title'].casefold(),t['id'])
        elif mode=='last_used':order=lambda t:(-(t['_evidence_last'] or date.min).toordinal(),t['title'].casefold(),t['id'])
        else:order=lambda t:(t['title'].casefold(),t['artist'].casefold(),t['id'])
        selected.sort(key=order)
    def reason(t):
        return {'ready':'Saved analyzed status and at least one manual cue; no plays in the selected evidence',
                'gems':str(t['rating'])+' personal stars; '+str(t['plays'])+' recorded plays',
                'rediscover':'Last recorded date is at least '+str(int(days))+' days before the snapshot reference date',
                'preparation':'Saved status indicates analysis or manual cue preparation to review',
                'random':('Genre-balanced' if args.get('random_mode','balanced')=='balanced' else 'Uniform')+' seeded sample; no taste prediction'}.get(mode,PERSPECTIVES[mode])
    offset=max(0,int(args.get('offset',0)))
    groups=defaultdict(list)
    for t in rows:groups[t['family']].append(t)
    balance=[]
    for key,group in groups.items():
        s=statistics(group);library_share=100*s['known_usage']/scope['known_usage'] if scope['known_usage'] else None
        play_share=100*s['recorded_plays']/scope['recorded_plays'] if scope['recorded_plays'] else None
        balance.append({'family':key,**s,'library_share':library_share,'play_share':play_share,
                        'exploration_gap':library_share-play_share if library_share is not None and play_share is not None and s['known_usage'] else None})
    balance.sort(key=lambda g:(-g['recorded_plays'],-g['entries'],g['family']))
    return {'snapshot':index.info,'context':context,'perspective':mode,'title':PERSPECTIVES[mode],
            'scope_stats':scope,'result_stats':statistics(selected),'total':len(selected),'eligible':eligible,'offset':offset,
            'rows':[public_track(t,reason(t)) for t in (selected if all_rows else selected[offset:offset+limit])],
            'genre_balance':balance,'seed':seed if mode=='random' else None,
            'sampling':args.get('random_mode','balanced') if mode=='random' else None,
            'rediscovery_date_available':index.reference is not None}


def bubbles(index,args):
    rows,context=index.scope(args);dimension=args.get('dimension','family');metric=args.get('metric','tracks')
    if dimension not in DIMENSIONS or metric not in METRICS:raise ValueError('Choose a supported bubble dimension and size metric')
    if dimension in {p['dimension'] for p in context['breadcrumbs']}:raise ValueError('Choose a dimension not already fixed by the current branch')
    groups=defaultdict(list)
    for t in rows:groups[index.key(t,dimension)].append(t)
    result=[]
    for key,group in groups.items():
        s=statistics(group);value=s['entries'] if metric=='tracks' else s['recorded_plays'] if metric=='plays' else s['full_track_seconds']
        unknown=s['unknown_usage'] if metric=='plays' else s['duration_unknown'] if metric=='duration' else 0
        rated=[t['rating'] for t in group if t['rating'] is not None and t['rating']>0]
        preparation_known=[t for t in group if t['preparation']!='unknown']
        tags=Counter(t['genre'] or '(blank)' for t in group)
        result.append({'key':key,'label':(group[0]['title'] or 'Untitled track')+' · '+(group[0]['artist'] or 'Artist unavailable') if dimension=='tracks' else index.label(key,dimension),
                       'value':value,'weight_unknown_entries':unknown,**s,
                       'color_hex':group[0]['color_hex'] if len({t['color_hex'] for t in group})==1 and all(t['color_status']=='assigned' for t in group) else None,
                       'color_status':group[0]['color_status'] if len({t['color_status'] for t in group})==1 else 'mixed',
                       'mean_personal_rating':sum(rated)/len(rated) if rated else None,
                       'manual_cue_percent':100*sum(t['preparation'] in ('manual','mixed') for t in preparation_known)/len(preparation_known) if preparation_known else None,
                       'cue_status_known':len(preparation_known),'saved_tags':[{'tag':tag,'tracks':n} for tag,n in tags.most_common(8)],'saved_tags_total':len(tags)})
    result.sort(key=lambda g:(-g['value'],-g['entries'],g['label'].casefold(),g['key']))
    offset=max(0,int(args.get('group_offset',0)))
    return {'snapshot':index.info,'context':context,'summary':statistics(rows),'dimension':dimension,'metric':metric,'metric_label':METRICS[metric],
            'groups':result[offset:offset+60],'groups_total':len(result),'group_offset':offset,
            'zero_weight_groups':sum(g['value']==0 for g in result),
            'visible_weight':sum(g['value'] for g in result[offset:offset+60]),'total_weight':sum(g['value'] for g in result),
            'note':'Circle areas encode the selected metric among the categories on this page. Zero/unknown weights remain in the category list. Full track duration is not time played.'}


def tonalities(index,args):
    rows,context=index.scope(args);groups=defaultdict(list);bands=Counter()
    for t in rows:
        groups[t['tonality']].append(t)
        if t['bpm'] is not None:bands[int(t['bpm']//10)*10]+=1
    values=[{'tonality':key,'label':key or 'Unknown / not captured',**statistics(group)} for key,group in groups.items()]
    values.sort(key=lambda g:(-g['entries'],g['label'].casefold()))
    return {'snapshot':index.info,'context':context,'summary':statistics(rows),'tonalities':values,
            'bpm_histogram':[{'minimum':key,'maximum':key+9.99,'tracks':n} for key,n in sorted(bands.items())[:200]],
            'bpm_bands_total':len(bands),'note':'Tonality is the saved tag, not a new key analysis. Different key notations stay separate. BPM means/medians weight each library entry equally; no half/double-time correction is applied.'}
