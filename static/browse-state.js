/* Per-tab browsing only. Never persist edits, upload paths or consent. */
window.BrowseState=(()=>{
  const key='workbench-browse-v1';let data={},active='',restoring=false;
  try{data=JSON.parse(sessionStorage.getItem(key)||'{}');if(!data||typeof data!=='object')data={};}catch{}
  const allowed=id=>/^(?:dj|bubble|tonal)-(?:snapshot|search|family|genre|tone|colour|basis|from|to|usage|preparation|bpm-min|bpm-max|min|max|rating-min|perspective|quality|stars|max-plays|days|random-mode|sample|seed|metric|dimension)$/.test(id) ||
    /^(?:history-(?:snapshot|year|search|track-search)|lab-(?:snapshot|report-select|report-section|report-search|track-search|pilot-(?:target|target-value|size|seed|speed|top))|intelligence-(?:source|before|after|playlist|history|lens|search|threshold)|musicbrainz-(?:library|snapshot)|file-health-(?:source|status|search))$/.test(id);
  function save(){try{sessionStorage.setItem(key,JSON.stringify(data));}catch{}}
  function value(id){return data[id];}
  function set(id,v){data[id]=v;save();}
  function remember(){for(const el of document.querySelectorAll('.view:not([hidden]) input[id],.view:not([hidden]) select[id]'))if(allowed(el.id))data[el.id]=el.value;save();}
  function restore(root=document){for(const el of root.querySelectorAll('input[id],select[id]'))if(allowed(el.id)&&typeof data[el.id]==='string'&&(el.tagName!=='SELECT'||[...el.options].some(o=>o.value===data[el.id])))el.value=data[el.id];}
  function enter(view){
    if(!document.getElementById('view-'+view))return;
    if(active && active!==view)remember();active=view;
    restore(document.getElementById('view-'+view));
    if(!restoring){if(location.hash!=='#'+view)history.pushState({view},'', '#'+view);set('view',view);}
  }
  function start(){
    restore();const view=location.hash.slice(1)||data.view||'start';
    if(document.getElementById('view-'+view)){restoring=true;showView(view);restoring=false;history.replaceState({view},'','#'+view);}
  }
  addEventListener('popstate',()=>{const view=location.hash.slice(1)||'start';if(!document.getElementById('view-'+view))return;restoring=true;showView(view);restoring=false;set('view',view);});
  document.addEventListener('change',event=>{if(allowed(event.target.id))set(event.target.id,event.target.value);},true);
  addEventListener('pagehide',remember);
  return {value,set,remember,restore,enter,start};
})();
