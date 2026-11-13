/* All library-derived strings are escaped; mutations use the local action token. */
let labInfo=null,labReport=null,labReportOffset=0,labTrackOffset=0,labTrackRows=[],labEdited=null,labUnlocked=false;
let labBatch=null,labPilotOffset=0,labPilotTimer=null;
const labPost=(url,data)=>api('/api/lab/'+url,{method:'POST',body:JSON.stringify(data)});
const labSnapshot=()=>$('#lab-snapshot').value;
const labSummary=data=>'<div class="lab-summary">'+Object.entries(data || {}).filter(([,v])=>v===null || typeof v!=='object').map(([k,v])=>'<div><span>'+esc(k.replaceAll('_',' '))+'</span><b>'+esc(v===null?'Unknown':v===true?'Yes':v===false?'No':v)+'</b></div>').join('')+'</div>';
function labSelect(selector,items,label,empty='Choose a snapshot') {
  const el=$(selector),old=el.value;el.innerHTML='<option value="">'+esc(empty)+'</option>'+items.map(r=>'<option value="'+esc(r.id)+'">'+esc(label(r))+'</option>').join('');
  if(items.some(r=>r.id===old))el.value=old;
}
async function loadLab() {
  labInfo=await api('/api/lab');
  const sources=[...(labInfo.workspace?[{id:'session',label:'Loaded XML + ZIP workspace'},{id:'orphans',label:'Unreferenced local tags (scan Media inventory first)'}]:[]),...labInfo.sources.map(r=>({...r,label:'Source capture · '+date(r.created)+' · '+r.label}))];
  labSelect('#lab-source',sources,r=>r.label,'Choose input capture');
  const label=r=>r.label+' · '+new Date(r.created).toLocaleString();
  for(const selector of ['#lab-snapshot','#lab-before','#lab-after'])labSelect(selector,labInfo.snapshots,label);
  if(!labSnapshot() && labInfo.snapshots.length)$('#lab-snapshot').value=labInfo.snapshots[0].id;
  labSelect('#lab-report-select',labInfo.reports,r=>r.kind+' · '+new Date(r.created).toLocaleString(),'Choose an evidence report');
  $('#lab-pilot-enabled').checked=labInfo.musicbrainz_enabled;$('#lab-pilot-enabled').disabled=labInfo.musicbrainz_forced_off;
  labPilotButtons();await labSnapshotChanged(false);
  if(typeof renderDiscoveryHints==='function')await renderDiscoveryHints();
}
async function labSnapshotChanged(clear=true) {
  const s=labInfo.snapshots.find(r=>r.id===labSnapshot());
  $('#lab-snapshot-info').textContent=s?'Scope: '+s.scope_key+' · Original snapshots remain immutable. '+(s.scope_key.startsWith('session:')?'Staged edits apply to copy exports from this same workspace.':'Edits apply to offline HTML; they do not attach to a different XML/ZIP workspace.'):'Save a snapshot from a loaded workspace or Source analyzer capture.';
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
$('#lab-capture-form').onsubmit=wrap(async e=>{e.preventDefault();const r=await labRun('snapshots',{source:$('#lab-source').value,label:$('#lab-label').value});$('#lab-snapshot').value=r.id;await labSnapshotChanged();notify('Immutable snapshot saved locally');});
$('#lab-snapshot').onchange=wrap(()=>labSnapshotChanged());
for(const kind of ['consistency','coverage','assets'])$('#lab-'+kind).onclick=wrap(()=>labRun('check',{snapshot:labSnapshot(),kind,working:$('#lab-working').checked,min_cues:$('#lab-min-cues').value,min_manual:$('#lab-min-manual').value,require_analysis:$('#lab-analysis-required').checked,paths:pathLines($('#lab-assets-path').value),verify:$('#lab-assets-verify').checked}));
$('#lab-compare-form').onsubmit=wrap(async e=>{e.preventDefault();await labRun('compare',{before:$('#lab-before').value,after:$('#lab-after').value,tolerance_ms:$('#lab-tolerance').value});});

async function labLoadReport() {
  const id=$('#lab-report-select').value;if(!id)return;
  const section=$('#lab-report-section').value,q=$('#lab-report-search').value;
  labReport=await api('/api/lab/reports/'+encodeURIComponent(id)+'?'+new URLSearchParams({offset:labReportOffset,section,q}));
  $('#lab-report-summary').innerHTML=labSummary(labReport.summary);
  const summary=labReport.summary;
  if(summary.scopes)$('#lab-report-summary').insertAdjacentHTML('beforeend','<h4>Inspected locations</h4>'+summary.scopes.map(r=>'<p class="subtle">'+esc(r.kind)+' · <code>'+esc(r.path)+'</code></p>').join('')+'<div class="lab-table"><table><thead><tr><th>Analysis extension</th><th>Files</th><th>Logical size</th></tr></thead><tbody>'+summary.analysis_extensions.map(r=>'<tr><td>'+esc(r.extension)+'</td><td>'+num(r.files)+'</td><td>'+esc(bytes(r.bytes))+'</td></tr>').join('')+'</tbody></table></div>');
  if(summary.stems)$('#lab-report-summary').insertAdjacentHTML('beforeend','<div class="stems-summary"><h3>STEMS evidence</h3><p>'+esc(summary.stems.preparation_status)+'</p>'+labSummary({prepared_tracks:summary.stems.prepared_tracks,related_candidate_files:summary.stems.related_candidate_files,rbsc_drum_capture_files:summary.stems.rbsc_drum_capture_files})+'<p>Related candidate file size: '+esc(bytes(summary.stems.related_candidate_bytes))+'. '+esc(summary.stems.note)+'</p></div>');
  if(summary.scope_warnings?.length)$('#lab-report-summary').insertAdjacentHTML('beforeend',summary.scope_warnings.map(w=>'<p class="subtle">'+esc(w)+'</p>').join(''));
  $('#lab-report-section').innerHTML='<option value="">All findings</option>'+labReport.sections.map(r=>'<option value="'+esc(r.section)+'">'+esc(r.section.replaceAll('_',' '))+' · '+num(r.count)+'</option>').join('');$('#lab-report-section').value=section;
  $('#lab-report-download').hidden=false;$('#lab-report-download').href='/api/lab/reports/'+encodeURIComponent(id)+'/download';
  $('#lab-report-rows').innerHTML='<table><thead><tr><th>Finding</th><th>Track / group</th><th>Evidence</th></tr></thead><tbody>'+labReport.rows.map((r,i)=>'<tr><td>'+esc(r.section.replaceAll('_',' '))+'</td><td><strong>'+esc(r.title || r.playlist || r.name || 'Group')+'</strong><br><span class="subtle">'+esc(r.artist || '')+'</span></td><td>'+esc(r.detail)+'<details><summary>Show evidence</summary><pre>'+esc(JSON.stringify(r,null,2))+'</pre></details>'+(r.section==='variant'?'<button class="button secondary" data-lab-normalize="'+i+'">Stage '+num(r.track_ids.length)+' as “'+esc(r.canonical)+'”</button>':'')+'</td></tr>').join('')+'</tbody></table>';
  $('#lab-report-count').textContent=num(labReport.total)+' findings · '+num(labReportOffset+1)+'–'+num(Math.min(labReportOffset+50,labReport.total));
  $('#lab-report-prev').disabled=labReportOffset===0;$('#lab-report-next').disabled=labReportOffset+50>=labReport.total;
  $$('[data-lab-normalize]').forEach(b=>b.onclick=wrap(async()=>{
    const r=labReport.rows[Number(b.dataset.labNormalize)];
    if(labReport.sources[0]!==labSnapshot())throw new Error('Select the snapshot used by this report before staging normalization');
    const result=await labPost('normalize',{snapshot:labSnapshot(),track_ids:r.track_ids,field:r.field,value:r.canonical});
    await labLoadTracks();notify(num(result.count)+' field overrides staged; reset individual fields in Metadata editor');
  }));
}
$('#lab-report-select').onchange=wrap(async()=>{labReportOffset=0;$('#lab-report-section').value='';await labLoadReport();});
for(const id of ['#lab-report-section','#lab-report-find'])$(id)[id.endsWith('section')?'onchange':'onclick']=wrap(async()=>{labReportOffset=0;await labLoadReport();});
$('#lab-report-prev').onclick=wrap(async()=>{labReportOffset=Math.max(0,labReportOffset-50);await labLoadReport();});
$('#lab-report-next').onclick=wrap(async()=>{labReportOffset+=50;await labLoadReport();});

async function labLoadTracks() {
  if(!labSnapshot())return;
  const r=await api('/api/lab/tracks?'+new URLSearchParams({snapshot:labSnapshot(),offset:labTrackOffset,q:$('#lab-track-search').value}));
  labTrackRows=r.rows;labUnlocked=r.unlocked;$('#lab-unlock').checked=labUnlocked;
  $('#lab-edit-state').textContent=(labUnlocked?'Staging unlocked':'Read-only')+' · '+num(r.override_fields)+' field overrides in this scope. Source database and audio tags stay unchanged.';
  $('#lab-tracks').innerHTML='<table><thead><tr><th>Track</th><th>Artist</th><th>Year / stars / genre</th><th></th></tr></thead><tbody>'+r.rows.map((item,i)=>{const t={...item.original,...Object.fromEntries(Object.entries(item.overrides).map(([k,v])=>[k,v.value]))};return '<tr><td>'+esc(t.title)+'<br><span class="subtle">'+esc(t.id)+'</span></td><td>'+esc(t.artist)+'</td><td>'+esc(t.year || '—')+' · '+esc(t.rating ?? 'Unknown')+' ★ · '+esc(t.genre || 'Unknown')+'</td><td><button class="button secondary" data-lab-edit="'+i+'">Inspect / edit'+(Object.keys(item.overrides).length?' · staged':'')+'</button></td></tr>';}).join('')+'</tbody></table>';
  $('#lab-tracks-count').textContent=num(r.total)+' tracks · '+num(labTrackOffset+1)+'–'+num(Math.min(labTrackOffset+30,r.total));$('#lab-tracks-prev').disabled=!labTrackOffset;$('#lab-tracks-next').disabled=labTrackOffset+30>=r.total;
  $$('[data-lab-edit]').forEach(b=>b.onclick=()=>labEdit(labTrackRows[Number(b.dataset.labEdit)]));
  if(labEdited){const updated=r.rows.find(t=>t.original.id===labEdited.original.id);if(updated)labEdit(updated);else $('#lab-edit-save').disabled=!labUnlocked;}
}
function labEdit(item) {
  labEdited=item;$('#lab-edit-form').hidden=false;$('#lab-edit-title').textContent=item.original.title+' · '+item.original.id;
  $('#lab-edit-fields').innerHTML=labInfo.fields.map(field=>{
    const edit=item.overrides[field],value=edit?edit.value:item.original[field];
    return '<label>'+esc(field)+'<input data-lab-field="'+field+'" '+(['rating','year'].includes(field)?'type="number" step="1" '+(field==='rating'?'min="0" max="5"':'min="1000" max="'+(new Date().getFullYear()+1)+'"'):'maxlength="255"')+' value="'+esc(value ?? '')+'" '+(!labUnlocked?'disabled':'')+'><small class="subtle">Captured: '+esc(item.original[field] ?? 'Unknown')+'</small>'+(edit?'<button class="text-button" type="button" data-lab-reset="'+field+'" '+(!labUnlocked?'disabled':'')+'>Reset override</button>':'')+'</label>';
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
  await labLoadTracks();notify(num(count)+' field changes staged locally');
});
$('#lab-track-find').onclick=wrap(async()=>{labTrackOffset=0;await labLoadTracks();});
$('#lab-tracks-prev').onclick=wrap(async()=>{labTrackOffset=Math.max(0,labTrackOffset-30);await labLoadTracks();});
$('#lab-tracks-next').onclick=wrap(async()=>{labTrackOffset+=30;await labLoadTracks();});
$('#lab-html').onclick=wrap(async()=>{
  const r=await labPost('offline-export',{snapshot:labSnapshot(),working:$('#lab-html-working').checked});const result=await poll(r.job);
  $('#lab-html-result').innerHTML='<p>Offline explorer saved. <a class="button secondary" href="/api/quick-export/'+esc(result.id)+'/html">HTML ↓</a> <a class="button secondary" href="/api/quick-export/'+esc(result.id)+'/zip">Minisite ZIP ↓</a></p>';
});

function labPilotButtons() {
  $('#lab-pilot-start').disabled=!labBatch || !$('#lab-pilot-enabled').checked || !$('#lab-pilot-consent').checked;
}
$('#lab-pilot-consent').onchange=labPilotButtons;
$('#lab-pilot-enabled').onchange=wrap(async()=>{try{const r=await labPost('features',{musicbrainz_enabled:$('#lab-pilot-enabled').checked});$('#lab-pilot-enabled').checked=r.musicbrainz_enabled;}finally{labPilotButtons();}});
$('#lab-pilot-preview').onclick=wrap(async()=>{
  const r=await labPost('musicbrainz/preview',{snapshot:labSnapshot(),top_genres:$('#lab-pilot-top').value,seed:$('#lab-pilot-seed').value,speed:$('#lab-pilot-speed').value});labBatch=r.id;labPilotOffset=0;
  localStorage.setItem('workbench-lab-batch',labBatch);$('#lab-pilot-consent').checked=false;await labLoadPilot();labPilotButtons();
});
async function labLoadPilot() {
  if(!labBatch)return;
  const r=await api('/api/lab/musicbrainz/'+encodeURIComponent(labBatch)+'?offset='+labPilotOffset);
  $('#lab-pilot-progress').textContent=r.status+' · '+num(r.summary.done)+' / '+num(r.total)+' tracks · '+num(r.summary.requests)+' requests · '+num(r.summary.cache_hits)+' cached'+(r.summary.message?' · '+r.summary.message:'');
  $('#lab-pilot-summary').innerHTML=labSummary(r.summary)+'<p class="subtle">'+r.summary.groups.map(g=>esc(g.genre)+': '+num(g.sampled)+' / '+num(g.requested)).join(' · ')+'</p>';
  $('#lab-pilot-results').innerHTML='<table><thead><tr><th>Local tags</th><th>Best candidate · review required</th><th>Community evidence</th></tr></thead><tbody>'+r.rows.map(t=>{
    const c=t.candidates?.[0],p=t.proposal;
    return '<tr><td>'+esc(t.title)+'<br><span class="subtle">'+esc(t.artist)+' · '+esc(t.genre || 'Unknown genre')+'</span></td><td>'+(c?'<a href="https://musicbrainz.org/recording/'+encodeURIComponent(c.mbid)+'" target="_blank" rel="noopener noreferrer">'+esc(c.title)+' · '+esc(c.artist)+'</a><br><span class="subtle">Similarity '+esc(c.confidence)+' · duration Δ '+esc(c.duration_delta ?? 'unknown')+'s'+(c.version_needs_review?' · version mismatch':'')+'</span><br><button class="button secondary" data-lab-approve="'+esc(t.id)+'" data-approved="'+(t.match_approved?'false':'true')+'">'+(t.match_approved?'Undo identity approval':'Approve this identity')+'</button>':esc(t.error || t.status))+'</td><td>'+(p?'<strong>'+esc(p.community_score ?? 'No rating')+'</strong> / 5 · '+num(p.votes)+' votes<br>Year '+esc(p.year ?? 'unknown')+' · '+esc(p.genre || 'No genre')+'<br><span class="subtle">'+esc(p.year_basis)+'</span>'+(t.match_approved?'<div class="lab-actions">'+(['year','genre'].filter(f=>p[f]!=null).map(f=>'<button class="text-button" data-lab-proposal="'+esc(t.id)+'" data-field="'+f+'">Stage '+f+': '+esc(p[f])+'</button>').join(''))+'</div>':''):'—')+'</td></tr>';
  }).join('')+'</tbody></table>';
  $('#lab-pilot-count').textContent=num(r.total)+' selected tracks · '+num(labPilotOffset+1)+'–'+num(Math.min(labPilotOffset+50,r.total));$('#lab-pilot-prev').disabled=!labPilotOffset;$('#lab-pilot-next').disabled=labPilotOffset+50>=r.total;
  $$('[data-lab-approve]').forEach(b=>b.onclick=wrap(async()=>{await labPost('musicbrainz/'+labBatch+'/review',{track_id:b.dataset.labApprove,approved:b.dataset.approved==='true'});await labLoadPilot();}));
  $$('[data-lab-proposal]').forEach(b=>b.onclick=wrap(async()=>{
    const t=r.rows.find(t=>t.id===b.dataset.labProposal);if(r.snapshot_id!==labSnapshot())throw new Error('Select the snapshot used for this pilot before staging suggestions');
    await labPost('musicbrainz/'+labBatch+'/stage',{track_id:t.id,field:b.dataset.field});notify('Proposed '+b.dataset.field+' staged after identity approval');await labLoadTracks();
  }));
  return r;
}
$('#lab-pilot-start').onclick=wrap(async()=>{
  const r=await labPost('musicbrainz/'+labBatch+'/start',{query_consent:$('#lab-pilot-consent').checked});$('#lab-pilot-cancel').disabled=false;$('#lab-pilot-start').disabled=true;
  clearInterval(labPilotTimer);labPilotTimer=setInterval(()=>labLoadPilot().catch(error=>notify(error.message,true)),2500);
  try{
    while(true){
      const task=await api('/api/tasks/'+r.job);
      if(task.status==='error')throw new Error(task.message);
      if(task.status==='complete'){notify('MusicBrainz pilot '+task.result.status);break;}
      await new Promise(resolve=>setTimeout(resolve,1500));
    }
  }finally{clearInterval(labPilotTimer);await labLoadPilot();$('#lab-pilot-cancel').disabled=true;labPilotButtons();}
});
$('#lab-pilot-cancel').onclick=wrap(async()=>{if(labBatch)await labPost('musicbrainz/'+labBatch+'/cancel',{});});
$('#lab-pilot-prev').onclick=wrap(async()=>{labPilotOffset=Math.max(0,labPilotOffset-50);await labLoadPilot();});
$('#lab-pilot-next').onclick=wrap(async()=>{labPilotOffset+=50;await labLoadPilot();});
labBatch=localStorage.getItem('workbench-lab-batch');if(labBatch)labLoadPilot().catch(()=>{labBatch=null;localStorage.removeItem('workbench-lab-batch');});
