/* Guided account and folder attachment. No transfer starts during discovery. */
window.CloudConnections=(()=>{
  const node=id=>document.getElementById('cloud-setup-'+id),t=key=>I18n.t(key);
  const names={dropbox:'Dropbox',google_drive:'Google Drive'};
  let model=null,step=0,furthest=0,busy=false,preview=null,revision=0,folder=null,folderStack=[],requestedSource='';
  const platformNames={windows:'Windows',mac:'macOS',linux:'Linux',unknown:'Unknown'};
  function browserPlatform(hints=navigator){
    const coarse=value=>{const text=String(value||'').slice(0,512).toLowerCase();
      if(/android|iphone|ipad|ipod/u.test(text))return 'unknown';
      if(/windows|win32|win64|winnt/u.test(text))return 'windows';
      if(/macos|macintel|macppc|darwin|macintosh|mac os|^mac$/u.test(text))return 'mac';
      if(/linux|ubuntu|debian|fedora/u.test(text))return 'linux';return 'unknown';};
    const declared=hints.userAgentData?.platform;
    if(declared){const value=coarse(declared);if(value!=='unknown'||/android|ios/iu.test(declared))return value;}
    if(/android|iphone|ipad|ipod/iu.test(String(hints.platform||'')+' '+String(hints.userAgent||'')))return 'unknown';
    const value=coarse(hints.platform);return value!=='unknown'?value:coarse(hints.userAgent);
  }
  function capturedPathStyles(candidates){
    const relative=new Set(candidates.filter(row=>row.recorded_library_root).flatMap(row=>row.samples||[]));
    const values=new Set();
    for(const row of candidates)for(let path of row.samples?.length?row.samples:[row.recorded_root||row.path]){
      if(typeof path!=='string'||!path)continue;
      if(relative.has(path)){values.add('cloud_relative');continue;}
      if(/^file:/iu.test(path)){try{path=decodeURIComponent(new URL(path).pathname);}catch{continue;}}
      if(/^\/?[A-Za-z]:[/\\]/u.test(path)||/^[/\\]{2}[^/\\]/u.test(path))values.add('windows');
      else if(/^\/(?:Users|Volumes|Applications|Library)(?:\/|$)/iu.test(path))values.add('mac');
      else if(/^\/(?:home|media|mnt|run|srv|opt|usr)(?:\/|$)/u.test(path))values.add('linux');
      else if(path.startsWith('/'))values.add('posix_unknown');
    }
    return ['windows','mac','linux','cloud_relative','posix_unknown'].filter(value=>values.has(value));
  }
  function renderPlatformContext(candidates){
    let hint=node('platform-context');if(!hint){hint=document.createElement('p');hint.id='cloud-setup-platform-context';hint.className='cloud-guidance subtle';node('suggestions').before(hint);}
    const host=Object.hasOwn(platformNames,model?.host_platform)?model.host_platform:'unknown',client=browserPlatform(),styles=capturedPathStyles(candidates);
    const styleNames={windows:'Windows path style',mac:'macOS path style',linux:'Linux path style',cloud_relative:'Cloud-relative path style',posix_unknown:'POSIX path style (platform unknown)'};
    const labels=[['cloudHostPlatform',host,'Workbench host platform',t(platformNames[host])],['cloudBrowserPlatform',client,'Browser platform',t(platformNames[client])],['cloudSourceStyles',styles.join(','),'Captured path styles',styles.length?styles.map(value=>t(styleNames[value])).join(', '):t('Unknown')]];
    hint.replaceChildren();for(const [index,[attribute,value,label,text]] of labels.entries()){if(index)hint.append(' · ');const span=document.createElement('span');span.dataset[attribute]=value;span.textContent=t(label)+': '+text;hint.append(span);}
    hint.append(document.createElement('br'));const note=document.createElement('small');note.textContent=t('Folders must exist on the Workbench host; preview validates your choices.');hint.append(note);
  }
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
    node('auth-error').textContent=[state.authorization_error,state.permission_error].filter(value=>typeof value==='string'&&value).join('\n');node('auth-error').hidden=!node('auth-error').textContent;
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
    if(!google)renderNamespaces();
    renderSuggestions();controls();
  }
  function renderNamespaces(){
    window.DropboxConnector?.renderNamespaces(accountState(),node('namespace'),node('namespace-choice'),node('namespace-context'),node('namespaces'),node('remote-root'));
  }
  function changeNamespace(clearRemote=false){
    folder=null;folderStack=[];node('folder-browser').hidden=true;if(clearRemote)node('remote-root').value='';
    invalidate();renderNamespaces();controls();
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
    const ranked=[];
    const append=(button,rank)=>ranked.push({button,rank});
    node('local-roots').replaceChildren(...roots.map(row=>new Option(row.root,row.root)));
    for(const row of roots){
      const button=document.createElement('button');button.type='button';button.className='cloud-location-option';
      const path=document.createElement('code'),evidence=document.createElement('span');path.textContent=row.root||'';
      evidence.textContent=(names[row.kind]||t('Local'))+' · '+t(row.provider_verified?'Detected provider folder':'Folder name only');
      button.append(path,evidence);button.dataset.cloudChoice='local';button.dataset.cloudEvidence=row.provider_verified?'provider_configuration':'folder_hint';button.onclick=()=>{node('local-root').value=row.root||'';invalidate();controls();};append(button,row.provider_verified?0:3);
    }
    const candidates=model?.suggestions||model?.source?.suggestions||[];renderPlatformContext(candidates);
    const choices=candidates.filter(item=>(!item.provider||item.provider===provider())&&(!item.kind||item.kind==='local'||item.kind===provider()||item.kind==='unknown'&&item.recorded_library_root));
    const logicalRoot=choices.find(item=>item.recorded_library_root&&item.kind===provider())||choices.find(item=>item.recorded_library_root);
    for(const row of choices){
      if(row.recorded_library_root&&row!==logicalRoot)continue;
      const local=row.local_root||row.root||row.path;if(!local||roots.some(item=>item.root===local))continue;
      const button=document.createElement('button');button.type='button';button.className='cloud-location-option';
      const path=document.createElement('code'),evidence=document.createElement('span');path.textContent=row.recorded_library_root?t('Recorded library root · /'):local;
      evidence.textContent=t(row.evidence==='correlated_cloud_paths'?'Matching full relative path in saved references':row.recorded_library_root?'Cloud-relative path suggestion':'Library path suggestion')+' · '+t('Recorded prefix · optional')+(row.tracks?' · '+num(row.tracks)+' '+t('Tracks'):'');button.append(path,evidence);
      if(row.recorded_library_root){const note=document.createElement('small');note.textContent=t('Use / only for captured paths relative to the selected cloud folder. It is not this computer’s filesystem root. Preview full paths before attaching.');button.append(note);}
      button.onclick=()=>{node('recorded-root').value=row.recorded_root||local;if(!row.recorded_library_root&&!row.foreign&&(row.local_root||row.root||row.available===true))node('local-root').value=local;invalidate();controls();};button.dataset.cloudChoice='recorded';button.dataset.cloudEvidence=row.evidence||'captured_path';append(button,row.evidence==='correlated_cloud_paths'?1:row.recorded_library_root?2:4);
    }
    for(const {button} of ranked.sort((a,b)=>a.rank-b.rank))container.append(button);
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
      const open=document.createElement('button');open.type='button';open.className='button secondary small';open.textContent=t('Check remote files');open.dataset.cloudActive=String(active);open.disabled=!active;open.onclick=()=>{const component=kind==='dropbox'?window.DropboxConnector:window.GoogleDriveConnector;component?.forSource?.(node('source').value);showView(kind==='dropbox'?'dropbox':'google-drive');};
      const change=document.createElement('button');change.type='button';change.className='button secondary small';change.textContent=t('Change attachment');change.onclick=()=>{node('google').checked=kind==='google_drive';node('dropbox').checked=kind==='dropbox';invalidate();renderProvider(true);showStep(2);};
      const remove=document.createElement('button');remove.type='button';remove.className='text-button';remove.textContent=t('Detach location');remove.onclick=wrap(()=>action(async()=>{await post('/detach',{provider:kind});invalidate();await load();notify(t('Location detached. Files and account connections are kept.'));}));
      buttons.append(open,change,remove);card.append(heading,identity,path,remote);
      if(!active){const warning=document.createElement('p');warning.className='cloud-error';warning.textContent=state.attachment_error||t('Not connected');card.append(warning);}
      card.append(buttons);list.append(card);
    }
  }
  async function load(){
    const generation=++revision,selected=requestedSource||(node('source').options.length?node('source').value:window.BrowseState?.value('cloud-setup-source')||initial.source||window.Journeys?.context?.()?.source);
    const journeys=await api('/api/journeys',{feedback:false});
    if(generation!==revision)return;
    const choices=(journeys.sources||[]).filter(row=>/^(?:snapshot|capture):[a-f0-9]{32}$/u.test(row.id));
    const chosen=choices.some(row=>row.id===selected)?selected:'';
    const query=chosen?'?'+new URLSearchParams({source:chosen}):'';
    const status=await api('/api/cloud-setup/status'+query,{feedback:false});
    if(generation!==revision)return;
    const oldAccount=accountState().connection_id;model=status;
    node('source').replaceChildren(new Option(t('Choose a saved collection snapshot'),''),...choices.map(row=>new Option(row.label+' · '+snapshotMoment(row.created),row.id)));
    node('source').value=chosen;
    requestedSource='';
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
  node('namespace-choice').onchange=()=>{node('namespace').value=node('namespace-choice').value;changeNamespace(true);};
  node('namespace').addEventListener('input',()=>changeNamespace());
  node('remote-root').addEventListener('input',()=>{if(provider()==='dropbox')renderNamespaces();});
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
  const prefixHelp=document.createElement('details');prefixHelp.className='cloud-advanced';prefixHelp.id='cloud-setup-path-help';
  prefixHelp.innerHTML='<summary data-i18n="Several recorded folders?">'+esc(t('Several recorded folders?'))+'</summary><p data-i18n="Keep the common cloud folder attached. In Audio folders, add a longer recorded prefix for any subfolder stored elsewhere, then preview this attachment again.">'+esc(t('Keep the common cloud folder attached. In Audio folders, add a longer recorded prefix for any subfolder stored elsewhere, then preview this attachment again.'))+'</p><button type="button" class="button secondary small" id="cloud-setup-audio-mappings" data-i18n="Review Audio folders mappings">'+esc(t('Review Audio folders mappings'))+'</button>';
  node('suggestions').after(prefixHelp);
  node('audio-mappings').onclick=()=>{const selected=node('source').value;if(!selected)return;window.FileHealth?.forSource?.(selected,{audioFolders:true});showView('file-health');};
  const visible=()=>!document.getElementById('view-cloud-connect').hidden;
  window.addEventListener('focus',()=>{if(visible()&&!busy)void load().catch(error=>notify(error.message,true));});
  window.addEventListener('workbench-language',()=>{if(visible()&&!busy)void load().catch(error=>notify(error.message,true));});
  function forSource(value,kind){
    if(typeof value!=='string'||!/^(?:snapshot|capture):[a-f0-9]{32}$/u.test(value))return false;
    requestedSource=value;revision++;invalidate();
    window.BrowseState?.set('cloud-setup-source',value);
    if(kind==='dropbox'||kind==='google_drive'){
      node('google').checked=kind==='google_drive';node('dropbox').checked=kind==='dropbox';renderProvider(true);
    }
    showStep(0,false);return true;
  }
  renderProvider();showStep(0,false);return {load,forSource,browserPlatform,capturedPathStyles};
})();
if(!document.getElementById('view-cloud-connect').hidden)CloudConnections.load().catch(error=>notify(error.message,true));
