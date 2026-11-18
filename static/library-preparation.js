/* User-requested sidecar preparation. Opening a view never scans audio. */
window.LibraryPreparation=(()=>{
  let current=null,revision=0,dialogSelection=null;
  const node=id=>document.getElementById('preparation-'+id);
  const input=source=>({source:source || window.Journeys?.context?.()?.source || '',workspace:session?.id || ''});
  async function status(selected=input()){
    if(!selected.source)return null;
    return api('/api/library-preparation?'+new URLSearchParams(selected),{feedback:false});
  }
  function render(data){
    current=data;
    node('source').textContent=data?.label || I18n.t('Load a library pair to begin.');
    node('metadata').textContent=I18n.t('Snapshot')+' · '+I18n.t(data?.snapshot?'Ready':'Not checked');
    const scan=data?.file_health;
    node('files').textContent=I18n.t('File health')+' · '+I18n.t(scan?.state==='complete'?'Complete':scan?.done?'Partial':'Not checked');
    node('open').disabled=!data;
  }
  async function load(){
    const request=++revision,selected=input();
    try{const data=await status(selected);if(request===revision)render(data);}
    catch(error){if(request===revision){render(null);node('source').textContent=error.message;}}
  }
  async function open(source,view){
    const selected=input(source),data=await status(selected);
    if(!data){notify(I18n.t('Load a library pair to begin.'));return;}
    dialogSelection={...selected,scope:data.scope,view};
    node('dialog-source').textContent=data.label;
    node('scan').checked=false;
    node('dialog-state').textContent=I18n.t(data.snapshot?'Ready':'Not checked');
    if(!node('dialog').open)node('dialog').showModal();
  }
  async function loaded(source){
    await Journeys.load();await Journeys.selectContext(source,true);await load();await open(source);
  }
  node('open').onclick=wrap(()=>open());
  node('later').onclick=()=>node('dialog').close();
  node('form').onsubmit=wrap(async event=>{
    event.preventDefault();if(busy || !dialogSelection)return;
    const selected={...dialogSelection},scan=node('scan').checked;
    node('dialog').close();node('open').disabled=true;
    try{
      const started=await api('/api/library-preparation',{method:'POST',body:JSON.stringify(selected)});
      const prepared=await poll(started.job);
      // Never move a newly selected collection back to a previous preparation.
      if((selected.source==='workspace' && session?.id!==selected.workspace) ||
          window.Journeys?.context?.()?.scope_key!==selected.scope)throw new Error(I18n.t('This workspace is no longer loaded'));
      await Journeys.load();await Journeys.selectContext('snapshot:'+prepared.id,true);
      if(scan){
        const job=await api('/api/file-health/scan',{method:'POST',body:JSON.stringify({source:'snapshot:'+prepared.id,force:true})});
        await poll(job.job);
      }
      await load();
      showView(scan?'file-health':selected.view || 'bubbles');
    }finally{await load();}
  });
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-open-preparation]');
    if(button)void wrap(()=>open())();
  });
  window.addEventListener('workbench-context',()=>void load());
  window.addEventListener('workbench-language',()=>void load());
  return {load,open,loaded};
})();
