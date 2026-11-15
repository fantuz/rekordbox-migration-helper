/* Explicit, local-only file-health explorer. Indexing never runs just
 * because the user opens this page. All sorting/filtering here is server-side
 * and applies to the whole scanned set, not only the 50 rendered rows.
 */
window.FileHealth=(()=>{
  let source='',offset=0,sort='artist',direction='asc',revision=0;
  const states=['playable','missing','inaccessible','unverified'];
  const label=key=>I18n.t(key),stateNames={playable:'Playable',missing:'Missing',inaccessible:'Inaccessible',unverified:'Unverified'};
  const node=id=>document.getElementById('file-health-'+id);
  const chosen=()=>node('source')?.value||'';
  const statusBadge=value=>'<span class="file-status file-status-'+esc(value)+'">'+esc(label(stateNames[value]||'Unverified'))+'</span>';
  function renderCounts(data){
    const buttons=[['all',data.checked,label('Checked')],['not_playable',data.counts.missing+data.counts.inaccessible,label('Not playable')],...states.map(s=>[s,data.counts[s],label(stateNames[s])])];
    node('counts').innerHTML=buttons.map(([value,count,name])=>'<button type="button" data-file-status="'+esc(value)+'" aria-pressed="'+(node('status').value===value)+'">'+esc(name)+' · '+num(count)+'</button>').join('')+
      '<span>'+esc(label('Unchecked'))+' · '+num(data.unchecked)+'</span>';
    for(const b of node('counts').querySelectorAll('[data-file-status]'))b.onclick=()=>{node('status').value=b.dataset.fileStatus;offset=0;void loadResults();};
  }
  function renderRows(data){
    const columns=[['artist','Artist'],['title','Track'],['playability','Playable?'],['status','File status'],['checked','Last checked']];
    const heads=columns.map(([id,name])=>'<th data-file-health-sort="'+id+'" aria-sort="'+(sort===id?(direction==='asc'?'ascending':'descending'):'none')+'"><button type="button" class="result-sort-button" data-file-health-sort="'+id+'" title="'+esc(label('Sort all scanned results'))+'">'+esc(label(name))+(sort===id?(direction==='asc'?' ↑':' ↓'):' ↕')+'</button></th>').join('');
    const rows=data.rows.map(t=>{
      const playback=TrackPlayback.button(source.startsWith('snapshot:')?source.slice(9):source,t.track_id);
      const when=t.checked_at?snapshotMoment(new Date(t.checked_at*1000).toISOString()):label('Unknown');
      const playable=t.status==='playable'?label('Yes'):['missing','inaccessible'].includes(t.status)?label('No'):label('Unknown');
      return '<tr><td>'+esc(t.artist||'—')+'</td><td>'+playback+'<strong>'+esc(t.title||label('Untitled'))+'</strong><br><small class="subtle">'+esc(t.track_id)+'</small></td><td>'+esc(playable)+'</td><td>'+statusBadge(t.status)+'</td><td>'+esc(when)+'</td></tr>';
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
    node('scan').disabled=!selected;
    if(!selected){node('results').replaceChildren();node('counts').replaceChildren();node('state').textContent=label('Choose a saved collection snapshot');return;}
    const args=new URLSearchParams({source:selected,status:node('status').value,q:node('search').value,sort,direction,offset:String(offset)});
    node('state').textContent=label('Loading');
    try{
      const r=await api('/api/file-health?'+args,{feedback:false});
      if(request!==revision || selected!==chosen())return;
      renderCounts(r);renderRows(r);
      const time=r.scan_time?snapshotMoment(new Date(r.scan_time*1000).toISOString()):label('Not checked');
      node('state').textContent=label('Scan local files')+': '+label(r.scan_state)+' · '+label('Last checked')+': '+time;
    }catch(e){if(request===revision)node('state').textContent=e.message;}
  }
  async function load(){
    const request=++revision;
    const info=await api('/api/journeys',{feedback:false});
    if(request!==revision)return;
    const options=info.sources.filter(s=>/^(?:snapshot|capture):[0-9a-f]{32}$/u.test(s.id));
    const old=node('source').value;
    const current=window.Journeys?.context?.()?.source;
    node('source').innerHTML='<option value="">'+esc(label('Choose a saved collection snapshot'))+'</option>'+options.map(s=>'<option value="'+esc(s.id)+'">'+esc(s.label)+' · '+esc(snapshotMoment(s.created))+'</option>').join('');
    const wanted=[old,current].find(v=>options.some(s=>s.id===v)) || options[0]?.id || '';
    node('source').value=wanted;
    offset=0;await loadResults();
  }
  node('source').onchange=wrap(async()=>{offset=0;await loadResults();});
  node('status').onchange=wrap(async()=>{offset=0;await loadResults();});
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
  window.addEventListener('workbench-language',()=>{if(!node('source').closest('.view').hidden)void loadResults();});
  return {load};
})();