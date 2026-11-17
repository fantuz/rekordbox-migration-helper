"""Orchestrate STEMS source advisories and selected asset/provider checks."""
from analysis_audit import audit_assets
from stems_eligibility import context,eligibility


def stems_report(snapshot,paths,session,progress,verify=False):
    profile=context(session)
    selected=paths if isinstance(paths,list) else [paths] if paths else []
    if selected:
        summary,rows=audit_assets(snapshot,selected,progress,verify,inspect=True,profile=profile)
        def advance(value,message):progress(90+min(value,90)/10,message)
    else:
        summary={'source_writes':False,'stems':{'prepared_tracks':None,
                 'preparation_status':'Native per-track STEMS preparation is unknown; no asset scopes were selected',
                 'related_candidate_files':0,'related_candidate_bytes':0,'rbsc_drum_capture_files':0,
                 'note':'Eligibility advisories are separate from native preparation and cache completeness'}}
        rows=[];advance=progress
    facts,advisories=eligibility(snapshot,profile,advance)
    summary['stems_eligibility']=facts
    return summary,rows+advisories
