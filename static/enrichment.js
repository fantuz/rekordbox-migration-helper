/* Background retrieval remains opt-in. No native notifications or external requests from this page. */
window.BackgroundPilot=(()=>{
  const node=id=>document.getElementById(id),t=key=>I18n.t(key);
  let pending=null,latest=null,known=new Map(),choiceSignature='';
  async function refresh(){
    if(pending)return pending;
    pending=(async()=>{
      const info=await api('/api/lab/musicbrainz/batches'),rows=info.batches;
      const signature=rows.map(r=>r.id+':'+r.status).join('|');
      if(signature!==choiceSignature){
        labSelect('#lab-pilot-batches',rows,r=>(r.label || t('Library snapshot'))+' · '+r.status+' · '+date(r.created),t('Saved batches'));
        node('lab-pilot-batches').value=labBatch || '';choiceSignature=signature;
      }
      for(const row of rows){
        if(['running','queued'].includes(known.get(row.id))&&!['running','queued'].includes(row.status))
          notify(t('MusicBrainz pilot')+' · '+row.status);
        known.set(row.id,row.status);
      }
      latest=rows.find(r=>['running','queued'].includes(r.status)) || rows.find(r=>r.id===labBatch&&r.status!=='preview') || rows.find(r=>r.status!=='preview');
      const banner=node('pilot-background');
      banner.hidden=!latest || preferences.get('workbench-pilot-dismissed')===latest.id+':'+latest.status;
      if(latest){
        const message=t('MusicBrainz pilot')+' · '+latest.status+' · '+num(latest.summary.done)+' / '+num(latest.summary.tracks);
        if(node('pilot-background-text').textContent!==message)node('pilot-background-text').textContent=message;
        banner.dataset.state=['running','queued'].includes(latest.status)?'running':'ready';
      }
      const selected=rows.find(r=>r.id===labBatch);
      if(selected){labPilotStatus=selected.status;labPilotButtons();node('lab-pilot-cancel').disabled=!['running','queued'].includes(selected.status);}
      if(labBatch && !node('view-lab').hidden && !node('lab-panel-pilot').hidden)await labLoadPilot();
      return rows;
    })();
    try{return await pending;}finally{pending=null;}
  }
  node('lab-pilot-batches').onchange=wrap(async()=>{
    labBatch=node('lab-pilot-batches').value;labPilotOffset=0;node('lab-pilot-consent').checked=false;
    preferences.set('workbench-lab-batch',labBatch);await labLoadPilot();labPilotButtons();
  });
  node('pilot-background-open').onclick=wrap(async()=>{
    if(!latest)return;labBatch=latest.id;labPilotOffset=0;preferences.set('workbench-lab-batch',labBatch);
    showView('lab');document.querySelector('[data-lab-tab="pilot"]').click();await labLoadPilot();
    node('lab-panel-pilot').scrollIntoView({behavior:'smooth',block:'start'});
  });
  node('pilot-background-dismiss').onclick=()=>{if(latest)preferences.set('workbench-pilot-dismissed',latest.id+':'+latest.status);node('pilot-background').hidden=true;};
  async function tick(){try{await refresh();}catch{/* Retry quietly if the local application is stopping or temporarily busy. */}
    setTimeout(tick,document.hidden?15000:4000);}
  tick();
  return {refresh};
})();

window.EnrichmentExports=(()=>{
  const node=id=>document.getElementById(id),t=key=>I18n.t(key);
  let chart=null,revision=0;
  function reset(){revision++;chart=null;node('chart-results').replaceChildren();node('chart-reviewed').checked=false;node('chart-export').disabled=true;}
  async function download(url,data,name){
    mutatingRequests++;
    try{
      const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-Workbench-Token':token},body:JSON.stringify(data)});
      if(!response.ok){const error=await response.json();throw new Error(I18n.error(error.error));}
      const blob=await response.blob(),link=document.createElement('a'),href=URL.createObjectURL(blob);
      link.href=href;link.download=name;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(href),30000);
    }finally{mutatingRequests--;}
  }
  node('chart-fetch').onclick=wrap(async()=>{
    const snapshot=node('intelligence-source').value;reset();const version=revision;
    node('chart-fetch').disabled=true;
    try{
      const result=await api('/api/intelligence/chart',{method:'POST',body:JSON.stringify({snapshot,period:node('chart-period').value,network_consent:node('chart-consent').checked})});
      if(version!==revision || snapshot!==node('intelligence-source').value)return;
      chart=result;
      node('chart-results').innerHTML='<p class="callout">'+esc(result.basis)+'</p><p><a href="https://listenbrainz.org/charts/" target="_blank" rel="noopener noreferrer">ListenBrainz</a> · '+esc(result.period)+' · '+esc(date(result.retrieved_at))+'</p>'+labSummary(result.summary)+
        '<div class="lab-table"><table><thead><tr><th>#</th><th>'+esc(t('Chart recording'))+'</th><th>'+esc(t('Local match'))+'</th></tr></thead><tbody>'+result.rows.map(row=>
          '<tr><td>'+num(row.rank)+'</td><td>'+esc(row.title)+'<br>'+esc(row.artist)+'</td><td><span class="match-status">'+esc(t(row.status))+'</span><select data-chart-rank="'+row.rank+'" aria-label="'+esc(t('Local match'))+'"><option value="">'+esc(t('Skip'))+'</option>'+
          row.candidates.map(c=>'<option value="'+esc(c.id)+'" '+(row.status==='exact_tags'?'selected':'')+'>'+esc(c.title)+' · '+esc(c.artist)+' · '+esc(c.album || '')+' · '+esc(c.id)+'</option>').join('')+'</select></td></tr>').join('')+'</tbody></table></div>';
      const choices=node('chart-results').querySelectorAll('[data-chart-rank]');
      for(const choice of choices){
        const play=document.createElement('span');choice.after(play);
        const update=()=>{play.innerHTML=TrackPlayback.button(snapshot,choice.value);node('chart-reviewed').checked=false;};
        choice.addEventListener('change',update);update();
      }
      node('chart-export').disabled=false;
    }finally{node('chart-fetch').disabled=false;}
  });
  node('chart-export').onclick=wrap(async()=>{
    if(!chart)return;
    const selected=[...node('chart-results').querySelectorAll('[data-chart-rank]')].filter(e=>e.value).map(e=>({rank:e.dataset.chartRank,track_id:e.value}));
    await download('/api/intelligence/chart/export',{report_id:chart.report_id,selected,reviewed:node('chart-reviewed').checked},'listenbrainz-chart.m3u8');
  });
  return {reset};
})();
