/* User-selected identities/releases, never automatic album inference. */
function musicBrainzCandidateMarkup(row){
  const t=key=>I18n.t(key),candidates=row.candidates||[];
  if(candidates.length<2)return '';
  return '<details><summary>'+esc(t('Alternative recordings'))+' · '+num(candidates.length)+'</summary>'+
    '<p class="subtle">'+esc(t('Retrieve another candidate from MusicBrainz. Changing identity removes this batch’s staged suggestions and requires approval again.'))+'</p>'+
    '<select data-mb-candidate-choice="'+esc(row.id)+'" aria-label="'+esc(t('Alternative recordings'))+'">'+
    candidates.map(c=>'<option value="'+esc(c.mbid)+'"'+(c.mbid===row.selected_mbid?' selected':'')+'>'+esc(c.title)+' · '+esc(c.artist)+' · '+esc(c.confidence)+' · '+esc(c.mbid)+'</option>').join('')+'</select>'+
    '<label><input type="checkbox" data-mb-candidate-consent="'+esc(row.id)+'"> '+esc(t('I agree to retrieve this recording from MusicBrainz.'))+'</label>'+
    '<button class="button secondary" data-mb-candidate="'+esc(row.id)+'">'+esc(t('Retrieve selected recording'))+'</button></details>';
}
function musicBrainzReleaseMarkup(row){
  const t=key=>I18n.t(key),releases=row.proposal?.possible_albums||[],selected=row.selected_release;
  if(!releases.length)return '';
  return '<details><summary>'+esc(t('Album / release'))+'</summary><p class="subtle">'+esc(t('Choose the release that matches your file. This is the provider’s returned release list, not a complete discography.'))+'</p>'+
    '<select data-mb-release-choice="'+esc(row.id)+'" aria-label="'+esc(t('Album / release'))+'"><option value="">'+esc(t('Choose a release'))+'</option>'+
    releases.map(r=>'<option value="'+esc(r.mbid)+'"'+(r.mbid===selected?.mbid?' selected':'')+'>'+esc([r.title,r.date,r.country,r.status,r.disambiguation,r.mbid].filter(Boolean).join(' · '))+'</option>').join('')+'</select>'+
    '<button class="button secondary" data-mb-release="'+esc(row.id)+'"'+(!row.match_approved?' disabled':'')+'>'+esc(t('Use this release'))+'</button>'+
    (selected?'<p><a target="_blank" rel="noopener noreferrer" href="https://musicbrainz.org/release/'+encodeURIComponent(selected.mbid)+'">'+esc(selected.title)+'</a> · '+esc(selected.date||t('Unknown'))+'</p>'+
      '<button class="text-button" data-mb-stage="'+esc(row.id)+'" data-field="album">'+esc(t('Stage album'))+'</button>'+
      (selected.date?'<button class="text-button" data-mb-stage="'+esc(row.id)+'" data-field="year">'+esc(t('Stage release year'))+'</button>':''):'')+
    '<p class="subtle">'+esc(t('Staged fields retain recording, release, retrieval time and review provenance. Personal stars stay unchanged.'))+'</p></details>';
}
function bindMusicBrainzChoices(result,batch){
  const root=$('#lab-pilot-results'),row=id=>result.rows.find(r=>r.id===id),element=(attribute,id)=>[...root.querySelectorAll('['+attribute+']')].find(e=>e.getAttribute(attribute)===id);
  for(const button of root.querySelectorAll('[data-mb-candidate]'))button.onclick=wrap(async()=>{
    const track=row(button.dataset.mbCandidate);button.disabled=true;
    try{
      const response=await labPost('musicbrainz/'+batch+'/candidate',{track_id:track.id,candidate_mbid:element('data-mb-candidate-choice',track.id).value,
        review_revision:track.review_revision,edit_revision:track.edit_revision,query_consent:element('data-mb-candidate-consent',track.id).checked});
      await poll(response.job);if(batch===labBatch)await labLoadPilot();
    }finally{if(button.isConnected)button.disabled=false;}
  });
  for(const button of root.querySelectorAll('[data-mb-release]'))button.onclick=wrap(async()=>{
    const track=row(button.dataset.mbRelease);
    await labPost('musicbrainz/'+batch+'/release',{track_id:track.id,release_mbid:element('data-mb-release-choice',track.id).value,review_revision:track.review_revision,edit_revision:track.edit_revision});
    if(batch===labBatch)await labLoadPilot();
  });
  for(const button of root.querySelectorAll('[data-mb-stage]'))button.onclick=wrap(async()=>{
    const track=row(button.dataset.mbStage);
    if(result.snapshot_id!==musicBrainzSnapshot())throw new Error(I18n.t('Select the snapshot used for this pilot before staging suggestions'));
    await labPost('musicbrainz/'+batch+'/stage',{track_id:track.id,field:button.dataset.field,year_basis:'release',review_revision:track.review_revision,edit_revision:track.edit_revision});
    notify(I18n.t('Metadata staged locally'));if(batch===labBatch)await labLoadPilot();
  });
  if(result.rows.some(r=>r.match_approved)){
    const unlock=document.createElement('button');unlock.className='button secondary';unlock.type='button';unlock.textContent=I18n.t('Unlock metadata edits');
    unlock.onclick=wrap(async()=>{await labPost('unlock',{snapshot:result.snapshot_id,unlocked:true});unlock.disabled=true;notify(I18n.t('Staging unlocked'));});
    root.prepend(unlock);
  }
}
