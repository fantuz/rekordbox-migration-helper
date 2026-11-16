/* Bounded views: server returns at most 50 rows; metadata never becomes markup. */
window.Intelligence=(()=>{
  let choices=null,last=null,offset=0,sourceRevision=0,requestRevision=0;
  const t=key=>I18n.t(key),e=value=>esc(value),node=id=>document.getElementById(id);
  function select(id,rows,label){const el=node(id),old=el.value || window.BrowseState?.value(id);el.innerHTML='<option value="">'+e(t('Choose a snapshot'))+'</option>'+rows.map(r=>'<option value="'+e(r.id)+'">'+e(label(r))+'</option>').join('');if(rows.some(r=>r.id===old))el.value=old;}
  async function load(){
    const [info,context]=await Promise.all([api('/api/lab'),api('/api/journeys')]);
    choices=[...info.snapshots,...context.sources.filter(r=>r.id.startsWith('capture:'))];
    for(const id of ['intelligence-source','intelligence-before','intelligence-after'])select(id,choices,r=>r.label+' · '+date(r.created));
    const shared=window.Journeys?.context?.();
    const selected=shared?.snapshot || (shared?.source?.startsWith('capture:')?shared.source:'');
    if(shared && !node('intelligence-source').value)node('intelligence-source').value=choices.some(r=>r.id===selected)?selected:'';
    node('intelligence-duplicates').disabled=!info.workspace || Boolean(shared && shared.source!=='workspace');
    if(!shared && !node('intelligence-source').value && choices.length)node('intelligence-source').value=choices[0].id;
    if(last?.snapshot===node('intelligence-source').value){await run(last.kind,false);return;}
    await sourceChanged();
  }
  async function sourceChanged(){
    const revision=++sourceRevision;requestRevision++;
    window.BrowseState?.remember();
    if(node('intelligence-source').value)node('intelligence-duplicates').disabled=true;
    window.EnrichmentExports?.reset();
    node('intelligence-results').replaceChildren();last=null;node('intelligence-save').disabled=true;node('intelligence-download').hidden=true;
    node('intelligence-pagination').hidden=true;
    for(const id of ['intelligence-playlists','intelligence-session','intelligence-contents','intelligence-lenses'])node(id).disabled=true;
    node('intelligence-playlist').replaceChildren();node('intelligence-history').replaceChildren();node('intelligence-history').disabled=true;node('intelligence-playlist').disabled=true;
    const snapshot=node('intelligence-source').value;if(!snapshot)return;
    const info=await api('/api/intelligence/options?'+new URLSearchParams({snapshot}));
    if(revision!==sourceRevision || snapshot!==node('intelligence-source').value)return;
    select('intelligence-playlist',info.playlists,r=>r.name+' · '+num(r.entries));node('intelligence-playlist').disabled=false;
    select('intelligence-history',info.histories,r=>r.name+' · '+date(r.date));
    const historyAvailable=info.history_details && info.history_order && info.histories.length>0;
    node('intelligence-history').disabled=!historyAvailable;
    node('intelligence-session').disabled=!historyAvailable;
    node('intelligence-playlists').disabled=info.playlists.length===0;
    node('intelligence-contents').disabled=info.playlists.length===0;node('intelligence-lenses').disabled=false;
    for(const option of node('intelligence-lens').options)option.disabled=(['recurring','history_absent'].includes(option.value)&&!info.history_details)||(option.value==='unfiled'&&!info.playlist_membership);
    if(node('intelligence-lens').selectedOptions[0]?.disabled)node('intelligence-lens').value='all';
  }
  function table(headers,rows,tracks=[],titleColumn=-1){return '<div class="lab-table"><table><thead><tr>'+headers.map(x=>'<th>'+e(t(x))+'</th>').join('')+'</tr></thead><tbody>'+rows.map((row,i)=>'<tr>'+row.map((x,j)=>'<td>'+(j===titleColumn?TrackPlayback.button(node('intelligence-source').value,tracks[i]?.track_id):'')+e(x ?? '—')+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';}
  function render(data,kind){
    let html='<p class="callout">'+e(t(data.basis))+'</p>';
    if(kind==='playlists')html+=table(['Playlist','Shared tracks','Tracks','Overlap','Same order'],data.rows.map(r=>[r.name,num(r.common_tracks),num(r.tracks),I18n.number(r.jaccard*100,{maximumFractionDigits:1})+'%',r.same_saved_order===null?t('Unknown'):r.same_saved_order?t('Yes'):t('No')]));
    if(kind==='contents')html+='<h3>'+e(data.playlist.name)+'</h3>'+labSummary(data.summary)+table(['Position','Track','Artist','Genre','BPM','Rating'],data.rows.map(r=>[r.sequence,r.title || t('Unknown'),r.artist,r.genre,r.bpm,r.rating]),data.rows,1);
    if(kind==='lenses')html+=labSummary(data.summary)+table(['Track','Artist','Genre','Playlists','Saved sessions','Entries'],data.rows.map(r=>[r.title,r.artist,r.genre,r.playlists,r.saved_sessions,r.saved_entries]),data.rows,0);
    if(kind==='session')html+=table(['Position','Track','Artist','BPM','BPM change','Tonality','Track colour'],data.rows.map(r=>[r.sequence,r.title || t('Unknown'),r.artist,r.bpm,r.bpm_delta,r.tonality,r.color_name]),data.rows,1);
    if(kind==='evolution' || kind==='duplicates'){
      html+='<div class="lab-summary">'+Object.entries(data).filter(([,v])=>typeof v==='number').map(([k,v])=>'<div><span>'+e(t(k.replaceAll('_',' ')))+'</span><b>'+num(v)+'</b></div>').join('')+'</div>';
      if(data.changed_fields)html+=table(['Field','Changed records'],Object.entries(data.changed_fields).map(([k,v])=>[I18n.field(k),num(v)]));
      if(data.unavailable_field_comparisons && Object.keys(data.unavailable_field_comparisons).length)html+='<h3>'+e(t('Unknown'))+'</h3>'+table(['Field','Tracks'],Object.entries(data.unavailable_field_comparisons).map(([k,v])=>[I18n.field(k),num(v)]));
      for(const field of ['genre','artist'])html+='<h3>'+e(I18n.field(field))+'</h3>'+table(['Name','Before','After','Change'],data.distributions[field].map(r=>[r.name || t('Unknown'),num(r.before),num(r.after),num(r.delta)]));
    }
    node('intelligence-results').innerHTML=html;
    const fields={playlists:['name','common_tracks','tracks','jaccard','same_saved_order'],
      contents:['sequence','title','artist','genre','bpm','rating','file_status'],
      lenses:['title','artist','genre','playlists','saved_sessions','saved_entries','file_status'],
      session:['sequence','title','artist','bpm','bpm_delta','tonality','color_name','file_status']};
    if(fields[kind])CollectionSort.bind('#intelligence-results','intelligence-'+kind,fields[kind],data.rows,()=>run(kind));
    const paged=['playlists','session','contents','lenses'].includes(kind);node('intelligence-pagination').hidden=!paged;
    node('intelligence-prev').disabled=!offset;node('intelligence-next').disabled=!paged || offset+50>=data.total;
    node('intelligence-count').textContent=paged?num(data.total)+' · '+num(Math.min(offset+1,data.total))+'–'+num(Math.min(offset+50,data.total)):'';
    node('intelligence-save').disabled=kind==='duplicates';
  }
  async function run(kind,reset=true){
    if(reset)offset=0;const revision=++requestRevision;
    const args={snapshot:node('intelligence-source').value,offset,...CollectionSort.args('intelligence-'+kind)};let data;
    if(kind==='playlists'){args.playlist=node('intelligence-playlist').value;args.minimum=node('intelligence-threshold').value;}
    if(kind==='contents'){args.playlist=node('intelligence-playlist').value;args.q=node('intelligence-search').value;}
    if(kind==='lenses'){args.lens=node('intelligence-lens').value;args.q=node('intelligence-search').value;}
    if(kind==='session')args.history=node('intelligence-history').value;
    if(kind==='evolution'){args.before=node('intelligence-before').value;args.after=node('intelligence-after').value;}
    if(kind==='duplicates')data=await api('/api/intelligence/duplicate-impact',{method:'POST',body:'{}'});
    else data=await api('/api/intelligence/'+kind+'?'+new URLSearchParams(args));
    if(revision!==requestRevision || (kind!=='evolution' && kind!=='duplicates' && args.snapshot!==node('intelligence-source').value) || (kind==='evolution' && (args.before!==node('intelligence-before').value || args.after!==node('intelligence-after').value)))return;
    last={kind,...args};render(data,kind);
    if(kind==='contents' && reset && !node('view-intelligence').hidden){
      const results=node('intelligence-results');results.tabIndex=-1;
      results.focus({preventScroll:true});
      results.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});
    }
  }
  function init(){
    node('intelligence-source').onchange=wrap(sourceChanged);
    for(const id of ['intelligence-before','intelligence-after'])node(id).onchange=()=>{requestRevision++;last=null;node('intelligence-results').replaceChildren();node('intelligence-save').disabled=true;node('intelligence-download').hidden=true;node('intelligence-pagination').hidden=true;};
    for(const kind of ['playlists','session','evolution','duplicates','contents','lenses'])node('intelligence-'+kind).onclick=wrap(()=>run(kind));
    for(const [id,delta] of [['intelligence-prev',-50],['intelligence-next',50]])node(id).onclick=wrap(async()=>{offset=Math.max(0,offset+delta);await run(last.kind,false);});
    node('intelligence-save').onclick=wrap(async()=>{if(!last)return;const record=await api('/api/intelligence/report',{method:'POST',body:JSON.stringify(last)});node('intelligence-download').href=record.download;node('intelligence-download').hidden=false;notify(t('Evidence report saved'));});
  }
  return {init,load};
})();
