/* Explicit local folder aliases; captured metadata and exported paths stay intact. */
window.AudioPaths=(()=>{
  const panels=new WeakMap(),t=key=>I18n.t(key);
  function row(value={}){
    const element=document.createElement('div');element.className='audio-path-row';
    element.innerHTML='<label>'+esc(t('Recorded folder'))+'<input data-audio-recorded placeholder="D:/Music" value="'+esc(value.recorded_root||'')+'"></label>'+
      '<label>'+esc(t('Folder on this computer'))+'<input data-audio-local placeholder="/media/music/Music" value="'+esc(value.local_root||'')+'"></label>'+
      '<button type="button" class="text-button" data-audio-remove>'+esc(t('Remove'))+'</button>';
    element.querySelector('[data-audio-remove]').onclick=()=>element.remove();
    return element;
  }
  function values(host){return [...host.querySelectorAll('.audio-path-row')].map(r=>({
    recorded_root:r.querySelector('[data-audio-recorded]').value.trim(),
    local_root:r.querySelector('[data-audio-local]').value.trim()
  })).filter(r=>r.recorded_root||r.local_root);}
  function showExamples(host,rows){
    host.querySelector('[data-audio-examples]').innerHTML='<table data-result-sort="off"><thead><tr>'+
      ['Recorded path','Local path','File status'].map(k=>'<th>'+esc(t(k))+'</th>').join('')+'</tr></thead><tbody>'+
      rows.map(r=>'<tr><td><code>'+esc(r.recorded)+'</code></td><td><code>'+esc(r.local||t('Unverified'))+'</code></td><td>'+esc(t(({playable:'Playable',missing:'Missing',inaccessible:'Inaccessible',unverified:'Unverified'})[r.status]))+'</td></tr>').join('')+'</tbody></table>';
  }
  async function load(host,source,force=false){
    if(!host)return;
    if(!source){host.hidden=true;panels.delete(host);return;}
    host.hidden=false;
    if(!force && panels.get(host)?.source===source)return;
    const state={source,revision:null};panels.set(host,state);
    host.innerHTML='<details class="audio-path-panel"><summary>'+esc(t('Audio folders'))+'</summary><p>'+esc(t('Map recorded Windows folders to this computer to use playback, File health and MusicBrainz. Original and exported paths stay unchanged.'))+'</p><div data-audio-rows></div>'+
      '<p data-audio-mounts class="subtle"></p><p data-audio-roots class="subtle"></p><div class="lab-actions"><button type="button" class="button secondary" data-audio-add>'+esc(t('Add folder'))+'</button><button type="button" class="button secondary" data-audio-preview>'+esc(t('Check example paths'))+'</button><button type="button" class="button" data-audio-save>'+esc(t('Save audio folders'))+'</button></div><p data-audio-note role="status"></p><div class="native-table" data-audio-examples></div></details>';
    const note=host.querySelector('[data-audio-note]'),container=host.querySelector('[data-audio-rows]');
    host.querySelector('[data-audio-add]').onclick=()=>container.append(row());
    try{
      const info=await api('/api/audio-paths?'+new URLSearchParams({source}),{feedback:false});
      if(panels.get(host)!==state)return;
      state.revision=info.revision;
      for(const mapping of info.mappings)container.append(row(mapping));
      if(!info.mappings.length)container.append(row({recorded_root:info.recorded_roots[0]||''}));
      host.querySelector('[data-audio-mounts]').textContent=t('Mounted folders')+': '+(info.mounted_roots.map(r=>r.path).join(' · ')||t('None detected'));
      host.querySelector('[data-audio-roots]').textContent=t('Allowed audio locations')+': '+(info.allowed_roots||[]).join(' · ');
      const act=save=>wrap(async()=>{
        const buttons=[...host.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);
        try{
          const result=await api('/api/audio-paths'+(save?'':'/preview'),{method:'POST',body:JSON.stringify({source,mappings:values(host),revision:state.revision})});
          if(panels.get(host)!==state)return;
          showExamples(host,result.examples);
          if(save){state.revision=result.revision;note.textContent=t('Audio folders saved. Re-scan File health and preview MusicBrainz again.');window.dispatchEvent(new CustomEvent('workbench-audio-paths',{detail:{source,scope:result.scope}}));TrackPlayback.recheck();}
          else note.textContent=t('Review the examples before saving. No library or audio files are changed.');
        }finally{buttons.forEach(b=>b.disabled=false);}
      });
      host.querySelector('[data-audio-preview]').onclick=act(false);
      host.querySelector('[data-audio-save]').onclick=act(true);
    }catch(error){if(panels.get(host)===state){note.textContent=error.message;panels.delete(host);}}
  }
  return {load};
})();
