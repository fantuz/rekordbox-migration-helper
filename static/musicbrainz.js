/* Dedicated, opt-in enrichment page with local-only target selection. */
let musicBrainzInfo=null,musicBrainzRevision=0,musicBrainzTargetRevision=0;
let musicBrainzContext={sources:[],snapshots:[]};
const musicBrainzTargetCache=new Map(),musicBrainzTargetPending=new Map();
const musicBrainzSnapshot=()=>$('#musicbrainz-snapshot').value;
const musicBrainzReady=()=>musicBrainzContext.snapshots.some(s=>s.id===musicBrainzSnapshot()&&s.scope_key===$('#musicbrainz-library').value);
const musicBrainzRequiresValue=()=>['genre','album','year','playlist'].includes($('#lab-pilot-target').value);
const musicBrainzHasTarget=()=>!musicBrainzRequiresValue() || Boolean($('#lab-pilot-target-value').value);
function musicBrainzSelectionChanged(){
  // A prior preview does not authorize a different target/sample.
  labPilotSnapshot=null;
  labPilotPreviewDirty=true;
  $('#lab-pilot-consent').checked=false;
  labPilotButtons();
}
async function musicBrainzTargetOptions(){
  const revision=++musicBrainzTargetRevision,snapshot=musicBrainzSnapshot(),target=$('#lab-pilot-target').value;
  const label=$('#musicbrainz-target-value-label'),selector=$('#lab-pilot-target-value');
  const values={genre:'genres',album:'albums',year:'years',playlist:'playlists'};
  label.hidden=!musicBrainzRequiresValue();
  $('#lab-pilot-top').closest('label').hidden=target!=='balanced';
  const hints={
    balanced:'Balance tracks across saved genres.',
    random:'The same seed repeats the random selection.',
    genre:'Only tracks matching the selected saved value are included.',
    album:'Only tracks matching the selected saved value are included.',
    year:'Only tracks matching the selected saved value are included.',
    playlist:'Only tracks matching the selected saved value are included.',
    missing_genre:'Only tracks with missing tags are included.',
    missing_album:'Only tracks with missing tags are included.',
    missing_year:'Only tracks with missing tags are included.'
  };
  $('#musicbrainz-target-hint').textContent=I18n.t(hints[target]||hints.balanced);
  if(!musicBrainzRequiresValue() || !snapshot || !musicBrainzReady()){
    selector.replaceChildren();selector.disabled=true;selector.removeAttribute('aria-busy');$('#musicbrainz-target-retry').hidden=true;labPilotButtons();return;
  }
  const old=selector.value;
  selector.replaceChildren(new Option(I18n.t('Loading'),''));selector.disabled=true;selector.setAttribute('aria-busy','true');
  $('#musicbrainz-target-retry').hidden=true;labPilotButtons();
  try{
    let choices=musicBrainzTargetCache.get(snapshot);
    if(!choices){
      if(!musicBrainzTargetPending.has(snapshot)){
        const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
        const pending=api('/api/lab/musicbrainz/targets?'+new URLSearchParams({snapshot}),{feedback:false,signal:controller.signal})
          .finally(()=>{clearTimeout(timer);musicBrainzTargetPending.delete(snapshot);});
        musicBrainzTargetPending.set(snapshot,pending);
      }
      choices=await musicBrainzTargetPending.get(snapshot);
      if(musicBrainzTargetCache.size>=10)musicBrainzTargetCache.delete(musicBrainzTargetCache.keys().next().value);
      musicBrainzTargetCache.set(snapshot,choices);
    }
    if(revision!==musicBrainzTargetRevision || snapshot!==musicBrainzSnapshot() || target!==$('#lab-pilot-target').value)return;
    const rows=choices[values[target]]||[];
    selector.innerHTML='<option value="">'+esc(I18n.t(rows.length?'Choose a target':'No matching references'))+'</option>'+
      rows.map(r=>'<option value="'+esc(r.value)+'">'+esc(r.label)+' · '+num(r.tracks)+' '+esc(I18n.t('tracks'))+'</option>').join('');
    if(rows.some(r=>r.value===old))selector.value=old;
    else if(rows.length)selector.value=rows[0].value;
    selector.disabled=!rows.length;selector.removeAttribute('aria-busy');
  }catch(error){
    if(revision===musicBrainzTargetRevision){selector.replaceChildren(new Option(I18n.t('The action could not be completed'),''));selector.disabled=true;selector.removeAttribute('aria-busy');$('#musicbrainz-target-hint').textContent=error.message;$('#musicbrainz-target-retry').hidden=false;}
  }
  labPilotButtons();
}
async function loadMusicBrainz(sync=false){
  const revision=++musicBrainzRevision;
  const [info,context]=await Promise.all([api('/api/lab'),api('/api/lab/musicbrainz/context')]);if(revision!==musicBrainzRevision)return;
  musicBrainzInfo=info;
  musicBrainzContext=context;
  const oldSource=$('#musicbrainz-library').value;
  labSelect('#musicbrainz-library',context.sources,s=>s.label);
  const shared=window.Journeys?.context?.();
  const sharedScope=info.snapshots.find(s=>s.id===shared?.snapshot)?.scope_key||shared?.source;
  const source=context.sources.find(s=>!sync&&s.id===oldSource)||context.sources.find(s=>s.kind==='workspace')||context.sources.find(s=>s.id===sharedScope)||context.sources[0];
  $('#musicbrainz-library').value=source?.id||'';
  musicBrainzSelectPrepared();
  $('#musicbrainz-source-note').hidden=Boolean(context.sources.length);
  $('#musicbrainz-prepare').disabled=!source;
  $('#lab-pilot-enabled').checked=info.musicbrainz_enabled;
  $('#lab-pilot-enabled').disabled=info.musicbrainz_forced_off || !source;
  await musicBrainzTargetOptions();
  labPilotButtons();await BackgroundPilot.refresh();
  if(labBatch && revision===musicBrainzRevision)await labLoadPilot();
}
function musicBrainzSelectPrepared(){
  const choices=musicBrainzContext.snapshots.filter(s=>s.scope_key===$('#musicbrainz-library').value);
  const old=musicBrainzSnapshot();
  labSelect('#musicbrainz-snapshot',choices,s=>s.label+' · '+snapshotMoment(s.created));
  $('#musicbrainz-snapshot').value=choices.some(s=>s.id===old)?old:choices[0]?.id||'';
}
$('#musicbrainz-library').onchange=wrap(async()=>{
  musicBrainzSelectionChanged();musicBrainzSelectPrepared();$('#musicbrainz-prepare').disabled=!$('#musicbrainz-library').value;await musicBrainzTargetOptions();
});
$('#musicbrainz-prepare').onclick=wrap(async()=>{
  const source=$('#musicbrainz-library').value;if(!source)return;
  $('#musicbrainz-prepare').disabled=true;musicBrainzSelectionChanged();
  try{
    const job=await api('/api/lab/musicbrainz/prepare',{method:'POST',body:JSON.stringify({source})});
    const result=await poll(job.job);
    if($('#musicbrainz-library').value!==source)return;
    await loadMusicBrainz();
    $('#musicbrainz-library').value=result.source;musicBrainzSelectPrepared();$('#musicbrainz-snapshot').value=result.id;
    await musicBrainzTargetOptions();labPilotButtons();
  }finally{$('#musicbrainz-prepare').disabled=!$('#musicbrainz-library').value;}
});
$('#musicbrainz-target-retry').onclick=wrap(()=>musicBrainzTargetOptions());
$('#musicbrainz-snapshot').onchange=wrap(async()=>{
  musicBrainzSelectionChanged();
  $('#musicbrainz-source-note').hidden=Boolean(musicBrainzSnapshot());
  await musicBrainzTargetOptions();
  if(musicBrainzSnapshot())await Journeys.selectContext('snapshot:'+musicBrainzSnapshot());
});
$('#lab-pilot-target').onchange=wrap(async()=>{musicBrainzSelectionChanged();await musicBrainzTargetOptions();});
$('#lab-pilot-target-value').onchange=musicBrainzSelectionChanged;
$('#lab-pilot-include-unavailable').onchange=musicBrainzSelectionChanged;
for(const id of ['lab-pilot-size','lab-pilot-top','lab-pilot-seed','lab-pilot-speed']){
  $('#'+id).addEventListener('change',musicBrainzSelectionChanged);
}
window.addEventListener('workbench-context',()=>{
  if(!$('#view-musicbrainz').hidden)loadMusicBrainz(true).catch(error=>notify(error.message,true));
});
window.addEventListener('workbench-language',()=>{
  if(!$('#view-musicbrainz').hidden)void musicBrainzTargetOptions();
});
