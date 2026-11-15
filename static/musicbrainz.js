/* Dedicated, opt-in enrichment page with local-only target selection. */
let musicBrainzInfo=null,musicBrainzRevision=0,musicBrainzTargetRevision=0;
const musicBrainzTargetCache=new Map();
const musicBrainzSnapshot=()=>$('#musicbrainz-snapshot').value;
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
  if(!musicBrainzRequiresValue() || !snapshot){
    selector.replaceChildren();labPilotButtons();return;
  }
  try{
    let choices=musicBrainzTargetCache.get(snapshot);
    if(!choices){
      choices=await api('/api/lab/musicbrainz/targets?'+new URLSearchParams({snapshot}),{feedback:false});
      musicBrainzTargetCache.set(snapshot,choices);
    }
    if(revision!==musicBrainzTargetRevision || snapshot!==musicBrainzSnapshot() || target!==$('#lab-pilot-target').value)return;
    const old=selector.value,rows=choices[values[target]]||[];
    selector.innerHTML='<option value="">'+esc(I18n.t('Choose a target'))+'</option>'+
      rows.map(r=>'<option value="'+esc(r.value)+'">'+esc(r.label)+' · '+num(r.tracks)+' '+esc(I18n.t('tracks'))+'</option>').join('');
    if(rows.some(r=>r.value===old))selector.value=old;
    else if(rows.length)selector.value=rows[0].value;
  }catch(error){
    if(revision===musicBrainzTargetRevision){selector.replaceChildren();$('#musicbrainz-target-hint').textContent=error.message;}
  }
  labPilotButtons();
}
async function loadMusicBrainz(sync=false){
  const revision=++musicBrainzRevision;
  const info=await api('/api/lab');if(revision!==musicBrainzRevision)return;
  musicBrainzInfo=info;
  labSelect('#musicbrainz-snapshot',info.snapshots,s=>s.label+' · '+snapshotMoment(s.created));
  const shared=window.Journeys?.context?.();
  if(sync || !musicBrainzSnapshot()){
    $('#musicbrainz-snapshot').value=info.snapshots.some(s=>s.id===shared?.snapshot)?shared.snapshot:'';
    if(!shared && info.snapshots.length)$('#musicbrainz-snapshot').value=info.snapshots[0].id;
  }
  $('#musicbrainz-source-note').hidden=Boolean(musicBrainzSnapshot());
  $('#lab-pilot-enabled').checked=info.musicbrainz_enabled;
  $('#lab-pilot-enabled').disabled=info.musicbrainz_forced_off;
  await musicBrainzTargetOptions();
  labPilotButtons();await BackgroundPilot.refresh();
  if(labBatch && revision===musicBrainzRevision)await labLoadPilot();
}
$('#musicbrainz-snapshot').onchange=wrap(async()=>{
  musicBrainzSelectionChanged();
  $('#musicbrainz-source-note').hidden=Boolean(musicBrainzSnapshot());
  await musicBrainzTargetOptions();
  if(musicBrainzSnapshot())await Journeys.selectContext('snapshot:'+musicBrainzSnapshot());
});
$('#lab-pilot-target').onchange=wrap(async()=>{musicBrainzSelectionChanged();await musicBrainzTargetOptions();});
$('#lab-pilot-target-value').onchange=musicBrainzSelectionChanged;
for(const id of ['lab-pilot-size','lab-pilot-top','lab-pilot-seed','lab-pilot-speed']){
  $('#'+id).addEventListener('change',musicBrainzSelectionChanged);
}
window.addEventListener('workbench-context',()=>{
  if(!$('#view-musicbrainz').hidden)loadMusicBrainz(true).catch(error=>notify(error.message,true));
});
window.addEventListener('workbench-language',()=>{
  if(!$('#view-musicbrainz').hidden)void musicBrainzTargetOptions();
});