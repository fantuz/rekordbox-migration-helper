/* Personal stars are explicit sidecar edits; captured ratings remain evidence. */
window.InlineRating=(()=>{
  const fields=new WeakMap(),pending=new Set(),busy=new Set(),epochs=new Map();
  let scheduled=false;
  const label=value=>value==null?I18n.t('Unknown'):value===0?I18n.t('Unrated'):I18n.number(value)+' / 5';
  function source(value){
    const key=String(value || '');
    if(key==='workspace')return session?'session:'+session.id:'';
    return key && !key.includes(':')?'snapshot:'+key:key;
  }
  function render(trackId,rating,collection=''){
    const value=Number.isInteger(rating)&&rating>=0&&rating<=5?rating:null;
    return '<span class="inline-rating" data-inline-rating="'+esc(trackId)+'" data-rating-source="'+esc(source(collection))+'" data-rating-captured="'+esc(value??'')+'" role="group" aria-label="'+esc(I18n.t('Personal stars'))+'">'+
      '<span class="inline-rating-choices">'+Array.from({length:5},(_,i)=>'<button type="button" class="inline-rating-star" data-inline-stars="'+(i+1)+'" aria-label="'+esc(I18n.t('Personal stars')+': '+I18n.number(i+1)+' / 5')+'" aria-pressed="'+(value===i+1)+'" disabled>'+((value??0)>i?'★':'☆')+'</button>').join('')+
      '<button type="button" class="inline-rating-clear" data-inline-stars="0" aria-label="'+esc(I18n.t('Unrated'))+'" title="'+esc(I18n.t('Unrated'))+'" disabled>×</button>'+
      '<button type="button" class="inline-rating-reset" data-inline-rating-reset aria-label="'+esc(I18n.t('Reset override'))+'" title="'+esc(I18n.t('Reset override'))+'" hidden disabled>↶</button>'+
      '<button type="button" class="inline-rating-retry" data-inline-rating-retry aria-label="'+esc(I18n.t('Refresh'))+'" hidden>↻</button></span>'+
      '<small class="inline-rating-state">'+esc(label(value))+'</small></span>';
  }
  function widgets(collection){return [...document.querySelectorAll('[data-inline-rating]')].filter(node=>fields.get(node)?.source===collection);}
  function paint(node){
    const field=fields.get(node);if(!field)return;
    const record=field.record,value=record?.value??(record?.value===null?null:field.captured);
    const saving=busy.has(field.source),disabled=saving || !record;
    node.setAttribute('aria-busy',String(saving || field.loading));
    node.classList.toggle('inline-rating-staged',record?.staged===true);
    for(const button of node.querySelectorAll('[data-inline-stars]')){
      const stars=Number(button.dataset.inlineStars);button.disabled=disabled;
      button.setAttribute('aria-pressed',String(value===stars));
      button.setAttribute('aria-label',stars?I18n.t('Personal stars')+': '+I18n.number(stars)+' / 5':I18n.t('Unrated'));
      if(stars)button.textContent=stars<=(value??0)?'★':'☆';
      else button.title=I18n.t('Unrated');
    }
    const reset=node.querySelector('[data-inline-rating-reset]');reset.hidden=!record?.staged;reset.disabled=disabled;
    reset.setAttribute('aria-label',I18n.t('Reset override'));reset.title=I18n.t('Reset override');
    const retry=node.querySelector('[data-inline-rating-retry]');retry.hidden=!field.error;retry.disabled=saving||field.loading;
    retry.setAttribute('aria-label',I18n.t('Refresh'));retry.title=field.error||I18n.t('Refresh');
    node.setAttribute('aria-label',I18n.t('Personal stars'));
    const status=node.querySelector('.inline-rating-state');
    status.textContent=saving?I18n.t('Saving working edits…'):field.error?I18n.t('Unavailable'):record?.staged?I18n.t('Staged working edits'):label(value);
    node.title=field.error||I18n.t('Captured:')+' '+label(record?record.captured:field.captured)+(record?.staged?' · '+I18n.t('Staged working edits')+': '+label(value):'');
    const cell=node.closest('td');if(cell?.children.length===1&&cell.firstElementChild===node)cell.dataset.sortValue=value==null?'':String(value);
  }
  async function hydrate(nodes){
    const groups=new Map();
    for(const node of nodes){const field=fields.get(node);if(!field||!node.isConnected||!field.source)continue;
      if(!groups.has(field.source))groups.set(field.source,[]);groups.get(field.source).push(node);}
    await Promise.all([...groups].map(async([collection,items])=>{
      if(busy.has(collection))return;
      const stamp=epochs.get(collection)||0;
      for(let offset=0;offset<items.length;offset+=100){
        const chunk=items.slice(offset,offset+100),params=new URLSearchParams({source:collection});
        for(const identity of new Set(chunk.map(node=>fields.get(node).id)))params.append('track_id',identity);
        for(const node of chunk){fields.get(node).loading=true;fields.get(node).error='';paint(node);}
        try{
          const response=await api('/api/ratings?'+params,{feedback:false});
          if((epochs.get(collection)||0)!==stamp){chunk.forEach(queue);continue;}
          for(const node of chunk){
            const field=fields.get(node),record=response.rows.find(row=>row.track_id===field.id);
            if(node.isConnected&&record)field.record={...record,scope:response.scope,edit_revision:response.edit_revision};
          }
        }catch(error){for(const node of chunk)fields.get(node).error=error.message;}
        finally{for(const node of chunk){fields.get(node).loading=false;paint(node);}}
      }
    }));
  }
  function queue(node){pending.add(node);if(!scheduled){scheduled=true;queueMicrotask(()=>{scheduled=false;const nodes=[...pending];pending.clear();void hydrate(nodes);});}}
  function attach(node,collection){
    if(fields.has(node))return;
    const raw=node.dataset.ratingCaptured,captured=raw===''?null:Number(raw);
    fields.set(node,{source:source(collection||node.dataset.ratingSource),id:node.dataset.inlineRating,captured,record:null,loading:false,error:''});
    node.dataset.ratingSource=fields.get(node).source;
    node.addEventListener('click',event=>{
      event.stopPropagation();const button=event.target.closest('[data-inline-stars],[data-inline-rating-reset],[data-inline-rating-retry]');
      if(button?.hasAttribute('data-inline-rating-retry')&&!button.disabled){queue(node);return;}
      if(button&&!button.disabled)void save(node,button);
    });
    queue(node);
  }
  function bind(root,collection=''){
    const host=typeof root==='string'?document.querySelector(root):root;if(!host)return;
    if(host.matches?.('[data-inline-rating]'))attach(host,collection);
    for(const node of host.querySelectorAll('[data-inline-rating]'))attach(node,collection);
  }
  async function save(node,button){
    const field=fields.get(node),record=field?.record;if(!record||busy.has(field.source))return;
    const reset=button.hasAttribute('data-inline-rating-reset'),value=Number(button.dataset.inlineStars);
    if(!reset&&record.value===value)return;
    const focus=reset?'reset':String(value),collection=field.source;
    epochs.set(collection,(epochs.get(collection)||0)+1);busy.add(collection);widgets(collection).forEach(paint);
    try{
      const response=await api('/api/ratings',{method:reset?'DELETE':'POST',body:JSON.stringify({
        source:collection,track_id:field.id,captured:record.captured,edit_revision:record.edit_revision,...(reset?{}:{value})})});
      for(const widget of widgets(collection)){
        const other=fields.get(widget);if(!other.record)continue;
        other.record.edit_revision=response.edit_revision;
        if(other.id===field.id)other.record={...response};
      }
      window.dispatchEvent(new CustomEvent('workbench-rating-saved',{detail:response}));
      if(session){const status=await api('/api/status',{feedback:false});if(status.session?.id===session.id){session=status.session;renderSession();}}
      notify(I18n.t(reset?'Restored the captured field value':'Staged working edits'));
    }catch(error){notify(error.message,true);}
    finally{
      busy.delete(collection);widgets(collection).forEach(paint);
      if(node.isConnected){const next=focus==='reset'?node.querySelector('[data-inline-stars="'+(field.record?.value||1)+'"]'):button;next?.focus({preventScroll:true});}
      // A conflict or interrupted response must display the actual saved state;
      // it must never silently resubmit the rejected choice.
      void hydrate(widgets(collection));
    }
  }
  const observer=new MutationObserver(records=>{
    for(const record of records)for(const added of record.addedNodes){
      if(added.nodeType!==1)continue;
      for(const node of [added,...added.querySelectorAll('[data-inline-rating]')])
        if(node.matches('[data-inline-rating]')&&node.dataset.ratingSource)attach(node);
    }
  });
  observer.observe(document.body,{childList:true,subtree:true});
  window.addEventListener('workbench-rating-saved',event=>{
    const record=event.detail;
    for(const node of document.querySelectorAll('[data-inline-rating]')){
      const field=fields.get(node);if(field?.record?.scope!==record.scope)continue;
      epochs.set(field.source,(epochs.get(field.source)||0)+1);
      field.record.edit_revision=record.edit_revision;
      if(field.id===record.track_id)field.record={...record};
      paint(node);
    }
  });
  window.addEventListener('workbench-language',()=>{for(const node of document.querySelectorAll('[data-inline-rating]'))paint(node);});
  window.addEventListener('workbench-metadata-saved',event=>{
    const {scope,trackId,record}=event.detail;
    for(const node of document.querySelectorAll('[data-inline-rating]')){
      const field=fields.get(node);if(field?.record?.scope!==scope)continue;
      epochs.set(field.source,(epochs.get(field.source)||0)+1);
      field.record.edit_revision=record.edit_revision;
      if(field.id===trackId){const edit=record.overrides.rating;field.record.value=edit?edit.value:record.original.rating;field.record.staged=Boolean(edit);}
      paint(node);
    }
  });
  return {render,bind};
})();
