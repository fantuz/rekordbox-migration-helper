async function openCleanupDialog() {
  const info=await api('/api/cleanup');
  $('#cleanup-size').textContent=num(info.files)+' temporary files · '+bytes(info.bytes);
  $('#cleanup-path').textContent=info.directory || '';
  $('#cleanup-state').textContent=info.message;$('#cleanup-ack').checked=false;$('#cleanup-confirm').disabled=true;
  $('#cleanup-dialog').showModal();
}
$('#cleanup-ack').onchange=()=>{$('#cleanup-confirm').disabled=!$('#cleanup-ack').checked;};
$('#cleanup-cancel').onclick=()=>$('#cleanup-dialog').close();
$('#cleanup-confirm').onclick=wrap(async()=>{
  $('#cleanup-confirm').disabled=true;$('#cleanup-cancel').disabled=true;
  for(const upload of activeUploads)upload.abort();
  await api('/api/desktop/stop',{method:'POST',body:JSON.stringify({acknowledged:$('#cleanup-ack').checked})});
  while(true){
    let info;
    try{info=await api('/api/cleanup');}
    catch{ $('#cleanup-state').textContent='The application has closed. Cleanup confirmation is recorded in cleanup-last.json in the data folder.';return; }
    $('#cleanup-state').textContent=info.message;
    if(info.phase==='complete'){$('#cleanup-state').textContent=info.message+' You can close this tab.';return;}
    if(info.phase==='error'){$('#cleanup-confirm').disabled=false;$('#cleanup-cancel').disabled=false;return;}
    await new Promise(resolve=>setTimeout(resolve,250));
  }
});
