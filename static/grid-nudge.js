/* The proof returned by the preview belongs to one workspace, track and direction. */
window.GridNudge=(()=>{
  const track=$('#grid-track'),direction=$('#grid-direction'),query=$('#grid-query');
  const previewButton=$('#grid-preview'),downloadButton=$('#grid-download');
  const status=$('#grid-status'),result=$('#grid-result');
  let workspace=null,revision=0,preview=null;

  function invalidate(){
    revision++;
    preview=null;
    result.replaceChildren();
    status.replaceChildren();
    direction.disabled=!track.value;
    previewButton.disabled=!track.value;
    downloadButton.disabled=true;
  }

  function resetTracks(){
    track.length=1;
    track.selectedIndex=0;
    track.disabled=true;
    invalidate();
  }

  function setWorkspace(id){
    $('#grid-import').hidden=Boolean(id);
    $('#grid-form').hidden=!id;
    $('#grid-workspace').textContent=(session?.id===id && session?.name) || id || '';
    if(workspace===id)return;
    workspace=id;
    query.value='';
    direction.value='later';
    resetTracks();
  }

  function showStatus(key,params){
    const message=document.createElement('span');
    I18n.text(message,key,params);
    status.replaceChildren(message);
  }

  function payload(){
    return {session_id:workspace,track_id:track.value,offset_ms:direction.value==='earlier'?-1:1};
  }

  function displayPreview(data){
    const timings=[
      ['First beat (ms)',data.first_ms],
      ['Last beat (ms)',data.last_ms]
    ];
    const table='<div class="lab-table"><table data-result-sort="off"><thead><tr>'+
      ['Grid shift','Before','After'].map(label=>'<th scope="col">'+I18n.html(label)+'</th>').join('')+
      '</tr></thead><tbody>'+timings.map(([label,time])=>'<tr><th scope="row">'+I18n.html(label)+'</th><td>'+
        esc(I18n.number(time))+'</td><td>'+esc(I18n.number(time+data.offset_ms))+'</td></tr>').join('')+'</tbody></table></div>';
    const changed=data.files.filter(file=>file.changed).map(file=>file.name).join(', ');
    result.innerHTML='<strong dir="auto">'+esc(data.title || data.track_id)+'</strong>'+
      '<div class="subtle">'+I18n.html('Recorded path')+' · <bdi dir="auto">'+esc(data.media_path)+'</bdi></div>'+table+
      '<p>'+I18n.html('Beats: {count}',{count:data.beats})+' · '+I18n.html('Changed files: {files}',{files:changed})+'</p>'+
      (data.cleared_entries?'<p>'+I18n.html('Secondary beat entries cleared: {count}',{count:data.cleared_entries})+'</p>':'');
  }

  $('#grid-search-form').onsubmit=async event=>{
    event.preventDefault();
    resetTracks();
    if(!workspace)return;
    const pending=revision;
    showStatus('Loading');
    try{
      const params=new URLSearchParams({session_id:workspace,q:query.value.trim()});
      const data=await api('/api/lab/grid-nudge/tracks?'+params);
      if(pending!==revision)return;
      for(const row of data.tracks){
        const label=[row.title,row.artist].filter(Boolean).join(' · ');
        const option=new Option((label?label+' · ':'')+row.id,row.id);
        option.dir='auto';
        track.add(option);
      }
      track.disabled=!data.tracks.length;
      if(!data.tracks.length)showStatus('No matching tracks');
      else if(data.has_more)showStatus('Showing the first 50 matches. Refine the search for more.');
      else status.replaceChildren();
    }catch(error){if(pending===revision)status.textContent=error.message;}
  };

  previewButton.onclick=async()=>{
    invalidate();
    if(!track.value)return;
    const pending=revision;
    previewButton.disabled=true;
    showStatus('Checking the beat grid…');
    try{
      const data=await api('/api/lab/grid-nudge/preview',{method:'POST',body:JSON.stringify(payload())});
      if(pending!==revision)return;
      preview=data;
      displayPreview(data);
      showStatus('Ready');
      downloadButton.disabled=false;
    }catch(error){if(pending===revision)status.textContent=error.message;}
    finally{if(pending===revision)previewButton.disabled=false;}
  };

  downloadButton.onclick=async()=>{
    if(!preview)return;
    const pending=revision;
    downloadButton.disabled=true;
    previewButton.disabled=true;
    showStatus('Prepare download');
    try{
      const blob=await api('/api/lab/grid-nudge/download',{method:'POST',download:true,body:JSON.stringify({...payload(),proof:preview.proof})});
      if(pending!==revision)return;
      const url=URL.createObjectURL(blob),link=document.createElement('a');
      link.href=url;link.download='analysis-grid-nudge.zip';document.body.append(link);link.click();link.remove();
      setTimeout(()=>URL.revokeObjectURL(url),30000);
      showStatus('Download started');
    }catch(error){
      if(pending===revision){invalidate();status.textContent=error.message;}
    }finally{
      if(pending===revision){previewButton.disabled=false;downloadButton.disabled=!preview;}
    }
  };

  query.addEventListener('input',resetTracks);
  track.addEventListener('change',invalidate);
  direction.addEventListener('change',invalidate);
  window.addEventListener('workbench-stale',resetTracks);
  window.addEventListener('workbench-language',()=>{if(preview)displayPreview(preview);});
  return {setWorkspace};
})();
