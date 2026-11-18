/* Move the existing controls, preserving their values, IDs and event handlers. */
window.CollectionNavigation=(()=>{
  const dock=document.getElementById('collection-navigation'),context=document.getElementById('collection-context');
  const contextGroup=document.getElementById('collection-context-toggle'),snapshotGroup=document.getElementById('collection-snapshot-toggle');
  const content=document.getElementById('collection-snapshot-content');
  const fallback=document.getElementById('collection-snapshot-fallback');
  let moved=null,anchor=null,view='',scheduled=false;
  const selectors={insights:'dj-snapshot',bubbles:'bubble-snapshot',tonality:'tonal-snapshot',history:'history-snapshot',lab:'lab-snapshot','file-health':'file-health-source'};
  const observer=new MutationObserver(()=>{if(!scheduled){scheduled=true;requestAnimationFrame(()=>{scheduled=false;refresh();});}});
  function setText(id,value){const node=document.getElementById(id);if(node.textContent!==value)node.textContent=value;node.title=value;}
  function refresh(){
    const source=document.getElementById('journey-context-source');
    setText('collection-context-current',source?.value?source.selectedOptions[0]?.textContent || '':I18n.t('Choose a collection'));
    document.getElementById('collection-context-fallback').hidden=Boolean(context&&!context.hidden&&context.children.length);
    const select=selectors[view]&&document.getElementById(selectors[view]),shared=window.Journeys?.context?.();
    setText('collection-snapshot-current',select?.value?select.selectedOptions[0]?.textContent || '':shared?.snapshot?I18n.t('Saved snapshot'):I18n.t('Choose a snapshot'));
    const note=document.getElementById('collection-snapshot-scope');
    note.textContent=shared?.snapshot?I18n.t('Saved snapshot')+' · '+snapshotMoment(shared.saved_at || shared.captured):I18n.t('This view uses Collection context. Prepare a snapshot for insight tools.');
  }
  function close(){contextGroup.open=false;snapshotGroup.open=false;}
  function restore(){
    if(moved&&anchor?.parentNode){anchor.replaceWith(moved);for(const select of moved.querySelectorAll('select'))delete select.dataset.dockOwner;}
    moved=null;anchor=null;observer.disconnect();if(context)observer.observe(context,{childList:true,subtree:true,characterData:true});
  }
  function enter(next){
    restore();close();view=next;
    const select=selectors[view]&&document.getElementById(selectors[view]);
    if(select){
      moved=select.closest('.insight-sourcebar') || select.closest('label');
      anchor=document.createComment('collection snapshot controls for '+view);moved.before(anchor);
      for(const field of moved.querySelectorAll('select'))field.dataset.dockOwner=view;
      content.append(moved);observer.observe(moved,{childList:true,subtree:true,characterData:true});
    }
    fallback.hidden=Boolean(moved);refresh();
  }
  for(const group of [contextGroup,snapshotGroup])group.addEventListener('toggle',()=>{if(group.open){(group===contextGroup?snapshotGroup:contextGroup).open=false;refresh();}});
  document.addEventListener('click',event=>{if(!dock.contains(event.target))close();});
  dock.addEventListener('keydown',event=>{if(event.key==='Escape'){const group=contextGroup.open?contextGroup:snapshotGroup.open?snapshotGroup:null;if(group){event.preventDefault();close();group.querySelector('summary').focus();}}});
  dock.addEventListener('change',refresh);
  document.getElementById('context-open-preparation').onclick=()=>{close();showView('files');};
  document.getElementById('context-open-lab').onclick=()=>{close();showView('lab');};
  document.getElementById('context-prepare-snapshot').onclick=wrap(()=>LibraryPreparation.open());
  if(context)document.getElementById('collection-context-content').append(context);
  window.addEventListener('workbench-context',refresh);
  window.addEventListener('workbench-language',refresh);
  enter(document.querySelector('.view:not([hidden])')?.id.replace('view-','') || 'start');
  return {enter,restore,refresh,isActive:select=>select.closest('.view')?.hidden===false || Boolean(select.dataset.dockOwner&&select.dataset.dockOwner===view)};
})();
