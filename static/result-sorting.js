/* Accessible, non-destructive sorting for tables rendered by the workbench.
 * Source/API order remains unchanged: only the rows already on this page move.
 * Paginated searches still require a server-side query to sort all results.
 */
window.ResultSorting=(()=>{
  let sorter=new Intl.Collator(I18n.language,{numeric:true,sensitivity:'base'});
  const statusRank={playable:0,missing:1,inaccessible:2,unverified:3,unchecked:4};
  const statusLabels={playable:'Playable',missing:'Missing',inaccessible:'Inaccessible',unverified:'Unverified',unchecked:'Unchecked'};
  const original=new WeakMap(),state=new WeakMap();
  function textOf(cell){return (cell.dataset.sortValue ?? cell.innerText ?? cell.textContent ?? '').trim();}
  function numberOf(value){
    const text=String(value).replace(/\u00a0/gu,' ').trim();
    if(/^\d{1,2}:\d{2}(?::\d{2})?$/u.test(text)){
      return text.split(':').reduce((sum,n)=>60*sum+Number(n),0);
    }
    if(!/^[+\-]?[\d.,\s]+(?:\s*%)?$/u.test(text))return null;
    const compact=text.replace(/[\s%]/gu,'');
    const decimal=compact.lastIndexOf('.')>compact.lastIndexOf(',')?'.':',';
    const other=decimal==='.'?',':'.';
    const groups=compact.split(decimal);
    const parsed=groups.length>1&&groups[groups.length-1].length===3&&groups[0].length<=3
      ? compact.replace(/[.,]/gu,'')
      : compact.replaceAll(other,'').replace(decimal,'.');
    const n=Number(parsed);return Number.isFinite(n)?n:null;
  }
  function compare(a,b,kind){
    const av=textOf(a),bv=textOf(b);
    if(!av && !bv)return 0;
    if(!av)return 1;if(!bv)return -1;
    if(kind==='status')return (statusRank[av]??99)-(statusRank[bv]??99);
    const an=numberOf(av),bn=numberOf(bv);
    if(kind==='number' || (an!==null && bn!==null))return (an??Infinity)-(bn??Infinity);
    return sorter.compare(av,bv);
  }
  function sort(table,index,direction){
    const tbody=table.tBodies[0],rows=Array.from(tbody?.rows||[]);
    if(!tbody || !rows.length)return;
    let baseline=original.get(table);
    if(!baseline || baseline.size!==rows.length || rows.some(r=>!baseline.has(r))){
      baseline=new Map(rows.map((r,i)=>[r,i]));original.set(table,baseline);
    }
    const head=table.tHead?.rows[0]?.cells[index];
    const kind=head?.dataset.sortType;
    rows.sort((a,b)=>{
      const left=a.cells[index],right=b.cells[index];
      if(!left||!right)return baseline.get(a)-baseline.get(b);
      const result=compare(left,right,kind);
      return result*(direction==='descending'?-1:1) || baseline.get(a)-baseline.get(b);
    });
    tbody.append(...rows);
    state.set(table,{index,direction});
    for(const th of table.tHead.rows[0].cells)th.removeAttribute('aria-sort');
    head?.setAttribute('aria-sort',direction);
  }
  function prepare(table){
    if(table.matches('[data-sort-scope="server"],[data-result-sort="off"]'))return;
    const headings=table.tHead?.rows[0]?.cells||[],body=table.tBodies[0];
    if(!headings.length || !body || body.rows.length<2 || [...body.rows].some(r=>r.cells.length!==headings.length))return;
    if(!table.dataset.statusColumn && [...body.rows].some(row=>row.querySelector('[data-play-track]'))){
      const th=document.createElement('th');th.textContent=I18n.t('File status');
      th.dataset.sortType='status';th.dataset.resultFileStatus='true';table.tHead.rows[0].append(th);
      for(const row of body.rows){
        const b=row.querySelector('[data-play-track]'),status=b?.dataset.fileStatus || 'unchecked';
        const td=document.createElement('td');td.className='result-file-status-cell';td.dataset.sortValue=status;
        td.textContent=I18n.t(statusLabels[status]||'Unchecked');row.append(td);
      }
      table.dataset.statusColumn='true';
    }
    for(let index=0;index<table.tHead.rows[0].cells.length;index++){
      const th=headings[index];if(th.querySelector('[data-sort-column]'))continue;
      if(th.querySelector('button,a,input,select,textarea') || !th.textContent.trim())continue;
      const button=document.createElement('button');button.type='button';button.className='result-sort-button';
      button.dataset.sortColumn=String(index);
      button.title='Sort visible rows on this page only';
      button.setAttribute('aria-label',I18n.t('Sort visible rows by')+' '+th.textContent.trim());
      while(th.firstChild)button.append(th.firstChild);
      th.append(button);th.classList.add('result-sortable');
    }
  }
  function visit(root){
    if(root.nodeType!==1)return;
    if(root.matches?.('table'))prepare(root);
    for(const table of root.querySelectorAll?.('table')||[])prepare(table);
  }
  const observer=new MutationObserver(records=>{
    // A single visit covers a newly rendered table, without repeatedly sorting
    // or rewriting the DOM of tables that are already initialized.
    const roots=new Set();
    for(const record of records){
      if(record.type==='childList')for(const node of record.addedNodes)if(node.nodeType===1)roots.add(node);
    }
    for(const root of roots)visit(root);
  });
  observer.observe(document.body,{childList:true,subtree:true});
  document.addEventListener('workbench-file-status',event=>{
    const row=event.target.closest('tr'),cell=row?.querySelector('.result-file-status-cell');
    if(!cell)return;
    const status=event.detail?.status || 'unverified';cell.dataset.sortValue=status;
    cell.textContent=I18n.t(statusLabels[status]||'Unverified');
  });
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-sort-column]');if(!button)return;
    const table=button.closest('table'),th=button.closest('th');if(!table||!th)return;
    const index=Number(button.dataset.sortColumn),prior=state.get(table);
    const direction=prior?.index===index&&prior.direction==='ascending'?'descending':'ascending';
    sort(table,index,direction);
  });
  window.addEventListener('workbench-language',()=>{
    sorter=new Intl.Collator(I18n.language,{numeric:true,sensitivity:'base'});
    for(const table of document.querySelectorAll('table[data-status-column]')){
      const heading=table.querySelector('th[data-result-file-status] .result-sort-button');
      if(heading)heading.textContent=I18n.t('File status');
      for(const cell of table.querySelectorAll('.result-file-status-cell'))cell.textContent=I18n.t(statusLabels[cell.dataset.sortValue]||'Unchecked');
    }
    visit(document.body);
  });
  visit(document.body);
  return {sort,prepare};
})();