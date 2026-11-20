/* Shared wait feedback. A slow request is not a timeout or proof of failure. */
window.Activity=(()=>{
  const SHOW_AFTER=200,WAIT_AFTER=1000,LONG_AFTER=30000;
  const pending=new Map();let timer=null,operation=null;
  const banner=document.createElement('aside');banner.id='request-activity';banner.hidden=true;
  banner.innerHTML='<span class="spinner" aria-hidden="true"></span><div><strong role="status" aria-live="polite" aria-atomic="true"></strong><p role="status" aria-live="polite"></p><small aria-live="off"></small></div>';
  document.body.append(banner);
  const title=banner.querySelector('strong'),hint=banner.querySelector('p'),elapsed=banner.querySelector('small');
  const put=(node,text)=>{if(node.textContent!==text)node.textContent=text;};
  function render(){
    const now=performance.now(),entries=[...pending.values()];
    const dialogs=[...document.querySelectorAll('dialog[open]')];
    const modal=document.activeElement?.closest('dialog[open]') || dialogs.at(-1);
    const inProgress=modal?.id==='progress' && operation;
    const entry=inProgress?operation:entries.reduce((old,row)=>!old || row.started<old.started?row:old,null);
    if(!entry || now-entry.started<SHOW_AFTER){banner.hidden=true;return;}
    // Keep feedback inside the modal top layer when a dialog is open. No focus
    // moves, modal opens, or page-wide input locks are needed for ordinary loads.
    const parent=modal || document.body;
    if(banner.parentElement!==parent)parent.append(banner);
    const quiet=now-(inProgress?entry.updated:entry.started),waiting=quiet>=WAIT_AFTER;
    if(inProgress&&!waiting&&document.getElementById('progress-cloud')?.hidden===false){banner.hidden=true;return;}
    banner.dataset.waiting=String(waiting);banner.hidden=false;
    put(title,I18n.t(waiting?'Waiting…':inProgress?'Working':'Loading'));
    put(hint,quiet>=LONG_AFTER?I18n.t('This is taking longer. Avoid starting the same action again.'):
      waiting?I18n.t(inProgress?'Waiting for the next progress update.':'Waiting for the application to respond.'):'');
    hint.hidden=!hint.textContent;
    put(elapsed,I18n.t('Elapsed: {seconds} s',{seconds:Math.floor((now-entry.started)/1000)}));
  }
  function begin(){
    const key=Symbol(),started=performance.now();pending.set(key,{started,updated:started});
    if(timer===null)timer=setInterval(render,100);
    render();let finished=false;
    return ()=>{
      if(finished)return;finished=true;pending.delete(key);
      if(!pending.size){clearInterval(timer);timer=null;}
      render();
    };
  }
  function progress(value,message){
    if(!operation){const finish=begin();operation={started:performance.now(),updated:performance.now(),finish};}
    if(operation.value!==value || operation.message!==message){operation.updated=performance.now();operation.value=value;operation.message=message;}
    render();
  }
  function finishProgress(){const previous=operation;operation=null;previous?.finish();render();}
  new MutationObserver(render).observe(document.body,{subtree:true,attributes:true,attributeFilter:['open']});
  window.addEventListener('workbench-language',render);
  return {begin,progress,finishProgress};
})();
