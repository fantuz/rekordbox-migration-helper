/* Guided account and folder attachment. No transfer starts during discovery. */
window.CloudConnections=(()=>{
  const node=id=>document.getElementById('cloud-setup-'+id),t=key=>I18n.t(key);
  const names={dropbox:'Dropbox',google_drive:'Google Drive'};
  let model=null,step=0,furthest=0,busy=false,preview=null,revision=0,folder=null,folderStack=[];
  const provider=()=>node('google').checked?'google_drive':'dropbox';
  const endpoint=()=>provider()==='dropbox'?'/api/dropbox':'/api/google-drive';
  const post=(path,value={})=>api('/api/cloud-setup'+path,{method:'POST',body:JSON.stringify(value)});
  const accountState=()=>{const value=model?.providers?.[provider()]||{};return value.status||value;};
  const accountName=state=>{const account=state?.account||{},name=account.name||account.display_name||'';return [name,account.email].filter((value,index,values)=>value&&values.indexOf(value)===index).join(' · ')||account.account_id||'';};
  function remember(){
    // Preserve only navigation declarations, never paths, credentials or consent.
    try{sessionStorage.setItem('workbench-cloud-setup',JSON.stringify({provider:provider(),arrangement:node('arrangement').value,sync_mode:node('sync-mode').value,source:node('source').value,step:Math.min(step,2)}));}catch{}
  }
  function restore(){
    try{
      const value=JSON.parse(sessionStorage.getItem('workbench-cloud-setup')||'{}');
      node('google').checked=value.provider==='google_drive';node('dropbox').checked=!node('google').checked;
      return value;
    }catch{return {};}
  }
  const initial=restore();
  function choices(select,values,old){
    select.replaceChildren(...values.map(([value,label])=>new Option(t(label),value)));
    if(values.some(([value])=>value===old))select.value=old;
  }
  function renderProvider(changed=false){
    const google=provider()==='google_drive',state=accountState(),mapping=state.mapping||model?.attachments?.[provider()]?.mapping||model?.attachments?.[provider()]||{},configuration=model?.settings?.[provider()]||mapping.configuration||mapping;
    choices(node('arrangement'),google?[['own_google','My Google account']]:[['personal','Personal Dropbox'],['own_team','Other Dropbox team'],['cloud_option','Cloud Option DJ team'],['professional','Professional DJ team']],changed?configuration.arrangement||'':node('arrangement').value||initial.arrangement||configuration.arrangement);
    choices(node('sync-mode'),google?[['selected','Selected music files only']]:[['selected','Selected music files only'],['all','All music files through Dropbox desktop']],changed?configuration.sync_mode||'':node('sync-mode').value||initial.sync_mode||configuration.sync_mode);
    choices(node('desktop-mode'),google?[['unknown','Unknown'],['not_installed','Desktop app not installed'],['stream','Stream files'],['mirror','Mirror files']]:[['unknown','Unknown'],['not_installed','Desktop app not installed'],['online_only','Online-only'],['local','Available offline'],['selective','Selective sync']],changed?configuration.desktop_mode||'unknown':node('desktop-mode').value||configuration.desktop_mode||'unknown');
    node('key-name').textContent=t(google?'Google desktop OAuth client ID':'Dropbox app key (public client ID)');
    if(changed||!node('client-id').value)node('client-id').value=google?state.client_id||'':state.app_key||'';
    if(changed)node('client-secret').value='';node('secret-details').hidden=!google;node('namespace-label').hidden=google;
    node('remote-name').textContent=t(google?'Google Drive folder ID or URL':'Dropbox folder in your account');
    node('redirect').value=state.redirect_uri||'';
    node('redirect-help').textContent=t(google?'Use a Google desktop OAuth client. Its loopback callback is handled by this application.':"Add this exact URL to your Dropbox app's OAuth 2 redirect URIs before connecting.");
    node('redirect-mismatch').hidden=google;
    node('developer-console').href=google?'https://console.cloud.google.com/apis/credentials':'https://www.dropbox.com/developers/apps';
    const connected=Boolean(state.connected),identity=accountName(state);
    node('account-state').textContent=names[provider()]+' · '+t(connected?'Connected account':'Not connected')+(identity?' · '+identity:'');
    node('account-state').dataset.connected=String(connected);
    node('auth-error').textContent=state.authorization_error||'';node('auth-error').hidden=!node('auth-error').textContent;
    const credentials=state.credential_storage||{available:state.secure_storage_available,persistent:state.persistent};
    node('remember').disabled=busy||credentials.available===false;
    if(changed||document.activeElement!==node('remember'))node('remember').checked=Boolean(state.remember??credentials.persistent);
    node('storage-state').textContent=t(state.credential_cleanup_pending?'Credential removal is pending. Select Disconnect to retry.':credentials.available===false?'Session-only connection; no secure credential store is available.':node('remember').checked?'Credentials stay in the operating system credential store.':'Session-only connection');
    if(changed){
      if(configuration.desktop_mode)node('desktop-mode').value=configuration.desktop_mode;
      if(configuration.default_upload)node('default-upload').value=configuration.default_upload;
      node('local-root').value=mapping.local_root||'';node('recorded-root').value=mapping.recorded_root||'';
      node('remote-root').value=google?mapping.remote_folder_id||mapping.remote_root||'':mapping.remote_root||'';
      node('namespace').value=mapping.namespace||'';folder=null;folderStack=[];node('folder-browser').hidden=true;
    }
    renderSuggestions();controls();
  }
  function controls(){
    for(const input of document.querySelectorAll('#view-cloud-connect input,#view-cloud-connect select,#view-cloud-connect button'))input.disabled=busy;
    const state=accountState(),credentials=state.credential_storage||{available:state.secure_storage_available};
    node('remember').disabled=busy||credentials.available===false;
    node('connect').disabled=busy||!node('client-id').value.trim();
    node('copy-redirect').disabled=busy||!node('redirect').value;
    node('disconnect').disabled=busy||!(state.connected||state.persistent||state.credential_cleanup_pending||state.credential_storage?.persistent);
    node('previous').disabled=busy||step===0;node('next').hidden=step===3;
    node('next').disabled=busy||(step===1&&!state.connected)||(step===2&&(!state.connected||!node('source').value||!node('local-root').value.trim()));
    node('next').textContent=t(step===2?'Preview attachment':'Next');
    node('attach').disabled=busy||preview?.attachable!==true||!preview?.preview_token;
    node('browse').disabled=busy||!state.connected;
    node('folder-up').disabled=busy||folderStack.length===0;
    document.querySelectorAll('[data-cloud-step]').forEach(button=>{const index=Number(button.dataset.cloudStep);button.disabled=busy||index>furthest;});
    document.querySelectorAll('[data-cloud-active=false]').forEach(button=>button.disabled=true);
  }
  function showStep(value,focus=true){
    step=Math.max(0,Math.min(3,value));furthest=Math.max(furthest,step);
    document.querySelectorAll('[data-cloud-panel]').forEach(panel=>panel.hidden=Number(panel.dataset.cloudPanel)!==step);
    document.querySelectorAll('[data-cloud-step]').forEach(button=>{
      const index=Number(button.dataset.cloudStep);button.dataset.complete=String(index<step);
      if(index===step)button.setAttribute('aria-current','step');else button.removeAttribute('aria-current');
    });
    controls();remember();
    if(focus)document.querySelector('[data-cloud-panel="'+step+'"] h3')?.focus({preventScroll:true});
  }
  function invalidate(){preview=null;furthest=Math.min(furthest,2);node('attach').disabled=true;remember();}
  async function action(work){if(busy)return;busy=true;controls();try{return await work();}finally{busy=false;controls();}}
  function rootValues(){
    const roots=model?.roots||[];
    return roots.filter(row=>row.kind===provider()||!row.kind||row.kind==='local');
  }
  function renderSuggestions(){
    const roots=rootValues(),container=node('suggestions');container.replaceChildren();
    node('local-roots').replaceChildren(...roots.map(row=>new Option(row.root,row.root)));
    for(const row of roots){
      const button=document.createElement('button');button.type='button';button.className='cloud-location-option';
      const path=document.createElement('code'),evidence=document.createElement('span');path.textContent=row.root||'';
      evidence.textContent=(names[row.kind]||t('Local'))+' · '+t(row.provider_verified?'Detected provider folder':'Folder name only');
      button.append(path,evidence);button.onclick=()=>{node('local-root').value=row.root||'';invalidate();controls();};container.append(button);
    }
    const candidates=model?.suggestions||model?.source?.suggestions||[];
    for(const row of candidates.filter(item=>(!item.provider||item.provider===provider())&&(!item.kind||item.kind==='local'||item.kind===provider()))){
      const local=row.local_root||row.root||row.path;if(!local||roots.some(item=>item.root===local))continue;
      const button=document.createElement('button');button.type='button';button.className='cloud-location-option';
      const path=document.createElement('code'),evidence=document.createElement('span');path.textContent=local;
      evidence.textContent=t('Library path suggestion')+' · '+t('Recorded prefix · optional')+(row.tracks?' · '+num(row.tracks)+' '+t('Tracks'):'');button.append(path,evidence);
      button.onclick=()=>{node('recorded-root').value=row.recorded_root||local;if(!row.foreign&&(row.local_root||row.root||row.available===true))node('local-root').value=local;invalidate();controls();};container.append(button);
    }
    if(!container.childElementCount){const message=document.createElement('p');message.className='subtle';message.textContent=t('No local cloud folders detected. You can enter a path manually.');container.append(message);}
  }
  function renderAttached(){
    const list=node('attached');list.replaceChildren();
    for(const [kind,value] of Object.entries(model?.attachments||{})){
      if(!value||!names[kind])continue;
      const mapping=value.mapping||value,state=model?.providers?.[kind]?.status||model?.providers?.[kind]||{};
      const active=state.attachment_active!==false&&Boolean(state.connected);
      const card=document.createElement('article');card.className='cloud-attached-card';card.dataset.active=String(active);
      const heading=document.createElement('h3');heading.textContent=names[kind]+' · '+t('Attached location');
      const identity=document.createElement('p');identity.textContent=active?accountName(state)||mapping.account_id||'':mapping.account_id||'';
      const path=document.createElement('code');path.textContent=mapping.local_root||'';
      const remote=document.createElement('small');remote.textContent=mapping.remote_name||mapping.remote_folder_id||mapping.remote_root||'/';
      const buttons=document.createElement('div');buttons.className='lab-actions';
      const open=document.createElement('button');open.type='button';open.className='button secondary small';open.textContent=t('Check remote files');open.dataset.cloudActive=String(active);open.disabled=!active;open.onclick=()=>showView(kind==='dropbox'?'dropbox':'google-drive');
      const change=document.createElement('button');change.type='button';change.className='button secondary small';change.textContent=t('Change attachment');change.onclick=()=>{node('google').checked=kind==='google_drive';node('dropbox').checked=kind==='dropbox';invalidate();renderProvider(true);showStep(2);};
      const remove=document.createElement('button');remove.type='button';remove.className='text-button';remove.textContent=t('Detach location');remove.onclick=wrap(()=>action(async()=>{await post('/detach',{provider:kind});invalidate();await load();notify(t('Location detached. Files and account connections are kept.'));}));
      buttons.append(open,change,remove);card.append(heading,identity,path,remote);
      if(!active){const warning=document.createElement('p');warning.className='cloud-error';warning.textContent=state.attachment_error||t('Not connected');card.append(warning);}
      card.append(buttons);list.append(card);
    }
  }
  async function load(){
    const generation=++revision,selected=node('source').options.length?node('source').value:window.BrowseState?.value('cloud-setup-source')||initial.source||window.Journeys?.context?.()?.source;
    const [base,journeys,active]=await Promise.all([api('/api/cloud-setup/status',{feedback:false}),api('/api/journeys',{feedback:false}),api(endpoint()+'/status',{feedback:false})]);
    const choices=(journeys.sources||[]).filter(row=>/^(?:snapshot|capture):[a-f0-9]{32}$/u.test(row.id));
    const chosen=choices.some(row=>row.id===selected)?selected:'';
    const status=chosen?await api('/api/cloud-setup/status?'+new URLSearchParams({source:chosen}),{feedback:false}):base;
    if(generation!==revision)return;
    const oldAccount=accountState().connection_id;model=status;model.providers||={};model.providers[provider()]={...model.providers[provider()],...active};
    node('source').replaceChildren(new Option(t('Choose a saved collection snapshot'),''),...choices.map(row=>new Option(row.label+' · '+snapshotMoment(row.created),row.id)));
    node('source').value=chosen;
    if(oldAccount&&oldAccount!==accountState().connection_id)invalidate();
    renderProvider();renderAttached();
    if(initial.step&&furthest===0)showStep(accountState().connected?2:1,false);else showStep(step,false);
  }
  function details(){
    const google=provider()==='google_drive';
    const value={provider:provider(),source:node('source').value,arrangement:node('arrangement').value,sync_mode:node('sync-mode').value,desktop_mode:node('desktop-mode').value,default_upload:node('default-upload').value,local_root:node('local-root').value.trim(),recorded_root:node('recorded-root').value.trim()};
    if(google)value.remote_folder_id=node('remote-root').value.trim()||'root';
    else{value.remote_root=node('remote-root').value.trim();value.namespace=node('namespace').value.trim();}
    return value;
  }
  function renderReview(value){
    preview=value;const counts=value.counts||value,matched=Number(counts.matched||0),total=Number(value.total??counts.total??0),mapping=value.mapping||value.proposed_mapping||{};
    node('review-state').textContent=t('Matching library paths')+' · '+num(matched)+' / '+num(total);
    const summary=node('review-summary');summary.replaceChildren();
    for(const [label,text] of [['Connected account',accountName(accountState())],['Source snapshot',node('source').selectedOptions[0]?.textContent||''],['Storage arrangement',node('arrangement').selectedOptions[0]?.textContent||''],['Rekordbox synchronization method',node('sync-mode').selectedOptions[0]?.textContent||''],['Folder on this computer',mapping.local_root||node('local-root').value],['Folder in cloud account',mapping.remote_name||mapping.remote_folder_id||mapping.remote_root||'/'],['Recorded prefix · optional',mapping.recorded_root||node('recorded-root').value]]){
      const row=document.createElement('p'),caption=document.createElement('strong'),content=document.createElement('code');caption.textContent=t(label);content.textContent=text||'—';row.append(caption,content);summary.append(row);
    }
    const cards=node('review-counts');cards.replaceChildren();
    for(const [key,label] of [['matched','Matching library paths'],['unmapped','Unmapped'],['ambiguous','Ambiguous paths'],['not_found','Not found'],['unverified','Unverified']]){
      const item=document.createElement('span'),number=document.createElement('strong');number.textContent=num(counts[key]||0);item.append(number,document.createTextNode(t(label)));cards.append(item);
    }
    const examples=node('review-examples');examples.replaceChildren();
    if((value.examples||[]).length){
      const table=document.createElement('table'),head=document.createElement('thead'),body=document.createElement('tbody');
      head.innerHTML='<tr>'+['Track','File status','Recorded path','Folder on this computer','Folder in cloud account'].map(label=>'<th>'+esc(t(label))+'</th>').join('')+'</tr>';
      for(const example of value.examples.slice(0,6)){
        const row=document.createElement('tr');
        const label={matched:'Matching library paths',unmapped:'Unmapped',ambiguous:'Ambiguous paths',not_found:'Not found',unverified:'Unverified'}[example.status]||'Unverified';
        for(const text of [example.title||example.track_id,t(label),example.recorded_path||example.path||'',example.local_path||'',example.remote_path||example.remote_id||'']){const cell=document.createElement('td');cell.textContent=text||'—';row.append(cell);}body.append(row);
      }
      table.append(head,body);examples.append(table);
    }
    node('review-reason').textContent=value.reason||value.hold_reason||(!value.attachable?t('Choose another folder or recorded prefix, then preview again.'):'');node('review-reason').hidden=!node('review-reason').textContent;
    const warnings=node('review-warnings');warnings.replaceChildren();warnings.hidden=!(value.metadata_warnings||[]).length;
    for(const warning of (value.metadata_warnings||[]).slice(0,5)){const row=document.createElement('p');row.textContent=String(warning.track_id||'')+' · '+String(warning.reason||'')+' · '+bytes(warning.recorded_size)+' → '+bytes(warning.remote_size);warnings.append(row);}
    controls();
  }
  async function previewAttachment(){
    invalidate();
    const result=await post('/preview',details()),value=result.job?await poll(result.job):result;
    renderReview(value);showStep(3);
  }
  async function browse(value=null,more=false){
    const input=value||details(),body={provider:provider(),namespace:node('namespace').value.trim()};
    if(provider()==='dropbox')body.remote_root=input.path??input.remote_root??node('remote-root').value.trim();
    else body.remote_folder_id=(input.id??input.remote_folder_id??node('remote-root').value.trim())||'root';
    if(more&&folder?.next_page_token)body.page_token=folder.next_page_token;
    const result=await post('/folders',body);folder={...result,request:body};node('folder-browser').hidden=false;
    node('folder-path').textContent=result.folder?.path||result.folder?.name||result.folder?.id||'/';
    if(!more)node('folder-rows').replaceChildren();
    for(const row of result.rows||[]){const button=document.createElement('button');button.type='button';button.className='cloud-folder-option';button.textContent=row.name||row.path||row.id;button.onclick=wrap(()=>action(async()=>{folderStack.push(folder.request);await browse(row);}));node('folder-rows').append(button);}
    node('folder-more').hidden=!result.next_page_token;controls();
  }
  for(const id of ['dropbox','google'])node(id).onchange=()=>{invalidate();furthest=0;renderProvider(true);showStep(0);};
  for(const id of ['arrangement','sync-mode','desktop-mode','default-upload','local-root','recorded-root','remote-root','namespace'])node(id).addEventListener('input',()=>{invalidate();controls();});
  node('source').onchange=wrap(async()=>{invalidate();controls();await load();});
  node('client-id').oninput=controls;
  node('copy-redirect').onclick=wrap(()=>copyCloudRedirect(node('redirect')));
  node('remember').onchange=()=>{node('storage-state').textContent=t(node('remember').checked?'Credentials stay in the operating system credential store.':'Session-only connection');};
  node('connect').onclick=wrap(()=>action(async()=>{
    const google=provider()==='google_drive',value={remember:node('remember').checked};value[google?'client_id':'app_key']=node('client-id').value.trim();
    if(google&&node('client-secret').value.trim())value.client_secret=node('client-secret').value.trim();
    try{await api(endpoint()+'/configure',{method:'POST',body:JSON.stringify(value)});}finally{node('client-secret').value='';}
    remember();const result=await api(endpoint()+'/connect',{method:'POST',body:JSON.stringify({return_to:'cloud-connect'})}),url=new URL(result.authorize_url||result.authorization_url);
    if(url.username||url.password||(google?url.origin!=='https://accounts.google.com'||url.pathname!=='/o/oauth2/v2/auth':url.origin!=='https://www.dropbox.com'||url.pathname!=='/oauth2/authorize'))throw new Error(t('The action could not be completed'));
    window.location.assign(url.href);
  }));
  node('disconnect').onclick=wrap(()=>action(async()=>{await api(endpoint()+'/disconnect',{method:'POST',body:'{}'});invalidate();await load();}));
  node('refresh').onclick=wrap(load);
  node('previous').onclick=()=>showStep(step-1);
  node('next').onclick=wrap(()=>step===2?action(previewAttachment):showStep(step+1));
  document.querySelectorAll('[data-cloud-step]').forEach(button=>button.onclick=()=>showStep(Number(button.dataset.cloudStep)));
  node('attach').onclick=wrap(()=>action(async()=>{
    const intent=preview;if(!intent?.preview_token||intent.attachable!==true)return;
    invalidate();await post('/attach',{preview_token:intent.preview_token,confirm:true});await load();showStep(0);notify(t('Cloud location attached'));
  }));
  node('browse').onclick=wrap(()=>action(async()=>{folderStack=[];await browse();}));
  node('folder-up').onclick=wrap(()=>action(async()=>{if(folderStack.length)await browse(folderStack.pop());}));
  node('folder-more').onclick=wrap(()=>action(()=>browse(folder.request,true)));
  node('folder-select').onclick=()=>{if(!folder?.folder)return;node('remote-root').value=provider()==='dropbox'?folder.folder.path||'':folder.folder.id||'';node('folder-browser').hidden=true;invalidate();controls();};
  node('folder-close').onclick=()=>node('folder-browser').hidden=true;
  const visible=()=>!document.getElementById('view-cloud-connect').hidden;
  window.addEventListener('focus',()=>{if(visible()&&!busy)void load().catch(error=>notify(error.message,true));});
  window.addEventListener('workbench-language',()=>{if(visible()&&!busy)void load().catch(error=>notify(error.message,true));});
  renderProvider();showStep(0,false);return {load};
})();
if(!document.getElementById('view-cloud-connect').hidden)CloudConnections.load().catch(error=>notify(error.message,true));
