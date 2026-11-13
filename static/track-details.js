/* A single-track file view. Comments and colours stage in the private sidecar. */
let trackDetailState=null,trackDetailRevision=0;
const trackHasOverride=(record,field)=>Object.hasOwn(record.overrides,field);
function trackColourValue(record){return trackHasOverride(record,'colour')?record.overrides.colour.value:record.original.colour;}
function trackPaletteLabel(item){return I18n.t(item.name)+(item.native_name && item.native_name!==item.name?' · '+item.native_name:'');}
function trackColourLabel(record,value){
  if(value==='')return I18n.t('No assigned colour');
  if(value===null || value===undefined)return I18n.t('Not captured');
  const option=(record.colour_palette || []).find(item=>item.value===value);
  return option?trackPaletteLabel(option):String(value);
}
function renderTrackWorkingEdits(s){
  if(trackDetailState!==s)return;
  const entries=Object.entries(s.record.overrides);
  $('#track-working-count').textContent=num(entries.length);
  $('#track-working-empty').hidden=Boolean(entries.length);
  $('#track-working-list').innerHTML=entries.map(([field,edit])=>{
    const value=field==='colour'?trackColourLabel(s.record,edit.value):String(edit.value ?? '');
    return '<li><b>'+esc(field==='colour'?I18n.t('Track colour'):I18n.field(field))+'</b><span>'+esc(value || I18n.t('Empty value'))+'</span></li>';
  }).join('');
}
function renderTrackColour(s){
  if(trackDetailState!==s)return;
  const r=s.record,value=trackColourValue(r),editable=r.colour_editable===true;
  $('#track-colour-palette').innerHTML=(r.colour_palette || []).map(item=>{
    const supported=editable && item.supported!==false,selected=value===item.value;
    const hex=/^#[0-9a-f]{6}$/i.test(item.hex || '')?item.hex:null;
    return '<button type="button" class="track-colour-choice" data-track-colour="'+esc(item.value)+'" aria-pressed="'+selected+'"'+(!supported || s.saving?' disabled':'')+(item.reason?' title="'+esc(item.reason)+'"':'')+'><span class="track-colour-swatch'+(hex?'':' unassigned')+'" aria-hidden="true"'+(hex?' style="--track-colour:'+hex+'"':'')+'></span><span>'+esc(trackPaletteLabel(item))+'</span><span class="track-colour-check" aria-hidden="true">'+(selected?'✓':'')+'</span></button>';
  }).join('');
  $('#track-colour-reset').disabled=s.saving || !trackHasOverride(r,'colour');
  $('#track-colour-original').textContent=I18n.t('Captured:')+' '+(r.original.color_name || trackColourLabel(r,r.original.colour));
  $('#track-colour-state').textContent=s.saving?I18n.t('Saving working edits…'):!editable?r.colour_edit_reason || I18n.t('Track colour is unavailable for this snapshot.'):trackHasOverride(r,'colour')?I18n.t('Track colour saved locally. It will be reviewed with the export.')+' '+trackColourLabel(r,value):I18n.t('Choose a colour to save a working edit. No unlock is required.');
  $('#track-colour-palette').setAttribute('aria-busy',String(s.saving));
}
function renderTrackCommentState(s){
  if(trackDetailState!==s)return;
  const saved=s.record.overrides.comment?.value ?? s.record.original.comment ?? '';
  const draft=$('#track-comment-text').value!==saved;
  $('#track-comment-reset').disabled=s.saving || !trackHasOverride(s.record,'comment');
  $('#track-comment-save').disabled=s.saving || !draft;
  $('#track-comment-state').textContent=draft?I18n.t('Unsaved comment changes'):trackHasOverride(s.record,'comment')?I18n.t('Comment saved locally and retained after temporary-file cleanup.'):I18n.t('Comments stage locally without unlocking other fields. Originals and audio tags remain unchanged.');
}
async function trackStoreEdit(s,field,value,reset=false){
  if(s.saving)return false;
  const focusedColour=document.activeElement?.dataset.trackColour;
  s.saving=true;renderTrackColour(s);renderTrackCommentState(s);
  try{
    const body={snapshot:s.snapshot,track_id:s.trackId,field};
    const result=reset?await api('/api/lab/overrides',{method:'DELETE',body:JSON.stringify(body)}):await labPost('overrides',{...body,value});
    if(result.overrides)s.record.overrides=result.overrides;
    else if(reset)delete s.record.overrides[field];
    else s.record.overrides[field]={value:result.value};
    renderTrackWorkingEdits(s);
    // Refresh export counters without reopening the editor or replacing its drafts.
    const status=await api('/api/status');
    if(session && status.session?.id===session.id){session=status.session;renderSession();}
    return true;
  }finally{
    s.saving=false;renderTrackColour(s);renderTrackCommentState(s);
    if(trackDetailState===s && focusedColour!==undefined && $('#track-detail-dialog').open){
      const choice=[...$('#track-colour-palette').querySelectorAll('[data-track-colour]')].find(button=>button.dataset.trackColour===focusedColour);
      choice?.focus({preventScroll:true});
    }
  }
}
async function openTrackDetails(snapshot,trackId){
  const revision=++trackDetailRevision;
  const record=await api('/api/lab/track?'+new URLSearchParams({snapshot,track_id:trackId}));
  if(revision!==trackDetailRevision)return;
  const s=trackDetailState={snapshot,trackId,record,saving:false};const t=record.original;
  $('#track-detail-title').textContent=t.title || I18n.t("Untitled track");
  $('#track-detail-scope').textContent=record.snapshot_label+' · '+record.scope+' · '+(record.scope.startsWith('session:')?I18n.t("Working edits attach to prepared XML/ZIP copies from this workspace."):I18n.t("Source-snapshot edits remain local to this scope; they do not attach to a different XML/ZIP workspace."));
  $('#track-detail-metadata').innerHTML=[[I18n.t("Artist"),t.artist || I18n.t("Unknown")],[I18n.t("Album"),t.album || I18n.t("Unknown")],[I18n.t("Saved genre"),t.genre || I18n.t("Unknown")],[I18n.t("Tonality"),t.tonality || I18n.t("Unknown")],['BPM',insightValue(t.bpm)],[I18n.t("Duration"),insightDuration(t.duration)],[I18n.t("Track colour"),t.color_name || (t.color_status==='unassigned'?I18n.t("No assigned colour"):I18n.t("Not captured"))],[I18n.t("Saved play count"),insightValue(t.play_count)]].map(([label,value])=>'<div><span>'+esc(label)+'</span><b>'+esc(value)+'</b></div>').join('');
  $('#track-comments-panel').open=true;$('#track-advanced-panel').open=false;
  $('#track-comment-text').value=record.overrides.comment?.value ?? t.comment ?? '';
  $('#track-comment-provenance').textContent=(record.comment_captured?I18n.t("Original comment captured."):I18n.t("Original comment not captured. Recapture matching inputs before applying this working comment to an export."))+" "+I18n.t("Comments are excluded from insight tables, CSV and shareable HTML. Rekordbox can append My Tags to comments; retain any text you want to preserve.");
  renderTrackCommentState(s);renderTrackColour(s);renderTrackWorkingEdits(s);
  $('#track-detail-fields').innerHTML=record.editable_fields.filter(field=>!['comment','colour'].includes(field)).map(field=>{
    const value=record.overrides[field]?.value ?? t[field];
    return '<label>'+esc(I18n.field(field))+'<input data-track-edit-field="'+esc(field)+'" '+(['rating','year'].includes(field)?'type="number" step="1" '+(field==='rating'?'min="0" max="5"':'min="1000" max="'+(new Date().getFullYear()+1)+'"'):'maxlength="255"')+' value="'+esc(value ?? '')+'" '+(!record.unlocked?'disabled':'')+("><small class=\"subtle\">"+esc(I18n.t("Captured:"))+" ")+esc(t[field] ?? I18n.t("Unknown"))+'</small>'+(record.overrides[field]?'<button type="button" class="text-button" data-track-field-reset="'+esc(field)+'" '+(!record.unlocked?'disabled':'')+(">"+esc(I18n.t("Reset override"))+"</button>"):'')+'</label>';
  }).join('');$('#track-detail-unlock').checked=record.unlocked;$('#track-detail-save').disabled=!record.unlocked;$('#track-detail-edit-state').textContent=I18n.t("Other fields start locked. Changes are staged for generated copies only.");
  $$('[data-track-field-reset]').forEach(button=>button.onclick=wrap(async()=>{
    if(!await trackStoreEdit(s,button.dataset.trackFieldReset,undefined,true) || trackDetailState!==s)return;
    $('[data-track-edit-field="'+button.dataset.trackFieldReset+'"]').value=t[button.dataset.trackFieldReset] ?? '';button.hidden=true;notify(I18n.t("Restored the captured field value"));
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
  if(await trackStoreEdit(s,'comment',$('#track-comment-text').value))notify(I18n.t("Working comment saved"));
});
$('#track-comment-reset').onclick=wrap(async()=>{
  const s=trackDetailState;if(!s)return;
  if(!await trackStoreEdit(s,'comment',undefined,true) || trackDetailState!==s)return;
  $('#track-comment-text').value=s.record.original.comment ?? '';renderTrackCommentState(s);
});
$('#track-comment-text').addEventListener('input',()=>{if(trackDetailState)renderTrackCommentState(trackDetailState);});
$('#track-colour-palette').addEventListener('click',wrap(async event=>{
  const button=event.target.closest('[data-track-colour]'),s=trackDetailState;
  if(!button || button.disabled || !s || trackColourValue(s.record)===button.dataset.trackColour)return;
  if(await trackStoreEdit(s,'colour',button.dataset.trackColour))notify(I18n.t('Working colour saved'));
}));
$('#track-colour-reset').onclick=wrap(async()=>{
  const s=trackDetailState;if(s)await trackStoreEdit(s,'colour',undefined,true);
});
$('#track-detail-unlock').onchange=wrap(async()=>{
  const s=trackDetailState;if(!s)return;const r=await labPost('unlock',{snapshot:s.snapshot,unlocked:$('#track-detail-unlock').checked});s.record.unlocked=r.unlocked;
  for(const input of $$('[data-track-edit-field],[data-track-field-reset]'))input.disabled=!r.unlocked;
  $('#track-detail-save').disabled=!r.unlocked;$('#track-detail-edit-state').textContent=r.unlocked?I18n.t("Staging unlocked for this snapshot scope. Review edited metadata before generating copies."):I18n.t('Other metadata is locked. Comments and colours remain editable.');
});
$('#track-detail-edit-form').onsubmit=wrap(async event=>{
  event.preventDefault();const s=trackDetailState;if(!s || !s.record.unlocked)return;let count=0;
  for(const input of $$('[data-track-edit-field]')){
    if(trackDetailState!==s)return;
    const field=input.dataset.trackEditField,previous=s.record.overrides[field]?.value ?? s.record.original[field];
    if(String(previous ?? '')===input.value)continue;
    if(await trackStoreEdit(s,field,input.value))count++;
  }
  $('#track-detail-edit-state').textContent=num(count)+" "+I18n.t("field changes staged locally. Insights continue to show captured values; working edits remain separate.");notify(num(count)+" "+I18n.t("metadata changes staged"));
});
