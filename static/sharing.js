/* Local sharing configuration. Exported files contain only the selected fields. */
window.SharingUI=(() => {
  const fields=['id','title','artist','album','genre','year','bpm','rating','duration','format','label','composer','play_count','date_added','last_played','analysed','manual_cues','auto_cues','bitrate','sample_rate','bit_depth','playlists','tonality','color_name','color_hex','color_status'];
  const defaults=['title','artist','album','genre','year','bpm','duration','format'];
  const t=key=>I18n.t(key), q=id=>document.getElementById(id);
  const fieldLabel=field=>fields.includes(field)||['current_path','original_path'].includes(field)?(field==='id'?t('Track ID'):I18n.field(field)):t(field);
  let revision=0,timer=null,ready=false,lastInfo=null;
  function options(){
    if(!ready)return {preset:'public'};
    const preset=q('share-preset').value, choice={preset,working:q('share-working').checked};
    if(preset==='private')choice.fields=Array.from(document.querySelectorAll('[data-share-field]:checked'),e=>e.dataset.shareField);
    if(preset==='selected'){
      choice.track_ids=q('share-track-ids').value.split(/[\s,;]+/).map(s=>s.trim()).filter(Boolean);
      choice.playlist=q('share-playlist').value || null;
    }
    return choice;
  }
  function renderMode(){
    const preset=q('share-preset').value;
    q('share-field-options').hidden=preset!=='private';q('share-selection').hidden=preset!=='selected';
    const paths=q('quick-paths');paths.disabled=preset!=='private';if(paths.disabled)paths.checked=false;
    refresh();
  }
  function requestOptions(){return {source:q('quick-source').value,scope:q('quick-scope').value,include_paths:q('quick-paths').checked,...options()};}
  function schedule(){revision++;q('quick-generate').disabled=true;clearTimeout(timer);timer=setTimeout(refresh,250);}
  function showDisclosure(info){
    const output=q('share-disclosure');output.replaceChildren();
    const summary=document.createElement('strong');summary.textContent=num(info.track_count)+' '+t('tracks')+' · '+t(info.aggregates_only?'Aggregate summary':'Selected metadata');output.append(summary);
    for(const line of [t('Included fields')+': '+info.fields.map(fieldLabel).join(', '),t('Metadata state')+': '+t(info.data_state==='working'?'Working metadata':'Captured metadata'),t('Excluded fields')+': '+info.omitted.map(fieldLabel).join(', '),t('Merge and relocation decisions are not applied.')]){const p=document.createElement('p');p.textContent=line;output.append(p);}
  }
  async function refresh(){
    if(!ready || q('view-quick')?.hidden)return;
    clearTimeout(timer);
    const serial=++revision, source=q('quick-source').value, output=q('share-disclosure');
    q('quick-generate').disabled=true;
    if(!source){output.textContent=t('Choose a metadata source to preview the export.');return;}
    output.textContent=t('Checking export contents…');
    try{
      const fingerprint=JSON.stringify(requestOptions());
      const info=await api('/api/quick-export/preview',{method:'POST',body:fingerprint});
      if(serial!==revision || fingerprint!==JSON.stringify(requestOptions()))return;
      const select=q('share-playlist'),old=select.value;
      select.replaceChildren(new Option(t('Choose a playlist'),''),...(info.available_playlists || []).map(name=>new Option(name,name)));
      if(Array.from(select.options).some(option=>option.value===old))select.value=old;
      lastInfo=info;showDisclosure(info);
      q('quick-generate').disabled=q('share-preset').value==='selected' && info.track_count===0;
    }catch(error){if(serial===revision)output.textContent=error.message;}
  }
  function init(){
    const form=q('quick-export-form');if(!form || ready)return;
    const section=document.createElement('div');section.className='sharing-options';
    section.innerHTML='<label><span data-i18n="Sharing preset">Sharing preset</span><select id="share-preset"><option value="public" data-i18n="Public summary">Public summary</option><option value="selected" data-i18n="Selected track list">Selected track list</option><option value="private" data-i18n="Private explorer">Private explorer</option></select></label><p class="subtle" data-i18n="Public summaries contain category totals, without individual tracks, playlists, dates, play counts or file paths.">Public summaries contain category totals, without individual tracks, playlists, dates, play counts or file paths.</p><div id="share-selection" hidden><label><span data-i18n="Playlist">Playlist</span><select id="share-playlist"></select></label><label><span data-i18n="Track IDs">Track IDs</span><textarea id="share-track-ids" rows="3" placeholder="12, 34, 56"></textarea></label><p class="subtle" data-i18n="Select a playlist, enter track IDs, or combine both.">Select a playlist, enter track IDs, or combine both.</p></div><details id="share-field-options" hidden><summary data-i18n="Choose included metadata fields">Choose included metadata fields</summary><div class="share-fields"></div></details><label class="backup-acknowledgement"><input id="share-working" type="checkbox"><span data-i18n="Apply working metadata overrides">Apply working metadata overrides</span></label><aside id="share-disclosure" class="callout" aria-live="polite"></aside>';
    form.insertBefore(section,q('quick-generate'));
    const target=section.querySelector('.share-fields');
    for(const field of fields){const label=document.createElement('label'),input=document.createElement('input'),span=document.createElement('span');input.type='checkbox';input.dataset.shareField=field;input.checked=defaults.includes(field);span.textContent=I18n.field(field);label.append(input,span);target.append(label);input.onchange=schedule;}
    q('share-preset').onchange=renderMode;q('share-playlist').onchange=schedule;q('share-track-ids').oninput=schedule;q('share-working').onchange=schedule;
    q('quick-scope').addEventListener('change',schedule);q('quick-paths').addEventListener('change',schedule);
    ready=true;renderMode();
    new MutationObserver(()=>{if(!q('view-quick').hidden)refresh();}).observe(q('view-quick'),{attributes:true,attributeFilter:['hidden']});
    window.addEventListener('workbench-language',()=>{for(const span of target.querySelectorAll('label span'))span.textContent=I18n.field(span.previousElementSibling.dataset.shareField);if(lastInfo)showDisclosure(lastInfo);});
  }
  return {init,refresh,options};
})();
