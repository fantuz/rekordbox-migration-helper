/* A single-track file view. Comments stage freely; other fields require unlock. */
let trackDetailState=null;
async function openTrackDetails(snapshot,trackId){
  const record=await api('/api/lab/track?'+new URLSearchParams({snapshot,track_id:trackId}));
  trackDetailState={snapshot,trackId,record};const t=record.original;
  $('#track-detail-title').textContent=t.title || I18n.t("Untitled track");
  $('#track-detail-scope').textContent=record.snapshot_label+' · '+record.scope+' · '+(record.scope.startsWith('session:')?I18n.t("Working edits attach to prepared XML/ZIP copies from this workspace."):I18n.t("Source-snapshot edits remain local to this scope; they do not attach to a different XML/ZIP workspace."));
  $('#track-detail-metadata').innerHTML=[[I18n.t("Artist"),t.artist || I18n.t("Unknown")],[I18n.t("Album"),t.album || I18n.t("Unknown")],[I18n.t("Saved genre"),t.genre || I18n.t("Unknown")],[I18n.t("Tonality"),t.tonality || I18n.t("Unknown")],['BPM',insightValue(t.bpm)],[I18n.t("Duration"),insightDuration(t.duration)],[I18n.t("Track colour"),t.color_name || (t.color_status==='unassigned'?I18n.t("No assigned colour"):I18n.t("Not captured"))],[I18n.t("Saved play count"),insightValue(t.play_count)]].map(([label,value])=>'<div><span>'+esc(label)+'</span><b>'+esc(value)+'</b></div>').join('');
  $('#track-comments-panel').open=false;$('#track-advanced-panel').open=false;
  $('#track-comment-text').value=record.overrides.comment?.value ?? t.comment ?? '';
  $('#track-comment-provenance').textContent=(record.comment_captured?I18n.t("Original comment captured."):I18n.t("Original comment not captured. Recapture matching inputs before applying this working comment to an export."))+" "+I18n.t("Comments are excluded from insight tables, CSV and shareable HTML. Rekordbox can append My Tags to comments; retain any text you want to preserve.");
  $('#track-comment-reset').disabled=!record.overrides.comment;
  $('#track-comment-state').textContent=I18n.t("Comments stage locally without unlocking other fields. Originals and audio tags remain unchanged.");
  $('#track-detail-fields').innerHTML=record.editable_fields.map(field=>{
    const value=record.overrides[field]?.value ?? t[field];
    return '<label>'+esc(I18n.field(field))+'<input data-track-edit-field="'+esc(field)+'" '+(['rating','year'].includes(field)?'type="number" step="1" '+(field==='rating'?'min="0" max="5"':'min="1000" max="'+(new Date().getFullYear()+1)+'"'):'maxlength="255"')+' value="'+esc(value ?? '')+'" '+(!record.unlocked?'disabled':'')+("><small class=\"subtle\">"+esc(I18n.t("Captured:"))+" ")+esc(t[field] ?? I18n.t("Unknown"))+'</small>'+(record.overrides[field]?'<button type="button" class="text-button" data-track-field-reset="'+esc(field)+'" '+(!record.unlocked?'disabled':'')+(">"+esc(I18n.t("Reset override"))+"</button>"):'')+'</label>';
  }).join('');$('#track-detail-unlock').checked=record.unlocked;$('#track-detail-save').disabled=!record.unlocked;$('#track-detail-edit-state').textContent=I18n.t("Other fields start locked. Changes are staged for generated copies only.");
  $$('[data-track-field-reset]').forEach(button=>button.onclick=wrap(async()=>{
    await api('/api/lab/overrides',{method:'DELETE',body:JSON.stringify({snapshot,track_id:trackId,field:button.dataset.trackFieldReset})});
    $('[data-track-edit-field="'+button.dataset.trackFieldReset+'"]').value=t[button.dataset.trackFieldReset] ?? '';delete record.overrides[button.dataset.trackFieldReset];button.hidden=true;notify(I18n.t("Restored the captured field value"));
  }));
  if(!$('#track-detail-dialog').open)$('#track-detail-dialog').showModal();
}
function bindTrackDetails(selector,snapshot){
  $$(selector+' [data-insight-open]').forEach(button=>button.onclick=wrap(()=>openTrackDetails(snapshot,button.dataset.insightOpen)));
}
async function openWorkspaceTrack(trackId){
  if(!session)throw new Error(I18n.t("Load a workspace to inspect this track"));
  const info=await api('/api/lab');let saved=info.snapshots.find(s=>s.scope_key==='session:'+session.id);
  if(!saved){
    if(busy)throw new Error(I18n.t("Wait for the current operation before capturing a track snapshot"));
    const r=await labPost('snapshots',{source:'session',get label(){return I18n.t("Track details · loaded collection");}});saved=await poll(r.job);
  }
  await openTrackDetails(saved.id,trackId);
}
$('#track-comment-save').onclick=wrap(async()=>{
  const s=trackDetailState;if(!s)return;
  const r=await labPost('overrides',{snapshot:s.snapshot,track_id:s.trackId,field:'comment',value:$('#track-comment-text').value});
  s.record.overrides.comment={value:r.value};$('#track-comment-reset').disabled=false;
  $('#track-comment-state').textContent=I18n.t("Comment saved locally and retained after temporary-file cleanup.");notify(I18n.t("Working comment saved"));
});
$('#track-comment-reset').onclick=wrap(async()=>{
  const s=trackDetailState;if(!s)return;
  await api('/api/lab/overrides',{method:'DELETE',body:JSON.stringify({snapshot:s.snapshot,track_id:s.trackId,field:'comment'})});
  delete s.record.overrides.comment;$('#track-comment-text').value=s.record.original.comment ?? '';$('#track-comment-reset').disabled=true;$('#track-comment-state').textContent=I18n.t("Working override removed; the captured comment is restored.");
});
$('#track-detail-unlock').onchange=wrap(async()=>{
  const s=trackDetailState;if(!s)return;const r=await labPost('unlock',{snapshot:s.snapshot,unlocked:$('#track-detail-unlock').checked});s.record.unlocked=r.unlocked;
  for(const input of $$('[data-track-edit-field],[data-track-field-reset]'))input.disabled=!r.unlocked;
  $('#track-detail-save').disabled=!r.unlocked;$('#track-detail-edit-state').textContent=r.unlocked?I18n.t("Staging unlocked for this snapshot scope. Review edited metadata before generating copies."):I18n.t("Other metadata is locked. Comments remain editable.");
});
$('#track-detail-edit-form').onsubmit=wrap(async event=>{
  event.preventDefault();const s=trackDetailState;if(!s || !s.record.unlocked)return;let count=0;
  for(const input of $$('[data-track-edit-field]')){
    const field=input.dataset.trackEditField,previous=s.record.overrides[field]?.value ?? s.record.original[field];
    if(String(previous ?? '')===input.value)continue;
    const r=await labPost('overrides',{snapshot:s.snapshot,track_id:s.trackId,field,value:input.value});s.record.overrides[field]={value:r.value};count++;
  }
  $('#track-detail-edit-state').textContent=num(count)+" "+I18n.t("field changes staged locally. Insights continue to show captured values; working edits remain separate.");notify(num(count)+" "+I18n.t("metadata changes staged"));
});
