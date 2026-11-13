let currentDocument='interface';
async function loadDocumentation(name=currentDocument){
  const index=await api('/api/docs');
  if(!index.chapters.some(row=>row.id===name))name='overview';currentDocument=name;
  $('#docs-index').innerHTML=index.chapters.map(row=>'<button class="button secondary small" data-help-doc="'+esc(row.id)+'" '+(row.id===name?'aria-current="page"':'')+'>'+I18n.html(row.title)+'</button>').join('');
  const result=await api('/api/docs/'+encodeURIComponent(name));
  $('#docs-source').textContent=result.file+' · English';$('#docs-content').innerHTML=result.html;
  $('#docs-download').href='/api/docs/'+encodeURIComponent(name)+'/source';
}
document.addEventListener('click',event=>{
  const link=event.target.closest('[data-help-doc]');if(!link)return;event.preventDefault();
  // Input choices stay in the form; the guide must not open behind its modal.
  const dialog=link.closest('dialog');if(dialog?.id==='import-dialog')dialog.close();
  currentDocument=link.dataset.helpDoc;showView('docs');
});
