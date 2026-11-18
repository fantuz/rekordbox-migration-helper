/* Explicit handoff and field review; no provider requests or audio writes. */
window.OneTaggerBridge=(()=>{
  const $=id=>document.getElementById('onetagger-'+id),t=key=>I18n.t(key);
  let snapshot='',selection='',offset=0,total=0,rows=[],scan=null,sequence=0,reviewSequence=0,busy=false,languageRefresh=false,reviewStale=false;
  const selected=new Set();
  const post=(path,body)=>api('/api/onetagger'+path,{method:'POST',body:JSON.stringify(body)});
  const outcome=value=>t(({written:'Written',failed:'Failed',skipped:'Skipped',unprocessed:'Unprocessed'})[value]||'Unknown');
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
      if(row.report){
        const details=element('details'),summary=element('summary',t('OneTagger report')+' · '+outcome(row.report.status));
        details.append(summary,element('pre',JSON.stringify(row.report,null,2)));
        const node=element('tr'),cell=element('td');cell.colSpan=5;cell.append(details);node.append(cell);result.body.append(node);
      }
      if(row.status==='reported'){message(row,t('No tag writes reported')+' · '+outcome(row.report.status));continue;}
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
  function reportSummary(){
    const node=$('report-summary');node.replaceChildren();node.hidden=!scan;
    $('evidence').hidden=!scan;
    if(!scan)return;
    const summary=scan.summary||{};
    if(reviewStale)node.append(element('p',t('Review is outdated; import or rescan again.')));
    if(scan.report){
      node.append(element('h4',t('Imported OneTagger report')),
        element('p','OneTagger '+scan.report.application_version+' · '+scan.report.application_commit+' · '+scan.report.run_id));
      if(scan.report.cancelled)node.append(element('p',t('Cancelled run; review completed writes individually.')));
      node.append(element('p',t('Provider scores are reported evidence; review the independently read tags.')));
      const details=element('details');details.append(element('summary',t('Report evidence')),element('pre',JSON.stringify(scan.report,null,2)));node.append(details);
    }
    node.append(element('p',[[t('Verified tags'),summary.verified],[t('Not written'),summary.not_written],
      [t('Unverified files'),summary.unreadable],[t('Proposed fields'),summary.changes]].map(([label,count])=>label+': '+num(count||0)).join(' · ')));
  }
  function controls(){
    for(const id of ['snapshot','selections','search','find','unlock','reviewed'])$(id).disabled=busy;
    for(const box of $('tracks').querySelectorAll('input'))box.disabled=busy;
    for(const box of $('review').querySelectorAll('input'))box.disabled=busy || reviewStale;
    $('create').disabled=busy || !selected.size;$('selected').textContent=num(selected.size)+' / 500';
    $('prev').disabled=busy || !offset;$('next').disabled=busy || offset+50>=total;
    $('rescan').disabled=busy || !selection;
    $('report-file').disabled=busy || !selection;
    $('stage').disabled=busy || reviewStale || !scan || !$('reviewed').checked || !$('review').querySelector('input:checked');
  }
  async function load(){
    const revision=++sequence,chosen=$('snapshot').value||snapshot||window.BrowseState?.value('onetagger-snapshot')||'';
    const data=await api('/api/onetagger?'+new URLSearchParams({snapshot:chosen,q:$('search').value,offset:String(offset)}),{feedback:false});
    if(revision!==sequence)return;
    $('snapshot').replaceChildren(new Option(t('Choose a saved collection snapshot'),''),...data.snapshots.map(s=>new Option(s.label+' · '+snapshotMoment(s.created),s.id)));
    $('snapshot').value=data.snapshots.some(s=>s.id===chosen)?chosen:'';
    snapshot=$('snapshot').value;rows=data.tracks;total=data.total;
    trackRows();
    $('selections').replaceChildren(new Option(t('Choose a selection'),''),...data.selections.map(s=>new Option(snapshotMoment(s.created)+' · '+num(s.tracks),s.id)));
    $('selections').value=data.selections.some(s=>s.id===selection)?selection:'';selection=$('selections').value;
    $('playlist').hidden=$('manifest').hidden=!selection;
    $('playlist').href='/api/onetagger/'+encodeURIComponent(selection)+'/playlist';$('manifest').href='/api/onetagger/'+encodeURIComponent(selection)+'/manifest';controls();
    $('evidence').href='/api/onetagger/'+encodeURIComponent(selection)+'/review?download=1';
    await AudioPaths.load($('audio-paths'),snapshot?'snapshot:'+snapshot:'');
  }
  async function review(){
    const generation=++reviewSequence,id=selection;
    scan=null;reviewStale=false;$('review').replaceChildren();$('reviewed').checked=false;reportSummary();controls();if(!id)return;
    const data=await api('/api/onetagger/'+encodeURIComponent(id)+'/review',{feedback:false});
    if(generation!==reviewSequence || id!==selection)return;
    scan=data.scan;reviewStale=!!scan && data.edit_revision!==scan.edit_revision;reportSummary();if(!scan){controls();return;}
    reviewRows();
    controls();
  }
  async function action(work){busy=true;controls();try{await work();}finally{busy=false;controls();if(languageRefresh){languageRefresh=false;await load();await review();}}}
  $('snapshot').onchange=wrap(async()=>{snapshot=$('snapshot').value;selected.clear();selection='';scan=null;reviewSequence++;$('review').replaceChildren();reportSummary();offset=0;await load();});
  $('find').onclick=wrap(async()=>{offset=0;await load();});
  $('search').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();$('find').click();}};
  $('prev').onclick=wrap(async()=>{offset=Math.max(0,offset-50);await load();});
  $('next').onclick=wrap(async()=>{offset+=50;await load();});
  $('selections').onchange=wrap(async()=>{selection=$('selections').value;await load();await review();});
  $('create').onclick=wrap(()=>action(async()=>{
    const result=await post('/export',{snapshot,track_ids:[...selected]});selection=result.id;
    await load();await review();notify(t('Selection ready for OneTagger'));
  }));
  $('rescan').onclick=wrap(()=>action(async()=>{const result=await post('/'+encodeURIComponent(selection)+'/rescan',{});scan=null;$('review').replaceChildren();$('reviewed').checked=false;reportSummary();await poll(result.job);await review();}));
  $('report-file').onchange=wrap(()=>action(async()=>{
    const file=$('report-file').files[0];if(!file)return;
    const id=selection,source=snapshot;
    try{
      if(file.size>8*1024*1024)throw new Error(t('Choose a results report smaller than 8 MiB'));
      const result=await api('/api/onetagger/'+encodeURIComponent(id)+'/import-results',{method:'POST',body:file});
      scan=null;$('review').replaceChildren();$('reviewed').checked=false;reportSummary();
      await poll(result.job);
      if(id===selection && source===snapshot){await review();notify(t('OneTagger report ready for review'));}
    }finally{$('report-file').value='';}
  }));
  $('unlock').onclick=wrap(async()=>{
    await api('/api/lab/unlock',{method:'POST',body:JSON.stringify({snapshot,unlocked:true})});notify(t('Staging unlocked'));
  });
  $('reviewed').onchange=controls;
  $('stage').onclick=wrap(()=>action(async()=>{
    const changes=[...$('review').querySelectorAll('input:checked')].map(b=>({track_id:b.dataset.track,field:b.dataset.onetaggerField}));
    await post('/'+encodeURIComponent(selection)+'/stage',{changes,reviewed:$('reviewed').checked,review_revision:scan.review_revision,edit_revision:scan.edit_revision});
    await review();notify(t('Metadata staged locally'));
  }));
  window.addEventListener('workbench-language',()=>{if(!$('bridge').closest('.view').hidden){if(busy)languageRefresh=true;else void load().then(review).catch(error=>notify(error.message,true));}});
  window.addEventListener('workbench-audio-paths',()=>{reviewSequence++;scan=null;$('review').replaceChildren();reportSummary();controls();});
  controls();return {load};
})();

if(!document.getElementById('view-onetagger').hidden)OneTaggerBridge.load().catch(error=>notify(error.message,true));
