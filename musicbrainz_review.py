"""Explicit recording/release review with compare-and-swap and staged provenance."""
from hashlib import sha256
import json
import re
from threading import Event
from uuid import uuid4
from flask import jsonify,request
from werkzeug.exceptions import Conflict
from workbench_store import encoded,now
from metadata_overrides import validate,comparable
from metadata_concurrency import require_revision,revision as edit_stamp

def revision(result):
    return sha256(encoded(result).encode()).hexdigest()

def selected_candidate(result):
    candidates=result.get('candidates') or []
    return next((r for r in candidates if r.get('mbid')==result.get('selected_mbid')),candidates[0] if candidates else {})

def read(db,batch,track,expected):
    row=db.execute('SELECT payload FROM mb_results WHERE batch_id=? AND track_id=?',(batch,track)).fetchone()
    if not row:raise ValueError('No retrieved match exists for this track')
    result=json.loads(row[0])
    if not isinstance(expected,str) or expected!=revision(result):
        raise Conflict('This MusicBrainz result changed. Reload and review the selected recording again.')
    return result

def write(db,batch,track,result):
    db.execute('UPDATE mb_results SET payload=? WHERE batch_id=? AND track_id=?',(encoded(result),batch,track))

def reset_staged(db,scope,track,batch,fields=('year','genre','album')):
    # Clear only this batch's still-staged suggestions; preserve later manual edits.
    for row in db.execute('SELECT field,value,origin FROM overrides WHERE scope_key=? AND track_id=?',(scope,track)).fetchall():
        if row['field'] not in fields:continue
        try:origin=json.loads(row['origin'])
        except (TypeError,ValueError):continue
        if not isinstance(origin,dict) or origin.get('provider')!='MusicBrainz' or origin.get('batch_id')!=batch:continue
        db.execute('INSERT INTO override_history VALUES (?,?,?,?,?,?,?)',(uuid4().hex,scope,track,row['field'],row['value'],None,now()))
        db.execute('DELETE FROM overrides WHERE scope_key=? AND track_id=? AND field=?',(scope,track,row['field']))

def register(owner,store,enabled,unlocked,gate,pool,cancellations,network_lock,client_factory):
    from musicbrainz_pilot import proposals
    def body():
        b=request.get_json(silent=True)
        if not isinstance(b,dict):raise ValueError('Provide a MusicBrainz review')
        return b
    def source(saved,batch):
        with saved.connection() as db:r=db.execute('SELECT snapshot_id FROM mb_batches WHERE id=?',(batch,)).fetchone()
        if not r:raise ValueError('Pilot batch not found')
        return saved.snapshot(r[0])
    def idle(batch):
        if batch in cancellations:raise Conflict('Finish or cancel this batch before reviewing its matches.')

    @owner.app.post('/api/lab/musicbrainz/<identity>/candidate')
    def choose_candidate(identity):
        b=body();saved=store();track=str(b.get('track_id',''));candidate=b.get('candidate_mbid');expected=b.get('review_revision')
        if b.get('query_consent') is not True:raise ValueError('Confirm retrieval of the selected MusicBrainz recording')
        if not enabled():raise ValueError('Enable MusicBrainz before retrieving another recording')
        s=source(saved,identity)
        from enrichment_context import require_snapshot
        require_snapshot(owner,s)
        with network_lock:
            if cancellations:raise Conflict('Finish or cancel queued MusicBrainz lookups before retrieving another recording.')
            with saved.connection() as db:
                result=read(db,identity,track,expected)
                if not isinstance(candidate,str) or not re.fullmatch('[0-9a-f-]{36}',candidate) or not any(r.get('mbid')==candidate for r in result.get('candidates',[])):
                    raise ValueError('Choose a recording from the retrieved candidates')
            event=Event();cancellations[identity]=event
            def finished(_status):
                event.set()
                with network_lock:
                    if cancellations.get(identity) is event:cancellations.pop(identity,None)
            def work(progress):
                try:
                    progress(5,'Retrieving the selected MusicBrainz recording')
                    client=client_factory(saved,gate,enabled,2.0,event)
                    detail=client.get('recording/'+candidate,{'inc':'ratings+genres+tags+releases+isrcs+artist-credits'})
                    if detail.get('id')!=candidate:raise ValueError('Candidate details do not match the requested recording')
                    proposal=proposals(detail)
                    progress(90,'Saving reviewed candidate choices')
                    if event.is_set() or not enabled():raise InterruptedError('MusicBrainz review cancelled')
                    with saved.connection() as db:
                        db.execute('BEGIN IMMEDIATE')
                        result=read(db,identity,track,expected)
                        require_revision(db,s['scope_key'],b.get('edit_revision'))
                        reset_staged(db,s['scope_key'],track,identity)
                        result.update(selected_mbid=candidate,proposal=proposal,match_approved=False,selected_release=None,
                                      status='candidate_needs_review',candidate_selected_at=now())
                        result.pop('reviewed_at',None);write(db,identity,track,result)
                    return {'selected_mbid':candidate,'review_revision':revision(result)}
                finally:finished(None)
            try:job=owner.launch(work,'Retrieving a selected MusicBrainz recording',pool=pool,on_finished=finished,cancel_event=event)
            except Exception:finished(None);raise
        return jsonify(job=job)

    @owner.app.post('/api/lab/musicbrainz/<identity>/release')
    def choose_release(identity):
        b=body();saved=store();s=source(saved,identity);track=str(b.get('track_id',''))
        with network_lock:
            idle(identity)
            with saved.connection() as db:
                db.execute('BEGIN IMMEDIATE');result=read(db,identity,track,b.get('review_revision'))
                require_revision(db,s['scope_key'],b.get('edit_revision'))
                release=next((r for r in (result.get('proposal') or {}).get('possible_albums',[]) if r.get('mbid')==b.get('release_mbid')),None)
                if not release or not re.fullmatch('[0-9a-f-]{36}',str(release.get('mbid',''))) or not release.get('title'):
                    raise ValueError('Choose a release from this recording')
                if not result.get('match_approved'):raise ValueError('Approve the recording identity before choosing its release')
                # A changed release invalidates only release-derived staged fields.
                reset_staged(db,s['scope_key'],track,identity,('album','year'))
                result['selected_release']={**release,'recording_mbid':selected_candidate(result)['mbid'],'selected_at':now()}
                write(db,identity,track,result)
        return jsonify(selected_release=result['selected_release'],review_revision=revision(result))

    @owner.app.post('/api/lab/musicbrainz/<identity>/review')
    def review(identity):
        b=body();saved=store();s=source(saved,identity);track=str(b.get('track_id',''))
        with network_lock:
            idle(identity)
            with saved.connection() as db:
                db.execute('BEGIN IMMEDIATE');result=read(db,identity,track,b.get('review_revision'))
                require_revision(db,s['scope_key'],b.get('edit_revision'))
                if not result.get('candidates') or not result.get('proposal'):raise ValueError('No candidate with metadata is available')
                result['match_approved']=b.get('approved') is True;result['reviewed_at']=now()
                if not result['match_approved']:reset_staged(db,s['scope_key'],track,identity);result['selected_release']=None
                write(db,identity,track,result)
        return jsonify(match_approved=result['match_approved'],review_revision=revision(result))

    @owner.app.post('/api/lab/musicbrainz/<identity>/stage')
    def stage(identity):
        b=body();field=b.get('field');track=str(b.get('track_id',''))
        if field not in ('year','genre','album'):raise ValueError('Stage a proposed year, genre or selected album; personal stars remain a manual choice')
        saved=store();s=source(saved,identity);unlocked(s)
        local=next((t for t in s['tracks'] if t['id']==track),None)
        if local is None:raise ValueError('The retrieved track is outside the selected snapshot')
        with network_lock:
            idle(identity)
            with saved.connection() as db:
                db.execute('BEGIN IMMEDIATE');result=read(db,identity,track,b.get('review_revision'))
                require_revision(db,s['scope_key'],b.get('edit_revision'))
                if not result.get('match_approved'):raise ValueError('Approve this retrieved identity before staging its available metadata')
                proposal=result.get('proposal') or {};release=result.get('selected_release');candidate=selected_candidate(result)
                basis='recording';value=proposal.get(field)
                if field=='album' or field=='year' and b.get('year_basis')=='release':
                    if not release or release.get('recording_mbid')!=candidate.get('mbid'):
                        raise ValueError('Select the matching release explicitly before staging its album or year')
                    basis='release';value=release['title'] if field=='album' else str(release.get('date') or '')[:4]
                    if value=='':raise ValueError('The selected release has no recorded year')
                elif field=='year' and b.get('year_basis','recording')!='recording':raise ValueError('Choose recording or release year')
                if value is None:raise ValueError('No proposed value is available')
                value=validate(field,value)
                provenance={'provider':'MusicBrainz','batch_id':identity,'recording_id':candidate['mbid'],
                            'release_id':release['mbid'] if basis=='release' else None,'field':field,'basis':basis,
                            'source_url':'https://musicbrainz.org/'+basis+'/'+(release['mbid'] if basis=='release' else candidate['mbid']),
                            'retrieved_at':proposal.get('retrieved_at'),'reviewed_at':result.get('reviewed_at'),'staged_at':now()}
                old=db.execute('SELECT value,baseline FROM overrides WHERE scope_key=? AND track_id=? AND field=?',(s['scope_key'],track,field)).fetchone()
                if old and comparable(field,json.loads(old['baseline']))!=comparable(field,local.get(field)):raise ValueError('Metadata baseline changed; reset and review this edit')
                db.execute('INSERT INTO override_history VALUES (?,?,?,?,?,?,?)',(uuid4().hex,s['scope_key'],track,field,old['value'] if old else None,encoded(value),now()))
                db.execute('INSERT OR REPLACE INTO overrides VALUES (?,?,?,?,?,?,?)',
                           (s['scope_key'],track,field,encoded(value),encoded(local.get(field)),encoded(provenance),now()))
                stamp=edit_stamp(db,s['scope_key'])
        return jsonify(value=value,origin=encoded(provenance),provenance=provenance,edit_revision=stamp)
