/* A single-track file view. Comments stage freely; other fields require unlock. */
let trackDetailState=null;
async function openTrackDetails(snapshot,trackId){
  const record=await api('/api/lab/track?'+new URLSearchParams({snapshot,track_id:trackId}));
  trackDetailState={snapshot,trackId,record};const t=record.original;
  $('#track-detail-title').textContent=t.title || 'Untitled track';
  $('#track-detail-scope').textContent=record.snapshot_label+' · '+record.scope+' · '+(record.scope.startsWith('session:')?'Working edits attach to prepared XML/ZIP copies from this workspace.':'Source-snapshot edits remain local to this scope; they do not attach to a different XML/ZIP workspace.');
  $('#track-detail-metadata').innerHTML=[['Artist',t.artist || 'Unknown'],['Album',t.album || 'Unknown'],['Saved genre',t.genre || 'Unknown'],['Tonality',t.tonality || 'Unknown'],['BPM',insightValue(t.bpm)],['Duration',insightDuration(t.duration)],['Track colour',t.color_name || (t.color_status==='unassigned'?'No assigned colour':'Not captured')],['Saved play count',insightValue(t.play_count)]].map(([label,value])=>'<div><span>'+esc(label)+'</span><b>'+esc(value)+'</b></div>').join('');
  $('#track-comments-panel').open=false;$('#track-advanced-panel').open=false;
  $('#track-comment-text').value=record.overrides.comment?.value ?? t.comment ?? '';
  $('#track-comment-provenance').textContent=(record.comment_captured?'Captured comment is available.':'The original comment was not captured. You can keep a working comment here; a fresh matching capture is needed before safely applying it to source-derived exports.')+' Comments are excluded from insight tables, CSV and shareable HTML. Rekordbox can append My Tags to comments; retain any text you want to preserve.';
  $('#track-comment-reset').disabled=!record.overrides.comment;
  $('#track-comment-state').textContent='Comments are editable without unlocking other fields. Saving stages a local working value; source files and audio tags stay unchanged.';
  $('#track-detail-fields').innerHTML=record.editable_fields.map(field=>{
    const value=record.overrides[field]?.value ?? t[field];
    return '<label>'+esc(field)+'<input data-track-edit-field="'+esc(field)+'" '+(['rating','year'].includes(field)?'type="number" step="1" '+(field==='rating'?'min="0" max="5"':'min="1000" max="'+(new Date().getFullYear()+1)+'"'):'maxlength="255"')+' value="'+esc(value ?? '')+'" '+(!record.unlocked?'disabled':'')+'><small class="subtle">Captured: '+esc(t[field] ?? 'Unknown')+'</small>'+(record.overrides[field]?'<button type="button" class="text-button" data-track-field-reset="'+esc(field)+'" '+(!record.unlocked?'disabled':'')+'>Reset override</button>':'')+'</label>';
  }).join('');$('#track-detail-unlock').checked=record.unlocked;$('#track-detail-save').disabled=!record.unlocked;$('#track-detail-edit-state').textContent='Other fields start locked. Changes are staged for generated copies only.';
  $$('[data-track-field-reset]').forEach(button=>button.onclick=wrap(async()=>{
    await api('/api/lab/overrides',{method:'DELETE',body:JSON.stringify({snapshot,track_id:trackId,field:button.dataset.trackFieldReset})});
    $('[data-track-edit-field="'+button.dataset.trackFieldReset+'"]').value=t[button.dataset.trackFieldReset] ?? '';delete record.overrides[button.dataset.trackFieldReset];button.hidden=true;notify('Restored the captured field value');
  }));
  if(!$('#track-detail-dialog').open)$('#track-detail-dialog').showModal();
}
function bindTrackDetails(selector,snapshot){
  $$(selector+' [data-insight-open]').forEach(button=>button.onclick=wrap(()=>openTrackDetails(snapshot,button.dataset.insightOpen)));
}
async function openWorkspaceTrack(trackId){
  if(!session)throw new Error('Load a workspace to inspect this track');
  const info=await api('/api/lab');let saved=info.snapshots.find(s=>s.scope_key==='session:'+session.id);
  if(!saved){
    if(busy)throw new Error('Wait for the current operation before capturing a track snapshot');
    const r=await labPost('snapshots',{source:'session',label:'Track details · loaded collection'});saved=await poll(r.job);
  }
  await openTrackDetails(saved.id,trackId);
}
$('#track-comment-save').onclick=wrap(async()=>{
  const s=trackDetailState;if(!s)return;
  const r=await labPost('overrides',{snapshot:s.snapshot,track_id:s.trackId,field:'comment',value:$('#track-comment-text').value});
  s.record.overrides.comment={value:r.value};$('#track-comment-reset').disabled=false;
  $('#track-comment-state').textContent='Working comment saved locally. It will be retained when temporary inputs are cleaned up. Source files remain unchanged.';notify('Working comment saved');
});
$('#track-comment-reset').onclick=wrap(async()=>{
  const s=trackDetailState;if(!s)return;
  await api('/api/lab/overrides',{method:'DELETE',body:JSON.stringify({snapshot:s.snapshot,track_id:s.trackId,field:'comment'})});
  delete s.record.overrides.comment;$('#track-comment-text').value=s.record.original.comment ?? '';$('#track-comment-reset').disabled=true;$('#track-comment-state').textContent='Working override removed; the captured comment is restored.';
});
$('#track-detail-unlock').onchange=wrap(async()=>{
  const s=trackDetailState;if(!s)return;const r=await labPost('unlock',{snapshot:s.snapshot,unlocked:$('#track-detail-unlock').checked});s.record.unlocked=r.unlocked;
  for(const input of $$('[data-track-edit-field],[data-track-field-reset]'))input.disabled=!r.unlocked;
  $('#track-detail-save').disabled=!r.unlocked;$('#track-detail-edit-state').textContent=r.unlocked?'Staging unlocked for this snapshot scope. Review edited metadata before generating copies.':'Other metadata is locked. Comments remain editable.';
});
$('#track-detail-edit-form').onsubmit=wrap(async event=>{
  event.preventDefault();const s=trackDetailState;if(!s || !s.record.unlocked)return;let count=0;
  for(const input of $$('[data-track-edit-field]')){
    const field=input.dataset.trackEditField,previous=s.record.overrides[field]?.value ?? s.record.original[field];
    if(String(previous ?? '')===input.value)continue;
    const r=await labPost('overrides',{snapshot:s.snapshot,track_id:s.trackId,field,value:input.value});s.record.overrides[field]={value:r.value};count++;
  }
  $('#track-detail-edit-state').textContent=num(count)+' field changes staged locally. Insights continue to show captured values; working edits remain separate.';notify(num(count)+' metadata changes staged');
});
