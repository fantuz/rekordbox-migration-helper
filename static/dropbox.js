/* Explicit account authorization, metadata checks and single-file downloads. */
window.DropboxConnector=(()=>{
  const node=id=>document.getElementById('dropbox-'+id),t=key=>I18n.t(key);
  let connection=null,source='',offset=0,pageRows=0,totalRows=0,revision=0,filesRevision=0,busy=false,pending=null,requestedSource='',mappingDraft=false;
  const statusNames={present:'Present',not_found:'Not found',unmapped:'Unmapped',unverified:'Unverified'};
  const post=(path,body={})=>api('/api/dropbox'+path,{method:'POST',body:JSON.stringify(body)});
  function mappingChanged(){
    const local=node('local-root').value.trim(),remote=node('remote-root').value.trim(),namespace=node('namespace').value.trim();
    const saved=connection?.mapping;if(!saved)return Boolean(local||remote||namespace);
    const localKey=value=>{let path=String(value||'').trim().replace(/\\/gu,'/');const windows=/^[A-Za-z]:\//u.test(path);if(path.length>1&&!/^[A-Za-z]:\/$/u.test(path))path=path.replace(/\/$/u,'');return windows?path.toLowerCase():path;};
    const remoteKey=value=>{const path=String(value||'').trim();return (path==='/'?'':path.replace(/\/$/u,'')).normalize('NFC').toLowerCase();};
    const accountRoot=connection?.account?.root_namespace_id||'';
    return localKey(local)!==localKey(saved.local_root)||remoteKey(remote)!==remoteKey(saved.remote_root)||
      (namespace||accountRoot)!==(String(saved.namespace||accountRoot));
  }
  function renderNamespaces(state,input,select,context,list,remote){
    const account=state.account||{},valid=value=>typeof value==='string'&&/^\d{1,40}$/u.test(value);
    const home=valid(account.home_namespace_id)?account.home_namespace_id:'',root=valid(account.root_namespace_id)?account.root_namespace_id:'';
    const values=[];
    if(home||root)values.push([home||root,'Member home folder']);
    if(root&&home&&root!==home)values.push([root,'Team root folder']);
    const current=input.value.trim(),effective=current||root||home;
    select.replaceChildren(new Option(t("Leave blank to use the connected account's namespace."),''),...values.map(([value,label])=>new Option(t(label)+' · '+value,value)));
    select.value=values.some(([value])=>value===current)?current:'';select.disabled=busy||!state.connected;
    list.replaceChildren(...values.map(([value,label])=>new Option(t(label),value)));
    const known=values.find(([value])=>value===effective),identity=account.name||account.display_name||account.email||account.account_id||'';
    const lines=[];
    if(identity)lines.push(t('Connected account')+' · '+identity);
    if(effective)lines.push(t(known?.[1]||'Team namespace (optional)')+' · '+effective);
    if(effective)lines.push(t('Folder in cloud account')+' · '+(remote.value.trim()||'/'));
    if(typeof account.home_path==='string'&&account.home_path)lines.push(t('Member home folder')+' · '+account.home_path);
    context.textContent=lines.join('\n');context.hidden=!lines.length;
  }
  function controls(){
    mappingDraft=mappingChanged();
    for(const id of ['app-key','remember','save','connect','disconnect','local-root','remote-root','namespace','namespace-choice','mapping-save','source','search','status','find','check','refresh'])node(id).disabled=busy;
    node('connect').disabled=busy||!node('app-key').value.trim();
    node('disconnect').disabled=busy||!(connection?.connected||connection?.persistent||connection?.credential_storage?.persistent||connection?.credential_cleanup_pending);
    node('remember').disabled=busy||connection?.credential_storage?.available===false;
    node('mapping-save').disabled=busy||!connection?.connected;
    node('namespace-choice').disabled=busy||!connection?.connected;
    let hint=node('mapping-draft');if(!hint){hint=document.createElement('p');hint.id='dropbox-mapping-draft';hint.className='dropbox-note';hint.setAttribute('role','status');node('mapping-save').after(hint);}
    hint.textContent=t('Verify folder mapping');hint.hidden=!mappingDraft;
    node('check').disabled=busy||mappingDraft||!connection?.connected||!connection?.mapping||!node('source').value;
    node('previous').disabled=busy||offset===0;node('next').disabled=busy||offset+pageRows>=totalRows;
    for(const button of node('results').querySelectorAll('[data-dropbox-download]'))button.disabled=busy||mappingDraft||!connection?.connected;
  }
  function renderConnection(data){
    if(connection&&(connection.account?.account_id||'')!==(data.account?.account_id||''))mappingDraft=false;
    connection=data;
    if(document.activeElement!==node('app-key'))node('app-key').value=data.app_key||'';
    node('redirect').value=data.redirect_uri||'';
    node('remember').checked=Boolean(data.remember ?? data.credential_storage?.persistent);
    node('connection-state').textContent=t(data.connected?'Connected to Dropbox':'Dropbox is not connected')+(data.connected&&data.account?.name?' · '+data.account.name:'');
    node('connection-state').dataset.connected=String(Boolean(data.connected));
    node('authorization-error').textContent=[data.authorization_error,data.permission_error].filter(value=>typeof value==='string'&&value).join('\n');node('authorization-error').hidden=!node('authorization-error').textContent;
    node('cleanup-state').textContent=data.credential_cleanup_pending?t('Credential removal is pending. Select Disconnect Dropbox to retry.'):'';node('cleanup-state').hidden=!data.credential_cleanup_pending;
    node('storage-state').textContent=t(data.credential_storage?.available===false?'Session-only connection; no secure credential store is available.':node('remember').checked?'Credentials stay in the operating system credential store.':'Session-only connection');
    const mapping=data.mapping||{};
    for(const [id,field] of [['local-root','local_root'],['remote-root','remote_root'],['namespace','namespace']]){
      if(!mappingDraft&&document.activeElement!==node(id))node(id).value=mapping[field]??'';
    }
    node('roots').replaceChildren(...(data.roots||[]).map(root=>new Option(root.root,root.root)));
    renderNamespaces(data,node('namespace'),node('namespace-choice'),node('namespace-context'),node('namespaces'),node('remote-root'));
    controls();
  }
  async function loadFiles(){
    mappingDraft=mappingChanged();
    const generation=++filesRevision,selected=node('source').value;source=selected;
    if(!selected||mappingDraft||!connection?.connected||!connection?.mapping){offset=pageRows=totalRows=0;node('results').replaceChildren();node('count').textContent='';node('checked').textContent=t('Not checked');controls();return;}
    const data=await api('/api/dropbox/files?'+new URLSearchParams({source:selected,offset:String(offset),q:node('search').value,status:node('status').value}),{feedback:false});
    if(generation!==filesRevision||selected!==node('source').value)return;
    const rows=data.rows||[],table=document.createElement('table'),head=document.createElement('thead'),body=document.createElement('tbody');
    head.innerHTML='<tr>'+['Track','Artist','File status','Size','Actions'].map(key=>'<th>'+esc((key==='File status'?'Dropbox · ':'')+t(key))+'</th>').join('')+'</tr>';
    for(const row of rows){
      const tr=document.createElement('tr');
      const name=document.createElement('td'),title=document.createElement('strong'),path=document.createElement('small');
      title.textContent=row.title||row.filename||row.track_id;
      name.innerHTML=TrackPlayback.button(selected.startsWith('snapshot:')?selected.slice(9):selected,row.track_id);
      name.append(title);path.className='subtle dropbox-path';path.textContent=row.remote_path||row.filename||'';name.append(path);
      const artist=document.createElement('td');artist.textContent=row.artist||'—';
      const state=document.createElement('td'),badge=document.createElement('span');badge.className='dropbox-evidence dropbox-evidence-'+(Object.hasOwn(statusNames,row.status)?row.status:'unverified');badge.textContent=t(statusNames[row.status]||'Unverified');state.append(badge);
      const size=document.createElement('td');size.textContent=row.size===null||row.size===undefined?t('Unknown'):bytes(row.size);
      const action=document.createElement('td');
      if(row.downloadable===true){const button=document.createElement('button');button.type='button';button.className='button secondary small';button.dataset.dropboxDownload=row.track_id;button.textContent=t('Download this track');button.onclick=wrap(()=>prepareDownload(selected,row.track_id));action.append(button);}
      else if(row.local_state==='online_only')action.textContent=t('Open cloud-managed audio');
      tr.append(name,artist,state,size,action);body.append(tr);
    }
    table.append(head,body);node('results').replaceChildren(table);
    const total=Number(data.total||0);totalRows=total;pageRows=rows.length;node('count').textContent=num(total)+' · '+(total?num(offset+1)+'–'+num(Math.min(offset+rows.length,total)):'0');
    const checked=data.checked_at?snapshotMoment(typeof data.checked_at==='number'?new Date(data.checked_at*1000).toISOString():data.checked_at):t('Not checked');
    node('checked').textContent=checked+(data.complete===false?' · '+t('Unverified'):'')+(typeof data.scan_note==='string'&&data.scan_note?' · '+data.scan_note:'');
    controls();
  }
  async function load(){
    const generation=++revision;
    const [status,journeys]=await Promise.all([api('/api/dropbox/status',{feedback:false}),api('/api/journeys',{feedback:false})]);
    if(generation!==revision)return;
    renderConnection(status);
    const old=requestedSource||node('source').value||window.BrowseState?.value('dropbox-source')||window.Journeys?.context?.()?.source;
    const choices=(journeys.sources||[]).filter(row=>/^(?:snapshot|capture):[a-f0-9]{32}$/u.test(row.id));
    node('source').replaceChildren(new Option(t('Choose a saved collection snapshot'),''),...choices.map(row=>new Option(row.label+' · '+snapshotMoment(row.created),row.id)));
    node('source').value=choices.some(row=>row.id===old)?old:'';
    requestedSource='';
    if(source!==node('source').value)offset=0;
    await loadFiles();
  }
  async function action(work){
    if(busy)return;busy=true;controls();
    try{await work();}finally{busy=false;controls();}
  }
  const configuration=()=>({app_key:node('app-key').value.trim(),remember:node('remember').checked});
  node('save').onclick=wrap(()=>action(async()=>{await post('/configure',configuration());await load();}));
  node('connect').onclick=wrap(()=>action(async()=>{
    await post('/configure',configuration());
    const result=await post('/connect'),url=new URL(result.authorize_url);
    if(url.origin!=='https://www.dropbox.com'||url.pathname!=='/oauth2/authorize'||url.username||url.password)throw new Error(t('The action could not be completed'));
    window.location.assign(url.href);
  }));
  node('disconnect').onclick=wrap(()=>action(async()=>{await post('/disconnect');await load();}));
  node('mapping-save').onclick=wrap(()=>action(async()=>{
    await post('/mapping',{local_root:node('local-root').value.trim(),remote_root:node('remote-root').value.trim(),namespace:node('namespace').value.trim()});mappingDraft=false;await load();
  }));
  node('refresh').onclick=wrap(load);
  node('namespace-choice').onchange=()=>{
    node('namespace').value=node('namespace-choice').value;node('remote-root').value='';pending=null;
    if(node('download-dialog').open)node('download-dialog').close();
    renderNamespaces(connection||{},node('namespace'),node('namespace-choice'),node('namespace-context'),node('namespaces'),node('remote-root'));
    mappingDraft=true;void loadFiles();
  };
  function mappingInputChanged(){mappingDraft=mappingChanged();pending=null;if(node('download-dialog').open)node('download-dialog').close();renderNamespaces(connection||{},node('namespace'),node('namespace-choice'),node('namespace-context'),node('namespaces'),node('remote-root'));void loadFiles();}
  for(const id of ['namespace','remote-root','local-root'])for(const event of ['input','change'])node(id).addEventListener(event,mappingInputChanged);
  node('copy-redirect').onclick=wrap(()=>copyCloudRedirect(node('redirect')));
  node('check').onclick=wrap(()=>action(async()=>{if(mappingChanged()){mappingDraft=true;await loadFiles();return;}const selected=node('source').value,result=await post('/check',{source:selected});if(result.job)await poll(result.job);window.dispatchEvent(new CustomEvent('workbench-cloud-evidence',{detail:{source:selected,provider:'dropbox'}}));if(selected===node('source').value){offset=0;await loadFiles();}notify(t('Cloud check complete'));}));
  node('source').onchange=wrap(async()=>{offset=0;await loadFiles();});
  node('find').onclick=wrap(async()=>{offset=0;await loadFiles();});
  node('status').onchange=wrap(async()=>{offset=0;await loadFiles();});
  node('search').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();node('find').click();}};
  node('app-key').oninput=controls;
  node('remember').onchange=()=>{node('storage-state').textContent=t(node('remember').checked?'Credentials stay in the operating system credential store.':'Session-only connection');};
  node('previous').onclick=wrap(async()=>{offset=Math.max(0,offset-50);await loadFiles();});
  node('next').onclick=wrap(async()=>{offset+=50;await loadFiles();});
  async function prepareDownload(selected,identity){
    await action(async()=>{
      const result=await post('/download/prepare',{source:selected,track_id:identity});
      if(result.confirmation_required!==true||!result.confirmation_token)return;
      pending={source:selected,track_id:identity,confirmation_token:result.confirmation_token};
      node('download-title').textContent=result.title||result.filename||identity;
      node('download-path').textContent=result.local_path||'';
      node('download-size').textContent=result.size===null||result.size===undefined?t('Unknown'):bytes(result.size);
      node('download-dialog').showModal();node('download-cancel').focus();
    });
  }
  node('download-cancel').onclick=()=>{pending=null;node('download-dialog').close();};
  node('download-dialog').addEventListener('cancel',()=>{pending=null;});
  node('download-dialog').addEventListener('close',()=>{pending=null;});
  node('download-confirm').onclick=wrap(async()=>{
    const intent=pending;if(!intent)return;pending=null;node('download-dialog').close();
    await action(async()=>{const result=await post('/download',{...intent,confirm:true});if(result.job)await poll(result.job);window.dispatchEvent(new CustomEvent('workbench-cloud-evidence',{detail:{source:intent.source,provider:'dropbox',track_id:intent.track_id}}));await loadFiles();TrackPlayback.recheck();notify(t('One track downloaded'));});
  });
  const visible=()=>!document.getElementById('view-dropbox').hidden;
  window.addEventListener('focus',()=>{if(visible()&&!busy)void load().catch(error=>notify(error.message,true));});
  window.addEventListener('workbench-language',()=>{if(visible()&&!busy)void load().catch(error=>notify(error.message,true));});
  function forSource(value){
    if(typeof value!=='string'||!/^(?:snapshot|capture):[a-f0-9]{32}$/u.test(value))return false;
    requestedSource=value;revision++;filesRevision++;pending=null;
    if(node('download-dialog').open)node('download-dialog').close();
    window.BrowseState?.set('dropbox-source',value);return true;
  }
  for(const button of document.querySelectorAll('#view-dropbox [data-view="cloud-connect"]'))button.onclick=()=>{window.CloudConnections?.forSource?.(node('source').value,'dropbox');showView('cloud-connect');};
  controls();return {load,forSource,renderNamespaces};
})();
if(!document.getElementById('view-dropbox').hidden)DropboxConnector.load().catch(error=>notify(error.message,true));
