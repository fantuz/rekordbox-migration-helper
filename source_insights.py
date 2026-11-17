"""Read-only native field and smart-playlist evidence from detached snapshots."""
from collections import Counter
import math
from xml.etree import ElementTree

ROLES={'composer':'ComposerID','remixer':'RemixerID','original_artist':'OrgArtistID','lyricist':'Lyricist'}
NATIVE_FIELDS=('ReleaseDate','DiscNo','TrackNo','HotCueAutoLoad','Analysed','AnalysisUpdated')
PROPERTIES={'artist':'artist','album':'album','albumArtist':'album_artist','originalArtist':'original_artist',
            'bpm':'bpm','grouping':'colour','comments':'comment','producer':'composer','stockDate':'date_added',
            'counter':'play_count','fileName':'filename','genre':'genre','key':'tonality','label':'label',
            'mixName':'mix_name','myTag':'my_tag','rating':'rating','dateReleased':'release_date',
            'remixedBy':'remixer','duration':'duration','name':'title','year':'year'}
OPERATORS={1:'is',2:'is_not',3:'greater',4:'less',5:'range',6:'in_last',7:'not_in_last',
           8:'contains',9:'not_contains',10:'starts_with',11:'ends_with'}
HOT_KINDS={1,2,3,5,*range(6,18)}


def native_evidence(row,columns,artists):
    roles={}
    for role,field in ROLES.items():
        raw=row.get(field);name=artists.get(str(raw))
        state='not_captured' if field not in columns else 'empty' if raw in (None,'') else 'resolved' if name is not None else 'unresolved'
        roles[role]={'field':field,'raw_id':raw,'name':name,'state':state}
    return {'artist_roles':roles,'fields':{field:{'captured':field in columns,'raw':row.get(field)} for field in NATIVE_FIELDS},
            'units':{'BPM':'BPM multiplied by 100','Length':'seconds','InMsec':'milliseconds','OutMsec':'milliseconds'},
            'native_stems_readiness':None}


def inspect_smartlist(xml,lookups=None):
    """Decode supported labels without executing a rule or dropping unknown conditions."""
    result={'validation':'unsupported','conditions':[],'executable':False}
    if xml is None:return {**result,'validation':'not_checked','detail':'Smart-playlist definition was not captured'}
    if not isinstance(xml,str) or len(xml)>65536 or '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():
        return {**result,'detail':'Smart-playlist definition exceeds bounds or contains a document/entity declaration'}
    result['raw_definition']=xml
    try:root=ElementTree.fromstring(xml)
    except (ElementTree.ParseError,ValueError):return {**result,'validation':'corrupt','detail':'Malformed smart-playlist XML'}
    nodes=list(root.iter())
    if root.tag!='NODE' or len(nodes)>129 or any(e.tag!='CONDITION' for e in nodes[1:]) or list(root)!=nodes[1:]:
        return {**result,'detail':'Unsupported smart-playlist structure or condition-count limit'}
    logical=root.get('LogicalOperator');result['match']='all' if logical=='1' else 'any' if logical=='2' else 'unknown'
    result['automatic_update']=root.get('AutomaticUpdate')
    supported=logical in ('1','2') and bool(nodes[1:]);lookups=lookups or {}
    for node in nodes[1:]:
        prop=node.get('PropertyName','');raw=node.get('ValueLeft','');right=node.get('ValueRight','')
        try:op=OPERATORS.get(int(node.get('Operator','')))
        except ValueError:op=None
        condition={'property':prop,'field':PROPERTIES.get(prop),'operator':op,
                   'raw':dict(node.attrib),'value':raw,'value_right':right,'unit':node.get('ValueUnit'),
                   'supported':prop in PROPERTIES and op is not None}
        if prop=='myTag':
            try:
                identity=int(raw)
                if not -(2**31)<=identity<2**32:raise ValueError()
                if identity<0:identity+=2**32
                condition.update(lookup_id=str(identity),value=lookups.get('mytags',{}).get(str(identity)))
            except ValueError:condition.update(value=None,supported=False)
            condition['supported'] &= condition['value'] is not None
        elif prop=='key':
            condition.update(lookup_id=raw,value=lookups.get('keys',{}).get(raw))
            condition['supported'] &= condition['value'] is not None
        elif prop=='bpm':
            # Different generations may encode BPM or BPM×100. Preserve ambiguity.
            condition['unit']='unverified native rule unit'
        supported &= condition['supported']
        result['conditions'].append(condition)
    return {**result,'validation':'recognized' if supported else 'unsupported',
            'detail':'Smart-playlist fields decoded for inspection; rule was not executed' if supported else
                     'Rule contains unsupported or unresolved evidence; every condition is retained'}


def source_insights(snapshot,progress=lambda *_:None,max_rows=10000):
    rows=[];counts=Counter();total=0;flags=Counter()
    def add(row):
        nonlocal total
        total+=1
        if len(rows)<max_rows:rows.append(row)
    tracks=snapshot.get('tracks',[])
    for index,track in enumerate(tracks):
        if index%250==0:progress(10+60*index/max(1,len(tracks)),'Inspecting captured native fields')
        base={'track_id':track.get('id'),'title':track.get('title',''),'artist':track.get('artist','')}
        evidence=track.get('native_evidence')
        if evidence:
            counts['tracks_with_native_evidence']+=1
            for role,entry in evidence.get('artist_roles',{}).items():
                counts['roles_'+entry['state']]+=1
                if entry['state'] in ('resolved','unresolved'):
                    add({**base,'section':'artist_role','severity':'info' if entry['state']=='resolved' else 'review',
                         'validation':'recognized' if entry['state']=='resolved' else 'unsupported','role':role,**entry,
                         'detail':role.replace('_',' ')+' → '+str(entry.get('name') or 'Unresolved artist ID: '+str(entry.get('raw_id')))})
            values={k:v for k,v in evidence.get('fields',{}).items() if v['captured']}
            if values:add({**base,'section':'native_fields','severity':'info','validation':'recognized','fields':values,
                           'units':evidence.get('units'),'native_stems_readiness':None,
                           'detail':'Captured native metadata and raw analysis flags; STEMS readiness remains unknown'})
            for field in ('Analysed','HotCueAutoLoad','AnalysisUpdated'):
                item=values.get(field)
                if item:flags[(field,str(item['raw']))]+=1
        for cue in track.get('cues') or []:
            counts['cues_checked']+=1;issues=[];kind=cue.get('kind')
            if kind not in ({0,4}|HOT_KINDS):issues.append('Unrecognized native cue kind')
            start=cue.get('in_ms');end=cue.get('out_ms')
            def valid(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0
            if not valid(start):issues.append('Missing or invalid cue start time')
            if end not in (None,0,-1,2**32-1) and (not valid(end) or valid(start) and end<=start):issues.append('Invalid loop end time')
            active=cue.get('active_loop')
            if active in (1,'1',True):
                counts['active_loops']+=1
                if end in (None,0,-1,2**32-1):issues.append('Active-loop flag without a captured loop end')
            elif active not in (None,0,'0',False):issues.append('Unrecognized active-loop flag')
            if issues:
                counts['cue_anomalies']+=1
                add({**base,'section':'cue_validation','severity':'review','validation':'corrupt','cue':cue,
                     'detail':'; '.join(issues)})
    for (field,raw),count in sorted(flags.items()):
        add({'section':'analysis_flags','severity':'info','validation':'recognized','title':field,'raw_value':raw,
             'tracks':count,'native_stems_readiness':None,'detail':f'{count} tracks share this captured raw value; no STEMS-ready bit is inferred'})
    for playlist in snapshot.get('playlists',[]):
        if not playlist.get('smart'):continue
        progress(80,'Inspecting captured smart-playlist rules')
        result=inspect_smartlist(playlist.get('smart_definition'),snapshot.get('smart_rule_lookups'))
        if playlist.get('smart_definition_status')=='oversized':
            result={'validation':'unsupported','conditions':[],'executable':False,
                    'detail':'Smart-playlist definition exceeds the capture limit; original criteria hash retained'}
        counts['smart_rules_'+result['validation']]+=1
        add({'section':'smart_playlist','title':playlist.get('name',''),'playlist_id':playlist.get('id'),'criteria_sha256':playlist.get('criteria_sha256'),
             'severity':'info' if result['validation']=='recognized' else 'review',**result})
    if not counts['tracks_with_native_evidence']:
        add({'section':'source_capability','severity':'review','validation':'not_checked','title':'Native field evidence',
             'detail':'Native role and raw-field evidence is unavailable in this snapshot; capture a modern native library again'})
    return {'tracks':len(tracks),'tracks_with_native_evidence':counts['tracks_with_native_evidence'],
            'resolved_artist_roles':counts['roles_resolved'],'unresolved_artist_roles':counts['roles_unresolved'],
            'smart_rules_recognized':counts['smart_rules_recognized'],'smart_rules_unsupported':counts['smart_rules_unsupported'],
            'smart_rules_corrupt':counts['smart_rules_corrupt'],'smart_rules_not_checked':counts['smart_rules_not_checked'],
            'cues_checked':counts['cues_checked'],'cue_anomalies':counts['cue_anomalies'],'active_loops':counts['active_loops'],
            'findings':total,'retained_findings':len(rows),'row_limit':max_rows,'findings_complete':total==len(rows),
            'native_stems_readiness':None,'source_writes':False},rows
