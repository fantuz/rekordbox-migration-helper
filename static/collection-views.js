/* Native captures share the collection selector; source files are never mutated. */
window.NativeCollection=(()=>{
  const revisions={review:0,reference:0};
  const state={review:{offset:0,basis:'path',q:'',sort:'count',direction:'desc',provider:'all',flag:window.BrowseState?.value('native-zero-filter')||''},reference:{offset:0,provider:'all',mode:'all',q:'',sort:'title',direction:'asc'}};
  const labels={unreviewed:'Unreviewed',keep_separate:'Keep separate',candidate:'Candidate for later cleanup'};
  const fileStates=['playable','missing','inaccessible','unverified'];
  const fileStateLabels={playable:'Accessible',missing:'Missing',inaccessible:'Inaccessible',unverified:'Unverified'};
  const fileBadge=status=>'<span class="file-status file-status-'+esc(status)+'">'+text(fileStateLabels[status] || 'Unverified')+'</span>';
  const source=()=>window.Journeys?.context()?.source || '';
  const active=()=>source().startsWith('capture:') || source().startsWith('snapshot:');
  const text=s=>esc(I18n.t(s));
  function setup(view){
    const host=$('#view-'+view);
    if(!host || host.querySelector('.native-collection'))return;
    const old=document.createElement('div');old.className='workspace-collection';
    while(host.firstChild)old.append(host.firstChild);host.append(old);
    const panel=document.createElement('div');panel.className='native-collection';panel.hidden=true;host.append(panel);
  }
  function playback(id){const s=source();return TrackPlayback.button(s.startsWith('snapshot:')?s.slice(9):s,id);}
  function track(t){return playback(t.id)+'<strong>'+esc(t.title || I18n.t('Untitled'))+'</strong>'+'<br><span>'+esc(t.artist || '')+'</span>';}
  function pager(view,data){
    const first=data.total?data.offset+1:0,last=Math.min(data.offset+50,data.total);
    return '<nav class="native-pagination" aria-label="'+text('Results pages')+'"><button type="button" class="button secondary" data-native-prev="'+view+'" '+(!data.offset?'disabled':'')+'>'+text('Previous')+'</button><span class="native-page-range" aria-live="polite">'+num(first)+'–'+num(last)+' '+text('of')+' '+num(data.total)+' '+text('results')+'</span><button type="button" class="button secondary" data-native-next="'+view+'" '+(data.offset+50>=data.total?'disabled':'')+'>'+text('Next')+'</button></nav>';
  }
  function heading(field,label,values,cssClass=''){
    const direction=values.sort===field?(values.direction==='asc'?'ascending':'descending'):'none';
    return '<th scope="col" class="'+esc(cssClass)+'" aria-sort="'+direction+'"><button type="button" class="result-sort-button native-global-sort" data-native-sort="'+esc(field)+'" title="'+text('Sort all results')+'" aria-label="'+text('Sort all results by')+' '+text(label)+'">'+text(label)+'</button></th>';
  }
  async function load(view){
    setup(view);const panel=$('#view-'+view+' .native-collection'),old=$('#view-'+view+' .workspace-collection');
    if(!panel)return;
    panel.hidden=!active();old.hidden=active();if(!active())return;
    const scope=source(),revision=++revisions[view],values=state[view];
    panel.setAttribute('aria-busy','true');
    // Preserve the current page while the next complete-dataset sort is requested.
    // api() displays the shared Loading / Waiting indicator for slow responses.
    if(!panel.querySelector('.native-table') || panel.dataset.loadedScope!==scope)
      panel.innerHTML='<p role="status">'+text('Loading')+'</p>';
    let r;
    try{
      r=await api('/api/collection/'+(view==='review'?'duplicates':'references')+'?'+new URLSearchParams({source:scope,...values,...DisplayPreferences.args()}));
    }finally{
      if(revision===revisions[view])panel.removeAttribute('aria-busy');
    }
    if(scope!==source() || revision!==revisions[view])return;
    ReviewWorkspace.dispose(panel.querySelector('.review-workspace'));
    panel.dataset.loadedScope=scope;
    const options=view==='review'?[['path','Same recorded path'],['metadata','Same artist and title']]:[['all','All references'],['changed','Original path differs'],['missing_path','No recorded current path']];
    panel.innerHTML=(view==='review'?'<div class="review-workspace native-review-workspace">':'')+'<article class="wide-card '+(view==='review'?'review-candidates':'')+'"><h2>'+text(view==='review'?'Captured duplicate candidates':'Captured file references')+'</h2>'+(view==='review'?'<details class="native-review-note"><summary>'+text('Details')+'</summary><p>'+esc(r.note)+'</p></details>':'<p class="callout">'+esc(r.note)+'</p>')+'<form class="native-filter"><label>'+text('Evidence')+'<select name="mode">'+options.map(([v,l])=>'<option value="'+v+'" '+(v===(values.basis || values.mode)?'selected':'')+'>'+text(l)+'</option>').join('')+'</select></label><label>'+text('Search')+'<input name="query" value="'+esc(values.q)+'"></label>'+CloudAnalysis.control('native-'+view+'-provider',values.provider)+'<button class="button">'+text('Apply')+'</button></form><p class="native-result-count">'+(view==='review'?num(r.groups)+' '+text('candidate groups')+' · '+num(r.tracks)+' '+text('tracks'):num(r.tracks)+' '+text('tracks')+' · '+num(r.changed)+' '+text('different original paths')+' · '+num(r.missing_path)+' '+text('empty current paths'))+'</p><div class="native-table"><table data-sort-scope="server"><thead><tr>'+(view==='review'?heading('title','Track',values)+heading('count','Records',values,'native-count')+heading('duration_spread','Duration spread',values,'native-spread')+heading('review','Review status',values,'native-review-state')+'<th scope="col" class="native-action">'+text('Review')+'</th>':heading('title','Track',values)+heading('current_path','Current path',values)+heading('original_path','Original path',values)+heading('analysis_path','Analysis path',values))+'</tr></thead><tbody>'+r.rows.map(t=>view==='review'?'<tr><td><strong>'+esc(t.title)+'</strong><br><span class="native-candidate-artist">'+esc(t.artist)+'</span></td><td class="native-count">'+num(t.count)+'</td><td class="native-spread">'+esc(t.duration_spread ?? I18n.t('Unknown'))+'</td><td class="native-review-state">'+text(labels[t.review] || 'Unreviewed')+'</td><td><button class="button secondary" data-native-group="'+esc(t.id)+'">'+text('Review')+'</button></td></tr>':'<tr><td>'+track(t)+'</td><td><code>'+esc(t.current_path || '')+'</code></td><td><code>'+esc(t.original_path || '')+'</code></td><td><code>'+esc(t.analysis_path || '')+'</code></td></tr>').join('')+'</tbody></table></div>'+pager(view,r)+'</article>'+(view==='review'?'<section class="native-detail" id="native-review-detail"><div class="detail-empty"><h3>'+text('Review')+'</h3><p>'+text('Compare captured records')+'</p></div></section></div>':'<div class="native-detail"></div>');
    if(view==='review'){
      const link=document.createElement('button');link.type='button';link.className='text-button';link.dataset.cleanupFrom='review';link.textContent=I18n.t('Collection cleanup');
      panel.querySelector('h2').after(link);
      const filters=document.createElement('div');filters.className='native-metadata-filters';filters.innerHTML=MetadataFlags.controls(r.flag_counts,values.flag);
      panel.querySelector('.native-review-note').insertAdjacentHTML('beforeend','<p>'+text('Filter groups containing flagged records. Keep all siblings visible for comparison.')+'</p>');
      panel.querySelector('.native-filter').after(filters);
      filters.querySelectorAll('[data-metadata-flag]').forEach(button=>button.onclick=wrap(async()=>{values.flag=button.dataset.metadataFlag;values.offset=0;BrowseState.set('native-zero-filter',values.flag);await load(view);}));
    }
    const providerControl=panel.querySelector('[data-cloud-analysis-provider]');CloudAnalysis.paint(providerControl,r.cloud?.counts);
    const display=document.createElement('div');display.innerHTML=DisplayPreferences.controls({keys:false,unknown:false,sidecars:true});panel.querySelector('.native-filter').append(display);DisplayPreferences.sync();
    const cloudHelp=I18n.t(CloudAnalysis.note),sidecarNote=DisplayPreferences.sidecarNote(r);
    if(view==='review'){
      const explanation=document.createElement('p');
      explanation.textContent=cloudHelp;
      panel.querySelector('.native-review-note').append(explanation);
    }
    const noteText=view==='review'?sidecarNote:[cloudHelp,sidecarNote].filter(Boolean).join(' · ');
    if(noteText){
      const note=document.createElement('p');
      note.className='subtle cloud-analysis-note';
      note.textContent=noteText;
      panel.querySelector('.native-filter').after(note);
    }
    panel.querySelector('form').onsubmit=wrap(async e=>{e.preventDefault();values.q=e.target.elements.query.value;values.provider=e.target.elements.provider.value;values[view==='review'?'basis':'mode']=e.target.elements.mode.value;values.offset=0;await load(view);});
    panel.querySelectorAll('[data-native-sort]').forEach(button=>button.onclick=wrap(async()=>{
      const field=button.dataset.nativeSort;
      values.direction=values.sort===field&&values.direction==='asc'?'desc':'asc';
      values.sort=field;values.offset=0;
      await load(view);
      panel.querySelector('[data-native-sort="'+field+'"]')?.focus({preventScroll:true});
    }));
    panel.querySelector('[data-native-prev]').onclick=wrap(async()=>{values.offset=Math.max(0,values.offset-50);await load(view);});
    panel.querySelector('[data-native-next]').onclick=wrap(async()=>{values.offset+=50;await load(view);});
    if(view==='review')ReviewWorkspace.refresh(panel.querySelector('.review-workspace'),panel.querySelector('.native-detail'),[],false);
    panel.querySelectorAll('[data-native-group]').forEach(b=>{b.setAttribute('aria-controls','native-review-detail');b.setAttribute('aria-current','false');b.onclick=wrap(()=>detail(b.dataset.nativeGroup,0,b));});
  }
  async function detail(id,offset=0,trigger=null){
    const scope=source(),revision=++revisions.review,basis=state.review.basis;
    const root=$('#view-review .native-review-workspace'),host=root.querySelector('.native-detail');
    host.innerHTML='<p>'+text('Loading')+'</p>';
    ReviewWorkspace.refresh(root,host);ReviewWorkspace.present(root,trigger);
    root.querySelectorAll('[data-native-group]').forEach(button=>button.setAttribute('aria-current',String(button.dataset.nativeGroup===id)));
    const r=await api('/api/collection/duplicates/'+encodeURIComponent(id)+'?'+new URLSearchParams({source:scope,basis,offset,...DisplayPreferences.args()}));
    if(scope!==source() || revision!==revisions.review)return;
    const hadFocus=host.contains(document.activeElement);
    const fields=[['duration','Duration'],['size','Recorded size (bytes)'],['rating','Rating'],['play_count','Play count'],['manual_cues','Manual cues'],['auto_cues','Automatic cues']];
    host.innerHTML='<article class="wide-card"><p class="native-review-scope">'+text('Review notes are saved locally. Merging and path edits require the XML + ZIP export workspace.')+'</p><div class="native-compare-records">'+r.rows.map(t=>'<article class="native-compare-record" data-file-track="'+esc(t.id)+'"><header>'+track(t)+'<span class="native-file-status">'+fileBadge('unverified')+'</span>'+MetadataFlags.badges(t)+'</header><dl>'+fields.map(([field,label])=>'<div><dt>'+text(label)+'</dt><dd>'+(field==='rating'?InlineRating.render(t.id,t.rating,scope):esc(t[field] ?? I18n.t('Unknown')))+'</dd></div>').join('')+'</dl><div class="native-record-path"><span>'+text('Current path')+'</span><code>'+esc(t.current_path || '')+'</code></div></article>').join('')+'</div>'+pager('detail',r)+'<div class="native-review-actions"><label>'+text('Review status')+'<select class="native-status">'+Object.entries(labels).map(([v,l])=>'<option value="'+v+'" '+(v===r.review?'selected':'')+'>'+text(l)+'</option>').join('')+'</select></label><button class="button native-save">'+text('Save review')+'</button></div></article>';
    host.querySelector('[data-native-prev]').onclick=wrap(()=>detail(id,Math.max(0,offset-50)));
    host.querySelector('[data-native-next]').onclick=wrap(()=>detail(id,offset+50));
    host.querySelector('.native-save').onclick=wrap(async()=>{
      const status=host.querySelector('select').value;
      await api('/api/collection/duplicates/'+encodeURIComponent(id)+'/review',{method:'POST',body:JSON.stringify({source:scope,basis,status})});
      if(scope!==source() || revision!==revisions.review || !root.isConnected || root.closest('[hidden]'))return;
      // Update only the affected row: replacing the whole list loses the
      // user's scroll position and can race with scroll anchoring in browsers.
      const trigger=[...root.querySelectorAll('[data-native-group]')].find(button=>button.dataset.nativeGroup===id);
      const cell=trigger?.closest('tr')?.querySelector('.native-review-state');
      if(cell)cell.textContent=I18n.t(labels[status] || 'Unreviewed');
      await detail(id,offset);notify(I18n.t('Review saved locally'));
    });
    ReviewWorkspace.refresh(root,host,['.native-review-actions']);
    // Availability is advisory: a record is never deleted or excluded
    // automatically because a disk is disconnected or access is denied.
    const evidence=document.createElement('div');
    evidence.className='native-file-evidence';
    evidence.innerHTML='<p>'+text('Local file evidence is advisory; unavailable files are not duplicates to delete.')+'</p><div class="native-file-summary" role="status"></div><label>'+text('File evidence')+'<select class="native-file-filter"><option value="all">'+text('All records')+'</option>'+fileStates.map(k=>'<option value="'+k+'">'+text(fileStateLabels[k])+'</option>').join('')+'</select></label><button type="button" class="button secondary native-file-refresh">'+text('Refresh file evidence')+'</button>';
    const cards=host.querySelector('.native-compare-records');
    cards.before(evidence);
    const selector=evidence.querySelector('.native-file-filter');
    const refresh=evidence.querySelector('.native-file-refresh');
    let current=null;
    selector.onchange=()=>{
      for(const card of cards.querySelectorAll('[data-file-track]'))
        card.hidden=Boolean(current && selector.value!=='all' && current[card.dataset.fileTrack]!==selector.value);
    };
    function paintEvidence(){
      const counts=Object.fromEntries(fileStates.map(k=>[k,0]));
      for(const card of cards.querySelectorAll('[data-file-track]')){
        const status=current?.[card.dataset.fileTrack]||'unverified';counts[status]++;
        card.querySelector('.native-file-status').innerHTML=fileBadge(status);
      }
      evidence.querySelector('.native-file-summary').innerHTML=fileStates.map(k=>fileBadge(k)+' '+num(counts[k])).join(' · ');selector.onchange();
    }
    cards.addEventListener('workbench-file-status',event=>{
      const card=event.target.closest('[data-file-track]');if(!card || !fileStates.includes(event.detail?.status))return;
      current={...current,[card.dataset.fileTrack]:event.detail.status};paintEvidence();
    });
    async function loadEvidence(refreshNow=false){
      const ids=r.rows.map(t=>String(t.id));
      if(!ids.length)return;
      refresh.disabled=true;
      try{
        const evidenceResult=await api('/api/playback/availability',{feedback:false,method:'POST',
          body:JSON.stringify({source:scope,track_ids:ids,refresh:refreshNow})});
        if(scope!==source() || revision!==revisions.review || !host.isConnected)return;
        current=evidenceResult.statuses;
        const counts=Object.fromEntries(fileStates.map(k=>[k,0]));
        for(const card of cards.querySelectorAll('[data-file-track]')){
          const status=current[card.dataset.fileTrack] || 'unverified';
          counts[status]++;
          card.querySelector('.native-file-status').innerHTML=fileBadge(status);
        }
        evidence.querySelector('.native-file-summary').innerHTML=fileStates.map(k=>fileBadge(k)+' '+num(counts[k])).join(' · ');
        selector.onchange();
      }catch{
        // Local-only access may be unavailable in a remote browser.
        evidence.querySelector('.native-file-summary').textContent=I18n.t('File evidence unavailable');
      }finally{refresh.disabled=false;}
    }
    refresh.onclick=wrap(()=>loadEvidence(true));
    void loadEvidence();
    if(hadFocus)host.querySelector('.review-panel-heading h3').focus({preventScroll:true});
  }
  function update(view){
    if(active() && ['statistics','review','reference'].includes(view)){$('#collection-metrics').hidden=true;$('.dataset-bar').hidden=true;}
    if(['review','reference'].includes(view))return load(view).catch(e=>notify(e.message,true));
  }
  window.addEventListener('workbench-context',()=>{
    for(const v of ['review','reference']){state[v].offset=0;revisions[v]++;}
    const view=$('.view:not([hidden])')?.id?.replace('view-','');
    if(view==='statistics')renderStatistics().catch(e=>notify(e.message,true));
    update(view);
    if(view==='history')loadHistory().catch(e=>notify(e.message,true));
  });
  window.addEventListener('workbench-display-preferences',()=>{
    const view=$('.view:not([hidden])')?.id?.replace('view-','');
    if(active()&&['review','reference'].includes(view)){state[view].offset=0;void load(view).catch(error=>notify(error.message,true));}
  });
  return {active,source,update};
})();

window.Investigations=(()=>{
  let preview=null,revision=0;
  const text=s=>esc(I18n.t(s));
  const keys=()=>[...document.querySelectorAll('[data-investigation]:checked')].map(e=>e.value);
  async function load(){
    const version=++revision;preview=null;
    const data=await api('/api/investigations');if(version!==revision)return;
    const host=$('#investigations-content');
    host.innerHTML='<p class="callout">'+text('Archive saved investigations to remove them from active menus. Restore a cleanup below. Original libraries, music, uploaded inputs and exports are preserved. Archives retain their disk space.')+'</p><div class="action-row"><button class="button" id="investigations-preview">'+text('Preview cleanup')+'</button><button class="button secondary" id="investigations-refresh">'+text('Refresh')+'</button></div><div id="investigation-preview"></div>'+[...new Set(data.items.map(i=>i.kind))].map(kind=>'<fieldset><legend><label><input type="checkbox" data-investigation-kind="'+kind+'">'+esc(kind)+'</label></legend>'+data.items.filter(i=>i.kind===kind).map(i=>'<label class="investigation-row"><input type="checkbox" data-investigation="'+kind+'" value="'+esc(i.key)+'" '+(i.blocked?'disabled':'')+'><span><strong>'+esc(i.label)+'</strong><small>'+esc(date(i.created))+' · '+esc(i.id)+(i.blocked?' · '+esc(i.blocked):'')+'</small></span></label>').join('')+'</fieldset>').join('')+'<h3>'+text('Restore archived investigations')+'</h3>'+data.archives.map(a=>'<p>'+esc(date(a.created))+' · '+num(a.items)+' '+text('items')+' <button class="button secondary" data-restore-investigations="'+a.id+'">'+text('Restore cleanup')+'</button></p>').join('');
    host.querySelectorAll('[data-investigation-kind]').forEach(c=>c.onchange=()=>{host.querySelectorAll('[data-investigation="'+c.dataset.investigationKind+'"]:not(:disabled)').forEach(i=>i.checked=c.checked);invalidate();});
    host.querySelectorAll('[data-investigation]').forEach(c=>c.onchange=invalidate);
    $('#investigations-refresh').onclick=wrap(load);
    $('#investigations-preview').onclick=wrap(async()=>{
      const selection=keys();const r=await api('/api/investigations/preview',{method:'POST',body:JSON.stringify({keys:selection})});
      if(JSON.stringify(selection)!==JSON.stringify(keys()))return;
      preview={keys:selection,token:r.token};$('#investigation-preview').innerHTML='<article class="wide-card"><h3>'+text('Cleanup preview')+'</h3><p>'+esc(r.note)+'</p><ul>'+r.items.map(i=>'<li>'+esc(i.kind)+' · '+esc(i.label)+'</li>').join('')+'</ul>'+r.blockers.map(b=>'<p class="callout">'+esc(b.key)+' · '+esc(b.reason)+'</p>').join('')+'<button class="button" id="investigations-confirm" '+(r.blockers.length?'disabled':'')+'>'+text('Archive selected investigations')+'</button></article>';
      $('#investigations-confirm').onclick=wrap(async()=>{if(!preview)return;await api('/api/investigations/archive',{method:'POST',body:JSON.stringify(preview)});await refreshLists();});
    });
    host.querySelectorAll('[data-restore-investigations]').forEach(b=>b.onclick=wrap(async()=>{await api('/api/investigations/'+b.dataset.restoreInvestigations+'/restore',{method:'POST',body:'{}'});await refreshLists();}));
    if(window.WorkspaceMaintenance)await WorkspaceMaintenance.load(data);
  }
  function invalidate(){preview=null;$('#investigation-preview').innerHTML='';}
  async function refreshLists(){await load();await Journeys.load();await loadAnalyzer();await loadLab();await loadWorkspace();notify(I18n.t('Saved investigations updated'));}
  return {load};
})();
