/* Explicit handoff and field review; no provider requests or audio writes. */
window.OneTaggerBridge=(()=>{
  const $=id=>document.getElementById('onetagger-'+id),t=key=>I18n.t(key);
  let snapshot='',selection='',offset=0,total=0,rows=[],scan=null,sequence=0,reviewSequence=0,busy=false;
  const selected=new Set();
  const post=(path,body)=>api('/api/onetagger'+path,{method:'POST',body:JSON.stringify(body)});
  function element(tag,text){
    const node=document.createElement(tag);
    if(text!==undefined)node.textContent=String(text);
    return node;
  }
  function table(headers){
    const node=element('table'),head=element('thead'),row=element('tr'),body=element('tbody');
    node.dataset.sortScope='server';
    for(const header of headers){
      const cell=element('th');
      if(typeof header==='string')cell.textContent=t(header);else cell.append(header);
      row.append(cell);
    }
    head.append(row);node.append(head,body);return {node,body};
  }
  function trackRows(){
    const page=element('input');page.type='checkbox';page.id='onetagger-page';
    page.setAttribute('aria-label',t('Select this page'));
    const result=table([page,'Track','Artist']);
    for(const track of rows){
      const row=element('tr'),choice=element('td'),title=element('td'),box=element('input');
      box.type='checkbox';box.dataset.onetaggerTrack=track.id;box.checked=selected.has(track.id);
      box.setAttribute('aria-label',t('Select track')+' · '+(track.title||track.id));
      box.onchange=()=>{
        if(box.checked && selected.size>=500){box.checked=false;return;}
        box.checked?selected.add(track.id):selected.delete(track.id);controls();
      };
      choice.append(box);title.textContent=track.title||track.id;
      title.append(element('br'),element('small',track.id));
      row.append(choice,title,element('td',track.artist||'—'));result.body.append(row);
    }
    page.onchange=()=>{
      for(const box of result.body.querySelectorAll('input')){box.checked=page.checked;box.onchange();}
    };
    $('tracks').replaceChildren(result.node);
  }
  function reviewRows(){
    const result=table(['Stage','Track','Field','Current value','Proposed value']);
    function message(row,text){
      const node=element('tr'),value=element('td',text);value.colSpan=3;
      node.append(element('td','—'),element('td',row.title||row.track_id),value);result.body.append(node);
    }
    for(const row of scan.rows){
      if(row.status==='unreadable'){message(row,row.error);continue;}
      if(row.warnings?.length)message(row,t('Tag warnings')+': '+row.warnings.map(w=>w.field+': '+w.reason).join(' · '));
      if(!row.changes.length){message(row,t('No tag changes'));continue;}
      for(const change of row.changes){
        const node=element('tr'),choice=element('td'),box=element('input');
        box.type='checkbox';box.dataset.onetaggerField=change.field;box.dataset.track=row.track_id;
        box.setAttribute('aria-label',t('Stage')+' · '+change.field+' · '+(row.title||row.track_id));
        box.onchange=controls;choice.append(box);
        const current=String(change.working_value??'—')+(change.replaces_staged_edit?' · '+t('Staged'):'');
        node.append(choice,element('td',row.title||row.track_id),element('td',t(change.field)),element('td',current),element('td',change.value??'—'));
        result.body.append(node);
      }
    }
    $('review').replaceChildren(result.node);
  }
  function controls(){
    for(const id of ['snapshot','selections','search','find','unlock','reviewed'])$(id).disabled=busy;
    for(const box of $('tracks').querySelectorAll('input'))box.disabled=busy;
    for(const box of $('review').querySelectorAll('input'))box.disabled=busy;
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
    trackRows();
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
    reviewRows();
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
