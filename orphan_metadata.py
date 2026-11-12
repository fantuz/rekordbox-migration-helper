"""Read tags only from explicitly selected, locally available inventory files."""
from hashlib import sha256
from pathlib import Path
import re

from media import file_record
from metadata_export import track
from workbench_store import now


def capture_orphans(inventory,progress,limit=5000):
    from tinytag import TinyTag
    files=inventory.get('orphans',[])
    if len(files)>limit:files=files[:limit]
    tracks=[];warnings=[]
    for n,record in enumerate(files):
        path=Path(record['path'])
        try:
            before=file_record(path)
            if before['cloud_only']:warnings.append(path.name+': online-only, skipped');continue
            tag=TinyTag.get(str(path),image=False)
            after=file_record(path)
            if (before['size'],before['mtime_ns'])!=(after['size'],after['mtime_ns']):warnings.append(path.name+': changed while tags were read');continue
            title,artist=tag.title or '',tag.artist or '';origin='local file tags'
            if not title:
                pieces=re.split(r'\s+[-–—]\s+',path.stem,maxsplit=1)
                if len(pieces)==2:artist=artist or pieces[0];title=pieces[1]
                else:title=path.stem
                origin='filename fallback; verify identity'
            item=track({'id':'orphan:'+sha256(str(path).encode()).hexdigest()[:24],'title':title,'artist':artist,'album':tag.album,'genre':tag.genre,
                        'year':str(tag.year or '')[:4],'duration':tag.duration,'current_path':str(path),'format':path.suffix.lstrip('.')})
            item.update(metadata_origin=origin,cues=None,raw_tags={'year':tag.year},isrc='',size=before['size'])
            tracks.append(item)
        except Exception as error:
            warnings.append(path.name+': '+str(error)[:160])
        if n%50==0:progress(100*(n+1)/max(1,len(files)),'Reading local tags from unreferenced inventory files')
    return {'schema':1,'source_kind':'Unreferenced local media tags','scope_key':'orphans:'+sha256(str(inventory.get('roots',[])).encode()).hexdigest(),
            'captured':now(),'tracks':tracks,'playlists':[],'asset_references':[],'warnings':warnings[:100],
            'capabilities':{'cue_positions':False,'playlist_order':False,'analysis_references':False}}
