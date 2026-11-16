/* All library-derived strings are escaped; mutations use the local action token. */
let labInfo=null,labReport=null,labReportOffset=0,labTrackOffset=0,labTrackRows=[],labEdited=null,labUnlocked=false,labTracksRevision=0;
let labBatch=null,labPilotOffset=0,labPilotTimer=null,labPilotStatus=null,labPilotRevision=0,labPilotSnapshot=null,labPilotPreviewDirty=false,labPilotSort=preferences.get('workbench-mb-sort')||'sample',labPilotDirection=preferences.get('workbench-mb-direction')||'asc';
const labPilotSortChoices=[['sample','Original order'],['title','Title'],['artist','Artist'],['genre','Genre'],['status','Status'],['confidence','Similarity'],['candidate','Candidate title'],['year','Year'],['community','Community rating'],['file_status','File status']];
if(!labPilotSortChoices.some(([field])=>field===labPilotSort))labPilotSort='sample';
if(!['asc','desc'].includes(labPilotDirection))labPilotDirection='asc';
function rememberPilotSort(){
  preferences.set('workbench-mb-sort',labPilotSort);preferences.set('workbench-mb-direction',labPilotDirection);
}
function pilotFileStatus(status){
  const labels={playable:'Playable',missing:'Missing',inaccessible:'Inaccessible',unverified:'Unverified',unchecked:'Unchecked'};
  return esc(I18n.t(labels[status]||'Unchecked'));
}
const labPost=(url,data)=>api('/api/lab/'+url,{method:'POST',body:JSON.stringify(data)});
const labSnapshot=()=>$('#lab-snapshot').value;
const labSummary=data=>'<div class="lab-summary">'+Object.entries(data || {}).filter(([,v])=>v===null || typeof v!=='object').map(([k,v])=>'<div><span>'+esc(I18n.t(k.replaceAll('_',' ')))+'</span><b>'+esc(v===null?I18n.t("Unknown"):v===true?I18n.t("Yes"):v===false?I18n.t("No"):v)+'</b></div>').join('')+'</div>';
function labSelect(selector,items,label,empty=I18n.t("Choose a snapshot")) {
  const el=$(selector),old=el.value;el.innerHTML='<option value="">'+esc(empty)+'</option>'+items.map(r=>'<option value="'+esc(r.id)+'">'+esc(label(r))+'</option>').join('');
  if(items.some(r=>r.id===old))el.value=old;
}
async function loadLab() {
  labInfo=await api('/api/lab');
  const sources=[...(labInfo.workspace?[{id:'session',get label(){return I18n.t("Loaded XML + ZIP workspace");}},{id:'orphans',get label(){return I18n.t("Unreferenced local tags (scan Media inventory first)");}}]:[]),...labInfo.sources.map(r=>({...r,label:I18n.t("Source capture ·")+" "+snapshotMoment(r.created)+' · '+r.label}))];
  labSelect('#lab-source',sources,r=>r.label,I18n.t("Choose input capture"));
  const label=r=>r.label+' · '+snapshotMoment(r.created);
  for(const selector of ['#lab-snapshot','#lab-before','#lab-after'])labSelect(selector,labInfo.snapshots,label);
  const shared=window.Journeys?.context?.();
  if(shared?.snapshot && labInfo.snapshots.some(r=>r.id===shared.snapshot))$('#lab-snapshot').value=shared.snapshot;
  if(shared && !shared.snapshot){$('#lab-snapshot').value='';$('#lab-tracks').replaceChildren();$('#lab-edit-form').hidden=true;}
  if(!shared && !labSnapshot() && labInfo.snapshots.length)$('#lab-snapshot').value=labInfo.snapshots[0].id;
  labSelect('#lab-report-select',labInfo.reports,r=>r.kind+' · '+new Date(r.created).toLocaleString(I18n.language),I18n.t("Choose an evidence report"));
  $('#lab-pilot-enabled').checked=labInfo.musicbrainz_enabled;$('#lab-pilot-enabled').disabled=labInfo.musicbrainz_forced_off;
  labPilotButtons();await labSnapshotChanged(false);
  if(window.BackgroundPilot)await BackgroundPilot.refresh();
  if(typeof renderDiscoveryHints==='function')await renderDiscoveryHints();
}
async function labSnapshotChanged(clear=true) {
  const s=labInfo.snapshots.find(r=>r.id===labSnapshot());
  $('#lab-unlock').disabled=!s;
  if(!s){labEdited=null;labUnlocked=false;$('#lab-unlock').checked=false;$('#lab-tracks').replaceChildren();$('#lab-tracks-count').textContent='';$('#lab-edit-form').hidden=true;$('#lab-edit-state').textContent=I18n.t('Read-only');}
  $('#lab-snapshot-info').textContent=s?I18n.t("Scope:")+" "+s.scope_key+" "+I18n.t("· Original snapshots remain immutable.")+" "+(s.scope_key.startsWith('session:')?I18n.t("Staged edits apply to copy exports from this same workspace."):I18n.t("Edits apply to offline HTML; they do not attach to a different XML/ZIP workspace.")):I18n.t("Save a snapshot from a loaded workspace or Source analyzer capture.");
  if(clear){labTrackOffset=0;labEdited=null;$('#lab-edit-form').hidden=true;}
  if(s)await labLoadTracks();
}
async function labRun(url,data) {
  const r=await labPost(url,data),result=await poll(r.job);await loadLab();
  if(result.id && result.summary){$('#lab-report-select').value=result.id;labReportOffset=0;$('#lab-report-section').value='';await labLoadReport();}
  return result;
}
$$('[data-lab-tab]').forEach(b=>b.onclick=()=>{
  $$('.lab-panel').forEach(p=>p.hidden=p.id!=='lab-panel-'+b.dataset.labTab);
  $$('[data-lab-tab]').forEach(t=>t.classList.toggle('selected',t===b));
});
$('#lab-capture-form').onsubmit=wrap(async e=>{e.preventDefault();const r=await labRun('snapshots',{source:$('#lab-source').value,label:$('#lab-label').value});if(window.Journeys){await Journeys.load();await Journeys.selectContext('snapshot:'+r.id);}$('#lab-snapshot').value=r.id;await labSnapshotChanged();notify(I18n.t("Immutable snapshot saved locally"));});
$('#lab-snapshot').onchange=wrap(()=>labSnapshotChanged());
for(const kind of ['consistency','coverage','assets'])$('#lab-'+kind).onclick=wrap(()=>labRun('check',{snapshot:labSnapshot(),kind,working:$('#lab-working').checked,min_cues:$('#lab-min-cues').value,min_manual:$('#lab-min-manual').value,require_analysis:$('#lab-analysis-required').checked,paths:pathLines($('#lab-assets-path').value),verify:$('#lab-assets-verify').checked}));
$('#lab-compare-form').onsubmit=wrap(async e=>{e.preventDefault();await labRun('compare',{before:$('#lab-before').value,after:$('#lab-after').value,tolerance_ms:$('#lab-tolerance').value});});

async function labLoadReport() {
  const id=$('#lab-report-select').value;if(!id)return;
  const section=$('#lab-report-section').value,q=$('#lab-report-search').value;
  labReport=await api('/api/lab/reports/'+encodeURIComponent(id)+'?'+new URLSearchParams({offset:labReportOffset,section,q}));
  $('#lab-report-summary').innerHTML=labSummary(labReport.summary);
  const summary=labReport.summary;
  if(summary.scopes)$('#lab-report-summary').insertAdjacentHTML('beforeend',("<h4>"+esc(I18n.t("Inspected locations"))+"</h4>")+summary.scopes.map(r=>'<p class="subtle">'+esc(r.kind)+' · <code>'+esc(r.path)+'</code></p>').join('')+("<div class=\"lab-table\"><table><thead><tr><th>"+esc(I18n.t("Analysis extension"))+"</th><th>"+esc(I18n.t("Files"))+"</th><th>"+esc(I18n.t("Logical size"))+"</th></tr></thead><tbody>")+summary.analysis_extensions.map(r=>'<tr><td>'+esc(r.extension)+'</td><td>'+num(r.files)+'</td><td>'+esc(bytes(r.bytes))+'</td></tr>').join('')+'</tbody></table></div>');
  if(summary.stems)$('#lab-report-summary').insertAdjacentHTML('beforeend',("<div class=\"stems-summary\"><h3>"+esc(I18n.t("STEMS evidence"))+"</h3><p>")+esc(summary.stems.preparation_status)+'</p>'+labSummary({prepared_tracks:summary.stems.prepared_tracks,related_candidate_files:summary.stems.related_candidate_files,rbsc_drum_capture_files:summary.stems.rbsc_drum_capture_files})+("<p>"+esc(I18n.t("Related candidate file size:"))+" ")+esc(bytes(summary.stems.related_candidate_bytes))+'. '+esc(summary.stems.note)+'</p></div>');
  if(summary.scope_warnings?.length)$('#lab-report-summary').insertAdjacentHTML('beforeend',summary.scope_warnings.map(w=>'<p class="subtle">'+esc(w)+'</p>').join(''));
  $('#lab-report-section').innerHTML=("<option value=\"\">"+esc(I18n.t("All findings"))+"</option>")+labReport.sections.map(r=>'<option value="'+esc(r.section)+'">'+esc(r.section.replaceAll('_',' '))+' · '+num(r.count)+'</option>').join('');$('#lab-report-section').value=section;
  $('#lab-report-download').hidden=false;$('#lab-report-download').href='/api/lab/reports/'+encodeURIComponent(id)+'/download';
  $('#lab-report-rows').innerHTML=("<table><thead><tr><th>"+esc(I18n.t("Finding"))+"</th><th>"+esc(I18n.t("Track / group"))+"</th><th>"+esc(I18n.t("Evidence"))+"</th></tr></thead><tbody>")+labReport.rows.map((r,i)=>'<tr><td>'+esc(r.section.replaceAll('_',' '))+'</td><td>'+((labReport.sources?.length===1&&r.track_id)?TrackPlayback.button(labReport.sources[0],r.track_id):'')+'<strong>'+esc(r.title || r.playlist || r.name || I18n.t("Group"))+'</strong>'+'<br><span class="subtle">'+esc(r.artist || '')+'</span></td><td>'+esc(r.detail)+("<details><summary>"+esc(I18n.t("Show evidence"))+"</summary><pre>")+esc(JSON.stringify(r,null,2))+'</pre></details>'+(r.section==='variant'?'<button class="button secondary" data-lab-normalize="'+i+("\">"+esc(I18n.t("Stage"))+" "+"")+num(r.track_ids.length)+' as “'+esc(r.canonical)+'”</button>':'')+'</td></tr>').join('')+'</tbody></table>';
  $('#lab-report-count').textContent=num(labReport.total)+' findings · '+num(labReportOffset+1)+'–'+num(Math.min(labReportOffset+50,labReport.total));
  $('#lab-report-prev').disabled=labReportOffset===0;$('#lab-report-next').disabled=labReportOffset+50>=labReport.total;
  $$('[data-lab-normalize]').forEach(b=>b.onclick=wrap(async()=>{
    const r=labReport.rows[Number(b.dataset.labNormalize)];
    if(labReport.sources[0]!==labSnapshot())throw new Error(I18n.t("Select the snapshot used by this report before staging normalization"));
    const result=await labPost('normalize',{snapshot:labSnapshot(),track_ids:r.track_ids,field:r.field,value:r.canonical});
    await labLoadTracks();notify(num(result.count)+" "+I18n.t("field overrides staged; reset individual fields in Metadata editor"));
  }));
}
$('#lab-report-select').onchange=wrap(async()=>{labReportOffset=0;$('#lab-report-section').value='';await labLoadReport();});
for(const id of ['#lab-report-section','#lab-report-find'])$(id)[id.endsWith('section')?'onchange':'onclick']=wrap(async()=>{labReportOffset=0;await labLoadReport();});
$('#lab-report-prev').onclick=wrap(async()=>{labReportOffset=Math.max(0,labReportOffset-50);await labLoadReport();});
$('#lab-report-next').onclick=wrap(async()=>{labReportOffset+=50;await labLoadReport();});

async function labLoadTracks() {
  const revision=++labTracksRevision,snapshot=labSnapshot();if(!snapshot)return;
  const r=await api('/api/lab/tracks?'+new URLSearchParams({snapshot,offset:labTrackOffset,q:$('#lab-track-search').value}));
  if(revision!==labTracksRevision || snapshot!==labSnapshot())return;
  labTrackRows=r.rows;labUnlocked=r.unlocked;$('#lab-unlock').checked=labUnlocked;
  $('#lab-edit-state').textContent=(labUnlocked?I18n.t("Staging unlocked"):I18n.t("Read-only"))+' · '+num(r.override_fields)+" "+I18n.t("field overrides in this scope. Source database and audio tags stay unchanged.");
  $('#lab-tracks').innerHTML=("<table><thead><tr><th>"+esc(I18n.t("Track"))+"</th><th>"+esc(I18n.t("Artist"))+"</th><th>"+esc(I18n.t("Year / stars / genre"))+"</th><th></th></tr></thead><tbody>")+r.rows.map((item,i)=>{const t={...item.original,...Object.fromEntries(Object.entries(item.overrides).map(([k,v])=>[k,v.value]))};return '<tr><td>'+TrackPlayback.button(snapshot,t.id)+esc(t.title)+'<br><span class="subtle">'+esc(t.id)+'</span></td><td>'+esc(t.artist)+'</td><td>'+esc(t.year || '—')+' · '+esc(t.rating ?? I18n.t("Unknown"))+' ★ · '+esc(t.genre || I18n.t("Unknown"))+'</td><td><button class="button secondary" data-lab-edit="'+i+("\">"+esc(I18n.t("Inspect / edit"))+"")+(Object.keys(item.overrides).length?" "+I18n.t("· staged"):'')+'</button></td></tr>';}).join('')+'</tbody></table>';
  $('#lab-tracks-count').textContent=num(r.total)+' tracks · '+num(labTrackOffset+1)+'–'+num(Math.min(labTrackOffset+30,r.total));$('#lab-tracks-prev').disabled=!labTrackOffset;$('#lab-tracks-next').disabled=labTrackOffset+30>=r.total;
  $$('[data-lab-edit]').forEach(b=>b.onclick=wrap(()=>openTrackDetails(labSnapshot(),labTrackRows[Number(b.dataset.labEdit)].original.id)));
  if(labEdited){const updated=r.rows.find(t=>t.original.id===labEdited.original.id);if(updated)labEdit(updated);else $('#lab-edit-save').disabled=!labUnlocked;}
}
function labEdit(item) {
  labEdited=item;$('#lab-edit-form').hidden=false;$('#lab-edit-title').innerHTML=TrackPlayback.button(labSnapshot(),item.original.id)+esc(item.original.title+' · '+item.original.id);
  $('#lab-edit-fields').innerHTML=labInfo.fields.map(field=>{
    const edit=item.overrides[field],value=edit?edit.value:item.original[field];
    return '<label>'+esc(I18n.field(field))+'<input data-lab-field="'+field+'" '+(['rating','year'].includes(field)?'type="number" step="1" '+(field==='rating'?'min="0" max="5"':'min="1000" max="'+(new Date().getFullYear()+1)+'"'):'maxlength="255"')+' value="'+esc(value ?? '')+'" '+(!labUnlocked?'disabled':'')+("><small class=\"subtle\">"+esc(I18n.t("Captured:"))+" ")+esc(item.original[field] ?? I18n.t("Unknown"))+'</small>'+(edit?'<button class="text-button" type="button" data-lab-reset="'+field+'" '+(!labUnlocked?'disabled':'')+(">"+esc(I18n.t("Reset override"))+"</button>"):'')+'</label>';
  }).join('');$('#lab-edit-save').disabled=!labUnlocked;
  $$('[data-lab-reset]').forEach(b=>b.onclick=wrap(async()=>{await api('/api/lab/overrides',{method:'DELETE',body:JSON.stringify({snapshot:labSnapshot(),track_id:item.original.id,field:b.dataset.labReset})});await labLoadTracks();}));
}
$('#lab-unlock').onchange=wrap(async()=>{try{await labPost('unlock',{snapshot:labSnapshot(),unlocked:$('#lab-unlock').checked});}finally{await labLoadTracks();}});
$('#lab-edit-form').onsubmit=wrap(async e=>{
  e.preventDefault();if(!labEdited)return;let count=0;
  for(const input of $$('[data-lab-field]')){
    const field=input.dataset.labField,previous=labEdited.overrides[field]?.value ?? labEdited.original[field];
    if(String(previous ?? '')===input.value)continue;
    await labPost('overrides',{snapshot:labSnapshot(),track_id:labEdited.original.id,field,value:input.value});count++;
  }
  await labLoadTracks();notify(num(count)+" "+I18n.t("field changes staged locally"));
});
$('#lab-track-find').onclick=wrap(async()=>{labTrackOffset=0;await labLoadTracks();});
$('#lab-tracks-prev').onclick=wrap(async()=>{labTrackOffset=Math.max(0,labTrackOffset-30);await labLoadTracks();});
$('#lab-tracks-next').onclick=wrap(async()=>{labTrackOffset+=30;await labLoadTracks();});
$('#lab-html').onclick=wrap(async()=>{
  const r=await labPost('offline-export',{snapshot:labSnapshot(),working:$('#lab-html-working').checked});const result=await poll(r.job);
  $('#lab-html-result').innerHTML=("<p>"+esc(I18n.t("Offline explorer saved."))+" "+"<a class=\"button secondary\" href=\"/api/quick-export/")+esc(result.id)+'/html">HTML ↓</a> <a class="button secondary" href="/api/quick-export/'+esc(result.id)+("/zip\">"+esc(I18n.t("Minisite ZIP ↓"))+"</a></p>");
});

function labPilotButtons() {
  $('#lab-pilot-preview').disabled=!musicBrainzReady() || !musicBrainzHasTarget();
  $('#lab-pilot-start').disabled=!musicBrainzReady() || !labBatch || labPilotPreviewDirty || labPilotSnapshot!==musicBrainzSnapshot() || ['running','queued','complete'].includes(labPilotStatus) || !$('#lab-pilot-enabled').checked || !$('#lab-pilot-consent').checked;
}
$('#lab-pilot-consent').onchange=labPilotButtons;
$('#lab-pilot-enabled').onchange=wrap(async()=>{try{const r=await labPost('features',{musicbrainz_enabled:$('#lab-pilot-enabled').checked});$('#lab-pilot-enabled').checked=r.musicbrainz_enabled;}finally{labPilotButtons();}});
const labPilotSelection=()=>({snapshot:musicBrainzSnapshot(),
  top_genres:$('#lab-pilot-top').value,seed:$('#lab-pilot-seed').value,
  speed:$('#lab-pilot-speed').value,sample_size:$('#lab-pilot-size').value,
  target:$('#lab-pilot-target').value,target_value:$('#lab-pilot-target-value').value,
  include_unavailable:$('#lab-pilot-include-unavailable').checked});
$('#lab-pilot-preview').onclick=wrap(async()=>{
  const requested=labPilotSelection(),signature=JSON.stringify(requested);
  const preview=await labPost('musicbrainz/preview',requested);
  const r=preview.job?await poll(preview.job):preview;
  labBatch=r.id;labPilotOffset=0;
  // The user may switch targets while preview generation is in flight.
  // Never enable Start for a preview of a different selection.
  labPilotPreviewDirty=JSON.stringify(labPilotSelection())!==signature;
  preferences.set('workbench-lab-batch',labBatch);$('#lab-pilot-consent').checked=false;
  await labLoadPilot();labPilotButtons();
});
async function labLoadPilot(feedback=true,signal) {
  if(!labBatch)return;
  const revision=++labPilotRevision,batch=labBatch;
  const r=await api('/api/lab/musicbrainz/'+encodeURIComponent(labBatch)+'?'+new URLSearchParams({offset:labPilotOffset,sort:labPilotSort,direction:labPilotDirection}),{feedback,signal});
  if(revision!==labPilotRevision || batch!==labBatch)return;
  labPilotSnapshot=r.snapshot_id;labPilotStatus=r.status;labPilotButtons();
  $('#musicbrainz-availability-summary').textContent=I18n.t(r.summary.playable_only?'Playable tracks only':'Include tracks with unavailable or unverified audio')+' · '+I18n.t('Excluded unavailable tracks')+': '+num(r.summary.excluded_unplayable||0)+' · '+I18n.t('Skipped unavailable tracks')+': '+num(r.summary.skipped_unplayable||0);
  const batchSource=musicBrainzInfo?.snapshots.find(s=>s.id===r.snapshot_id);
  $('#musicbrainz-batch-source').textContent=I18n.t('Source snapshot')+' · '+(batchSource?.label || r.snapshot_id)+(r.summary.target && r.summary.target!=='balanced'?' · '+I18n.t('Quick enrichment target')+': '+I18n.t(({balanced:'Balanced genres',random:'Random selection',genre:'Genre',album:'Album',year:'Year',playlist:'Playlist',missing_genre:'Missing genre',missing_album:'Missing album',missing_year:'Missing year'})[r.summary.target]||r.summary.target)+(r.summary.target_value?' · '+r.summary.target_value:''):'');$('#lab-pilot-cancel').disabled=!['queued','running'].includes(r.status);
  $('#lab-pilot-progress').textContent=I18n.t(r.status)+' · '+num(r.summary.done)+' / '+num(r.total)+' '+I18n.t('tracks')+' · '+num(r.summary.requests)+' '+I18n.t('requests')+' · '+num(r.summary.cache_hits)+' '+I18n.t('cached')+(r.summary.message?' · '+r.summary.message:'');
  $('#lab-pilot-summary').innerHTML=labSummary(Object.fromEntries(['tracks','done','candidate_matches','rating_available','genre_available','tags_available','year_available','service_errors'].filter(k=>r.summary[k]!=null).map(k=>[k,r.summary[k]])))+'<p class="subtle">'+r.summary.groups.map(g=>esc(g.genre)+': '+num(g.sampled)+(g.requested==null?'':' / '+num(g.requested))).join(' · ')+'</p>';
  const pilotHeader=(fields,label)=>{
    const field=fields.includes(labPilotSort)?labPilotSort:fields[0];
    const order=labPilotSort===field?(labPilotDirection==='asc'?'ascending':'descending'):'none';
    const criterion=labPilotSortChoices.find(([value])=>value===field)[1];
    return '<th scope="col" aria-sort="'+order+'"><button type="button" class="result-sort-button" data-lab-pilot-sort="'+field+'" title="'+esc(I18n.t('Sort all results by')+' '+I18n.t(criterion))+'" aria-label="'+esc(I18n.t('Sort all results by')+' '+I18n.t(criterion))+'">'+esc(I18n.t(label))+'</button></th>';
  };
  const controls='<div class="file-health-controls"><label><span>'+esc(I18n.t('Sort all results by'))+'</span><select id="lab-pilot-sort">'+labPilotSortChoices.map(([field,label])=>'<option value="'+field+'"'+(field===labPilotSort?' selected':'')+'>'+esc(I18n.t(label))+'</option>').join('')+'</select></label><label><span>'+esc(I18n.t('Sort direction'))+'</span><select id="lab-pilot-direction"><option value="asc"'+(labPilotDirection==='asc'?' selected':'')+'>'+esc(I18n.t('Ascending'))+'</option><option value="desc"'+(labPilotDirection==='desc'?' selected':'')+'>'+esc(I18n.t('Descending'))+'</option></select></label></div><p class="subtle">'+esc(I18n.t('File status uses the last File Health scan; playback buttons check current availability.'))+'</p>';
  $('#lab-pilot-results').innerHTML=controls+('<table data-sort-scope="server"><thead><tr>'+pilotHeader(['title','artist','genre'],'Local tags')+pilotHeader(['confidence','candidate','status'],'Best candidate · review required')+pilotHeader(['year','community'],'Community evidence')+pilotHeader(['file_status'],'File status')+'</tr></thead><tbody>')+r.rows.map(t=>{
    const c=t.candidates?.[0],p=t.proposal;
    return '<tr data-mb-track="'+esc(t.id)+'"><td>'+TrackPlayback.button(r.snapshot_id,t.id)+esc(t.title)+'<br><span class="subtle">'+esc(t.artist)+' · '+esc(t.genre || I18n.t("Unknown genre"))+'</span></td><td>'+(c?'<a href="https://musicbrainz.org/recording/'+encodeURIComponent(c.mbid)+'" target="_blank" rel="noopener noreferrer">'+esc(c.title)+' · '+esc(c.artist)+("</a><br><span class=\"subtle\">"+esc(I18n.t("Similarity"))+" ")+esc(c.confidence)+" "+I18n.t("· duration Δ")+" "+esc(c.duration_delta ?? I18n.t('Unknown'))+'s'+(c.version_needs_review?" "+I18n.t("· version mismatch"):'')+'</span><br><button class="button secondary" data-lab-approve="'+esc(t.id)+'" data-approved="'+(t.match_approved?'false':'true')+'">'+(t.match_approved?I18n.t("Undo identity approval"):I18n.t("Approve this identity"))+'</button>':esc(t.error || I18n.t(t.status)))+'</td><td>'+(p?'<strong>'+esc(p.community_score ?? I18n.t("No rating returned"))+'</strong> / 5 · '+num(p.votes)+(" "+I18n.t('votes')+"<br>"+esc(I18n.t("Year"))+" ")+esc(p.year ?? I18n.t('Unknown'))+' · '+esc(p.genre || I18n.t("No genre"))+'<br><span class="subtle">'+esc(I18n.t(p.year_basis))+'</span>'+(p.tags?.length?'<p class="community-tags">'+p.tags.map(tag=>esc(tag.name)+' ('+num(tag.count)+')').join(' · ')+'</p>':'')+(t.match_approved?'<div class="lab-actions">'+(['year','genre'].filter(f=>p[f]!=null).map(f=>'<button class="text-button" data-lab-proposal="'+esc(t.id)+'" data-field="'+f+("\">"+esc(I18n.t("Stage"))+" "+"")+f+': '+esc(p[f])+'</button>').join(''))+'</div>':''):'—')+'</td><td class="lab-pilot-file-status" data-file-status="'+esc(t.file_status)+'">'+pilotFileStatus(t.file_status)+'</td></tr>';
  }).join('')+'</tbody></table>';
  $('#lab-pilot-count').textContent=num(r.total)+" "+I18n.t("selected tracks ·")+" "+num(labPilotOffset+1)+'–'+num(Math.min(labPilotOffset+50,r.total));$('#lab-pilot-prev').disabled=!labPilotOffset;$('#lab-pilot-next').disabled=labPilotOffset+50>=r.total;
  $('#lab-pilot-sort').onchange=wrap(async()=>{
    labPilotSort=$('#lab-pilot-sort').value;labPilotOffset=0;rememberPilotSort();
    await labLoadPilot();$('#lab-pilot-sort')?.focus({preventScroll:true});
  });
  $('#lab-pilot-direction').onchange=wrap(async()=>{
    labPilotDirection=$('#lab-pilot-direction').value;labPilotOffset=0;rememberPilotSort();
    await labLoadPilot();$('#lab-pilot-direction')?.focus({preventScroll:true});
  });
  $('#lab-pilot-results').querySelectorAll('[data-lab-pilot-sort]').forEach(button=>button.onclick=wrap(async()=>{
    const field=button.dataset.labPilotSort;
    if(field===labPilotSort)labPilotDirection=labPilotDirection==='asc'?'desc':'asc';
    else{labPilotSort=field;labPilotDirection='asc';}
    labPilotOffset=0;rememberPilotSort();
    await labLoadPilot();
    $('#lab-pilot-results [data-lab-pilot-sort="'+field+'"]')?.focus({preventScroll:true});
  }));
  $$('[data-lab-approve]').forEach(b=>b.onclick=wrap(async()=>{await labPost('musicbrainz/'+labBatch+'/review',{track_id:b.dataset.labApprove,approved:b.dataset.approved==='true'});await labLoadPilot();}));
  $$('[data-lab-proposal]').forEach(b=>b.onclick=wrap(async()=>{
    const t=r.rows.find(t=>t.id===b.dataset.labProposal);if(r.snapshot_id!==musicBrainzSnapshot())throw new Error(I18n.t("Select the snapshot used for this pilot before staging suggestions"));
    await labPost('musicbrainz/'+labBatch+'/stage',{track_id:t.id,field:b.dataset.field});notify(I18n.t("Proposed")+" "+b.dataset.field+" "+I18n.t("staged after identity approval"));await labLoadTracks();
  }));
  return r;
}
// Saved scan evidence stays consistent with server sorting; live probes only update playback buttons.
$('#lab-pilot-start').onclick=wrap(async()=>{
  $('#lab-pilot-start').disabled=true;
  try{await labPost('musicbrainz/'+labBatch+'/start',{query_consent:$('#lab-pilot-consent').checked});await BackgroundPilot.refresh();await labLoadPilot();}
  finally{labPilotButtons();}
});
$('#lab-pilot-cancel').onclick=wrap(async()=>{if(labBatch)await labPost('musicbrainz/'+labBatch+'/cancel',{});});
$('#lab-pilot-prev').onclick=wrap(async()=>{labPilotOffset=Math.max(0,labPilotOffset-50);await labLoadPilot();});
$('#lab-pilot-next').onclick=wrap(async()=>{labPilotOffset+=50;await labLoadPilot();});
labBatch=preferences.get('workbench-lab-batch');
