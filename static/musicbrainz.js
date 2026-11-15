/* A dedicated enrichment view; retrieval and staging remain explicit choices. */
let musicBrainzInfo=null,musicBrainzRevision=0;
const musicBrainzSnapshot=()=>$('#musicbrainz-snapshot').value;
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
  $('#lab-pilot-enabled').checked=info.musicbrainz_enabled;$('#lab-pilot-enabled').disabled=info.musicbrainz_forced_off;
  labPilotButtons();await BackgroundPilot.refresh();
  if(labBatch && revision===musicBrainzRevision)await labLoadPilot();
}
$('#musicbrainz-snapshot').onchange=wrap(async()=>{
  $('#lab-pilot-consent').checked=false;labPilotButtons();
  $('#musicbrainz-source-note').hidden=Boolean(musicBrainzSnapshot());
  if(musicBrainzSnapshot())await Journeys.selectContext('snapshot:'+musicBrainzSnapshot());
});
window.addEventListener('workbench-context',()=>{
  if(!$('#view-musicbrainz').hidden)loadMusicBrainz(true).catch(error=>notify(error.message,true));
});
