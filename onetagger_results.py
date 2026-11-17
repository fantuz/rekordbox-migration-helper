"""Bounded OneTagger result evidence. Imported paths never grant audio access."""
from datetime import datetime
import json
from math import isfinite
import re

from metadata_overrides import xml_text

FIELDS=('title','artist','album','genre','year')
EXTENDED_FIELDS=FIELDS+('label','composer')
IDENTITY=('id','snapshot','snapshot_digest','scope_key','mapping_revision')
MAX_BYTES=8*1024*1024
STATES={'written','failed','skipped','unprocessed'}
SCHEMA='onetagger.tagging-results'


def decode_report(data):
    """Reject ambiguous JSON before checking membership or accessing any audio."""
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate JSON keys are not supported in OneTagger results')
            result[key]=value
        return result
    def number(value):
        parsed=float(value)
        if not isfinite(parsed):raise ValueError('Nonfinite numbers are not supported in OneTagger results')
        return parsed
    def constant(_):raise ValueError('Nonfinite numbers are not supported in OneTagger results')
    try:
        value=json.loads(data.decode('utf-8-sig'),object_pairs_hook=unique,parse_float=number,parse_constant=constant)
    except (UnicodeError,json.JSONDecodeError,RecursionError,OverflowError):
        raise ValueError('Choose a valid UTF-8 OneTagger results JSON report') from None
    # Accept the original draft API envelope as well as the producer's file.
    if isinstance(value,dict) and set(value)=={'report'}:return value['report']
    return value


def text(value,limit=256,optional=False):
    if optional and value is None:return None
    if not isinstance(value,str) or not value or len(value)>limit or not xml_text(value):
        raise ValueError('Invalid text in OneTagger results report')
    return value


def tags(value,version=1):
    if value is None:return None
    fields=FIELDS if version==1 else EXTENDED_FIELDS
    if not isinstance(value,dict) or not set(FIELDS)<=set(value)<=set(fields):raise ValueError('Unsupported report tag fields')
    for field,item in value.items():
        if item is None:continue
        if field=='year':
            if type(item) is not int or not -(2**31)<=item<2**31:raise ValueError('Invalid report year')
        elif not isinstance(item,str) or len(item)>16384 or any(0xD800<=ord(c)<=0xDFFF for c in item):raise ValueError('Invalid report tag value')
    return {field:value.get(field) for field in fields}


def validate_report(value,manifest):
    if not isinstance(value,dict) or value.get('schema')!=SCHEMA or type(value.get('version')) is not int or value['version'] not in (1,2):
        raise ValueError('Choose a supported OneTagger results JSON (version 1 or 2)')
    version=value['version']
    identity=value.get('selection')
    if not isinstance(identity,dict) or identity!={k:manifest[k] for k in IDENTITY}:
        raise ValueError('This report belongs to a different or outdated Helper selection')
    run_id=text(value.get('run_id'))
    if not re.fullmatch('[0-9a-f]{32}',run_id):raise ValueError('Invalid OneTagger run ID')
    if type(value.get('cancelled')) is not bool:raise ValueError('Invalid report cancellation state')
    header={k:text(value.get(k)) for k in ('application_version','application_commit','created_at','completed_at')}
    try:
        times=[datetime.fromisoformat(header[k]) for k in ('created_at','completed_at')]
        if any(t.tzinfo is None or t.utcoffset() is None for t in times):raise ValueError()
    except (ValueError,OverflowError):raise ValueError('Provide timezone-aware OneTagger report timestamps') from None
    rows=value.get('tracks');selected={r['track_id']:r for r in manifest['tracks']}
    if not isinstance(rows,list) or len(rows)!=len(selected):raise ValueError('Report must retain every selected track, including skipped files')
    checked={}
    for row in rows:
        if not isinstance(row,dict):raise ValueError('Invalid report track')
        track_id=text(row.get('track_id'))
        if track_id not in selected or track_id in checked:raise ValueError('Report track membership is invalid or duplicated')
        path=selected[track_id]['local_path']
        if row.get('local_path')!=path or row.get('final_path')!=path:
            raise ValueError('A reported file path changed. Create a new Helper selection after moving files.')
        status=row.get('status')
        if not isinstance(status,str) or status not in STATES:raise ValueError('Invalid report track outcome')
        before=tags(row.get('before'),version);after=tags(row.get('after'),version)
        state=row.get('file_state')
        if state is not None:
            if not isinstance(state,dict) or set(state)!={'size','modified_ns'} or type(state['size']) is not int or not 0<=state['size']<2**64 or not isinstance(state['modified_ns'],str) or not re.fullmatch('[0-9]{1,30}',state['modified_ns']):
                raise ValueError('Invalid report file state')
        attempts=row.get('attempts')
        if not isinstance(attempts,list) or len(attempts)>100:raise ValueError('Invalid report provider attempts')
        clean=[]
        for attempt in attempts:
            if not isinstance(attempt,dict):raise ValueError('Invalid provider evidence')
            outcome=attempt.get('status');reason=attempt.get('reason');score=attempt.get('score')
            if not isinstance(outcome,str) or outcome not in STATES-{'unprocessed'}:raise ValueError('Invalid provider outcome')
            if reason is not None and (not isinstance(reason,str) or reason not in {'fuzzy','id','isrc','album'}):raise ValueError('Invalid matching reason')
            if score is not None:
                try:finite=type(score) in (int,float) and isfinite(score)
                except OverflowError:finite=False
                if not finite:raise ValueError('Invalid match score')
            if type(attempt.get('used_shazam')) is not bool:raise ValueError('Invalid match evidence')
            clean.append({'provider':text(attempt.get('provider')),'track_id':text(attempt.get('track_id'),optional=True),
                          'release_id':text(attempt.get('release_id'),optional=True),'status':outcome,'reason':reason,
                          'score':score,'used_shazam':attempt['used_shazam']})
        if status=='written' and not any(a['status']=='written' for a in clean):raise ValueError('Written result has no successful write attempt')
        checked[track_id]={'track_id':track_id,'status':status,'before':before,'after':after,'file_state':state,
                           'before_error':text(row.get('before_error'),optional=True),'after_error':text(row.get('after_error'),optional=True),
                           'attempts':clean}
    return {'schema':SCHEMA,'version':version,'run_id':run_id,**header,'selection':dict(identity),
            'cancelled':value['cancelled'],'rows':checked}

