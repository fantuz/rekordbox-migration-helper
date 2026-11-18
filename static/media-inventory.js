let inventoryOffset=0,inventoryRevision=0,inventoryWorkspace='',inventoryRootsReady=false,inventoryLastSettings='';
const inventoryDrafts=new Map();
const mediaRoots=()=>$$('#media-roots .media-root').map(row=>({root:row.querySelector('.media-folder').value.trim(),recorded_prefix:row.querySelector('.media-prefix').value.trim(),export_uri:row.querySelector('.media-export').value.trim()}));
const inventorySettings=()=>JSON.stringify({roots:mediaRoots().filter(row=>row.root),advanced:$('#media-advanced').checked});
function updateInventorySettings(){
  $('#scan-media').disabled=!session || busy || !mediaRoots().some(row=>row.root);
  $('#inventory-settings-note').textContent=inventoryLastSettings && inventorySettings()!==inventoryLastSettings?I18n.t('Settings changed. Results below still describe the last scan.'):'';
}
function addMediaRoot(root={}) {
  $('#media-roots .inventory-empty')?.remove();
  const row=document.createElement("div");row.className="media-root";
  row.innerHTML='<label>'+esc(I18n.t('Folder on this computer'))+'<input class="media-folder" placeholder="/home/you/Music or D:\\Music" value="'+esc(root.root||'')+'"></label><button type="button" class="button secondary small media-remove">'+esc(I18n.t('Remove'))+'</button><details><summary>'+esc(I18n.t('Optional path mapping'))+'</summary><div><label>'+esc(I18n.t('Recorded prefix · optional'))+'<input class="media-prefix" placeholder="C:/Users/you/Music" value="'+esc(root.recorded_prefix||'')+'"></label><label>'+esc(I18n.t('Exported reference prefix · required for staging'))+'<input class="media-export" placeholder="file://localhost/D:/Music" value="'+esc(root.export_uri||'')+'"></label></div></details>';
  row.querySelector('.media-remove').onclick=()=>{
    const next=row.nextElementSibling || row.previousElementSibling;
    row.remove();
    if(!$('#media-roots .media-root'))$('#media-roots').innerHTML='<p class="inventory-empty">'+esc(I18n.t('Choose folders, then scan to check this library.'))+'</p>';
    updateInventorySettings();(next?.querySelector('input') || $('#add-media-root')).focus();
  };
  row.oninput=updateInventorySettings;
  $("#media-roots").append(row);
  updateInventorySettings();
}
addMediaRoot();
$("#add-media-root").onclick=()=>addMediaRoot();
$('#media-advanced').onchange=updateInventorySettings;
$("#scan-media").onclick=wrap(async()=>{
  if (!session || busy) return;
  const roots=mediaRoots().filter(row=>row.root);
  if(!roots.length){notify(I18n.t('Choose folders, then scan to check this library.'));return;}
  const workspace=session.id;
  const result=await api("/api/inventory/scan",{method:"POST",body:JSON.stringify({roots,workspace,advanced:$('#media-advanced').checked})});
  const done=await poll(result.job);
  if(session?.id!==workspace)return;
  inventoryOffset=0;inventoryRootsReady=false;inventoryDrafts.delete(workspace);await refresh();await loadInventory();
  notify(num(done.files)+" "+I18n.t("media files indexed")+(done.warnings.length?" "+I18n.t("· some folders need attention"):""));
});
async function loadInventory() {
  $('#inventory-library').textContent=session?.name || I18n.t('Load a library pair to begin.');
  $('#scan-media').disabled=!session || busy;
  const context=window.Journeys?.context?.();
  $('#inventory-context-note').textContent=context && context.scope_key!=='session:'+session?.id?I18n.t('Collection context')+': '+context.label:'';
  if (!session){++inventoryRevision;for(const id of ['counts','list','warnings','range'])$('#inventory-'+id).replaceChildren();$('#inventory-report').hidden=true;$('#inventory-scan-state').textContent=I18n.t('Not checked');return;}
  if(inventoryWorkspace!==session.id){
    if(inventoryWorkspace)inventoryDrafts.set(inventoryWorkspace,{roots:mediaRoots(),advanced:$('#media-advanced').checked});
    inventoryWorkspace=session.id;inventoryOffset=0;inventoryLastSettings='';
    const draft=inventoryDrafts.get(inventoryWorkspace);inventoryRootsReady=Boolean(draft);
    $('#media-roots').replaceChildren();
    if(draft){for(const root of draft.roots)addMediaRoot(root);$('#media-advanced').checked=draft.advanced;}
  }
  const revision=++inventoryRevision,workspace=session.id;
  const result=await api("/api/inventory?"+new URLSearchParams({offset:inventoryOffset,status:$("#inventory-status").value,q:$("#inventory-search").value,...CollectionSort.args("inventory")}));
  if(revision!==inventoryRevision || session?.id!==workspace)return;
  if(!inventoryRootsReady){
    $('#media-roots').replaceChildren();for(const root of result.roots?.length?result.roots:[{}])addMediaRoot(root);
    $('#media-advanced').checked=Boolean(result.advanced);inventoryRootsReady=true;
  }
  inventoryLastSettings=result.scan_id?JSON.stringify({roots:result.roots || [],advanced:Boolean(result.advanced)}):'';
  updateInventorySettings();
  const labels={found:'Found',available:'Playable',review:'Needs review',ambiguous:'Several candidates',not_found:'Absent from scanned roots',cloud_only:'Cloud placeholder',unverified:'Unverified'};
  const evidence={mapped_path_and_size:'Mapped path and size',filename_and_size:'Filename and size',tags_and_duration:'Tags and duration'};
  $('#inventory-counts').innerHTML=Object.entries(result.counts).map(([name,n])=>'<article><span>'+esc(I18n.t(labels[name]||'Unknown'))+'</span><strong>'+num(n)+'</strong></article>').join('');
  $('#inventory-scan-state').textContent=I18n.t(result.scan_id?(result.complete===false?'Incomplete search':'Complete'):'Not checked');
  $('#inventory-warnings').textContent=(result.warnings||[]).join('\n');
  $('#inventory-report').hidden=!result.scan_id;
  $('#inventory-list').innerHTML=result.rows.map(r=>{
    const candidates=r.candidates.map(c=>'<li><code>'+esc(c.path)+'</code><small>'+esc((c.evidence||[r.evidence]).map(k=>I18n.t(evidence[k]||'Unknown')).join(' · '))+'</small>'+(c.tags?'<small>'+esc(c.tags.artist)+' · '+esc(c.tags.title)+' · '+esc(String(Math.round(c.tags.duration)))+' s</small>':'')+'<code>'+esc(c.export_uri||'')+'</code></li>').join('');
    const staged=r.staged_uri && r.staged_uri===r.candidates[0]?.export_uri;
    return '<div class="inventory-row"><div>'+TrackPlayback.button('',r.track_id,workspace)+esc(r.title)+'<small>'+esc(r.artist)+'</small></div><span>'+esc(I18n.t(labels[r.status]||'Unknown'))+'</span><div><small>'+num(r.candidate_count)+' '+esc(I18n.t('results'))+'</small><ul class="recovery-candidates">'+candidates+'</ul></div><button class="button secondary small" data-inventory-ref="'+esc(r.track_id)+'" data-undo="'+Boolean(staged)+'" '+(staged||(result.scan_id&&r.status==='found'&&r.candidates[0]?.export_uri)?'':'disabled')+'>'+esc(I18n.t(staged?'Undo':'Stage reference'))+'</button></div>';
  }).join('') || '<p>'+esc(I18n.t('No inventory items in this view.'))+'</p>';
  $$('[data-inventory-ref]').forEach(b=>b.onclick=wrap(async()=>{
    if(session?.id!==workspace)return;
    const done=await api('/api/inventory/stage',{method:'POST',body:JSON.stringify({track_id:b.dataset.inventoryRef,workspace,scan_id:result.scan_id,undo:b.dataset.undo==='true'})});
    if(session?.id!==workspace)return;
    session=done.session;renderSession();await loadInventory();
  }));
  CollectionSort.list('#inventory-list','inventory',['title','artist','status','candidate_count'],async()=>{inventoryOffset=0;await loadInventory();});
  $('#inventory-report').href='/api/inventory/report?'+new URLSearchParams({workspace});
  $("#inventory-range").textContent=result.total?num(inventoryOffset+1)+"–"+num(Math.min(inventoryOffset+50,result.total))+" "+I18n.t("of")+" "+num(result.total)+(" "+I18n.t("References")+""):I18n.t("No matching references");
  $("#inventory-more").disabled=inventoryOffset+50>=result.total;
  $('#inventory-prev').disabled=!inventoryOffset;
}
$('#inventory-prev').onclick=wrap(async()=>{inventoryOffset=Math.max(0,inventoryOffset-50);await loadInventory();});
$("#inventory-more").onclick=wrap(async()=>{inventoryOffset+=50;await loadInventory();});
$("#inventory-status").onchange=wrap(async()=>{inventoryOffset=0;await loadInventory();});
$("#inventory-search").onchange=wrap(async()=>{inventoryOffset=0;await loadInventory();});
window.addEventListener('workbench-language',()=>{if(!$('#view-inventory').hidden)void loadInventory();});
window.addEventListener('workbench-context',()=>{if(!$('#view-inventory').hidden)void loadInventory();});
