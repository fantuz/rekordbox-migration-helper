/* Captured metadata warnings; independent of live file availability. */
window.MetadataFlags=(()=>{
  const labels={zero_duration:'Zero duration',zero_size:'Zero recorded size'};
  const badge=key=>'<span class="metadata-flag metadata-flag-'+key+'">'+esc(I18n.t(labels[key]))+'</span>';
  function badges(row){return (row.flags||[]).filter(k=>labels[k]).map(badge).join(' ');}
  function controls(counts={},selected=''){
    return '<div class="metadata-quick-filters" role="group" aria-label="'+esc(I18n.t('Metadata flags'))+'">'+
      ['',...Object.keys(labels)].map(key=>'<button type="button" class="metadata-flag-filter '+(key?'metadata-flag-'+key:'')+'" data-metadata-flag="'+key+'" aria-pressed="'+String(key===selected)+'">'+
        esc(I18n.t(key?labels[key]:'All records'))+(key?' <b>'+num(counts[key]||0)+'</b>':'')+'</button>').join('')+'</div>';
  }
  return {badges,controls};
})();
