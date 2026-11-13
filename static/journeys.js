/* Guided local workflows. Confirmations are user statements, never restore certification. */
window.Journeys=(()=>{
  let info=null,selectedPlan='',syncing=false,contextRevision=0,loadRevision=0,contextQueue=Promise.resolve();
  const post=(path,data)=>api('/api/journeys'+path,{method:'POST',body:JSON.stringify(data)});
  const statuses={get issue(){return I18n.t('Issue');},get review(){return I18n.t('Needs review');},get unknown(){return I18n.t('Unknown');},get not_checked(){return I18n.t('Not checked');},get clear(){return I18n.t('No finding in scope');}};
  const stepLabels={get backup(){return I18n.t('Keep a separate backup');},get capture(){return I18n.t('Capture the source library');},get availability(){return I18n.t('Check audio and cloud availability');},get paths(){return I18n.t('Plan destination paths');},get cleanup(){return I18n.t('Review optional cleanup');},get export(){return I18n.t('Create copy exports');},get restore(){return I18n.t('Restore on the destination');},get compare(){return I18n.t('Capture and compare the destination');}};
  const snapshotOptions=(value='')=>'<option value="">'+esc(I18n.t('Choose a snapshot'))+'</option>'+(value && !info.sources.some(s=>s.id==='snapshot:'+value)?'<option selected value="'+esc(value)+'">'+esc(I18n.t('Saved snapshot'))+' · '+esc(value)+'</option>':'')+info.sources.filter(s=>s.id.startsWith('snapshot:')).map(s=>'<option value="'+esc(s.id.slice(9))+'" '+(s.id.slice(9)===value?'selected':'')+'>'+esc(s.label)+' · '+esc(I18n.date(s.created))+'</option>').join('');
  function activePlan(){return info?.plans.find(p=>p.id===selectedPlan);}
  function button(view,label){return '<button class="button secondary" type="button" data-journey-view="'+esc(view)+'">'+esc(label)+'</button>';}
  function renderContext(){
    const host=$('#collection-context');if(!host || !info)return;
    const c=info.context;
    host.innerHTML='<div class="journey-context-row"><label><span>'+esc(I18n.t('Collection context'))+'</span><select id="journey-context-source" aria-label="'+esc(I18n.t('Collection context'))+'"><option value="">'+esc(I18n.t('Choose a snapshot'))+'</option>'+info.sources.map(s=>'<option value="'+esc(s.id)+'" '+(s.id===info.selected?'selected':'')+'>'+esc(s.label)+'</option>').join('')+'</select></label>'+(c?'<div class="journey-context-detail"><strong>'+num(c.tracks)+' '+esc(I18n.t('tracks'))+'</strong><span>'+esc(I18n.t('Captured metadata'))+' · '+esc(c.scope)+' · '+esc(I18n.date(c.captured))+'</span><span>'+num(c.working_override_fields)+' '+esc(I18n.t('staged metadata fields'))+' · '+esc(I18n.t('Cleanup decisions are separate'))+'</span>'+(!c.snapshot?'<button class="text-button" data-journey-context-capture>'+esc(I18n.t('Save a snapshot for insight tools'))+'</button>':'')+'</div>':'<p>'+esc(I18n.t('Load a workspace or save a source snapshot.'))+'</p>')+'</div>';
    if(host.querySelector('[data-journey-context-capture]'))host.querySelector('[data-journey-context-capture]').onclick=()=>showView('lab');
    $('#journey-context-source').onchange=wrap(async()=>{if(!$('#journey-context-source').value)return;await selectContext($('#journey-context-source').value,true);});
  }
  function syncContext(activate=false){
    const source=info.selected,detail=info.context,identity=source.startsWith('snapshot:')?source.slice(9):'';
    syncing=true;
    try{
      for(const id of ['lab-snapshot','dj-snapshot','bubble-snapshot','tonal-snapshot','history-snapshot','intelligence-source','quick-source']){
        const select=$('#'+id);if(!select)continue;
        const wanted=id==='quick-source'?(identity?'lab:'+identity:source==='workspace'?'session':source.startsWith('capture:')?source.slice(8):''):identity;
        const supported=[...select.options].some(o=>o.value===wanted),next=supported?wanted:'';
        const changed=select.value!==next;select.value=next;
        if(changed && activate && select.closest('.view')?.hidden===false)select.dispatchEvent(new Event('change',{bubbles:true}));
      }
    }finally{syncing=false;}
    window.dispatchEvent(new CustomEvent('workbench-context',{detail}));
  }
  async function selectContext(source,activate=false){
    const revision=++contextRevision;
    const pending=contextQueue.catch(()=>{}).then(()=>post('/context',{source}));contextQueue=pending;
    const detail=await pending;if(revision!==contextRevision)return;
    info.selected=source;info.context=detail;renderContext();syncContext(activate);
  }
  function render(){
    const host=$('#journey-panel');if(!host || !info)return;
    const p=activePlan();
    host.innerHTML='<div class="journey-goals"><button class="journey-goal goal-health" data-journey="integrity"><strong>'+esc(I18n.t('Check library health'))+'</strong><span>'+esc(I18n.t('Integrity, references and preparation evidence'))+'</span></button><button class="journey-goal goal-migration" data-journey="migration"><strong>'+esc(I18n.t('Migrate a library'))+'</strong><span>'+esc(I18n.t('A saved checklist from backup to destination comparison'))+'</span></button><button class="journey-goal goal-duplicates" data-journey-view="review"><strong>'+esc(I18n.t('Review duplicates'))+'</strong><span>'+esc(I18n.t('Compare evidence and stage copy changes'))+'</span></button><button class="journey-goal goal-share" data-journey-view="quick"><strong>'+esc(I18n.t('Share & offline summary'))+'</strong><span>'+esc(I18n.t('A browser-ready summary without audio'))+'</span></button></div>'+
      (info.plans.length?'<div class="journey-resume"><label><span>'+esc(I18n.t('Resume a journey'))+'</span><select id="journey-resume"><option value="">'+esc(I18n.t('Choose a journey'))+'</option>'+info.plans.map(plan=>'<option value="'+esc(plan.id)+'" '+(plan.id===selectedPlan?'selected':'')+'>'+esc(plan.kind==='migration'?I18n.t('Migrate a library'):I18n.t('Check library health'))+' · '+esc(I18n.date(plan.updated))+'</option>').join('')+'</select></label></div>':'')+
      (p?(p.kind==='migration'?migration(p):health(p)):'');
    host.querySelectorAll('[data-journey-view]').forEach(b=>b.onclick=()=>showView(b.dataset.journeyView));
    host.querySelectorAll('[data-journey-open-report]').forEach(b=>b.onclick=wrap(async()=>{showView('lab');await loadLab();$('#lab-report-select').value=b.dataset.journeyOpenReport;labReportOffset=0;$('#lab-report-section').value='';await labLoadReport();$('.lab-report').scrollIntoView({block:'start',behavior:'smooth'});}));
    host.querySelectorAll('[data-journey]').forEach(b=>b.onclick=wrap(async()=>{const p=await post('',{kind:b.dataset.journey,source:info.selected});selectedPlan=p.id;await load();}));
    if($('#journey-resume'))$('#journey-resume').onchange=()=>{selectedPlan=$('#journey-resume').value;render();renderReport().catch(error=>notify(error.message,true));};
    if(p?.kind==='migration')bindMigration(p);
    if(p?.kind==='integrity')bindHealth(p);
  }
  function migration(p){
    return '<article class="wide-card journey-body"><h3>'+esc(I18n.t('Migration assistant'))+'</h3><p class="callout">'+esc(I18n.t('Keep a separate backup before transforming a library. These confirmations record your progress; they do not verify a successful restore.'))+'</p><ol class="journey-steps">'+info.steps.map(step=>{const state=p.steps[step.id]?.status || 'pending';return '<li><div><strong>'+esc(stepLabels[step.id])+'</strong><span>'+esc(state==='confirmed'?I18n.t('Confirmed by you'):state==='skipped'?I18n.t('Optional step skipped'):I18n.t('Pending'))+'</span></div>'+(step.id==='restore'?'<button class="button secondary" data-help-doc="inputs-and-restore" type="button">'+esc(I18n.t('Step-by-step export and restore guide'))+'</button>':button(step.view,I18n.t('Open tool')))+'<label class="journey-confirm"><input type="checkbox" data-journey-step="'+esc(step.id)+'" '+(state==='confirmed'?'checked':'')+'>'+esc(I18n.t('Confirm'))+'</label>'+(step.id==='cleanup'?'<button class="text-button" data-journey-skip="cleanup">'+esc(I18n.t('Skip optional cleanup'))+'</button>':'')+'</li>';}).join('')+'</ol><form id="journey-migration-form"><div class="journey-fields"><label><span>'+esc(I18n.t('Source snapshot'))+'</span><select id="journey-before">'+snapshotOptions(p.before_snapshot)+'</select></label><label><span>'+esc(I18n.t('Destination snapshot'))+'</span><select id="journey-after">'+snapshotOptions(p.after_snapshot)+'</select></label><label><span>'+esc(I18n.t('Destination music folder (planning only)'))+'</span><input id="journey-destination" maxlength="4096" value="'+esc(p.destination_root)+'"></label><label><span>'+esc(I18n.t('Cloud handling (your statement)'))+'</span><select id="journey-cloud">'+[['unknown',I18n.t('Unknown')],['copy',I18n.t('Copy')],['move',I18n.t('Move')],['no-cloud',I18n.t('No cloud')]].map(([value,label])=>'<option value="'+value+'" '+(p.cloud_mode===value?'selected':'')+'>'+esc(label)+'</option>').join('')+'</select></label></div><label><span>'+esc(I18n.t('Notes'))+'</span><textarea id="journey-notes" maxlength="4000">'+esc(p.notes)+'</textarea></label><div class="action-row"><button class="button" type="submit">'+esc(I18n.t('Save progress'))+'</button><button class="button secondary" type="button" id="journey-compare">'+esc(I18n.t('Compare destination'))+'</button>'+button('analyzer',I18n.t('Capture a source or destination'))+'</div><p class="subtle">'+esc(I18n.t('Destination paths are notes only. Use File references to stage actual path changes. Capture the restored destination in Source analyzer, then save it in Library lab.'))+'</p></form>'+report(p.comparison)+'</article>';
  }
  function health(p){
    return '<article class="wide-card journey-body"><h3>'+esc(I18n.t('Integrity checker'))+'</h3><p>'+esc(I18n.t('Quick checks use saved evidence. Deep checks add only the analysis locations you choose. Audio availability requires a separate Media inventory scan.'))+'</p><form id="journey-health-form"><div class="journey-fields"><label><span>'+esc(I18n.t('Check scope'))+'</span><select id="journey-depth"><option value="quick">'+esc(I18n.t('Quick · captured evidence'))+'</option><option value="deep">'+esc(I18n.t('Deep · selected analysis locations'))+'</option></select></label><label><span>'+esc(I18n.t('Analysis folders or backup ZIPs · one per line'))+'</span><textarea id="journey-assets" disabled></textarea></label></div><div class="action-row"><button class="button" type="submit" '+(!info.selected?'disabled':'')+'>'+esc(I18n.t('Run integrity checks'))+'</button>'+button('inventory',I18n.t('Open Media inventory'))+button('analyzer',I18n.t('Capture a source or destination'))+'</div></form><div class="journey-status-legend">'+Object.entries(statuses).map(([key,label])=>'<span class="journey-status '+key+'">'+esc(label)+'</span>').join('')+'</div><p class="subtle">'+esc(I18n.t('No finding in scope does not mean every location, cloud download or restore has been checked.'))+'</p>'+report(p.report)+'</article>';
  }
  function report(r){
    if(!r)return '';
    return '<div class="journey-report"><h4>'+esc(I18n.t('Saved evidence report'))+'</h4><p>'+esc(I18n.date(r.created))+'</p>'+(r.summary?.checks?'<div class="journey-status-legend">'+Object.entries(r.summary.checks).map(([key,value])=>'<span class="journey-status '+esc(key)+'">'+esc(statuses[key] || key)+' · '+num(value)+'</span>').join('')+'</div>':'')+'<a class="button secondary" href="/api/lab/reports/'+esc(r.id)+'/download">'+esc(I18n.t('Download JSON report ↓'))+'</a> <button class="button secondary" data-journey-open-report="'+esc(r.id)+'">'+esc(I18n.t('Open report'))+'</button><div class="journey-report-details" data-journey-report="'+esc(r.id)+'"></div></div>';
  }
  async function renderReport(){
    for(const host of document.querySelectorAll('[data-journey-report]')){
      const r=await api('/api/lab/reports/'+encodeURIComponent(host.dataset.journeyReport));
      if(!host.isConnected)continue;
      host.innerHTML='<div class="journey-findings">'+r.rows.filter(row=>row.status).map(row=>'<div><span class="journey-status '+esc(row.status)+'">'+esc(statuses[row.status] || row.status)+'</span><div><strong>'+esc(I18n.t(row.title))+'</strong><p>'+esc(row.detail)+(row.count===null?'':' · '+num(row.count))+'</p></div></div>').join('')+'</div>'+(r.kind==='migration comparison'?'<pre>'+esc(JSON.stringify(r.summary,null,2))+'</pre>':'');
    }
  }
  function bindMigration(p){
    $('#journey-migration-form').onsubmit=wrap(async e=>{e.preventDefault();await saveMigration(p);notify(I18n.t('Progress saved locally'));});
    document.querySelectorAll('[data-journey-step]').forEach(el=>el.onchange=wrap(async()=>{const status=el.checked?'confirmed':'pending';await saveMigration(p);await post('/'+p.id,{step:el.dataset.journeyStep,status});await load();}));
    document.querySelectorAll('[data-journey-skip]').forEach(el=>el.onclick=wrap(async()=>{await saveMigration(p);await post('/'+p.id,{step:el.dataset.journeySkip,status:'skipped'});await load();}));
    $('#journey-compare').onclick=wrap(async()=>{await saveMigration(p);const r=await post('/'+p.id+'/compare',{});await poll(r.job);await load();});
  }
  async function saveMigration(p){
    await post('/'+p.id,{before_snapshot:$('#journey-before').value,after_snapshot:$('#journey-after').value,destination_root:$('#journey-destination').value,cloud_mode:$('#journey-cloud').value,notes:$('#journey-notes').value});await load();
  }
  function bindHealth(p){
    $('#journey-depth').onchange=()=>{$('#journey-assets').disabled=$('#journey-depth').value!=='deep';};
    $('#journey-health-form').onsubmit=wrap(async e=>{e.preventDefault();const depth=$('#journey-depth').value,asset_paths=depth==='deep'?$('#journey-assets').value.split(/\r?\n/).map(v=>v.trim()).filter(Boolean):[];const r=await post('/'+p.id+'/check',{source:info.selected,depth,asset_paths});await poll(r.job);await load();});
  }
  async function load(){
    const revision=++loadRevision,selection=contextRevision,received=await api('/api/journeys');if(revision!==loadRevision)return;
    if(selection!==contextRevision && info){received.selected=info.selected;received.context=info.context;}
    info=received;if(!selectedPlan && info.plans.length)selectedPlan=info.plans[0].id;renderContext();render();syncContext(true);await renderReport();
  }
  function init(){
    document.addEventListener('change',event=>{
      if(syncing || !info || !['lab-snapshot','dj-snapshot','bubble-snapshot','tonal-snapshot','history-snapshot','intelligence-source','quick-source'].includes(event.target.id) || !event.target.value)return;
      const source=event.target.id==='quick-source'?(event.target.value.startsWith('lab:')?'snapshot:'+event.target.value.slice(4):event.target.value==='session'?'workspace':/^[a-f0-9]{32}$/.test(event.target.value)?'capture:'+event.target.value:''):'snapshot:'+event.target.value;if(!source)return;
      selectContext(source).catch(error=>notify(error.message,true));
    });
    window.addEventListener('workbench-language',()=>{
      const fields=[...document.querySelectorAll('#journey-panel input,#journey-panel select,#journey-panel textarea')].map(el=>({id:el.id,step:el.dataset.journeyStep,value:el.value,checked:el.checked}));
      renderContext();render();
      for(const saved of fields){const el=saved.id?document.getElementById(saved.id):document.querySelector('[data-journey-step="'+saved.step+'"]');if(!el)continue;if(el.type==='checkbox')el.checked=saved.checked;else el.value=saved.value;}
      renderReport().catch(error=>notify(error.message,true));
    });
  }
  return {init,load,selectContext,context:()=>info?.context || null};
})();
