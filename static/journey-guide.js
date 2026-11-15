/* Optional saved checklists. Confirmations are user statements, not migration certification. */
window.GuidedJourneys=(()=>{
  const t=key=>I18n.t(key),text=key=>esc(t(key));
  let info=null,chosen='',planId='',revision=0;
  const post=(path,data)=>api('/api/journeys'+path,{method:'POST',body:JSON.stringify(data)});
  function render(){
    if(!info)return;
    const plan=info.plans.find(p=>p.id===planId),template=info.templates[plan?.kind || chosen];
    const saved=info.plans.filter(p=>info.templates[p.kind]);
    $('#guided-journeys').innerHTML='<h2>'+text('Library journeys')+'</h2><p class="callout">'+text('Guided steps are optional. Every tool remains available in the sidebar.')+'</p>'+
      ['migration','library'].map(group=>'<h3>'+text(group==='migration'?'Migration assistant':'Library preparation')+'</h3><div class="guided-goals">'+Object.entries(info.templates).filter(([,v])=>v.group===group).map(([key,value])=>'<button class="journey-goal '+(key===(plan?.kind || chosen)?'selected':'')+'" data-guide="'+key+'"><strong>'+text(value.title)+'</strong><span>'+text(value.note)+'</span></button>').join('')+'</div>').join('')+
      (saved.length?'<label class="guided-resume">'+text('Resume a journey')+'<select id="guide-resume"><option value="">'+text('Choose a journey')+'</option>'+saved.map(p=>'<option value="'+esc(p.id)+'" '+(p.id===planId?'selected':'')+'>'+text(info.templates[p.kind].title)+' · '+esc(date(p.updated))+'</option>').join('')+'</select></label>':'')+
      (template?'<article class="wide-card guided-plan"><h3>'+text(template.title)+'</h3><p class="callout">'+text(template.note)+'</p>'+(plan?'<p>'+text('These confirmations record your progress; they do not certify a migration or backup.')+'</p><ol class="journey-steps">'+template.steps.map((step,i)=>{const status=plan.steps[step.id]?.status || 'pending';return '<li><div><strong>'+text(step.title)+'</strong><span>'+text(status==='confirmed'?'Confirmed by you':status==='skipped'?'Optional step skipped':'Pending')+'</span></div><button class="button secondary" data-guide-open="'+i+'">'+text(step.doc?'Documentation':'Open tool')+'</button><label><input type="checkbox" data-guide-step="'+step.id+'" '+(status==='confirmed'?'checked':'')+'>'+text('Confirm')+'</label>'+(step.optional?'<button class="text-button" data-guide-skip="'+step.id+'">'+text('Skip optional cleanup')+'</button>':'')+'</li>';}).join('')+'</ol><label>'+text('Notes')+'<textarea id="guide-notes" maxlength="4000">'+esc(plan.notes)+'</textarea></label><button class="button" id="guide-save">'+text('Save progress')+'</button>':'<button class="button" id="guide-start">'+text('Start journey')+'</button>')+'</article>':'');
    $$('[data-guide]').forEach(button=>button.onclick=()=>{chosen=button.dataset.guide;planId='';render();$('.guided-plan').scrollIntoView({block:'nearest'});});
    if($('#guide-resume'))$('#guide-resume').onchange=()=>{planId=$('#guide-resume').value;chosen='';render();};
    if($('#guide-start'))$('#guide-start').onclick=wrap(async()=>{const result=await post('',{kind:chosen,source:info.selected});planId=result.id;await load();});
    if($('#guide-save'))$('#guide-save').onclick=wrap(async()=>{await saveNotes();await load();notify(t('Progress saved locally'));});
    $$('[data-guide-step]').forEach(input=>input.onchange=wrap(async()=>{const status=input.checked?'confirmed':'pending';await saveNotes();await post('/'+planId,{step:input.dataset.guideStep,status});await load();}));
    $$('[data-guide-skip]').forEach(button=>button.onclick=wrap(async()=>{await saveNotes();await post('/'+planId,{step:button.dataset.guideSkip,status:'skipped'});await load();}));
    $$('[data-guide-open]').forEach(button=>button.onclick=wrap(async()=>{
      await saveNotes();const step=template.steps[Number(button.dataset.guideOpen)];
      if(step.doc){const link=document.createElement('button');link.dataset.helpDoc=step.doc;document.body.append(link);link.click();link.remove();return;}
      showView(step.view);
      if(step.view==='lab'){await loadLab();if(step.tab)document.querySelector('[data-lab-tab="'+step.tab+'"]').click();}
      if(step.view==='intelligence')await Intelligence.load();
      if(step.target){const target=document.querySelector(step.target);if(target){target.open=true;target.scrollIntoView({block:'center'});}}
    }));
  }
  async function saveNotes(){if(planId && $('#guide-notes'))await post('/'+planId,{notes:$('#guide-notes').value});}
  async function load(){const version=++revision;const received=await api('/api/journeys');if(version!==revision)return;info=received;if(!info.plans.some(p=>p.id===planId))planId='';render();}
  return {load};
})();
