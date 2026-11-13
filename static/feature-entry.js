/* Prominent tool entrances; accents supplement plain labels and keyboard focus. */
function renderFeaturedTools(){
  const cards=[['compare','Compare snapshots','Find changed cues, ratings and playlist membership.'],['editor','Metadata editor','Review tags and stage field, comment or colour edits.'],['pilot','MusicBrainz metadata','Preview community matches, years, genres and available ratings.']];
  $('#featured-tools').innerHTML=cards.map(([tab,title,note])=>'<button class="tool-entry tool-'+esc(tab)+'" data-open-lab="'+esc(tab)+'"><strong>'+esc(I18n.t(title))+'</strong><span>'+esc(I18n.t(note))+'</span><span class="tool-entry-action">'+esc(I18n.t('Open tool →'))+'</span></button>').join('');
}
document.addEventListener('click',event=>{
  const link=event.target.closest('[data-open-lab]');if(!link)return;
  showView('lab');document.querySelector('[data-lab-tab="'+link.dataset.openLab+'"]').click();
  $('#view-lab .lab-tabs').scrollIntoView({block:'start',behavior:'smooth'});
});
$('#quick-xml-form').onsubmit=wrap(async event=>{
  event.preventDefault();if(busy)return;
  const file=$('#quick-xml-input').files[0];if(!file)return;
  busy=true;
  try{
    const started=await uploadFile(file,'/api/quick-export/xml');await poll(started.job);
    await loadQuickExports();$('#quick-source').value=started.source;updateQuickSource();
    await loadAnalyzer();await loadLab();await Journeys.load();await Journeys.selectContext('capture:'+started.source);updateQuickSource();
    notify(I18n.t('XML metadata is ready for sharing'));
  }finally{busy=false;finishProgress();updateQuickSource();}
});
Journeys.init();SharingUI.init();Intelligence.init();renderFeaturedTools();
window.addEventListener('workbench-language',renderFeaturedTools);
