/* Path discovery only inventories names. Selecting a result never starts analysis. */
const pathLines=value=>[...new Set(value.split(/\r?\n/).map(v=>v.trim()).filter(Boolean))];
let locationHints=null;
function appendPath(selector,path){
  const field=$(selector),values=pathLines(field.value);if(!values.includes(path))values.push(path);
  if(values.length>20)throw new Error(I18n.t("Use up to twenty paths per search or audit"));
  field.value=values.join('\n');
}
function discoveryPanel(prefix,title,kind){
  return '<details class="discovery-panel"><summary>'+esc(title)+("</summary><p>"+esc(I18n.t("Search folders you choose, including an already-mounted Windows volume on Linux. The app does not mount disks. Close rekordbox and pause sync before capturing a discovered database."))+"</p><label>"+esc(I18n.t("Search roots · one absolute folder per line"))+"<textarea id=\"")+prefix+("-roots\" rows=\"2\" placeholder=\""+esc(I18n.t("Full folder path"))+"\"></textarea></label><div id=\"")+prefix+("-mounts\" class=\"discovery-hints\"></div><div class=\"lab-actions\"><label>"+esc(I18n.t("Search depth"))+"<select id=\"")+prefix+("-depth\"><option value=\"5\">"+esc(I18n.t("5 folders deep"))+"</option><option value=\"8\" selected>"+esc(I18n.t("8 folders deep"))+"</option><option value=\"12\">"+esc(I18n.t("12 folders deep"))+"</option></select></label><button class=\"button secondary\" id=\"")+prefix+("-scan\" type=\"button\">"+esc(I18n.t("Search selected folders"))+"</button></div><p class=\"subtle\">"+esc(I18n.t("Names and file metadata only. Limited to 15 seconds, 12,000 folders and 200,000 entries. Links and online-only subfolders are skipped. A narrow root gives better coverage."))+"</p><div id=\"")+prefix+'-results" aria-live="polite"></div></details>';
}
$('#refresh-source-locations').insertAdjacentHTML('afterend',discoveryPanel('source-discovery',I18n.t("Find libraries in custom folders or mounted volumes"),'libraries'));
$('#source-discovery-roots').closest('details').insertAdjacentHTML('beforebegin','<details id="cloud-locations" class="discovery-panel"><summary data-i18n="Cloud library locations">'+esc(I18n.t('Cloud library locations'))+'</summary><p data-i18n="Suggestions only. Choosing a folder does not start analysis.">'+esc(I18n.t('Suggestions only. Choosing a folder does not start analysis.'))+'</p><div id="cloud-location-results" aria-live="polite"></div><div class="action-row"><button type="button" class="button secondary" id="cloud-locations-refresh" data-i18n="Refresh">'+esc(I18n.t('Refresh'))+'</button><a class="button secondary" href="/api/cloud-locations/report" data-i18n="Download JSON report ↓">'+esc(I18n.t('Download JSON report ↓'))+'</a></div></details>');
const cloudEvidence={dropbox_config:'Provider configuration',windows_registration:'Windows registration',folder_name:'Folder name only',file_provider_folder:'Folder name only',volume_label:'Volume label'};
function renderCloudLocations(data){
  const host=$('#cloud-location-results'),roots=data?.roots || [],libraries=data?.libraries || [],moves=data?.relocations || [];
  host.innerHTML=roots.map((r,i)=>'<div class="detected-source"><div><strong>'+esc(I18n.t(r.kind==='dropbox'?'Dropbox':'Google Drive'))+'</strong><code>'+esc(r.root)+'</code><small>'+esc(I18n.t(cloudEvidence[r.evidence] || 'Unknown'))+' · '+esc(I18n.t(r.availability==='local'?'Accessible':'Cloud placeholder'))+'</small></div><button type="button" class="text-button" data-cloud-root="'+i+'" '+(r.availability==='local'?'':'disabled')+'>'+esc(I18n.t('Add'))+'</button></div>').join('') || '<p>'+esc(I18n.t('No local cloud folders detected. You can enter a path manually.'))+'</p>';
  host.insertAdjacentHTML('beforeend',libraries.map((r,i)=>'<div class="detected-source"><div><code>'+esc(r.path)+'</code><small>'+esc(r.databases.join(', '))+'</small></div><button type="button" class="button secondary small" data-cloud-library="'+i+'">'+esc(I18n.t('Use this library'))+'</button></div>').join(''));
  if(moves.length)host.insertAdjacentHTML('beforeend','<h4>'+esc(I18n.t('Possible library relocation'))+'</h4>'+moves.map((r,i)=>'<div class="detected-source"><div><code>'+esc(r.previous_path)+'</code><span aria-hidden="true">↓</span><code>'+esc(r.candidate_path)+'</code><small>'+esc(I18n.t(r.ambiguous?'Several candidates':'Needs review'))+' · '+esc(I18n.t('Matching directory suffix'))+'</small></div><button class="button secondary small" type="button" data-cloud-move="'+i+'">'+esc(I18n.t('Use this library'))+'</button></div>').join(''));
  if(!data?.recorded_locations)host.insertAdjacentHTML('beforeend','<p class="subtle">'+esc(I18n.t('No previous location was recorded; relocation is not established.'))+'</p>');
  host.insertAdjacentHTML('beforeend','<p class="subtle">'+esc(I18n.t('Folder and settings evidence does not verify library identity.'))+(data?.partial?' '+esc(I18n.t('· Partial search')):'')+'</p>');
  host.querySelectorAll('[data-cloud-root]').forEach(b=>b.onclick=()=>{
    appendPath('#source-discovery-roots',roots[Number(b.dataset.cloudRoot)].root);
    $('#source-discovery-roots').closest('details').open=true;$('#source-discovery-roots').focus();
  });
  for(const [attribute,items,field] of [['cloudLibrary',libraries,'path'],['cloudMove',moves,'candidate_path']])
    host.querySelectorAll(attribute==='cloudLibrary'?'[data-cloud-library]':'[data-cloud-move]').forEach(b=>b.onclick=()=>{
      $('#analyzer-path').value=items[Number(b.dataset[attribute])][field];$('#analyzer-path').focus();
    });
}
$('#cloud-locations-refresh').onclick=wrap(async()=>renderDiscoveryHints(await api('/api/discovery?fresh=true')));
const assetInput=$('#lab-assets-path');
assetInput.outerHTML=("<textarea id=\"lab-assets-path\" rows=\"3\" placeholder=\""+esc(I18n.t("One absolute folder or ZIP path per line"))+"\"></textarea>");
$('#lab-assets-path').closest('label').firstChild.textContent=I18n.t("Analysis folders or backup ZIPs · up to 20 paths");
$('#lab-assets-path').closest('label').insertAdjacentHTML('afterend','<div id="asset-location-hints" class="discovery-hints"></div>'+discoveryPanel('asset-discovery',I18n.t("Find analysis and STEMS-related asset locations"),'assets'));
async function renderDiscoveryHints(data){
  locationHints=data || await api('/api/discovery');
  renderCloudLocations(locationHints.cloud_locations);
  for(const prefix of ['source-discovery','asset-discovery']){
    $('#'+prefix+'-mounts').innerHTML=(locationHints.mounted_roots || []).map((r,i)=>'<button class="text-button" type="button" data-mount-root="'+prefix+'" data-mount-index="'+i+("\">"+esc(I18n.t("Add"))+" "+"")+esc(r.path)+'</button>').join('');
  }
  $$('[data-mount-root]').forEach(b=>b.onclick=wrap(()=>appendPath('#'+b.dataset.mountRoot+'-roots',locationHints.mounted_roots[Number(b.dataset.mountIndex)].path)));
  const options=[...(locationHints.analysis_paths || [])];
  if(session?.metadata?.zip_path)options.unshift({path:session.metadata.zip_path,get origin(){return I18n.t("Loaded backup ZIP");}});
  $('#asset-location-hints').innerHTML=options.map((r,i)=>'<button class="text-button" type="button" data-asset-hint="'+i+("\">"+esc(I18n.t("Add"))+" "+"")+esc(r.path)+'</button>').join('') || ("<span class=\"subtle\">"+esc(I18n.t("Enter paths manually, or use the bounded search below. A backup ZIP can be audited directly."))+"</span>");
  $$('[data-asset-hint]').forEach(b=>b.onclick=wrap(()=>appendPath('#lab-assets-path',options[Number(b.dataset.assetHint)].path)));
}
async function runDiscovery(prefix,kind){
  const start=await api('/api/discovery/scan',{method:'POST',body:JSON.stringify({roots:pathLines($('#'+prefix+'-roots').value),depth:Number($('#'+prefix+'-depth').value),kind})});
  const r=await poll(start.job),rows=kind==='assets'?r.analysis_paths:r.libraries,target=$('#'+prefix+'-results');
  target.innerHTML='<p><b>'+num(rows.length)+' locations</b> · '+num(r.directories_visited)+" "+I18n.t("folders checked")+(r.partial?" "+I18n.t("· Partial search"):'')+'</p>'+r.warnings.map(w=>'<p class="subtle">'+esc(w)+'</p>').join('')+rows.slice(0,40).map((item,i)=>'<div class="detected-source"><code>'+esc(item.path)+'</code><small>'+esc(item.kind || item.databases.join(', '))+'</small><button class="text-button" type="button" data-discovery-choice="'+prefix+'" data-choice-index="'+i+'">'+(kind==='assets'?I18n.t("Add to audit"):I18n.t("Use this library"))+'</button></div>').join('')+(rows.length>40?("<p class=\"subtle\">"+esc(I18n.t("Showing the first 40 locations. Choose a narrower root or download the full report."))+"</p>"):'')+'<a class="button secondary small" href="'+esc(r.download)+("\">"+esc(I18n.t("Download search report ↓"))+"</a>");
  $$('[data-discovery-choice="'+prefix+'"]').forEach(b=>b.onclick=wrap(()=>{const path=rows[Number(b.dataset.choiceIndex)].path;if(kind==='assets')appendPath('#lab-assets-path',path);else $('#analyzer-path').value=path;}));
}
$('#source-discovery-scan').onclick=wrap(()=>runDiscovery('source-discovery','libraries'));
$('#asset-discovery-scan').onclick=wrap(()=>runDiscovery('asset-discovery','assets'));
