/* Read-only export preview. The independent readback check is not a Serato import test. */
window.SeratoDraft=(()=>{
  const node=id=>document.getElementById(id),t=key=>I18n.t(key);
  let revision=0,report=null;
  const selection=()=>({snapshot:node('intelligence-source').value,volume_root:node('serato-volume').value,
    target_platform:node('serato-target-platform').value,target_volume_root:node('serato-target-volume').value});
  function reset(){revision++;report=null;node('serato-report').replaceChildren();node('serato-ack').checked=false;node('serato-export').disabled=true;node('serato-target-note').textContent=I18n.t('Preview Serato export')+' · '+I18n.t('Serato import remains unverified');}
  function buttons(){node('serato-export').disabled=!report?.export_ready || !node('serato-ack').checked;}
  function render(){
    if(!report)return;
    const target=report.target_profile||{};
    node('serato-target-note').textContent=(target.simulated?t('Simulated Serato target'):t('Native Serato target'))+
      ' · '+(target.platform||'')+' · '+(target.target_volume_root||'')+' · '+t('Serato import remains unverified');

    const rows=(labels,values)=>'<div class="lab-table"><table><thead><tr>'+labels.map(label=>'<th>'+esc(t(label))+'</th>').join('')+'</tr></thead><tbody>'+values.map(row=>'<tr>'+row.map(value=>'<td>'+esc(value)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
    const section=(label,count,html)=>'<details><summary>'+esc(t(label))+' · '+num(count)+'</summary>'+html+'</details>';
    node('serato-report').innerHTML='<p class="callout">'+esc(t('Readback passed; Serato import remains unverified.'))+'</p>'+labSummary({[t('Tracks')]:report.tracks_written,[t('Crates')]:report.crates_total,[t('Omitted records')]:report.omitted_total,[t('Omitted playlist entries')]:report.omitted_playlist_entries_total})+
      '<p>'+esc(t('Preview shows up to 100 rows per section. The ZIP manifest contains every detail.'))+'</p>'+
      section('Crates',report.crates_total,rows(['Name','Tracks'],report.crates.map(c=>[c.name,num(c.entries)+(c.folder?' · '+t('Folder'):'')])) )+
      section('Omitted records',report.omitted_total,rows(['Track ID','Reason'],report.omitted.map(r=>[r.track_id,r.reason])))+
      section('Omitted playlist entries',report.omitted_playlist_entries_total,rows(['Name','Track ID','Reason'],report.omitted_playlist_entries.map(r=>[r.playlist,r.track_id,r.reason])))+
      section('Export notes',report.warnings_total,'<ul>'+report.warnings.map(r=>'<li>'+esc(r.reason)+'</li>').join('')+'</ul>')+
      section('Metadata coverage',Object.keys(report.metadata_fields).length,rows(['Field','Tracks'],Object.entries(report.metadata_fields).map(([field,count])=>[field,num(count)])))+
      '<p><strong>'+esc(t('Not transferred'))+':</strong> '+report.not_transferred.map(esc).join(', ')+'.</p>'+
      (!report.export_ready?'<p class="callout">'+esc(t('No tracks can be exported for this volume.'))+'</p>':'');
  }
  node('serato-volume').addEventListener('input',reset);
  node('serato-target-platform').addEventListener('change',()=>{
    const platform=node('serato-target-platform').value;
    node('serato-target-volume').value=platform==='windows'?'C:/':platform==='macos'?'/Volumes/DJ':'';
    reset();
  });
  node('serato-target-volume').addEventListener('input',reset);
  node('intelligence-source').addEventListener('change',reset);
  window.addEventListener('workbench-context',reset);
  window.addEventListener('workbench-language',render);
  node('serato-ack').addEventListener('change',buttons);
  node('serato-preview').onclick=wrap(async()=>{
    reset();const version=revision,selected=selection();node('serato-preview').disabled=true;
    try{
      const result=await api('/api/intelligence/serato/preview',{method:'POST',body:JSON.stringify(selected)});
      if(version!==revision || JSON.stringify(selection())!==JSON.stringify(selected))return;
      report=result;render();buttons();
    }finally{node('serato-preview').disabled=false;}
  });
  node('serato-export').onclick=wrap(async()=>{
    if(!report?.export_ready || !node('serato-ack').checked)return;
    const selected=selection();node('serato-export').disabled=true;mutatingRequests++;
    try{
      const response=await fetch('/api/intelligence/serato',{method:'POST',headers:{'Content-Type':'application/json','X-Workbench-Token':token},body:JSON.stringify({...selected,draft_acknowledged:true})});
      if(!response.ok){const error=await response.json();throw new Error(I18n.error(error.error));}
      const href=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=href;link.download='serato-draft.zip';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(href),30000);
    }finally{mutatingRequests--;buttons();}
  });
  return {reset};
})();
document.querySelectorAll('[data-open-serato]').forEach(button=>button.onclick=()=>{
  showView('intelligence');
  const entry=document.querySelector('.serato-entry');entry.open=true;
  entry.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});
  document.getElementById('serato-volume').focus({preventScroll:true});
});
