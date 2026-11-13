/* Refresh translated views without submitting forms or losing working values. */
let languageRevision=0;
function languageFieldSelector(node){
  if(node.id)return '#'+CSS.escape(node.id);
  const parts=[];
  while(node && node!==document.body && !node.id){
    const siblings=[...node.parentElement.children].filter(other=>other.tagName===node.tagName);
    parts.unshift(node.tagName.toLowerCase()+':nth-of-type('+(siblings.indexOf(node)+1)+')');node=node.parentElement;
  }
  return node?.id?'#'+CSS.escape(node.id)+' > '+parts.join(' > '):null;
}
function languageField(node){return {value:node.value,checked:node.checked};}
let languageWorkingFields=null;
document.addEventListener('input',event=>{if(languageWorkingFields && event.target.matches('input:not([type=file]),textarea,select')){const key=languageFieldSelector(event.target);if(key)languageWorkingFields.set(key,languageField(event.target));}});
window.addEventListener('workbench-language',async()=>{
  document.documentElement.dataset.languageBusy='true';
  const revision=++languageRevision;
  while(busy || activeUploads.size || mutatingRequests){await new Promise(resolve=>setTimeout(resolve,200));if(revision!==languageRevision)return;}
  const fields=new Map();for(const node of document.querySelectorAll('input:not([type=file]),textarea,select')){const key=languageFieldSelector(node);if(key)fields.set(key,languageField(node));}
  languageWorkingFields=fields;
  const panels=[...document.querySelectorAll('details[id]')].map(node=>[node.id,node.open]);
  const focus=document.activeElement,focusKey=focus?languageFieldSelector(focus):null;
  const selection=focus && 'selectionStart' in focus?[focus.selectionStart,focus.selectionEnd]:null;
  const view=document.querySelector('.nav.active')?.dataset.view || 'files',scroll=[window.scrollX,window.scrollY];
  const track=trackDetailState && $('#track-detail-dialog').open?{...trackDetailState}:null;
  try{
    await refresh();
    if(selected)renderDetail();
    const loaders={history:loadHistory,insights:loadDJInsights,bubbles:loadBubbleExplorer,tonality:loadTonalityInsights,docs:loadDocumentation,intelligence:()=>Intelligence.load()};
    if(loaders[view])await loaders[view]();
    if(track)await openTrackDetails(track.snapshot,track.trackId);
    const titles={files:'Library preparation',analyzer:'Source analysis',storage:'Cloud and local storage',quick:'Share & offline summary',review:'Duplicate review',reference:'File references',activity:'Activity and reports',statistics:'Collection statistics',inventory:'Media inventory',exports:'Library export',lab:'Library lab',intelligence:'Library intelligence',history:'Play history',insights:'DJ insights',bubbles:'Library bubbles',tonality:'Tonality and tempo',docs:'Documentation'};
    const activeView=document.querySelector('.nav.active')?.dataset.view || 'files';
    $('#page-title').textContent=I18n.t(titles[activeView] || 'Library preparation');
  }catch(error){notify(error.message,true);}
  finally{
    if(revision===languageRevision){
      for(const [key,saved] of fields){const node=document.querySelector(key);if(!node)continue;if(node.type==='checkbox'||node.type==='radio')node.checked=saved.checked;else if(!node.matches('[data-language-select],#language') && (node.tagName!=='SELECT' || [...node.options].some(option=>option.value===saved.value)))node.value=saved.value;}
      for(const [id,open] of panels){const node=document.getElementById(id);if(node)node.open=open;}
      const sameView=document.querySelector('.nav.active')?.dataset.view===view;
      if(focusKey && sameView){const node=document.querySelector(focusKey);node?.focus({preventScroll:true});if(node && selection && selection[0]!==null)try{node.setSelectionRange(...selection);}catch{}}
      I18n.apply();if(sameView)window.scrollTo(...scroll);languageWorkingFields=null;document.documentElement.dataset.languageBusy='false';
    }
  }
});
