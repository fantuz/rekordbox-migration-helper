/* One local playback action shared by every live-library track renderer. */
window.TrackPlayback=(()=>{
  const queue=new Set(),cache=new Map();let timer=null,running=false,availabilityRevision=0;
  // Per-button force markers survive batched IntersectionObserver callbacks.
  const forceRefresh=new WeakSet();let lastForcedRefresh=0;
  const MIN_FORCE_INTERVAL_MS=5000;
  const t=key=>I18n.t(key);
  function button(snapshot,identity,workspace='',dropboxSource=''){
    if(!identity || (!snapshot && !workspace))return '';
    const remote=/^(?:snapshot|capture):[a-f0-9]{32}$/u.test(dropboxSource)?' data-dropbox-play-source="'+esc(dropboxSource)+'"':'';
    return '<button type="button" class="track-play" disabled aria-busy="true" data-play-track="'+esc(identity)+'" data-play-snapshot="'+esc(snapshot || '')+'" data-play-workspace="'+esc(workspace)+'"'+remote+' title="'+esc(t('Play in default media player'))+'" aria-label="'+esc(t('Play in default media player'))+'"><svg aria-hidden="true" width="11" height="11" viewBox="0 0 12 12"><path fill="currentColor" d="M3 1v10l8-5z"/></svg></button>';
  }
  function scope(b){return b.dataset.playWorkspace?{workspace:b.dataset.playWorkspace}:{snapshot:b.dataset.playSnapshot};}
  function key(b){return JSON.stringify([scope(b),b.dataset.playTrack]);}
  function status(b,available,fileState='unverified',cloud){
    const remote=!available&&!cloud?.can_open&&fileState!=='inaccessible'&&Boolean(b.dataset.dropboxPlaySource);
    b.disabled=!available&&!cloud?.can_open&&!remote;b.dataset.available=String(available);b.dataset.fileStatus=fileState;b.dataset.cloudOpen=String(Boolean(cloud?.can_open));b.dataset.dropboxDownloadReady=String(remote);b.setAttribute('aria-busy','false');
    b.title=t(remote?'Download and play this track':cloud?.can_open?'Open cloud-managed audio':available?'Play in default media player':'Audio file unavailable at the recorded library paths');
    b.setAttribute('aria-label',b.title);
    b.dispatchEvent(new CustomEvent('workbench-file-status',{bubbles:true,detail:{status:fileState}}));
  }
  const observer=new IntersectionObserver(entries=>{
    for(const entry of entries)if(entry.isIntersecting){observer.unobserve(entry.target);queue.add(entry.target);}
    schedule();
  });
  function schedule(){if(!timer)timer=setTimeout(flush,100);}
  async function flush(){
    timer=null;if(running){schedule();return;}running=true;
    try{
      const groups=new Map();
      for(const b of queue){queue.delete(b);if(!b.isConnected)continue;
        const old=cache.get(key(b));if(!forceRefresh.has(b) && old && Date.now()-old.time<10000){status(b,old.available,old.fileState,old.cloud);continue;}
        const id=JSON.stringify(scope(b));if(!groups.has(id))groups.set(id,[]);groups.get(id).push(b);
      }
      // A focus/visibility refresh bypasses SQLite for every group, including
      // buttons whose visibility callback arrives in a later animation frame.
      for(const [source,buttons] of groups){
        const ids=[...new Set(buttons.map(b=>b.dataset.playTrack))];
        for(let offset=0;offset<ids.length;offset+=100){
          const requestRevision=availabilityRevision,force=buttons.some(b=>forceRefresh.has(b));
          const r=await api('/api/playback/availability',{feedback:false,method:'POST',body:JSON.stringify({...JSON.parse(source),track_ids:ids.slice(offset,offset+100),...(force?{refresh:true}:{})})});
          // A download/focus refresh may happen while this request is pending.
          // Its older result must neither refill the cache nor clear the new
          // force marker; retry the surviving buttons with current attributes.
          if(requestRevision!==availabilityRevision){for(const b of buttons)if(b.isConnected)queue.add(b);continue;}
          for(const b of buttons)if(Object.hasOwn(r.tracks,b.dataset.playTrack)){
            const available=r.tracks[b.dataset.playTrack],fileState=r.statuses?.[b.dataset.playTrack] || (available?'playable':'unverified'),cloud=r.cloud?.[b.dataset.playTrack];cache.set(key(b),{available,fileState,cloud,time:Date.now()});forceRefresh.delete(b);if(b.isConnected)status(b,available,fileState,cloud);
          }
        }
      }
      if(cache.size>2000)cache.clear();
    }catch{/* A later focus or click retries if the local application was busy. */}
    finally{running=false;if(queue.size)schedule();}
  }
  function scan(root){
    if(!(root instanceof Element))return;
    const buttons=root.matches('[data-play-track]')?[root]:[...root.querySelectorAll('[data-play-track]')];
    for(const b of buttons)if(!b.dataset.playObserved){b.dataset.playObserved='true';observer.observe(b);}
  }
  function forget(root){
    if(!(root instanceof Element))return;
    const buttons=root.matches('[data-play-track]')?[root]:[...root.querySelectorAll('[data-play-track]')];
    for(const b of buttons){observer.unobserve(b);queue.delete(b);delete b.dataset.playObserved;}
  }
  new MutationObserver(records=>{
    for(const r of records)for(const n of r.removedNodes)forget(n);
    for(const r of records)for(const n of r.addedNodes)scan(n);
  }).observe(document.body,{childList:true,subtree:true});
  function confirmCloudOpen(result){
    const dialog=document.getElementById('cloud-playback-dialog');
    if(dialog.open)return Promise.resolve(false);
    document.getElementById('cloud-playback-track').textContent=result.title;
    const provider=document.getElementById('cloud-playback-provider');
    provider.textContent=result.cloud_provider==='dropbox'?'Dropbox':result.cloud_provider==='google_drive'?'Google Drive':t('Cloud-managed audio');
    provider.className='cloud-provider cloud-provider-'+result.cloud_provider;
    return new Promise(resolve=>{
      let approved=false;
      document.getElementById('cloud-playback-confirm').onclick=()=>{approved=true;dialog.close();};
      document.getElementById('cloud-playback-cancel').onclick=()=>dialog.close();
      dialog.addEventListener('close',()=>resolve(approved),{once:true});
      dialog.showModal();document.getElementById('cloud-playback-cancel').focus();
    });
  }
  document.addEventListener('click',event=>{
    const b=event.target.closest('[data-play-track]');if(!b)return;
    event.preventDefault();event.stopImmediatePropagation();if(b.disabled)return;
    const source=scope(b),identity=b.dataset.playTrack;b.disabled=true;
    (async()=>{
      if(b.dataset.dropboxDownloadReady==='true'){
        await window.DropboxConnector.playTrack(b.dataset.dropboxPlaySource,identity);
        return;
      }
      let result=await api('/api/playback/open',{method:'POST',body:JSON.stringify({...source,track_id:identity})});
      if(result.confirmation_required){
        if(!await confirmCloudOpen(result))return;
        result=await api('/api/playback/open',{method:'POST',body:JSON.stringify({...source,track_id:identity,confirm_cloud_open:true,confirmation_token:result.confirmation_token})});
      }
      if(result.opened)notify(t('Opened in your default media player'));
    })()
      .catch(error=>notify(error.message,true))
      .finally(()=>{queue.add(b);cache.delete(key(b));schedule();});
  },true);
  // Prevent a sibling's keyboard handler from selecting a keeper when playing.
  document.addEventListener('keydown',event=>{if(event.target.matches('[data-play-track]'))event.stopPropagation();},true);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)recheck();});
  window.addEventListener('focus',recheck);
  window.addEventListener('workbench-language',()=>{for(const b of document.querySelectorAll('[data-play-track]'))if(b.dataset.available)status(b,b.dataset.available==='true',b.dataset.fileStatus,{can_open:b.dataset.cloudOpen==='true'});});
  function recheck(options={}){
    availabilityRevision++;
    const now=Date.now();
    // A completed single-file download must bypass even a recent negative
    // filesystem result. Focus/visibility refreshes retain their normal limit.
    const explicit=options.force===true;
    const forced=explicit||now-lastForcedRefresh>=MIN_FORCE_INTERVAL_MS;
    if(forced)lastForcedRefresh=now;
    if(!explicit)cache.clear();
    for(const b of document.querySelectorAll('[data-play-track]')){
      if(explicit&&options.source){
        const source=options.source.startsWith('snapshot:')?options.source.slice(9):options.source;
        if(b.dataset.playSnapshot!==source||b.dataset.playTrack!==options.track_id)continue;
      }
      cache.delete(key(b));
      if(forced)forceRefresh.add(b);
      observer.unobserve(b);observer.observe(b);
    }
  }
  function bind(selector,snapshot){
    for(const title of document.querySelectorAll(selector+' [data-insight-open]')){
      if(!title.previousElementSibling?.matches('[data-play-track]'))title.insertAdjacentHTML('beforebegin',button(snapshot,title.dataset.insightOpen));
    }
  }
  scan(document.body);
  return {button,bind,recheck};
})();
