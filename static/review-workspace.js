/* One review surface: independent desktop panes, a native modal on narrow screens. */
window.ReviewWorkspace=(()=>{
  const entries=new Map();
  const label=(tag,key,className='')=>{
    const node=document.createElement(tag);node.className=className;I18n.text(node,key);return node;
  };
  function restore(entry,focus=true){
    if(entry.panel.parentElement===entry.drawer)entry.home.after(entry.panel);
    entry.panel.hidden=entry.compact;
    if(focus && entry.root.isConnected && !entry.root.closest('[hidden]')){
      const target=entry.opener?.isConnected?entry.opener:entry.openButton;
      target?.focus({preventScroll:true});
    }
  }
  function layout(entry){
    const width=entry.root.getBoundingClientRect().width;if(!width)return;
    entry.compact=width<=930;entry.root.dataset.reviewCompact=String(entry.compact);
    if(!entry.compact && entry.drawer.open){entry.drawer.close();restore(entry,false);}
    if(!entry.drawer.open)entry.panel.hidden=entry.compact;
  }
  function mount(root,panel){
    if(entries.has(root))return entries.get(root);
    const home=document.createComment('review panel position');panel.before(home);
    const drawer=document.createElement('dialog');drawer.className='review-drawer';
    drawer.dataset.i18nAria='Duplicate review';I18n.apply(drawer);root.append(drawer);
    const openButton=label('button','Review','button secondary review-open-selected');openButton.type='button';
    openButton.disabled=true;
    const bar=document.createElement('div');bar.className='review-list-heading';
    bar.append(label('strong','Review'),openButton);root.querySelector('.review-candidates').prepend(bar);
    const entry={root,panel,home,drawer,openButton,compact:false,opener:null,ready:false};entries.set(root,entry);
    panel.classList.add('review-inspector');panel.tabIndex=-1;
    openButton.onclick=()=>present(root,openButton);
    drawer.addEventListener('close',()=>{if(!drawer.open)restore(entry);});
    drawer.addEventListener('click',event=>{
      if(event.target!==drawer)return;
      const r=drawer.getBoundingClientRect();
      if(event.clientX<r.left || event.clientX>r.right || event.clientY<r.top || event.clientY>r.bottom)drawer.close();
    });
    entry.observer=new ResizeObserver(()=>layout(entry));entry.observer.observe(root);layout(entry);
    return entry;
  }
  function refresh(root,panel,actions=[],ready=true){
    if(!root || !panel)return;
    const entry=mount(root,panel);entry.ready=ready;entry.openButton.disabled=!ready;
    if(!ready && entry.drawer.open){entry.drawer.close();restore(entry);}
    const body=document.createElement('div');body.className='review-inspector-body';body.tabIndex=0;
    body.dataset.i18nAria='Review';body.setAttribute('role','region');I18n.apply(body);
    while(panel.firstChild)body.append(panel.firstChild);
    const dock=document.createElement('div');dock.className='review-action-dock';
    for(const selector of actions){const node=body.querySelector(selector);if(node)dock.append(node);}
    const toolbar=document.createElement('div');toolbar.className='review-panel-heading';
    const heading=label('h3','Review');heading.tabIndex=-1;
    const close=label('button','Close','button secondary review-close');close.type='button';close.onclick=()=>entry.drawer.close();
    toolbar.append(heading,close);panel.append(toolbar,body);if(dock.childElementCount)panel.append(dock);
    layout(entry);
  }
  function present(root,opener){
    const entry=entries.get(root);if(!entry || !entry.ready)return;
    entry.opener=opener || entry.openButton;layout(entry);entry.panel.hidden=false;
    if(entry.compact){
      entry.drawer.append(entry.panel);if(!entry.drawer.open)entry.drawer.showModal();
    }else root.scrollIntoView({block:'start',behavior:'instant'});
    entry.panel.querySelector('.review-inspector-body').scrollTop=0;
    entry.panel.querySelector('.review-panel-heading h3').focus({preventScroll:true});
  }
  function closeAll(){for(const entry of entries.values())if(entry.drawer.open){entry.drawer.close();restore(entry,false);}}
  function dispose(root){
    const entry=entries.get(root);if(!entry)return;
    if(entry.drawer.open)entry.drawer.close();restore(entry,false);entry.observer.disconnect();entries.delete(root);
  }
  window.addEventListener('workbench-context',closeAll);
  return {refresh,present,closeAll,dispose};
})();
