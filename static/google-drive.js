/* Explicit account authorization, metadata checks and single-file downloads. */
window.GoogleDriveConnector=(()=>{
  const node=id=>document.getElementById('google-drive-'+id),t=key=>I18n.t(key);
  let connection=null,source='',offset=0,pageRows=0,totalRows=0,revision=0,filesRevision=0,busy=false,pending=null,requestedSource='';
  const statusNames={present:'Reachable',not_found:'Not found',unmapped:'Unmapped',ambiguous:'Ambiguous paths',unverified:'Unverified'};
  const post=(path,body={},item='')=>CloudOperations.post('google_drive','/api/google-drive',path,body,item);
  function controls(){
    for(const id of ['client-id','client-secret','remember','save','connect','disconnect','source','search','status','find','check','refresh'])node(id).disabled=busy;
    node('connect').disabled=busy||!node('client-id').value.trim();
    node('disconnect').disabled=busy||!(connection?.connected||connection?.persistent||connection?.credential_storage?.persistent||connection?.credential_cleanup_pending);
    node('remember').disabled=busy||connection?.credential_storage?.available===false;
    node('check').disabled=busy||!connection?.connected||!connection?.mapping||!node('source').value;
    node('previous').disabled=busy||offset===0;node('next').disabled=busy||offset+pageRows>=totalRows;
    for(const button of node('results').querySelectorAll('[data-google-drive-download]'))button.disabled=busy||!connection?.connected;
  }
  function renderConnection(data){
    connection=data;
    if(document.activeElement!==node('client-id'))node('client-id').value=data.client_id||'';
    node('redirect').value=data.redirect_uri||'';
    node('remember').checked=Boolean(data.remember ?? data.credential_storage?.persistent);
    node('connection-state').textContent=t(data.connected?'Connected to Google Drive':'Google Drive is not connected')+(data.connected?' · '+[data.account?.name,data.account?.email].filter(Boolean).join(' · '):'');
    node('connection-state').dataset.connected=String(Boolean(data.connected));
    node('authorization-error').textContent=typeof data.authorization_error==='string'?data.authorization_error:'';node('authorization-error').hidden=!node('authorization-error').textContent;
    node('cleanup-state').textContent=data.credential_cleanup_pending?t('Credential removal is pending. Select Disconnect to retry.'):'';node('cleanup-state').hidden=!data.credential_cleanup_pending;
    node('storage-state').textContent=t(data.credential_storage?.available===false?'Session-only connection; no secure credential store is available.':node('remember').checked?'Credentials stay in the operating system credential store.':'Session-only connection');
    const mapping=data.mapping||null,summary=node('mapping-summary');summary.replaceChildren();
    if(mapping){
      for(const [label,value] of [['Folder on this computer',mapping.local_root],['Folder in cloud account',mapping.remote_name||mapping.remote_folder_id||mapping.remote_root]]){
        const row=document.createElement('p'),caption=document.createElement('strong'),path=document.createElement('code');
        caption.textContent=t(label);path.textContent=value||'';row.append(caption,path);summary.append(row);
      }
    }else summary.textContent=t('Not attached');
    controls();
  }
  async function loadFiles(){
    const generation=++filesRevision,selected=node('source').value;source=selected;
    if(!selected||!connection?.connected||!connection?.mapping){offset=pageRows=totalRows=0;node('results').replaceChildren();node('count').textContent='';node('checked').textContent=t('Not checked');controls();return;}
    const data=await api('/api/google-drive/files?'+new URLSearchParams({source:selected,offset:String(offset),q:node('search').value,status:node('status').value}),{feedback:false});
    if(generation!==filesRevision||selected!==node('source').value)return;
    const rows=data.rows||[],table=document.createElement('table'),head=document.createElement('thead'),body=document.createElement('tbody');
    head.innerHTML='<tr>'+['Track','Artist','File status','Size','Actions'].map(key=>'<th>'+esc((key==='File status'?'Google Drive · ':'')+t(key))+'</th>').join('')+'</tr>';
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
      if(row.downloadable===true){const button=document.createElement('button');button.type='button';button.className='button secondary small';button.dataset.googleDriveDownload=row.track_id;button.textContent=t('Download this track');button.onclick=wrap(()=>prepareDownload(selected,row.track_id));action.append(button);}
      else if(row.local_state==='online_only')action.textContent=t('Open cloud-managed audio');
      tr.append(name,artist,state,size,action);body.append(tr);
    }
    table.append(head,body);node('results').replaceChildren(table);
    const total=Number(data.total||0);totalRows=total;pageRows=rows.length;node('count').textContent=num(total)+' · '+(total?num(offset+1)+'–'+num(Math.min(offset+rows.length,total)):'0');
    node('checked').textContent=data.checked_at?snapshotMoment(typeof data.checked_at==='number'?new Date(data.checked_at*1000).toISOString():data.checked_at):t('Not checked');
    controls();
  }
  async function load(){
    const generation=++revision;
    const [status,journeys]=await Promise.all([api('/api/google-drive/status',{feedback:false}),api('/api/journeys',{feedback:false})]);
    if(generation!==revision)return;
    renderConnection(status);
    const old=requestedSource||node('source').value||window.BrowseState?.value('google-drive-source')||window.Journeys?.context?.()?.source;
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
  const configuration=()=>{
    const value={client_id:node('client-id').value.trim(),remember:node('remember').checked};
    if(node('client-secret').value.trim())value.client_secret=node('client-secret').value.trim();
    return value;
  };
  async function configure(){try{return await post('/configure',configuration());}finally{node('client-secret').value='';}}
  node('save').onclick=wrap(()=>action(async()=>{await configure();await load();}));
  node('connect').onclick=wrap(()=>action(async()=>{
    await configure();
    const result=await post('/connect'),url=new URL(result.authorize_url);
    if(url.origin!=='https://accounts.google.com'||url.pathname!=='/o/oauth2/v2/auth'||url.username||url.password)throw new Error(t('The action could not be completed'));
    window.location.assign(url.href);
  }));
  node('disconnect').onclick=wrap(()=>action(async()=>{await post('/disconnect');await load();}));
  node('refresh').onclick=wrap(()=>CloudOperations.run('google_drive','Refresh',load));
  node('copy-redirect').onclick=wrap(()=>copyCloudRedirect(node('redirect')));
  node('check').onclick=wrap(()=>action(async()=>{const selected=node('source').value,result=await post('/check',{source:selected});window.dispatchEvent(new CustomEvent('workbench-cloud-evidence',{detail:{source:selected,provider:'google_drive'}}));if(selected===node('source').value){offset=0;await loadFiles();}notify(CloudOperations.checked('google_drive',result));}));
  node('source').onchange=wrap(async()=>{offset=0;await browseFiles();});
  const browseFiles=()=>CloudOperations.run('google_drive','Saved file evidence',loadFiles,'',200);
  node('find').onclick=wrap(async()=>{offset=0;await browseFiles();});
  node('status').onchange=wrap(async()=>{offset=0;await browseFiles();});
  node('search').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();node('find').click();}};
  node('client-id').oninput=controls;
  node('remember').onchange=()=>{node('storage-state').textContent=t(node('remember').checked?'Credentials stay in the operating system credential store.':'Session-only connection');};
  node('previous').onclick=wrap(async()=>{offset=Math.max(0,offset-50);await browseFiles();});
  node('next').onclick=wrap(async()=>{offset+=50;await browseFiles();});
  async function prepareDownload(selected,identity){
    await action(async()=>{
      const result=await post('/download/prepare',{source:selected,track_id:identity},identity);
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
    await action(async()=>{await post('/download',{...intent,confirm:true},node('download-title').textContent);window.dispatchEvent(new CustomEvent('workbench-cloud-evidence',{detail:{source:intent.source,provider:'google_drive',track_id:intent.track_id}}));await loadFiles();TrackPlayback.recheck({force:true,source:intent.source,track_id:intent.track_id});notify(t('One track downloaded'));});
  });
  const visible=()=>!document.getElementById('view-google-drive').hidden;
  window.addEventListener('focus',()=>{if(visible()&&!busy)void load().catch(error=>notify(error.message,true));});
  window.addEventListener('workbench-language',()=>{if(visible()&&!busy)void load().catch(error=>notify(error.message,true));});
  function forSource(value){
    if(typeof value!=='string'||!/^(?:snapshot|capture):[a-f0-9]{32}$/u.test(value))return false;
    requestedSource=value;revision++;filesRevision++;pending=null;
    if(node('download-dialog').open)node('download-dialog').close();
    window.BrowseState?.set('google-drive-source',value);return true;
  }
  for(const button of document.querySelectorAll('#view-google-drive [data-view="cloud-connect"]'))button.onclick=()=>{window.CloudConnections?.forSource?.(node('source').value,'google_drive');showView('cloud-connect');};
  controls();return {load,forSource};
})();
if(!document.getElementById('view-google-drive').hidden)GoogleDriveConnector.load().catch(error=>notify(error.message,true));
