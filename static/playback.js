/* One local playback action shared by every live-library track renderer. */
window.TrackPlayback=(()=>{
  const queue=new Set(),cache=new Map();let timer=null,running=false;
  // Per-button force markers survive batched IntersectionObserver callbacks.
  const forceRefresh=new WeakSet();let lastForcedRefresh=0;
  const MIN_FORCE_INTERVAL_MS=5000;
  const t=key=>I18n.t(key);
  function button(snapshot,identity,workspace=''){
    if(!identity || (!snapshot && !workspace))return '';
    return '<button type="button" class="track-play" disabled aria-busy="true" data-play-track="'+esc(identity)+'" data-play-snapshot="'+esc(snapshot || '')+'" data-play-workspace="'+esc(workspace)+'" title="'+esc(t('Play in default media player'))+'" aria-label="'+esc(t('Play in default media player'))+'"><svg aria-hidden="true" width="11" height="11" viewBox="0 0 12 12"><path fill="currentColor" d="M3 1v10l8-5z"/></svg></button>';
  }
  function scope(b){return b.dataset.playWorkspace?{workspace:b.dataset.playWorkspace}:{snapshot:b.dataset.playSnapshot};}
  function key(b){return JSON.stringify([scope(b),b.dataset.playTrack]);}
  function status(b,available){
    b.disabled=!available;b.dataset.available=String(available);b.setAttribute('aria-busy','false');
    b.title=t(available?'Play in default media player':'Audio file unavailable at the recorded library paths');
    b.setAttribute('aria-label',b.title);
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
        const old=cache.get(key(b));if(!forceRefresh.has(b) && old && Date.now()-old.time<10000){status(b,old.available);continue;}
        const id=JSON.stringify(scope(b));if(!groups.has(id))groups.set(id,[]);groups.get(id).push(b);
      }
      // A focus/visibility refresh bypasses SQLite for every group, including
      // buttons whose visibility callback arrives in a later animation frame.
      for(const [source,buttons] of groups){
        const force=buttons.some(b=>forceRefresh.has(b));
        const ids=[...new Set(buttons.map(b=>b.dataset.playTrack))];
        for(let offset=0;offset<ids.length;offset+=100){
          const r=await api('/api/playback/availability',{feedback:false,method:'POST',body:JSON.stringify({...JSON.parse(source),track_ids:ids.slice(offset,offset+100),...(force?{refresh:true}:{})})});
          for(const b of buttons)if(Object.hasOwn(r.tracks,b.dataset.playTrack)){
            const available=r.tracks[b.dataset.playTrack];cache.set(key(b),{available,time:Date.now()});forceRefresh.delete(b);if(b.isConnected)status(b,available);
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
  document.addEventListener('click',event=>{
    const b=event.target.closest('[data-play-track]');if(!b)return;
    event.preventDefault();event.stopImmediatePropagation();if(b.disabled)return;
    const source=scope(b),identity=b.dataset.playTrack;b.disabled=true;
    api('/api/playback/open',{method:'POST',body:JSON.stringify({...source,track_id:identity})})
      .then(()=>notify(t('Opened in your default media player')))
      .catch(error=>notify(error.message,true))
      .finally(()=>{queue.add(b);cache.delete(key(b));schedule();});
  },true);
  // Prevent a sibling's keyboard handler from selecting a keeper when playing.
  document.addEventListener('keydown',event=>{if(event.target.matches('[data-play-track]'))event.stopPropagation();},true);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)recheck();});
  window.addEventListener('focus',recheck);
  window.addEventListener('workbench-language',()=>{for(const b of document.querySelectorAll('[data-play-track]'))if(b.dataset.available)status(b,b.dataset.available==='true');});
  function recheck(){
    const now=Date.now();
    const forced=now-lastForcedRefresh>=MIN_FORCE_INTERVAL_MS;
    if(forced)lastForcedRefresh=now;
    cache.clear();
    for(const b of document.querySelectorAll('[data-play-track]')){
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
