"""Explainable comparisons and quality/coverage checks on immutable snapshots."""
from collections import Counter,defaultdict
from datetime import datetime,timezone
from difflib import SequenceMatcher
import re
import unicodedata

from engine import path_key


def normalized(value):return ' '.join(unicodedata.normalize('NFKC',str(value or '')).casefold().split())
def row(section,track,detail,**extra):return {'section':section,'severity':'review','track_id':track.get('id',''),'title':track.get('title',''),'artist':track.get('artist',''),'detail':detail,**extra}


def match_tracks(before,after):
    old={t['id']:t for t in before['tracks']};new={t['id']:t for t in after['tracks']};mapping={};evidence={}
    def compatible(a,b):
        if a.get('uuid') and b.get('uuid'):return a['uuid']==b['uuid']
        return normalized(a.get('title'))==normalized(b.get('title')) and normalized(a.get('artist'))==normalized(b.get('artist')) and (a.get('duration') is None or b.get('duration') is None or abs(a['duration']-b['duration'])<=2)
    for field in ('uuid','id','isrc','path'):
        left=defaultdict(set);right=defaultdict(set)
        for records,index,excluded in ((old,left,set(mapping)),(new,right,set(mapping.values()))):
            for identity,t in records.items():
                if identity in excluded:continue
                values=[t.get(field)] if field!='path' else [path_key(t.get(f)) for f in ('current_path','original_path')]
                for value in values:
                    if value:index[value].add(identity)
        candidates=defaultdict(set);reverse=defaultdict(set)
        for key,ids in left.items():
            if len(ids)!=1 or len(right.get(key,set()))!=1:continue
            a,b=next(iter(ids)),next(iter(right[key]))
            if field!='uuid' and not compatible(old[a],new[b]):continue
            candidates[a].add(b);reverse[b].add(a)
        for a,ids in candidates.items():
            if len(ids)==1:
                b=next(iter(ids))
                if len(reverse[b])==1:mapping[a]=b;evidence[a]=field
    return old,new,mapping,evidence


def cue_changes(old,new,tolerance=0):
    def position(c):return (c.get('in_ms'),c.get('out_ms') if c.get('out_ms') is not None and c['out_ms']>=0 else -1)
    def same(a,b):
        if a.get('kind')!=b.get('kind'):return False
        av,bv=position(a),position(b)
        return all(x==y if x is None or y is None or x<0 or y<0 else abs(x-y)<=tolerance for x,y in zip(av,bv))
    remaining=list(new);changes=[]
    for a in old:
        matched=next((b for b in remaining if same(a,b)),None)
        if matched is None:
            stable=[b for b in remaining if b.get('kind')==a.get('kind') and ((a.get('kind') or 0)>0 or (a.get('uuid') and a.get('uuid')==b.get('uuid')))]
            if len(stable)==1:matched=stable[0];changes.append(('changed_cue',a,matched))
            else:changes.append(('lost_cue',a,None));continue
        elif any(a.get(f)!=matched.get(f) for f in ('label','color')):changes.append(('cue_annotation',a,matched))
        remaining.remove(matched)
    changes.extend(('added_cue',None,b) for b in remaining)
    return changes


def compare_snapshots(before,after,tolerance_ms=0):
    tolerance_ms=int(tolerance_ms)
    if not 0<=tolerance_ms<=50:raise ValueError('Cue tolerance must be between 0 and 50 milliseconds')
    old,new,mapping,evidence=match_tracks(before,after);rows=[];counts=Counter()
    for a,b in mapping.items():
        left,right=old[a],new[b]
        if left.get('rating') is not None and right.get('rating') is not None and left['rating']!=right['rating']:
            rows.append(row('rating',right,f"Personal stars: {left['rating']} → {right['rating']}",before=left['rating'],after=right['rating'],match=evidence[a]));counts['ratings_changed']+=1
        for field in ('year','artist','album','genre'):
            if left.get(field)!=right.get(field):rows.append(row('metadata',right,field+' changed',field=field,before=left.get(field),after=right.get(field),match=evidence[a]));counts['metadata_changed']+=1
        if left.get('cues') is not None and right.get('cues') is not None:
            for kind,prior,current in cue_changes(left['cues'],right['cues'],tolerance_ms):
                rows.append(row(kind,right,kind.replace('_',' '),before=prior,after=current,manual_involved=any(c and not c.get('auto') for c in (prior,current)),match=evidence[a]));counts[kind]+=1
        else:counts['cue_comparison_unavailable']+=1
    for identity in old.keys()-mapping.keys():rows.append(row('unmatched_before',old[identity],'No unique safe match in the later snapshot; cue loss is not inferred'));counts['unmatched_before']+=1
    for identity in new.keys()-set(mapping.values()):rows.append(row('unmatched_after',new[identity],'New or unmatched track in the later snapshot'));counts['unmatched_after']+=1
    if before.get('capabilities',{}).get('playlist_order') and after.get('capabilities',{}).get('playlist_order'):
        previous=before.get('playlists',[]);later=after.get('playlists',[]);used=set()
        for p in previous:
            candidates=[q for q in later if q['id'] not in used and ((p.get('uuid') and p['uuid']==q.get('uuid')) or (p['id']==q['id'] and not (p.get('uuid') and q.get('uuid') and p['uuid']!=q['uuid'])))]
            if len(candidates)!=1:
                candidates=[q for q in later if q['id'] not in used and q['name']==p['name'] and q.get('parent')==p.get('parent') and not (p.get('uuid') and q.get('uuid') and p['uuid']!=q['uuid'])]
            if len(candidates)!=1:rows.append(row('playlist',{},'Playlist removed or ambiguous',playlist=p['name'],before=p));counts['playlists_unmatched']+=1;continue
            q=candidates[0];used.add(q['id']);changes={}
            if p['name']!=q['name']:changes['name']=[p['name'],q['name']]
            if p.get('criteria_sha256')!=q.get('criteria_sha256'):changes['smart_criteria']='changed'
            if not p.get('smart') and not q.get('smart'):
                prior=[mapping.get(i,'unmatched-before:'+i) for i in p['tracks']];current=q['tracks']
                if prior!=current:
                    changes.update(removed=list((Counter(prior)-Counter(current)).elements()),added=list((Counter(current)-Counter(prior)).elements()),order_changed=Counter(prior)==Counter(current))
            if changes:rows.append(row('playlist',{},'Playlist changed',playlist=q['name'],changes=changes));counts['playlists_changed']+=1
        for q in later:
            if q['id'] not in used:rows.append(row('playlist',{},'New or unmatched playlist',playlist=q['name']));counts['playlists_added']+=1
    else:counts['playlist_comparison_unavailable']=1
    return {'matched_tracks':len(mapping),'before_tracks':len(old),'after_tracks':len(new),'cue_tolerance_ms':tolerance_ms,**counts},rows


def metadata_consistency(snapshot):
    rows=[];counts=Counter();year=datetime.now(timezone.utc).year
    for track in snapshot['tracks']:
        missing=[f for f in ('title','artist','album','genre','year','bpm') if track.get(f) in (None,'')]
        if missing:rows.append(row('missing',track,'Missing or unavailable: '+', '.join(missing),fields=missing));counts['tracks_with_missing_tags']+=1
        raw=track.get('raw_tags',{})
        for field,low,high in (('year',1900,year+1),('bpm',30,300),('rating',0,5),('duration',1,6*3600)):
            value=raw.get(field,track.get(field))
            if value in (None,'',0) and field in ('year','bpm','duration'):continue
            try:unusual=not low<=float(value)<=high
            except (TypeError,ValueError):unusual=value not in (None,'')
            if unusual:rows.append(row('implausible',track,f'Unusual {field}: {value}',field=field,value=value,note='Review threshold, not proof of an error'));counts['implausible_values']+=1
    for field in ('artist','genre','album'):
        groups=defaultdict(Counter);identities=defaultdict(list)
        for track in snapshot['tracks']:
            if track.get(field):
                key=normalized(track[field]);groups[key][track[field]]+=1;identities[key].append(track['id'])
        for variants in groups.values():
            if len(variants)<2:continue
            canonical=sorted(variants,key=lambda s:(-variants[s],s))[0]
            rows.append(row('variant',{},f'{field}: case, spacing or Unicode variants',field=field,canonical=canonical,variants=dict(variants),track_ids=identities[normalized(canonical)],note='Candidate normalization only; names are not proof of artist identity'))
            counts['variant_groups']+=1
    return {'tracks':len(snapshot['tracks']),**counts},rows


def collection_coverage(snapshot,min_cues=1,min_manual=0,require_analysis=True):
    min_cues,min_manual=int(min_cues),int(min_manual)
    if not 0<=min_cues<=16 or not 0<=min_manual<=16:raise ValueError('Cue requirements must be between 0 and 16')
    rows=[];groups=defaultdict(lambda:Counter());counts=Counter()
    for t in snapshot['tracks']:
        issues=[];unknown=[]
        if require_analysis:
            if t.get('analysed') is None:unknown.append('analysis status')
            elif not t['analysed']:issues.append('not marked analysed')
        if t.get('manual_cues') is None or t.get('auto_cues') is None:unknown.append('cue counts')
        else:
            if t['manual_cues']+t['auto_cues']<min_cues:issues.append('too few cues')
            if t['manual_cues']<min_manual:issues.append('too few cues without automatic labels')
        unplayed=t.get('play_count')==0 and not t.get('last_played')
        if unplayed:rows.append(row('unplayed',t,'Saved play count is zero and no captured history date is available'));counts['unplayed']+=1
        if issues:rows.append(row('preparation',t,', '.join(issues),issues=issues));counts['needs_preparation']+=1
        if unknown:counts['unknown_preparation']+=1
        bpm=t.get('bpm');band='Unknown BPM' if bpm is None else str(int(bpm//10)*10)+'–'+str(int(bpm//10)*10+9)+' BPM'
        for key in (('genre',t.get('genre') or 'Unknown genre'),('bpm',band)):
            group=groups[key];group['tracks']+=1;group['unplayed']+=unplayed;group['needs_preparation']+=bool(issues);group['unknown']+=bool(unknown);group['prepared']+=not issues and not unknown;group['starred']+=bool(t.get('rating') and t['rating']>0)
    for (kind,name),group in sorted(groups.items(),key=lambda x:-x[1]['tracks']):
        rows.insert(0,row('coverage_group',{},kind+': '+name,group_kind=kind,name=name,**group,prepared_percent=round(100*group['prepared']/max(1,group['tracks']),1)))
    return {'tracks':len(snapshot['tracks']),'min_cues':min_cues,'min_manual_cues':min_manual,'require_analysis':require_analysis,**counts},rows
