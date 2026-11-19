/* Cloud labels describe captured/mapped locations, never live file access. */
window.CloudAnalysis=(()=>{
  const labels={all:'All locations',dropbox:'Dropbox',google_drive:'Google Drive',other:'No cloud match',unknown:'Not classified'};
  const note='Recorded or mapped paths; not cloud presence or local availability.';
  function control(id,value='all'){
    return '<label class="cloud-analysis-filter"><span data-i18n="Cloud location">'+esc(I18n.t('Cloud location'))+'</span><select id="'+esc(id)+'" name="provider" data-cloud-analysis-provider data-i18n-aria="Cloud location" aria-label="'+esc(I18n.t('Cloud location'))+'">'+Object.entries(labels).map(([key,label])=>'<option value="'+key+'"'+(value===key?' selected':'')+'>'+esc(I18n.t(label))+'</option>').join('')+'</select></label>';
  }
  function paint(select,counts){
    if(!select)return;
    const value=select.value;
    for(const option of select.options)option.textContent=I18n.t(labels[option.value])+(counts?' · '+num(counts[option.value]||0):'');
    select.classList.toggle('cloud-provider-dropbox',value==='dropbox');
    select.classList.toggle('cloud-provider-google_drive',value==='google_drive');
    select.title=I18n.t(note);
  }
  function statisticsSetup(){
    if(document.getElementById('stats-provider'))return;
    const wrapper=document.createElement('div');wrapper.innerHTML=control('stats-provider',window.BrowseState?.value('stats-provider')||'all');
    const label=wrapper.firstElementChild;document.getElementById('stats-apply').before(label);
    const caption=document.createElement('p');caption.className='subtle cloud-analysis-note';caption.dataset.i18n=note;caption.textContent=I18n.t(note);
    document.getElementById('stats-apply').closest('.stats-controls').after(caption);
    label.querySelector('select').onchange=wrap(async()=>{paint(label.querySelector('select'));await renderStatistics();});
  }
  function statisticsPaint(data){paint(document.getElementById('stats-provider'),data.cloud?.counts);}
  function cards(){return [['dropbox_paths',I18n.t('Dropbox paths'),I18n.t(note)],['google_drive_paths',I18n.t('Google Drive paths'),I18n.t(note)]];}
  document.addEventListener('change',event=>{if(event.target.matches('[data-cloud-analysis-provider]'))paint(event.target);});
  window.addEventListener('workbench-language',()=>{for(const node of document.querySelectorAll('[data-cloud-analysis-provider]'))paint(node);});
  return {control,paint,statisticsSetup,statisticsPaint,cards,note};
})();
