/* Collection sorting is performed by Python before pagination. */
window.CollectionSort=(()=>{
  const state={};
  function args(key){return state[key] || (state[key]=window.BrowseState?.value('sort:'+key) || {sort:'',direction:'asc'});}
  function bind(selector,key,fields,rows,reload){
    const root=document.querySelector(selector),table=root?.querySelector('table');if(!table)return;
    table.dataset.sortScope='server';
    const choices=fields.flat().filter(Boolean),current=args(key);
    const controls=document.createElement('div');controls.className='filter-actions collection-sort';
    const select=document.createElement('select');select.setAttribute('aria-label',I18n.t('Sort all results by'));
    for(const field of ['',...new Set(choices)]){
      const option=document.createElement('option');option.value=field;
      option.textContent=field?I18n.field(field):I18n.t('Original order');select.append(option);
    }
    select.value=current.sort;controls.append(select);table.before(controls);
    const change=field=>{state[key]={sort:field,direction:current.sort===field && current.direction==='asc'?'desc':'asc'};
      window.BrowseState?.set('sort:'+key,state[key]);return reload();};
    select.onchange=wrap(()=>change(select.value));
    const headers=[...table.tHead.rows[0].cells];
    if(choices.includes('file_status')){
      const head=document.createElement('th');head.textContent=I18n.t('File health');table.tHead.rows[0].append(head);
      [...table.tBodies[0].rows].forEach((tr,index)=>{const cell=tr.insertCell();cell.textContent=I18n.t(({playable:'Playable',missing:'Missing',inaccessible:'Inaccessible',unverified:'Unverified'})[rows[index]?.file_status] || 'Unchecked');});
      headers.push(head);
      controls.title=I18n.t('Last saved File health scan; unchecked tracks sort last');
    }
    headers.forEach((th,index)=>{
      const field=Array.isArray(fields[index])?fields[index][0]:fields[index];if(!field)return;
      const button=document.createElement('button');button.type='button';button.className='result-sort-button';
      button.textContent=th.textContent+(current.sort===field?(current.direction==='asc'?' ↑':' ↓'):' ↕');
      th.replaceChildren(button);th.setAttribute('aria-sort',current.sort===field?(current.direction==='asc'?'ascending':'descending'):'none');
      button.onclick=wrap(()=>change(field));
    });
  }
  return {args,bind};
})();
