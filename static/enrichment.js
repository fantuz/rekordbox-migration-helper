/* Background retrieval remains opt-in. No native notifications or external requests from this page. */
window.BackgroundPilot=(()=>{
  const node=id=>document.getElementById(id),t=key=>I18n.t(key);
  let pending=null,latest=null,known=new Map(),choiceSignature='',noticeKey='';
  async function refresh(){
    if(pending)return pending;
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
    pending=(async()=>{
      const info=await api('/api/lab/musicbrainz/batches',{feedback:false,signal:controller.signal}),rows=info.batches;
      const signature=rows.map(r=>r.id+':'+r.status).join('|');
      if(signature!==choiceSignature){
        labSelect('#lab-pilot-batches',rows,r=>(r.label || t('Library snapshot'))+' · '+t(r.status)+' · '+date(r.created),t('Saved batches'));
        choiceSignature=signature;
      }
      node('lab-pilot-batches').value=labBatch || '';
      for(const row of rows){
        if(['running','queued'].includes(known.get(row.id))&&!['running','queued'].includes(row.status))
          notify(t('MusicBrainz pilot')+' · '+t(row.status));
        known.set(row.id,row.status);
      }
      latest=rows.find(r=>r.status==='running') || rows.find(r=>r.status==='queued') || rows.find(r=>r.id===labBatch&&r.status!=='preview') || rows.find(r=>r.status!=='preview');
      const active=rows.filter(r=>['running','queued'].includes(r.status));
      const running=active.filter(r=>r.status==='running').length,queued=active.length-running;
      const totals=active.reduce((sum,r)=>{
        for(const key of ['done','tracks','requests','cache_hits'])sum[key]+=Number(r.summary[key]||0);
        return sum;
      },{done:0,tracks:0,requests:0,cache_hits:0});
      const banner=node('pilot-background');
      noticeKey=active.length?active.map(r=>r.id+':'+r.status).join('|'):latest?latest.id+':'+latest.status:'';
      banner.hidden=!latest || preferences.get('workbench-pilot-dismissed')===noticeKey;
      if(latest){
        const message=active.length
          ?t('MusicBrainz pilot')+' · '+num(running)+' '+t('running')+' · '+num(queued)+' '+t('queued')+' · '+
           num(totals.done)+' / '+num(totals.tracks)+' '+t('tracks')+' · '+
           num(totals.requests)+' '+t('requests')+' · '+num(totals.cache_hits)+' '+t('cached')
          :t('MusicBrainz pilot')+' · '+t(latest.status)+' · '+num(latest.summary.done)+' / '+num(latest.summary.tracks);
        if(node('pilot-background-text').textContent!==message)node('pilot-background-text').textContent=message;
        banner.dataset.state=['running','queued'].includes(latest.status)?'running':'ready';
      }
      const selected=rows.find(r=>r.id===labBatch);
      if(selected){labPilotStatus=selected.status;labPilotButtons();node('lab-pilot-cancel').disabled=!['running','queued'].includes(selected.status);}
      // Keep finished/interrupted batches visible alongside the queue. Their
      // completed work must not look as if it disappeared from the counters.
      const visible=[...active,...rows.filter(r=>!['preview','running','queued'].includes(r.status)).slice(0,10)];
      const focused=node('lab-pilot-queue').contains(document.activeElement)?document.activeElement.dataset.pilotBatch:null;
      node('lab-pilot-queue').innerHTML=visible.map(r=>'<div class="pilot-queue-row"><button class="text-button" data-pilot-batch="'+esc(r.id)+'" aria-pressed="'+(r.id===labBatch)+'">'+esc((r.queue_position?'#'+r.queue_position+' · ':'')+(r.label||t('Library snapshot')))+'<small>'+esc(t(r.summary.target==='balanced'?'Balanced genres':r.summary.target))+(r.summary.target_value?' · '+esc(r.summary.target_value):'')+'</small></button><span>'+esc(t(r.status))+'</span><span>'+num(r.summary.done||0)+' / '+num(r.summary.tracks||0)+' '+esc(t('tracks'))+'</span></div>').join('');
      for(const button of node('lab-pilot-queue').querySelectorAll('[data-pilot-batch]')){
        button.onclick=wrap(()=>selectBatch(button.dataset.pilotBatch));
        if(button.dataset.pilotBatch===focused)button.focus({preventScroll:true});
      }
      if(labBatch && !node('view-musicbrainz').hidden)await labLoadPilot(false,controller.signal);
      return rows;
    })();
    try{return await pending;}finally{clearTimeout(timeout);pending=null;}
  }
  async function selectBatch(identity){
    labBatch=identity;labPilotOffset=0;labPilotPreviewDirty=false;node('lab-pilot-consent').checked=false;
    preferences.set('workbench-lab-batch',labBatch);const batch=await labLoadPilot();if(batch)await Journeys.selectContext('snapshot:'+batch.snapshot_id);labPilotButtons();
    node('lab-pilot-batches').value=labBatch||'';
  }
  node('lab-pilot-batches').onchange=wrap(()=>selectBatch(node('lab-pilot-batches').value));
  node('pilot-background-open').onclick=wrap(async()=>{
    const button=node('pilot-background-open');if(!latest || button.disabled)return;
    button.disabled=true;button.setAttribute('aria-busy','true');
    try{
      labBatch=latest.id;labPilotOffset=0;preferences.set('workbench-lab-batch',labBatch);
      await Journeys.selectContext('snapshot:'+latest.snapshot_id);showView('musicbrainz');await loadMusicBrainz(true);
      node('lab-pilot-progress').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});
    }finally{button.disabled=false;button.removeAttribute('aria-busy');}
  });
  node('pilot-background-dismiss').onclick=()=>{if(latest)preferences.set('workbench-pilot-dismissed',noticeKey);node('pilot-background').hidden=true;};
  async function tick(){try{await refresh();}catch{/* Retry quietly if the local application is stopping or temporarily busy. */}
    setTimeout(tick,document.hidden?15000:4000);}
  tick();
  window.addEventListener('workbench-language',()=>{choiceSignature='';void refresh().catch(()=>{});});
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
        const play=document.createElement('span');choice.before(play);
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
