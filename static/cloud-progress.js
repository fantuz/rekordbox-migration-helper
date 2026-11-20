/* Exact progress for foreground cloud operations in the shared status dialog. */
window.CloudOperations=(()=>{
  const providers={dropbox:'Dropbox',google_drive:'Google Drive'};
  const phases={'/configure':'Save connection settings','/connect':'Connect account','/disconnect':'Disconnect',
    '/mapping':'Verify folder mapping','/folders':'Browse cloud folders','/preview':'Preview attachment',
    '/attach':'Attach this location','/detach':'Detach location','/check':'Check remote files',
    '/download/prepare':'Prepare download','/download':'Downloading audio'};
  const units={entries:'Entries',tracks:'Tracks',bytes:'Bytes'};
  const validCount=value=>Number.isSafeInteger(value)&&value>=0;
  const put=(node,text)=>{if(node.textContent!==text)node.textContent=text;};

  function render(detail){
    const box=$('#progress-cloud'),counts=$('#progress-counts'),item=$('#progress-item'),bar=$('#progress-bar');
    box.hidden=!detail;
    if(!detail){put(counts,'');put(item,'');bar.removeAttribute('aria-valuetext');return null;}
    const label=detail.provider+' · '+I18n.t(detail.phase),parts=[];
    const known=validCount(detail.total)&&validCount(detail.completed)&&detail.completed<=detail.total;
    if(Object.hasOwn(units,detail.unit)&&validCount(detail.completed)){
      parts.push(I18n.t(units[detail.unit])+' '+num(detail.completed)+(known?' / '+num(detail.total):''));
    }
    if(detail.unit!=='entries'&&validCount(detail.entries))parts.push(I18n.t('Entries')+' '+num(detail.entries));
    if(validCount(detail.pages))parts.push(I18n.t('Metadata pages')+' '+num(detail.pages));
    if(detail.unit==='entries'&&!known)parts.push(I18n.t('Total unknown'));
    const countText=parts.join(' · ');
    put(counts,countText);put(item,detail.item||'');
    if(countText)bar.setAttribute('aria-valuetext',countText);else bar.removeAttribute('aria-valuetext');
    return {label,percent:known&&detail.total>0?100*detail.completed/detail.total:null,
      activity:[label,countText,item.textContent].join(' · ')};
  }

  async function run(provider,phase,work,item='',delay=0){
    const leaf=String(item||'').replaceAll('\\','/').split('/').filter(Boolean).at(-1)||'';
    const itemName=Array.from(leaf.replace(/(?![\u200c\u200d])[\p{Cc}\p{Cf}\p{Cs}]/gu,'')).slice(0,180).join('');
    const owner=Symbol(),detail={provider:providers[provider]||I18n.t('Cloud-managed audio'),phase,item:itemName};
    const show=()=>{progressOwner=owner;progress(null,'',null,detail);};
    // Cached table reads usually finish before feedback becomes visible.
    const timer=delay?setTimeout(()=>{if(!$('#progress').open)show();},delay):null;
    if(!delay)show();
    try{
      const value=await work();
      return value?.job?await poll(value.job,detail,owner):value;
    }finally{clearTimeout(timer);if(progressOwner===owner)finishProgress();}
  }

  function post(provider,endpoint,path,body={},item=''){
    return run(provider,phases[path],()=>api(endpoint+path,{method:'POST',body:JSON.stringify(body),feedback:false}),item);
  }
  function checked(provider,result){
    const parts=[providers[provider],I18n.t('Cloud check complete')];
    if(validCount(result.checked))parts.push(I18n.t('Tracks')+' '+num(result.checked));
    if(validCount(result.coverage?.entries_listed))parts.push(I18n.t('Entries')+' '+num(result.coverage.entries_listed));
    if(validCount(result.coverage?.pages_read))parts.push(I18n.t('Metadata pages')+' '+num(result.coverage.pages_read));
    return parts.join(' · ');
  }
  return {run,post,render,checked};
})();
