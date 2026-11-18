/* Explicit, local-only file-health explorer. Indexing never runs just
 * because the user opens this page. All sorting/filtering here is server-side
 * and applies to the whole scanned set, not only the 50 rendered rows.
 */
window.FileHealth=(()=>{
  let source='',offset=0,sort='artist',direction='asc',revision=0;
  const states=['playable','missing','inaccessible','unverified'];
  const label=key=>I18n.t(key),stateNames={playable:'Accessible',missing:'Missing',inaccessible:'Inaccessible',unverified:'Unverified'};
  const node=id=>document.getElementById('file-health-'+id);
  const chosen=()=>node('source')?.value||'';
  const statusBadge=value=>'<span class="file-status file-status-'+esc(value)+'">'+esc(label(stateNames[value]||'Unverified'))+'</span>';
  const providerNames={all:'All locations',dropbox:'Dropbox',google_drive:'Google Drive',other:'No cloud match',unknown:'Not classified'};
  function providerBadge(kind){return '<span class="cloud-provider cloud-provider-'+kind+'">'+esc(kind==='dropbox'?'Dropbox':'Google Drive')+'</span>';}
  function renderProviders(data){
    node('providers').innerHTML=Object.entries(providerNames).map(([value,name])=>'<button type="button" class="cloud-provider cloud-provider-'+value+'" data-file-provider="'+value+'" aria-pressed="'+(node('provider').value===value)+'">'+esc(['dropbox','google_drive'].includes(value)?name:label(name))+' · '+num(data.provider_counts?.[value]||0)+'</button>').join('');
    for(const button of node('providers').querySelectorAll('[data-file-provider]'))button.onclick=()=>{node('provider').value=button.dataset.fileProvider;window.BrowseState?.set('file-health-provider',button.dataset.fileProvider);offset=0;void loadResults();};
    node('legacy').hidden=!data.provider_counts?.unknown;
  }
  function renderCounts(data){
    const buttons=[['all',data.checked,label('Checked')],['not_playable',data.unavailable_count ?? data.counts.missing+data.counts.inaccessible,label('Unavailable')],...states.map(s=>[s,data.counts[s],label(stateNames[s])]),['cloud_only',data.cloud_counts?.online_only||0,label('Online-only placeholder')],['cloud_not_local',data.cloud_counts?.not_local||0,label('Cloud availability unknown')]];
    node('counts').innerHTML=buttons.map(([value,count,name])=>'<button type="button" data-file-status="'+esc(value)+'" aria-pressed="'+(node('status').value===value)+'">'+esc(name)+' · '+num(count)+'</button>').join('')+
      '<span>'+esc(label('Unchecked'))+' · '+num(data.unchecked)+'</span>';
    for(const b of node('counts').querySelectorAll('[data-file-status]'))b.onclick=()=>{node('status').value=b.dataset.fileStatus;offset=0;void loadResults();};
  }
  function renderRows(data){
    const columns=[['artist','Artist'],['title','Track'],['','Cloud location'],['playability','Accessible?'],['status','File status'],['checked','Last checked']];
    const heads=columns.map(([id,name])=>id?'<th data-file-health-sort="'+id+'" aria-sort="'+(sort===id?(direction==='asc'?'ascending':'descending'):'none')+'"><button type="button" class="result-sort-button" data-file-health-sort="'+id+'" title="'+esc(label('Sort all scanned results'))+'" aria-label="'+esc(label('Sort all scanned results'))+' · '+esc(label(name))+'">'+esc(label(name))+'</button></th>':'<th>'+esc(label(name))+'</th>').join('');
    const rows=data.rows.map(t=>{
      const playback=TrackPlayback.button(source.startsWith('snapshot:')?source.slice(9):source,t.track_id);
      const when=t.checked_at?snapshotMoment(new Date(t.checked_at*1000).toISOString()):label('Unknown');
      const playable=t.status==='playable'?label('Yes'):['missing','inaccessible'].includes(t.status)?label('No'):label('Unknown');
      const providers=(t.providers&1?providerBadge('dropbox'):'')+(t.providers&2?providerBadge('google_drive'):'');
      const evidence=t.provider_evidence?.some(value=>value.endsWith(':detected_root'))?label('Cloud folder detected'):label('Path-name hint');
      const location=providers?'<div class="cloud-provider-list">'+providers+'</div><small class="subtle">'+esc(evidence)+'</small>':esc(label(t.provider_checked?'No cloud match':'Not classified'));
      const cloudState=t.cloud_state==='online_only'?'Online-only placeholder':t.cloud_state==='not_local'?'Cloud availability unknown':'';
      const state=cloudState?'<span class="file-status file-status-cloud">'+esc(label(cloudState))+'</span>':statusBadge(t.status);
      const metadata=(t.filename?'<br><small class="file-health-filename">'+esc(t.filename)+'</small>':'')+(t.logical_size!==null&&t.logical_size!==undefined?'<br><small class="subtle">'+esc(bytes(t.logical_size))+'</small>':'');
      return '<tr><td>'+esc(t.artist||'—')+'</td><td>'+playback+'<strong>'+esc(t.title||label('Untitled'))+'</strong><br><small class="subtle">'+esc(t.track_id)+'</small>'+metadata+'</td><td>'+location+'</td><td>'+esc(playable)+'</td><td>'+state+'</td><td>'+esc(when)+'</td></tr>';
    }).join('');
    node('results').innerHTML='<div class="native-table"><table data-sort-scope="server"><thead><tr>'+heads+'</tr></thead><tbody>'+rows+'</tbody></table></div>';
    for(const button of node('results').querySelectorAll('[data-file-health-sort] button'))
      button.onclick=()=>{const next=button.dataset.fileHealthSort;direction=next===sort&&direction==='asc'?'desc':'asc';sort=next;offset=0;void loadResults();};
    node('prev').disabled=!offset;
    node('next').disabled=offset+50>=data.total;
    node('page').textContent=num(data.total)+' '+label('results')+' · '+(data.total?num(offset+1)+'–'+num(Math.min(offset+50,data.total)):'0');
  }
  async function loadResults(){
    const request=++revision,selected=chosen();
    source=selected;
    await AudioPaths.load(node('audio-paths'),selected);
    node('scan').disabled=!selected;
    if(!selected){node('results').replaceChildren();node('counts').replaceChildren();node('providers').replaceChildren();node('legacy').hidden=true;node('state').textContent=label('Choose a saved collection snapshot');return;}
    const args=new URLSearchParams({source:selected,status:node('status').value,provider:node('provider').value,q:node('search').value,sort,direction,offset:String(offset)});
    node('state').textContent=label('Loading');
    try{
      const r=await api('/api/file-health?'+args,{feedback:false});
      if(request!==revision || selected!==chosen())return;
      renderCounts(r);renderProviders(r);renderRows(r);
      const time=r.scan_time?snapshotMoment(new Date(r.scan_time*1000).toISOString()):label('Not checked');
      node('state').textContent=label('Scan local files')+': '+label(r.scan_state)+' · '+label('Last checked')+': '+time;
    }catch(e){if(request===revision)node('state').textContent=e.message;}
  }
  async function load(){
    const request=++revision;
    const info=await api('/api/journeys',{feedback:false});
    if(request!==revision)return;
    const options=info.sources.filter(s=>/^(?:snapshot|capture):[0-9a-f]{32}$/u.test(s.id));
    const old=node('source').value || window.BrowseState?.value('file-health-source');
    const current=window.Journeys?.context?.()?.source;
    node('source').innerHTML='<option value="">'+esc(label('Choose a saved collection snapshot'))+'</option>'+options.map(s=>'<option value="'+esc(s.id)+'">'+esc(s.label)+' · '+esc(snapshotMoment(s.created))+'</option>').join('');
    const wanted=[current,old].find(v=>options.some(s=>s.id===v)) || options[0]?.id || '';
    node('source').value=wanted;
    if(source!==wanted)offset=0;await loadResults();
  }
  node('source').onchange=wrap(async()=>{offset=0;await loadResults();});
  node('status').onchange=wrap(async()=>{offset=0;await loadResults();});
  node('provider').onchange=wrap(async()=>{offset=0;await loadResults();});
  node('find').onclick=wrap(async()=>{offset=0;await loadResults();});
  node('search').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();offset=0;void loadResults();}};
  node('prev').onclick=wrap(async()=>{offset=Math.max(0,offset-50);await loadResults();});
  node('next').onclick=wrap(async()=>{offset+=50;await loadResults();});
  node('scan').onclick=wrap(async()=>{
    const selected=chosen();if(!selected)return;
    node('scan').disabled=true;
    try{
      const job=await api('/api/file-health/scan',{method:'POST',body:JSON.stringify({source:selected,force:true})});
      await poll(job.job);
    }finally{
      if(node('source').value)await loadResults();
      node('scan').disabled=!node('source').value;
    }
  });
  window.addEventListener('workbench-language',()=>{if(!node('results').closest('.view').hidden)void loadResults();});
  window.addEventListener('workbench-audio-paths',()=>{if(!node('results').closest('.view').hidden)void loadResults();});
  return {load};
})();
