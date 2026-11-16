/* Explicit handoff and field review; no provider requests or audio writes. */
window.OneTaggerBridge=(()=>{
  const $=id=>document.getElementById('onetagger-'+id),t=key=>I18n.t(key);
  let snapshot='',selection='',offset=0,total=0,rows=[],scan=null,sequence=0,reviewSequence=0,busy=false;
  const selected=new Set();
  const post=(path,body)=>api('/api/onetagger'+path,{method:'POST',body:JSON.stringify(body)});
  function controls(){
    $('create').disabled=busy || !selected.size;$('selected').textContent=num(selected.size)+' / 500';
    $('prev').disabled=busy || !offset;$('next').disabled=busy || offset+50>=total;
    $('rescan').disabled=busy || !selection;
    $('stage').disabled=busy || !scan || !$('reviewed').checked || !$('review').querySelector('input:checked');
  }
  async function load(){
    const revision=++sequence,chosen=$('snapshot').value||snapshot;
    const data=await api('/api/onetagger?'+new URLSearchParams({snapshot:chosen,q:$('search').value,offset:String(offset)}),{feedback:false});
    if(revision!==sequence)return;
    $('snapshot').replaceChildren(new Option(t('Choose a saved collection snapshot'),''),...data.snapshots.map(s=>new Option(s.label+' · '+snapshotMoment(s.created),s.id)));
    $('snapshot').value=data.snapshots.some(s=>s.id===chosen)?chosen:'';
    snapshot=$('snapshot').value;rows=data.tracks;total=data.total;
    $('tracks').innerHTML='<table data-sort-scope="server"><thead><tr><th><input type="checkbox" id="onetagger-page" aria-label="'+esc(t('Select this page'))+'"></th><th>'+esc(t('Track'))+'</th><th>'+esc(t('Artist'))+'</th></tr></thead><tbody>'+rows.map(r=>'<tr><td><input type="checkbox" data-onetagger-track="'+esc(r.id)+'" aria-label="'+esc(t('Select track'))+' · '+esc(r.title||r.id)+'"'+(selected.has(r.id)?' checked':'')+'></td><td>'+esc(r.title||r.id)+'<br><small>'+esc(r.id)+'</small></td><td>'+esc(r.artist||'—')+'</td></tr>').join('')+'</tbody></table>';
    for(const box of $('tracks').querySelectorAll('[data-onetagger-track]'))box.onchange=()=>{if(box.checked && selected.size>=500){box.checked=false;return;}box.checked?selected.add(box.dataset.onetaggerTrack):selected.delete(box.dataset.onetaggerTrack);controls();};
    $('page').onchange=()=>{for(const box of $('tracks').querySelectorAll('[data-onetagger-track]')){box.checked=$('page').checked;box.onchange();}};
    $('selections').replaceChildren(new Option(t('Choose a selection'),''),...data.selections.map(s=>new Option(snapshotMoment(s.created)+' · '+num(s.tracks),s.id)));
    $('selections').value=data.selections.some(s=>s.id===selection)?selection:'';selection=$('selections').value;
    $('playlist').hidden=$('manifest').hidden=!selection;
    $('playlist').href='/api/onetagger/'+selection+'/playlist';$('manifest').href='/api/onetagger/'+selection+'/manifest';controls();
  }
  async function review(){
    const generation=++reviewSequence,id=selection;
    scan=null;$('review').replaceChildren();$('reviewed').checked=false;controls();if(!id)return;
    const data=await api('/api/onetagger/'+id+'/review',{feedback:false});
    if(generation!==reviewSequence || id!==selection)return;
    scan=data.scan;if(!scan){controls();return;}
    $('review').innerHTML='<table data-sort-scope="server"><thead><tr><th>'+esc(t('Stage'))+'</th><th>'+esc(t('Track'))+'</th><th>'+esc(t('Field'))+'</th><th>'+esc(t('Current value'))+'</th><th>'+esc(t('Proposed value'))+'</th></tr></thead><tbody>'+scan.rows.map(row=>row.status==='unreadable'?'<tr><td>—</td><td>'+esc(row.title||row.track_id)+'</td><td colspan="3">'+esc(row.error)+'</td></tr>':(row.warnings?.length?'<tr><td>—</td><td>'+esc(row.title||row.track_id)+'</td><td colspan="3">'+esc(t('Tag warnings'))+': '+esc(row.warnings.map(w=>w.field+': '+w.reason).join(' · '))+'</td></tr>':'')+(row.changes.length?row.changes.map(c=>'<tr><td><input type="checkbox" data-onetagger-field="'+esc(c.field)+'" data-track="'+esc(row.track_id)+'" aria-label="'+esc(t('Stage'))+' · '+esc(c.field)+' · '+esc(row.title||row.track_id)+'"></td><td>'+esc(row.title||row.track_id)+'</td><td>'+esc(t(c.field))+'</td><td>'+esc(c.working_value??'—')+(c.replaces_staged_edit?' · '+esc(t('Staged')):'')+'</td><td>'+esc(c.value??'—')+'</td></tr>').join(''):'<tr><td>—</td><td>'+esc(row.title||row.track_id)+'</td><td colspan="3">'+esc(t('No tag changes'))+'</td></tr>')).join('')+'</tbody></table>';
    for(const box of $('review').querySelectorAll('input'))box.onchange=controls;
    controls();
  }
  async function action(work){busy=true;controls();try{await work();}finally{busy=false;controls();}}
  $('snapshot').onchange=wrap(async()=>{snapshot=$('snapshot').value;selected.clear();selection='';scan=null;reviewSequence++;$('review').replaceChildren();offset=0;await load();});
  $('find').onclick=wrap(async()=>{offset=0;await load();});
  $('search').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();$('find').click();}};
  $('prev').onclick=wrap(async()=>{offset=Math.max(0,offset-50);await load();});
  $('next').onclick=wrap(async()=>{offset+=50;await load();});
  $('selections').onchange=wrap(async()=>{selection=$('selections').value;await load();await review();});
  $('create').onclick=wrap(()=>action(async()=>{
    const result=await post('/export',{snapshot,track_ids:[...selected]});selection=result.id;
    await load();await review();notify(t('Selection ready for OneTagger'));
  }));
  $('rescan').onclick=wrap(()=>action(async()=>{const result=await post('/'+selection+'/rescan',{});await poll(result.job);await review();}));
  $('unlock').onclick=wrap(async()=>{
    await api('/api/lab/unlock',{method:'POST',body:JSON.stringify({snapshot,unlocked:true})});notify(t('Staging unlocked'));
  });
  $('reviewed').onchange=controls;
  $('stage').onclick=wrap(()=>action(async()=>{
    const changes=[...$('review').querySelectorAll('input:checked')].map(b=>({track_id:b.dataset.track,field:b.dataset.onetaggerField}));
    await post('/'+selection+'/stage',{changes,reviewed:$('reviewed').checked,review_revision:scan.review_revision,edit_revision:scan.edit_revision});
    notify(t('Metadata staged locally'));scan=null;$('review').replaceChildren();$('reviewed').checked=false;
  }));
  window.addEventListener('workbench-language',()=>{if(!$('bridge').closest('.view').hidden)void load().then(review);});
  window.addEventListener('workbench-audio-paths',()=>{reviewSequence++;scan=null;$('review').replaceChildren();controls();});
  controls();return {load};
})();
