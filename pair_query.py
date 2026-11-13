"""Bounded pagination cache for duplicate review; never a decision/source cache."""
from hashlib import sha256
import json
from threading import RLock


class PairQueryCache:
    """One result per catalog; replaced on evidence, decisions or scope changes.

    Catalog.refresh_counts replaces descriptions whenever source-derived evidence
    or keeper policy changes. Session dependencies are hashed by value, including
    nested inventory changes, rather than relying on dictionary object identity.
    """
    def __init__(self):
        self.lock=RLock()
        self.descriptions=None
        self.key=None
        self.value=None
        self.builds=0

    def query(self,session,values,build):
        catalog=session['catalog']
        scope={key:value for key,value in values.items() if key not in ('offset','view')}
        dependencies={'scope':scope,'policy':catalog.policy,
                      'decisions':session.get('decisions',{}),
                      'held':session.get('held_pairs',{}),
                      'inventory':(session.get('inventory') or {}).get('matches',{}),
                      'verification':session.get('media_verifications',{})}
        key=sha256(json.dumps(dependencies,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).digest()
        with self.lock:
            if self.descriptions is not catalog.descriptions or key!=self.key:
                value=build(scope)
                self.value=value;self.key=key;self.descriptions=catalog.descriptions;self.builds+=1
            return self.value


def build_query(session,values,in_scope,media_evidence):
    catalog=session['catalog'];mode=values.get('filter','all');rows=[];facets={}
    requested=values.get('evidence','')
    requested=requested.split(',') if isinstance(requested,str) else requested
    for identity,description in catalog.descriptions.items():
        row=media_evidence(session,description)
        if identity in session.get('held_pairs',{}):row={**row,'category':'review'}
        choice=session['decisions'].get(identity)
        if mode=='staged' and (not choice or choice['action']!='merge'):continue
        if mode in ('ready','auto','review') and (row['category']!=mode or choice):continue
        if not in_scope(session,row,values,include_evidence=False):continue
        for key,value in row['evidence'].items():facets[key]=facets.get(key,0)+int(value)
        if any(key and not row['evidence'].get(key,False) for key in requested):continue
        rows.append({**row,'decision':choice})
    rows.sort(key=lambda row:(row['category']=='review',row['title'].casefold(),row['id']))
    parent={};review_parent={}
    def root(mapping,identity):
        mapping.setdefault(identity,identity)
        while mapping[identity]!=identity:
            mapping[identity]=mapping[mapping[identity]];identity=mapping[identity]
        return identity
    for row in rows:
        parent[root(parent,row['a'])]=root(parent,row['b'])
        if row['category']=='review':review_parent[root(review_parent,row['a'])]=root(review_parent,row['b'])
    groups={}
    for row in rows:
        key=root(parent,row['a'])
        group=groups.setdefault(key,{'id':key,'pairs':[],'tracks':set()})
        group['pairs'].append(row);group['tracks'].update((row['a'],row['b']))
    group_rows=[]
    for group in groups.values():
        options=group['pairs'];representative=next((row for row in options if row['category']=='review'),options[0])
        group_rows.append({'id':group['id'],'representative':representative['id'],
                           'title':representative['title'],'artist':representative['artist'],
                           'track_ids':sorted(group['tracks']),'pair_ids':[row['id'] for row in options],
                           'track_count':len(group['tracks']),'pair_count':len(options),
                           'category':'review' if any(row['category']=='review' for row in options) else
                                      'auto' if any(row['category']=='auto' for row in options) else 'ready'})
    group_rows.sort(key=lambda row:(row['category']=='review',row['title'].casefold(),row['id']))
    return {'rows':rows,'group_rows':group_rows,'groups':len(groups),'tracks':len(parent),
            'potential_reduction':len(parent)-len(groups),
            'review_groups':len({root(review_parent,identity) for identity in review_parent}),
            'review_tracks':len(review_parent),'facets':facets}


def page(session,values,in_scope,media_evidence):
    offset=max(0,int(values.get('offset',0)))
    catalog=session['catalog']
    if not hasattr(catalog,'_pair_query_cache'):catalog._pair_query_cache=PairQueryCache()
    result=catalog._pair_query_cache.query(session,values,lambda scope:build_query(session,scope,in_scope,media_evidence))
    groups=values.get('view')=='groups';rows=result['group_rows'] if groups else result['rows']
    response={key:value for key,value in result.items() if key not in ('rows','group_rows')}
    response.update(total=len(rows),offset=offset,rows=rows[offset:offset+40])
    if groups:response.update(pair_count=len(result['rows']),view='groups')
    return response
