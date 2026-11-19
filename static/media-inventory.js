let inventoryOffset=0,inventoryRevision=0,inventoryWorkspace='',inventoryRootsReady=false,inventoryLastSettings='',inventoryScanPending=false;
const inventoryDrafts=new Map();
const inventoryLabels={found:'Reference candidate',available:'Playable',review:'Needs review',ambiguous:'Several candidates',not_found:'Absent from scanned roots',cloud_only:'Cloud placeholder',unverified:'Unverified'};
const mediaRoots=()=>$$('#media-roots .media-root').map(row=>({root:row.querySelector('.media-folder').value.trim(),recorded_prefix:row.querySelector('.media-prefix').value.trim(),export_uri:row.querySelector('.media-export').value.trim()}));
// Canonical fields/order: Flask may sort response object keys. Property order
// alone must not make an unchanged completed scan appear stale.
const inventorySettingsFor=(roots,advanced)=>JSON.stringify({roots:roots.filter(row=>row.root).map(row=>({root:row.root || '',recorded_prefix:row.recorded_prefix || '',export_uri:row.export_uri || ''})),advanced:Boolean(advanced)});
const inventorySettings=()=>inventorySettingsFor(mediaRoots(),$('#media-advanced').checked);
function updateInventorySettings(){
  const dirty=Boolean(inventoryLastSettings && inventorySettings()!==inventoryLastSettings);
  $('#scan-media').disabled=!session || busy || inventoryScanPending || !mediaRoots().some(row=>row.root);
  $('#inventory-settings-note').textContent=dirty?I18n.t('Settings changed. Results below still describe the last scan.'):'';
  $('#inventory-settings').dataset.changed=String(dirty);
  const active=!session?0:!inventoryLastSettings || dirty || inventoryScanPending?1:2;
  $$('#view-inventory .inventory-steps li').forEach((step,index)=>{
    step.dataset.state=index===active?'current':index<active?'complete':'pending';
    if(index===active)step.setAttribute('aria-current','step');else step.removeAttribute('aria-current');
  });
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
  row.querySelector('.media-folder').autocomplete='off';
  row.querySelector('.media-remove').setAttribute('aria-label',I18n.t('Remove folder from next scan'));
  row.oninput=updateInventorySettings;
  $("#media-roots").append(row);
  updateInventorySettings();
}
addMediaRoot();
$("#add-media-root").onclick=()=>addMediaRoot();
$('#media-advanced').onchange=updateInventorySettings;
$("#scan-media").onclick=wrap(async()=>{
  if (!session || busy || inventoryScanPending) return;
  const roots=mediaRoots().filter(row=>row.root);
  if(!roots.length){notify(I18n.t('Choose folders, then scan to check this library.'));return;}
  const workspace=session.id;
  inventoryScanPending=true;updateInventorySettings();
  try{
    const result=await api("/api/inventory/scan",{method:"POST",body:JSON.stringify({roots,workspace,advanced:$('#media-advanced').checked})});
    const done=await poll(result.job);
    if(session?.id!==workspace)return;
    // Keep the form draft: users may edit the next search before the progress
    // dialog opens or while the post-scan refresh is awaiting other views.
    // Results retain their submitted roots and the dirty-state note identifies
    // any difference instead of replacing newly entered paths.
    inventoryOffset=0;await refresh();await loadInventory();
    notify(num(done.files)+" "+I18n.t("media files indexed")+(done.warnings.length?" "+I18n.t("· some folders need attention"):""));
  }finally{inventoryScanPending=false;updateInventorySettings();}
});
function inventoryStageNote(row,canStage){
  if(row.staged_uri && row.staged_uri===row.candidates[0]?.export_uri)return I18n.t('Staged export reference');
  if(canStage)return I18n.t('Review suggestions before staging. Audio identity has not been verified.');
  if(row.status==='found')return I18n.t('Set an exported reference prefix, then scan again to enable staging.');
  if(row.status==='available')return I18n.t('This reference is already playable at its recorded path.');
  if(row.status==='cloud_only')return I18n.t('Cloud placeholders are not downloaded by this search.');
  if(row.status==='not_found')return I18n.t('No candidate was found in the scanned folders. Check other drives or cloud storage.');
  if(row.status==='unverified')return I18n.t('Search was incomplete. Review the folder warnings and scan again.');
  return I18n.t('Several candidates or conflicting evidence need review before staging.');
}
async function loadInventory() {
  $('#inventory-library').textContent=session?.name || I18n.t('Load a library pair to begin.');
  $('#scan-media').disabled=!session || busy;
  const context=window.Journeys?.context?.();
  $('#inventory-context-note').textContent=context && context.scope_key!=='session:'+session?.id?I18n.t('Snapshot tools use Collection context; this page keeps the loaded XML + ZIP workspace.')+' '+I18n.t('Collection context')+': '+context.label:'';
  if (!session){
    ++inventoryRevision;for(const id of ['counts','warnings','range'])$('#inventory-'+id).replaceChildren();
    $('#inventory-list').innerHTML='<p class="inventory-empty">'+esc(I18n.t('Load an XML + ZIP workspace to search its media references.'))+'</p>';
    $('#inventory-report').hidden=true;$('#inventory-scan-state').textContent=I18n.t('Not checked');
    $('#inventory-prev').disabled=true;$('#inventory-more').disabled=true;updateInventorySettings();return;
  }
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
  inventoryLastSettings=result.scan_id?inventorySettingsFor(result.roots || [],result.advanced):'';
  updateInventorySettings();
  const evidence={mapped_path_and_size:'Mapped path and size',filename_and_size:'Filename and size',tags_and_duration:'Tags and duration'};
  const all=Object.values(result.counts).reduce((sum,n)=>sum+Number(n),0),currentStatus=$('#inventory-status').value;
  const counts=[['all',all],...Object.entries(result.counts)];
  $('#inventory-counts').innerHTML=result.scan_id?counts.map(([name,n])=>'<article><button type="button" class="inventory-count" data-inventory-status="'+esc(name)+'" aria-pressed="'+(currentStatus===name)+'"><span>'+esc(I18n.t(name==='all'?'All records':inventoryLabels[name]||'Unknown'))+'</span><strong>'+num(n)+'</strong></button></article>').join(''):'';
  $$('[data-inventory-status]').forEach(button=>button.onclick=wrap(async()=>{$('#inventory-status').value=button.dataset.inventoryStatus;inventoryOffset=0;await loadInventory();}));
  $('#inventory-scan-state').textContent=result.scan_id?I18n.t(result.complete===false || result.warnings?.length?'Incomplete search':'Complete')+' · '+I18n.t('Last scan · audio files: {files} · folders: {folders}',{files:result.file_count,folders:result.roots?.length || 0}):I18n.t('Not checked');
  $('#inventory-warnings').textContent=(result.warnings||[]).join('\n');
  $('#inventory-report').hidden=!result.scan_id;
  $('#inventory-list').innerHTML=result.rows.map(r=>{
    const candidates=r.candidates.map(c=>'<li><code>'+esc(c.path)+'</code><small>'+esc((c.evidence||[r.evidence]).map(k=>I18n.t(evidence[k]||'Unknown')).join(' · '))+'</small>'+(c.tags?'<small>'+esc(c.tags.artist)+' · '+esc(c.tags.title)+' · '+esc(String(Math.round(c.tags.duration)))+' s</small>':'')+(c.export_uri?'<small>'+esc(I18n.t('Exported reference prefix · required for staging'))+'</small><code>'+esc(c.export_uri)+'</code>':'')+'</li>').join('');
    const staged=r.staged_uri && r.staged_uri===r.candidates[0]?.export_uri;
    const canStage=Boolean(staged || (result.scan_id&&r.status==='found'&&r.candidates[0]?.export_uri));
    const reason=inventoryStageNote(r,canStage);
    return '<div class="inventory-row" data-inventory-state="'+esc(r.status)+'"><div class="inventory-track">'+TrackPlayback.button('',r.track_id,workspace)+esc(r.title)+'<small>'+esc(r.artist)+'</small>'+(r.recorded_path?'<details class="inventory-recorded"><summary>'+esc(I18n.t('Recorded reference'))+'</summary><code>'+esc(r.recorded_path)+'</code></details>':'')+'</div><span class="inventory-status">'+esc(I18n.t(inventoryLabels[r.status]||'Unknown'))+'</span><div><small>'+num(r.candidate_count)+' '+esc(I18n.t('results'))+'</small><ul class="recovery-candidates">'+candidates+'</ul></div><div class="inventory-reference-action"><button class="button secondary small" data-inventory-ref="'+esc(r.track_id)+'" data-undo="'+Boolean(staged)+'" '+(canStage?'':'disabled')+'>'+esc(I18n.t(staged?'Undo':'Stage reference'))+'</button><small>'+esc(reason)+'</small></div></div>';
  }).join('') || '<p>'+esc(I18n.t('No inventory items in this view.'))+'</p>';
  if(!result.scan_id)$('#inventory-list').innerHTML='<p class="inventory-empty">'+esc(I18n.t('Scan folders to see reference candidates.'))+'</p>';
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
