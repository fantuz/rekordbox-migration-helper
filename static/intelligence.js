/* Bounded views: server returns at most 50 rows; metadata never becomes markup. */
window.Intelligence=(()=>{
  let choices=null,last=null,offset=0,sourceRevision=0,requestRevision=0;
  const t=key=>I18n.t(key),e=value=>esc(value),node=id=>document.getElementById(id);
  function select(id,rows,label){const el=node(id),old=el.value;el.innerHTML='<option value="">'+e(t('Choose a snapshot'))+'</option>'+rows.map(r=>'<option value="'+e(r.id)+'">'+e(label(r))+'</option>').join('');if(rows.some(r=>r.id===old))el.value=old;}
  async function load(){
    const info=await api('/api/lab');choices=info.snapshots;
    for(const id of ['intelligence-source','intelligence-before','intelligence-after'])select(id,choices,r=>r.label+' · '+date(r.created));
    const shared=window.Journeys?.context?.();
    if(shared?.snapshot && choices.some(r=>r.id===shared.snapshot))node('intelligence-source').value=shared.snapshot;
    if(shared && !shared.snapshot)node('intelligence-source').value='';
    if(!shared && !node('intelligence-source').value && choices.length)node('intelligence-source').value=choices[0].id;
    await sourceChanged();
  }
  async function sourceChanged(){
    const revision=++sourceRevision;requestRevision++;
    node('intelligence-results').replaceChildren();last=null;node('intelligence-save').disabled=true;node('intelligence-download').hidden=true;
    node('intelligence-pagination').hidden=true;
    for(const id of ['intelligence-playlists','intelligence-session'])node(id).disabled=true;
    node('intelligence-playlist').replaceChildren();node('intelligence-history').replaceChildren();node('intelligence-history').disabled=true;node('intelligence-playlist').disabled=true;
    const snapshot=node('intelligence-source').value;if(!snapshot)return;
    const info=await api('/api/intelligence/options?'+new URLSearchParams({snapshot}));
    if(revision!==sourceRevision || snapshot!==node('intelligence-source').value)return;
    select('intelligence-playlist',info.playlists,r=>r.name);node('intelligence-playlist').disabled=false;
    select('intelligence-history',info.histories,r=>r.name+' · '+date(r.date));
    node('intelligence-history').disabled=!info.history_order;
    node('intelligence-session').disabled=!info.history_order;
    node('intelligence-playlists').disabled=info.playlists.length===0;
  }
  function table(headers,rows){return '<div class="lab-table"><table><thead><tr>'+headers.map(x=>'<th>'+e(t(x))+'</th>').join('')+'</tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(x=>'<td>'+e(x ?? '—')+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';}
  function render(data,kind){
    let html='<p class="callout">'+e(t(data.basis))+'</p>';
    if(kind==='playlists')html+=table(['Playlist','Shared tracks','Tracks','Overlap','Same order'],data.rows.map(r=>[r.name,num(r.common_tracks),num(r.tracks),I18n.number(r.jaccard*100,{maximumFractionDigits:1})+'%',r.same_saved_order===null?t('Unknown'):r.same_saved_order?t('Yes'):t('No')]));
    if(kind==='session')html+=table(['Position','Track','Artist','BPM','BPM change','Tonality','Track colour'],data.rows.map(r=>[r.sequence,r.title || t('Unknown'),r.artist,r.bpm,r.bpm_delta,r.tonality,r.color_name]));
    if(kind==='evolution' || kind==='duplicates'){
      html+='<div class="lab-summary">'+Object.entries(data).filter(([,v])=>typeof v==='number').map(([k,v])=>'<div><span>'+e(t(k.replaceAll('_',' ')))+'</span><b>'+num(v)+'</b></div>').join('')+'</div>';
      if(data.changed_fields)html+=table(['Field','Changed records'],Object.entries(data.changed_fields).map(([k,v])=>[I18n.field(k),num(v)]));
      if(data.unavailable_field_comparisons && Object.keys(data.unavailable_field_comparisons).length)html+='<h3>'+e(t('Unknown'))+'</h3>'+table(['Field','Tracks'],Object.entries(data.unavailable_field_comparisons).map(([k,v])=>[I18n.field(k),num(v)]));
      for(const field of ['genre','artist'])html+='<h3>'+e(I18n.field(field))+'</h3>'+table(['Name','Before','After','Change'],data.distributions[field].map(r=>[r.name || t('Unknown'),num(r.before),num(r.after),num(r.delta)]));
    }
    node('intelligence-results').innerHTML=html;
    const paged=kind==='playlists' || kind==='session';node('intelligence-pagination').hidden=!paged;
    node('intelligence-prev').disabled=!offset;node('intelligence-next').disabled=!paged || offset+50>=data.total;
    node('intelligence-count').textContent=paged?num(data.total)+' · '+num(Math.min(offset+1,data.total))+'–'+num(Math.min(offset+50,data.total)):'';
    node('intelligence-save').disabled=kind==='duplicates';
  }
  async function run(kind,reset=true){
    if(reset)offset=0;const revision=++requestRevision;
    const args={snapshot:node('intelligence-source').value,offset};let data;
    if(kind==='playlists'){args.playlist=node('intelligence-playlist').value;args.minimum=node('intelligence-threshold').value;}
    if(kind==='session')args.history=node('intelligence-history').value;
    if(kind==='evolution'){args.before=node('intelligence-before').value;args.after=node('intelligence-after').value;}
    if(kind==='duplicates')data=await api('/api/intelligence/duplicate-impact',{method:'POST',body:'{}'});
    else data=await api('/api/intelligence/'+kind+'?'+new URLSearchParams(args));
    if(revision!==requestRevision || (kind!=='evolution' && kind!=='duplicates' && args.snapshot!==node('intelligence-source').value) || (kind==='evolution' && (args.before!==node('intelligence-before').value || args.after!==node('intelligence-after').value)))return;
    last={kind,...args};render(data,kind);
  }
  function init(){
    node('intelligence-source').onchange=wrap(sourceChanged);
    for(const id of ['intelligence-before','intelligence-after'])node(id).onchange=()=>{requestRevision++;last=null;node('intelligence-results').replaceChildren();node('intelligence-save').disabled=true;node('intelligence-download').hidden=true;node('intelligence-pagination').hidden=true;};
    for(const kind of ['playlists','session','evolution','duplicates'])node('intelligence-'+kind).onclick=wrap(()=>run(kind));
    for(const [id,delta] of [['intelligence-prev',-50],['intelligence-next',50]])node(id).onclick=wrap(async()=>{offset=Math.max(0,offset+delta);await run(last.kind,false);});
    node('intelligence-save').onclick=wrap(async()=>{if(!last)return;const record=await api('/api/intelligence/report',{method:'POST',body:JSON.stringify(last)});node('intelligence-download').href=record.download;node('intelligence-download').hidden=false;notify(t('Evidence report saved'));});
  }
  return {init,load};
})();
