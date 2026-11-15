/* Native captures share the collection selector; source files are never mutated. */
window.NativeCollection=(()=>{
  const revisions={review:0,reference:0};
  const state={review:{offset:0,basis:'path',q:''},reference:{offset:0,mode:'all',q:''}};
  const labels={unreviewed:'Unreviewed',keep_separate:'Keep separate',candidate:'Candidate for later cleanup'};
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
  function pager(view,data){return '<div class="action-row"><button class="button secondary" data-native-prev="'+view+'" '+(!data.offset?'disabled':'')+'>'+text('Previous')+'</button><span>'+num(data.total)+' '+text('results')+'</span><button class="button secondary" data-native-next="'+view+'" '+(data.offset+50>=data.total?'disabled':'')+'>'+text('Next')+'</button></div>';}
  async function load(view){
    setup(view);const panel=$('#view-'+view+' .native-collection'),old=$('#view-'+view+' .workspace-collection');
    if(!panel)return;
    panel.hidden=!active();old.hidden=active();if(!active())return;
    const scope=source(),revision=++revisions[view],values=state[view];
    ReviewWorkspace.dispose(panel.querySelector('.review-workspace'));
    panel.innerHTML='<p>'+text('Loading')+'</p>';
    const r=await api('/api/collection/'+(view==='review'?'duplicates':'references')+'?'+new URLSearchParams({source:scope,...values}));
    if(scope!==source() || revision!==revisions[view])return;
    const options=view==='review'?[['path','Same recorded path'],['metadata','Same artist and title']]:[['all','All references'],['changed','Original path differs'],['missing_path','No recorded current path']];
    panel.innerHTML=(view==='review'?'<div class="review-workspace native-review-workspace">':'')+'<article class="wide-card '+(view==='review'?'review-candidates':'')+'"><h2>'+text(view==='review'?'Captured duplicate candidates':'Captured file references')+'</h2><p class="callout">'+esc(r.note)+'</p><form class="native-filter"><label>'+text('Evidence')+'<select name="mode">'+options.map(([v,l])=>'<option value="'+v+'" '+(v===(values.basis || values.mode)?'selected':'')+'>'+text(l)+'</option>').join('')+'</select></label><label>'+text('Search')+'<input name="query" value="'+esc(values.q)+'"></label><button class="button">'+text('Apply')+'</button></form><p>'+(view==='review'?num(r.groups)+' '+text('candidate groups')+' · '+num(r.tracks)+' '+text('tracks'):num(r.tracks)+' '+text('tracks')+' · '+num(r.changed)+' '+text('different original paths')+' · '+num(r.missing_path)+' '+text('empty current paths'))+'</p><div class="native-table"><table><thead><tr>'+(view==='review'?'<th>'+text('Track')+'</th><th>'+text('Review status')+'</th><th>'+text('Review')+'</th>':'<th>'+text('Track')+'</th><th>'+text('Current path')+'</th><th>'+text('Original path')+'</th><th>'+text('Analysis path')+'</th>')+'</tr></thead><tbody>'+r.rows.map(t=>view==='review'?'<tr><td><strong>'+esc(t.title)+'</strong><br>'+esc(t.artist)+'<small>'+num(t.count)+' '+text('Records')+' · '+text('Duration spread')+': '+esc(t.duration_spread ?? I18n.t('Unknown'))+'</small></td><td>'+text(labels[t.review] || 'Unreviewed')+'</td><td><button class="button secondary" data-native-group="'+esc(t.id)+'">'+text('Review')+'</button></td></tr>':'<tr><td>'+track(t)+'</td><td><code>'+esc(t.current_path || '')+'</code></td><td><code>'+esc(t.original_path || '')+'</code></td><td><code>'+esc(t.analysis_path || '')+'</code></td></tr>').join('')+'</tbody></table></div>'+pager(view,r)+'</article>'+(view==='review'?'<section class="native-detail" id="native-review-detail"><div class="detail-empty"><h3>'+text('Review')+'</h3><p>'+text('Compare captured records')+'</p></div></section></div>':'<div class="native-detail"></div>');
    panel.querySelector('form').onsubmit=wrap(async e=>{e.preventDefault();values.q=e.target.elements.query.value;values[view==='review'?'basis':'mode']=e.target.elements.mode.value;values.offset=0;await load(view);});
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
    const r=await api('/api/collection/duplicates/'+encodeURIComponent(id)+'?'+new URLSearchParams({source:scope,basis,offset}));
    if(scope!==source() || revision!==revisions.review)return;
    const hadFocus=host.contains(document.activeElement);
    host.innerHTML='<article class="wide-card"><h3>'+text('Compare captured records')+'</h3><p>'+text('Review notes are saved locally. Merging and path edits require the XML + ZIP export workspace.')+'</p><div class="native-table"><table><thead><tr>'+['Track','Duration','Rating','Play count','Manual cues','Automatic cues','Current path'].map(t=>'<th>'+text(t)+'</th>').join('')+'</tr></thead><tbody>'+r.rows.map(t=>'<tr><td>'+track(t)+'</td>'+['duration','rating','play_count','manual_cues','auto_cues'].map(f=>'<td>'+esc(t[f] ?? I18n.t('Unknown'))+'</td>').join('')+'<td><code>'+esc(t.current_path)+'</code></td></tr>').join('')+'</tbody></table></div>'+pager('detail',r)+'<div class="native-review-actions"><label>'+text('Review status')+'<select class="native-status">'+Object.entries(labels).map(([v,l])=>'<option value="'+v+'" '+(v===r.review?'selected':'')+'>'+text(l)+'</option>').join('')+'</select></label><button class="button native-save">'+text('Save review')+'</button></div></article>';
    host.querySelector('[data-native-prev]').onclick=wrap(()=>detail(id,Math.max(0,offset-50)));
    host.querySelector('[data-native-next]').onclick=wrap(()=>detail(id,offset+50));
    host.querySelector('.native-save').onclick=wrap(async()=>{
      const listScroll=root.querySelector('.review-candidates>.native-table').scrollTop;
      await api('/api/collection/duplicates/'+encodeURIComponent(id)+'/review',{method:'POST',body:JSON.stringify({source:scope,basis,status:host.querySelector('select').value})});
      if(scope!==source() || revision!==revisions.review || !root.isConnected || root.closest('[hidden]'))return;
      await load('review');
      if(scope!==source() || revisions.review!==revision+1 || $('#view-review').hidden)return;
      $('#view-review .review-candidates>.native-table').scrollTop=listScroll;
      await detail(id,offset);notify(I18n.t('Review saved locally'));
    });
    ReviewWorkspace.refresh(root,host,['.native-review-actions']);
    if(hadFocus)host.querySelector('.review-panel-heading h3').focus({preventScroll:true});
  }
  function update(view){
    if(active() && ['statistics','review','reference'].includes(view)){$('#collection-metrics').hidden=true;$('.dataset-bar').hidden=true;}
    if(['review','reference'].includes(view))load(view).catch(e=>notify(e.message,true));
  }
  window.addEventListener('workbench-context',()=>{
    for(const v of ['review','reference']){state[v].offset=0;revisions[v]++;}
    const view=$('.view:not([hidden])')?.id?.replace('view-','');
    if(view==='statistics')renderStatistics().catch(e=>notify(e.message,true));
    update(view);
    if(view==='history')loadHistory().catch(e=>notify(e.message,true));
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
