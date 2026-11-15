/* Shared, contextual header notices. Move the original translated callout,
 * rather than duplicating it, so its help link remains interactive.
 * Safety instructions stay available from the header's Details control. */
window.HeaderInformation=(()=>{
  const banner=document.querySelector('#header-information');
  const details=document.querySelector('#header-information-details');
  const expanded=document.querySelector('#header-information-expanded');
  const context=document.querySelector('#header-information-context');
  const scope=document.querySelector('#header-information-scope');
  const sources=new Map();
  const locations={
    history:'#view-history > aside.callout',
    statistics:'#view-statistics > aside.callout',
    lab:'#view-lab > aside.callout',
  };
  for(const [view,selector] of Object.entries(locations)){
    const node=document.querySelector(selector);
    if(!node)continue;
    const position=document.createComment('contextual notice: '+view);
    node.before(position);
    sources.set(view,{node,position});
  }
  function restore(){
    for(const {node,position} of sources.values())position.after(node);
    expanded.replaceChildren();
  }
  function firstSentence(node){
    // The first sentence is short enough for the compact header; the original
    // callout, with its localized help link, remains fully readable in Details.
    const full=node.textContent.replace(/\s+/gu,' ').trim();
    const match=full.match(/^.*?[.!?。؟](?=\s|$)/u);
    return match?match[0]:full;
  }
  function refresh(view){
    if(!banner)return;
    restore();
    details.open=false;
    const record=sources.get(view);
    if(!record){
      context.hidden=true;
      scope.hidden=true;
      details.hidden=true;
      context.textContent='';
      return;
    }
    const tag=document.querySelector('#view-'+view+' .section-heading .readonly-badge');
    scope.textContent=tag?.textContent.trim() || '';
    scope.hidden=!scope.textContent;
    context.textContent=firstSentence(record.node);
    context.hidden=false;
    expanded.append(record.node);
    details.hidden=false;
  }
  const active=()=>document.querySelector('.nav.active')?.dataset.view || 'files';
  document.addEventListener('DOMContentLoaded',()=>refresh(active()),{once:true});
  window.addEventListener('workbench-language',()=>queueMicrotask(()=>refresh(active())));
  return {refresh};
})();