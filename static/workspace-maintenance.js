/* Explicit cache clearing, reversible fresh starts and separately confirmed archive deletion. */
window.WorkspaceMaintenance=(()=>{
  let version=0;
  const text=key=>esc(I18n.t(key)),post=(path,data={})=>api('/api/investigations/'+path,{method:'POST',body:JSON.stringify(data)});
  async function load(inventory){
    const revision=++version,cache=await api('/api/investigations/cache');if(revision!==version)return;
    $('#workspace-maintenance')?.remove();
    const section=document.createElement('section');section.id='workspace-maintenance';section.className='wide-card';
    section.innerHTML='<h3>'+text('Workspace maintenance')+'</h3><p>'+text('Reuse saved reports without scanning again. Clear caches to recompute views; original libraries and exports are kept.')+'</p><p>'+num(cache.results)+' · '+text('Cached results')+' · '+esc(bytes(cache.bytes))+' · '+num(cache.provider_entries)+' · MusicBrainz</p><div class="action-row"><button class="button secondary" id="maintenance-cache">'+text('Clear result and provider caches')+'</button><button class="button secondary" id="maintenance-fresh">'+text('Start fresh with an archive')+'</button><button class="button secondary" id="maintenance-purge" '+(!inventory.archives.length?'disabled':'')+'>'+text('Delete archived investigations')+'</button></div><div id="maintenance-preview"></div>';
    $('#investigations-content').prepend(section);
    $('#maintenance-cache').onclick=wrap(async()=>{await post('cache/clear');await Investigations.load();});
    $('#maintenance-fresh').onclick=wrap(async()=>{
      const result=await post('preview',{fresh:true});if(revision!==version)return;
      $('#maintenance-preview').innerHTML='<h4>'+text('Start fresh with an archive')+'</h4><p>'+text('All current investigations and staged metadata edits move into a recoverable archive. Loaded workspaces are detached. Original libraries, audio, inputs and completed exports stay unchanged.')+'</p><ul>'+result.items.map(row=>'<li>'+esc(row.kind)+' · '+esc(row.label)+'</li>').join('')+'</ul>'+result.blockers.map(row=>'<p class="callout">'+esc(row.reason)+'</p>').join('')+'<label><input type="checkbox" id="maintenance-ack">'+text('I reviewed the listed changes')+'</label><button disabled class="button" id="maintenance-confirm">'+text('Start fresh with an archive')+'</button>';
      $('#maintenance-ack').onchange=()=>{$('#maintenance-confirm').disabled=!$('#maintenance-ack').checked || result.blockers.length>0;};
      $('#maintenance-confirm').onclick=wrap(async()=>{
        if(!$('#maintenance-ack').checked)return;
        await post('archive',{fresh:true,token:result.token});
        preferences.remove('workbench-lab-batch');preferences.remove('workbench-pilot-dismissed');location.reload();
      });
    });
    $('#maintenance-purge').onclick=wrap(async()=>{
      const ids=inventory.archives.map(a=>a.id),result=await post('purge-preview',{ids});if(revision!==version)return;
      $('#maintenance-preview').innerHTML='<h4>'+text('Delete archived investigations')+'</h4><p class="callout">'+text('Permanent deletion removes these archives and their saved analysis copies. Recovery will no longer be available. Original libraries, audio, inputs and completed exports are kept.')+'</p><ul>'+result.archives.map(row=>'<li>'+esc(date(row.created))+' · '+num(row.items)+' '+text('items')+'</li>').join('')+'</ul><label><input type="checkbox" id="maintenance-ack">'+text('I understand this deletion cannot be undone')+'</label><button disabled class="button" id="maintenance-confirm">'+text('Permanently delete these archives')+'</button>';
      $('#maintenance-ack').onchange=()=>{$('#maintenance-confirm').disabled=!$('#maintenance-ack').checked;};
      $('#maintenance-confirm').onclick=wrap(async()=>{if(!$('#maintenance-ack').checked)return;try{await post('purge',{ids,token:result.token,confirmed:true});}finally{await Investigations.load();}});
    });
  }
  return {load};
})();
