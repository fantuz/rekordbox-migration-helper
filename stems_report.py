"""Orchestrate STEMS source advisories and selected asset/provider checks."""
from pathlib import Path
from analysis_audit import audit_assets
from stems_eligibility import context,eligibility


def stems_report(snapshot,paths,session,progress,verify=False):
    profile=context(session)
    selected=paths if isinstance(paths,list) else [paths] if paths else []
    if len(selected)>20:raise ValueError('Choose at most twenty STEMS folders or backup ZIPs')
    available=[];unavailable=[]
    for value in selected:
        if not isinstance(value,str):raise ValueError('Choose absolute STEMS folders or backup ZIP paths')
        path=Path(value.strip().strip('"')).expanduser()
        if not path.is_absolute():raise ValueError('Choose absolute STEMS folders or backup ZIP paths')
        if path.exists():available.append(str(path))
        else:unavailable.append({'section':'stems_scope_unavailable','title':path.name,'path':str(path),
                                'asset_family':'separation_cache','provider':'unknown','cache_state':'unavailable',
                                'severity':'review','validation':'not_checked','native_stems_readiness':None,
                                'detail':'Selected location is unavailable; reconnect or make it accessible and run a new check'})
    if available:
        summary,rows=audit_assets(snapshot,available,progress,verify,inspect=True,profile=profile,allow_empty=True)
        def advance(value,message):progress(90+min(value,90)/10,message)
    else:
        summary={'source_writes':False,'stems':{'prepared_tracks':None,
                 'preparation_status':'Native per-track STEMS preparation is unknown; no asset scopes were selected',
                 'related_candidate_files':0,'related_candidate_bytes':0,'rbsc_drum_capture_files':0,
                 'note':'Eligibility advisories are separate from native preparation and cache completeness'}}
        rows=[];advance=progress
    facts,advisories=eligibility(snapshot,profile,advance)
    summary['stems_eligibility']=facts
    summary['unavailable_scopes']=len(unavailable)
    return summary,rows+unavailable+advisories
