"""Read-only provider associations. Never join incomplete caches across physical/ZIP scopes."""
from collections import Counter,defaultdict
from pathlib import Path,PurePosixPath
import stat
import time

from media import cloud_placeholder
from stems_formats import HEX64,CACHE_FOLDERS
from stems_eligibility import namespace_status,cache_profile


def source_stamp(path):
    s=path.stat()
    if not stat.S_ISREG(s.st_mode):raise OSError('Source is not a regular file')
    return {'size':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns,'inode':s.st_ino,'device':s.st_dev,
            'cloud_only':cloud_placeholder(s)}


def selected_source(value,roots):
    """Only stat a manifest path inside an explicitly selected, link-free folder scope."""
    path=Path(value)
    if not path.is_absolute() or '..' in path.parts:return 'not_in_scope',None,None
    if len(path.parts)>64:return 'not_checked',None,None
    scopes=[root if isinstance(root,tuple) else (root,root) for root in roots]
    selected=next(((alias,scope) for alias,scope in scopes if path.is_relative_to(alias)),None)
    if selected is None:return 'not_in_scope',None,None
    alias,scope=selected
    try:
        current=path
        while current!=alias:
            if current.is_symlink() or current.is_junction():return 'linked_path',None,None
            current=current.parent
        resolved=path.resolve(strict=True)
        if not resolved.is_relative_to(scope):return 'not_in_scope',None,None
        stamp=source_stamp(resolved)
        if stamp['cloud_only']:return 'unavailable',None,None
        return 'checked',resolved,stamp
    except OSError:return 'unavailable',None,None


def provider_report(rows,roots,profile,progress,deadline,inventory_complete=True,max_rows=10000,now=None,source_aliases=None):
    now=time.time() if now is None else now
    caches={};markers={};reports=[];checked_sources={};source_memo={};counts=Counter();partial=False
    def root_key(row,root):return (row.get('_archive_scope') or '',str(root))
    def display(key):return key[0]+'!/'+key[1] if key[0] else key[1]
    def cache(key):return caches.setdefault(key,{'chunks':defaultdict(lambda:defaultdict(list)),'marker':None})
    for index,row in enumerate(rows):
        if index%250==0:progress(85,'Grouping provider cache metadata')
        if time.monotonic()>=deadline:partial=True;break
        if row.get('format')=='rbstems_marker':
            key=root_key(row,PurePosixPath(row['_source'].replace('\\','/')).parent)
            markers[key]=row;cache(key)['marker']=row
    for index,row in enumerate(rows):
        if index%250==0:progress(85,'Grouping provider cache companions')
        if time.monotonic()>=deadline:partial=True;break
        if row.get('format') not in ('rbstems_flac','rbstems_descriptor'):continue
        path=PurePosixPath(row['_source'].replace('\\','/'));parts=path.parts
        if len(parts)<3:continue
        model,prefix=parts[-3:-1];key=path.stem
        if not HEX64.fullmatch(model) or not HEX64.fullmatch(key) or prefix!=key[:2]:
            row.update(cache_state='unknown',detail=row['detail']+'; cache path does not match the inspected model/key layout')
            continue
        identity=root_key(row,path.parents[2]);entry=cache(identity)
        entry['chunks'][(model,key)]['flac' if row['format']=='rbstems_flac' else 'descriptor'].append(row)
    retained={}
    for row in rows:
        if row.get('format')=='rbstems_kept' and row['validation']=='recognized':
            row['retention_status']='protected' if row['until']>now else 'expired'
            row['cache_state']='unknown'
            for pair in row.get('_kept_pairs',[]):retained[tuple(pair)]=max(retained.get(tuple(pair),0),row['until'])
    facts={}
    for identity,group in caches.items():
        marker=group['marker'];needs_marker=PurePosixPath(identity[1]).name.casefold()!='rbstemsplus'
        location='recognized' if marker and marker['validation']=='recognized' else 'default_layout' if not needs_marker else 'unverified_marker'
        for (model,key),members in group['chunks'].items():
            if len(facts)%250==0:progress(85,'Checking scoped cache companions')
            if time.monotonic()>=deadline:partial=True;break
            state='present';reason='Expected FLAC and descriptor structures agree; audio payload and source identity are unverified'
            flacs=members['flac'];descs=members['descriptor']
            if not flacs or not descs:state='incomplete';reason='Expected cache FLAC/descriptor companion is absent from this scoped inventory'
            elif len(flacs)!=1 or len(descs)!=1:state='unknown';reason='Ambiguous cache companion names'
            elif any(r['validation']=='corrupt' for r in flacs+descs):state='incomplete';reason='A cache companion has corrupt metadata'
            elif any(r['validation']!='recognized' for r in flacs+descs):state='unknown';reason='A cache companion was not fully recognized'
            elif descs[0]['descriptor_frames']!=min(flacs[0]['frames']//4410,512):state='incomplete';reason='FLAC sample count and descriptor frame count disagree'
            if not inventory_complete and state=='incomplete':state='unknown';reason='Inventory is incomplete; missing cache companions are inconclusive'
            if location=='unverified_marker' and state=='present':state='unknown';reason='External cache-location marker is missing or unrecognized'
            facts[identity,model,key]=state
            counts['chunks_'+state]+=1
            retention='unknown' if len(caches)!=1 or (model,key) not in retained else 'protected' if retained[model,key]>now else 'expired'
            if len(reports)<max_rows:
                reports.append({'section':'stems_cache_chunk','asset_family':'separation_cache','provider':'rbstemsplus',
                                'validation':'recognized' if state=='present' else 'not_checked','severity':'info' if state=='present' else 'review',
                                'title':key,'model_namespace':model,'cache_root':display(identity),'cache_state':state,
                                'location_status':location,'retention_status':retention,'cache_profile_status':cache_profile(profile),
                                'native_stems_readiness':None,'detail':reason})
            else:partial=True
    inventory_complete=inventory_complete and not partial
    # Accept only aliases explicitly selected by the user, tied to their approved
    # physical scope. Do not resolve arbitrary manifest paths to discover scope.
    source_roots=[(root,root) for root in roots if root.is_dir()]
    source_roots.extend((alias,scope) for alias,scope in source_aliases or [] if scope.is_dir())
    for row in rows:
        if row.get('format')!='rbstems_manifest' or row['validation']!='recognized':continue
        model=row['model_namespace'];records=row.get('_manifest_records',[]);duplicates=Counter(r['path'] for r in records)
        for entry in records:
            if len(reports)>=max_rows or time.monotonic()>=deadline:partial=True;break
            progress(85,'Checking selected provider manifests and cache scopes')
            if entry['path'] not in source_memo:source_memo[entry['path']]=selected_source(entry['path'],source_roots)
            source_status,source_path,stamp=source_memo[entry['path']]
            stamp_status='matches_manifest' if stamp and (stamp['size'],stamp['mtime_ns'])==(entry['size'],entry['mtime_ns']) else 'changed' if stamp else source_status
            if source_path is not None:checked_sources[str(source_path)]=stamp
            for identity in caches or [None]:
                if len(reports)>=max_rows or time.monotonic()>=deadline:partial=True;break
                root_facts=[facts.get((identity,model,key)) for key in entry['keys']] if identity else []
                missing=sum(value is None or value=='incomplete' for value in root_facts)
                unverified=sum(value=='unknown' for value in root_facts)
                state='consistent';detail='Expected cache companions are structurally present and source metadata matches the provider manifest'
                if identity is None:state='unknown';detail='Select the provider cache folder to inspect expected chunks'
                elif not inventory_complete:state='unknown';detail='Incomplete scoped inventory cannot establish manifest completeness'
                elif not entry['complete']:state='incomplete';detail='Provider manifest records an incomplete preparation'
                elif not entry['keys']:state='unknown';detail='Manifest records no chunk keys; whole-track preparation is unproven'
                elif missing:state='incomplete';detail='Expected chunks are absent or invalid in this individual cache scope'
                elif unverified:state='unknown';detail='Some expected cache structures could not be verified'
                elif stamp_status=='changed':state='stale';detail='Source size or nanosecond modification time differs from the provider manifest'
                elif stamp_status!='matches_manifest':state='unknown';detail='Source metadata is unavailable or outside selected folder scopes'
                if duplicates[entry['path']]>1:state='unknown';detail='Manifest has repeated source paths; association is ambiguous'
                model_status=namespace_status(model,profile);profile_status=cache_profile(profile)
                if state=='consistent' and (model_status=='model_mismatch' or profile_status=='profile_mismatch'):
                    state='profile_mismatch';detail='Cache belongs to a different declared model or session profile'
                counts['manifest_'+state]+=1
                reports.append({'section':'stems_preparation','asset_family':'preparation_manifest','provider':'rbstemsplus',
                                'title':PurePosixPath(entry['path'].replace('\\','/')).name,'path':entry['path'],'manifest':row['path'],
                                'cache_root':display(identity) if identity else None,'model_namespace':model,
                                'expected_chunks':len(entry['keys']),'missing_or_invalid_chunks':missing,'unverified_chunks':unverified,
                                'cache_state':state,'source_stamp_status':stamp_status,'source_association':'metadata_match' if stamp_status=='matches_manifest' else 'unknown',
                                'model_status':model_status,'cache_profile_status':profile_status,'native_stems_readiness':None,
                                'validation':'recognized' if state=='consistent' else 'not_checked','severity':'info' if state=='consistent' else 'review',
                                'detail':detail+'; metadata consistency does not establish native readiness or audio identity'})
        if partial:break
    # Recheck metadata checked through manifest references; nothing outside selected roots was opened.
    for index,(path,stamp) in enumerate(checked_sources.items()):
        if index%250==0:progress(88,'Rechecking selected source metadata')
        if source_stamp(Path(path))!=stamp:raise ValueError('A referenced source changed during the STEMS audit; capture again')
    return reports,{'cache_locations':len(caches),'chunk_sets_present':counts['chunks_present'],
                    'chunk_sets_incomplete':counts['chunks_incomplete'],'chunk_sets_unknown':counts['chunks_unknown'],
                    'manifest_associations_consistent':counts['manifest_consistent'],'manifest_associations_incomplete':counts['manifest_incomplete'],
                    'manifest_associations_stale':counts['manifest_stale'],'manifest_associations_unknown':counts['manifest_unknown'],
                    'profile_mismatches':counts['manifest_profile_mismatch'],'findings_complete':not partial,
                    'native_prepared_tracks':None,'source_bytes_read':0}
