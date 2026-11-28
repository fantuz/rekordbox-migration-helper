/* Review one collection and publish a separate snapshot after server-side revalidation. */
window.CollectionCleanup = (() => {
  const base = '/api/collection-cleanup';
  const node = id => document.getElementById('cc-' + id);
  const pageSize = 50, maxSelection = 25, bytesPerMiB = 1024 ** 2;
  const selected = new Set();
  const statuses = {
    present:'Present', missing:'File absent in a verified local folder', cloud:'Cloud location',
    external:'External drive or network share', foreign:'Path from another operating system',
    outside:'Outside the local Music folder', unclassified:'Unclassified path', unavailable:'Unavailable',
    sidecar:'Metadata sidecar'
  };
  const candidates = {eligible:'Eligible', protected:'Protected', missing:'Missing', duplicate:'Verified duplicates'};
  const reasons = {
    host_review_only:'Read-only', save_snapshot:'Save snapshot', incomplete_capture:'Incomplete',
    ambiguous_identity:'Conflicting track IDs', cloud_reference:statuses.cloud, external_volume:statuses.external,
    foreign_os:statuses.foreign, outside_music:statuses.outside, unknown_path:statuses.unclassified,
    unavailable_folder:statuses.unavailable, metadata_sidecar:statuses.sidecar, alternate_reference:'Alternate file reference',
    native_link:'Native library link', hot_cue_bank:'Hot Cue Bank', cues:'Cues', playlist:'Playlists',
    play_history:'Play history', analysis:'Analysis', rating:'Rating', saved_metadata:'Captured metadata',
    unknown_metadata:'Unknown / not captured', size_conflict:'Recorded size differs', metadata_edit:'Staged working edits',
    edit_history:'Working metadata', enrichment_review:'Enrichment', mapped_path:'Mapped path and size',
    workspace_decision:'Staged', workspace_relocation:'Staged export reference', workspace_unavailable:'Unavailable',
    keep_separate:'Keep separate', derived_snapshot:'This snapshot is already a cleanup copy.'
  };
  const coverage = {
    smart_membership:'Smart playlist membership could not be verified.',
    unresolved_native_links:'Native track links could not be verified.',
    missing_native_columns:'Required library fields were unavailable.',
    unresolved_playlist_links:'Some playlist references could not be resolved.',
    older_capture:'Capture the original collection again to include cleanup evidence.'
  };
  const reviewOnly = 'Review only on this host. Open Workbench on the original Windows or macOS computer to create a cleaned snapshot.';
  const musicUnavailable = 'The local Music folder is unavailable on this computer. This report is read-only.';
  const proofs = {absent:statuses.missing, same_file:'Same resolved file', sha256:'Identical bytes verified'};
  const signals = {same_name_size:'Matching name and size only', distinct_metadata:'Identical media with different metadata'};
  const recipes = {
    missing: {labels:['Eligible','Missing'], filters:{candidate:'missing'}},
    duplicates: {labels:['Verified duplicates'], filters:{candidate:'duplicate'}},
    protected_missing: {labels:['Protected','Missing'], filters:{candidate:'protected',status:'missing'}},
    cloud: {labels:[statuses.cloud], filters:{status:'cloud'}},
    names: {labels:[signals.same_name_size], filters:{signal:'same_name_size'}},
    sizes: {labels:[reasons.size_conflict], filters:{reason:'size_conflict'}}
  };
  const advancedFilters = ['reason','signal','proof','size-min','size-max'];
  const filters = ['volume','status','candidate','search',...advancedFilters];
  const text = key => I18n.t(key);
  const label = (map, key) => text(map[key] || 'Unknown');
  const html = key => esc(text(key));
  const post = (path, body) => api(base + path, {method:'POST', body:JSON.stringify(body)});
  const isOpen = () => !document.getElementById('view-collection-cleanup').hidden;
  let generation = 0, pageRequest = 0, source = '', requested = '', hostInfo = null;
  let active = false, knownContext = '';
  const contextKey = detail => JSON.stringify([detail?.source || '',detail?.scope_key || '']);
  let report = '', page = null, offset = 0, preview = null, result = null, working = false;
  const canCopy = () => Boolean(hostInfo?.can_apply && page?.summary.can_apply && source.startsWith('snapshot:')
    && hostInfo.host === page.summary.host);
  const selectable = row => Boolean(row.candidate && !row.protected);
  const remainingSelection = () => Math.max(0, Math.min(maxSelection, (page?.summary.counts.total ?? 1) - 1) - selected.size);
  const addableRows = () => (page?.rows || []).filter(row => selectable(row) && !selected.has(row.id));
  const current = generationAtStart => generationAtStart === generation && isOpen();
  function setOptions(id, first, choices, value = '') {
    const select = node(id);
    select.replaceChildren(new Option(text(first), ''), ...choices.map(([key, title]) => new Option(title, key)));
    select.value = choices.some(([key]) => key === value) ? value : '';
  }
  function resetPreview() {
    preview = null;
    if (node('confirm-dialog').open) node('confirm-dialog').close();
    node('original').checked = node('local').checked = false;
    node('phrase').value = '';
    node('apply').disabled = true;
  }
  function clearFilters() {
    for(const id of [...filters,'recipe']) node(id).value = '';
    node('advanced').open = false;
  }
  function resetReport() {
    pageRequest++;
    selected.clear();
    resetPreview();
    page = null;
    offset = 0;
    clearFilters();
    setOptions('volume','All locations',[]);
    setOptions('status','All statuses',[]);
    setOptions('candidate','All tracks',[]);
    node('results').hidden = true;
    for(const id of ['rows','drives','counts']) node(id).replaceChildren();
    node('compare').checked = false;
  }
  function resetSource(value) {
    generation++;
    source = value;
    working = false;
    hostInfo = result = null;
    report = '';
    resetReport();
    node('output').hidden = node('report-label').hidden = node('save-hint').hidden = true;
    node('host-note').hidden = node('compare-label').hidden = true;
    node('scan').disabled = true;
    node('message').textContent = '';
    return generation;
  }
  function refreshControls() {
    node('scan').disabled = !source || !hostInfo || working;
    node('compare-label').hidden = !source.startsWith('snapshot:') || !hostInfo?.can_apply;
    node('compare').disabled = working;
    node('report').disabled = working;
    node('selection').hidden = !canCopy();
    node('clear').disabled = node('review').disabled = !canCopy() || !selected.size || working;
    node('selected').textContent = I18n.t('{count} of 25 selected',{count:num(selected.size)});
    const batch = Math.min(remainingSelection(), addableRows().length);
    node('select-page').textContent = text('Select eligible references on this page') + (batch ? ' · '+num(batch) : '');
    node('select-page').disabled = !canCopy() || working || !batch;
    for(const box of node('rows').querySelectorAll('input[type=checkbox]')) {
      box.checked = selected.has(box.value);
      box.disabled = working || !canCopy() || (!box.checked && !remainingSelection());
    }
  }
  function reportList(info, chosen) {
    const reports = info.reports || [];
    node('report').replaceChildren(...reports.map(r =>
      new Option(snapshotMoment(r.created) + ' · ' + num(r.summary.counts.total) + ' ' + text('tracks'), r.id)));
    node('report-label').hidden = reports.length < 2;
    report = reports.some(r => r.id === chosen) ? chosen : (reports[0]?.id || '');
    node('report').value = report;
  }
  async function loadSource(value, chosenReport = '') {
    const at = resetSource(value);
    node('source').value = value;
    const info = await api(base + '?' + new URLSearchParams({source:value}), {feedback:false});
    if (!current(at)) return;
    hostInfo = info;
    reportList(info, chosenReport);
    const note = node('host-note');
    note.hidden = info.can_apply;
    note.dataset.i18n = ['Windows','macOS'].includes(info.host) ? musicUnavailable : reviewOnly;
    note.textContent = text(note.dataset.i18n);
    node('save-hint').hidden = !source || source.startsWith('snapshot:');
    node('message').textContent = !value ? text('Choose a collection') : !report ? text('Not checked') : '';
    refreshControls();
    if(report) await loadPage();
  }
  async function openPage() {
    const at = resetSource('');
    const from = requested;
    requested = '';
    const info = await api('/api/journeys', {feedback:false});
    if(!current(at)) return;
    const choices = info.sources.filter(s => s.id === 'workspace' || /^(snapshot|capture):[a-f0-9]{32}$/.test(s.id));
    const wanted = from || window.Journeys?.context()?.source || info.selected;
    const value = choices.some(s=>s.id===wanted) ? wanted : '';
    setOptions('source','Choose a collection',choices.map(s=>[s.id,s.label + (s.created?' · '+snapshotMoment(s.created):'')]),value);
    await loadSource(value);
  }
  function enter(view) {
    if(view === 'collection-cleanup') {
      active = true;
      knownContext = contextKey(window.Journeys?.context());
      void wrap(openPage)();
    } else if(active) {
      active = false;
      resetSource('');
    }
  }
  function renderReport() {
    const {summary:s} = page;
    node('results').hidden = false;
    node('message').textContent = '';
    node('time').textContent = text('Last checked') + ' · ' + snapshotMoment(page.created);
    const gates = (s.gates || []).filter(key=>!['host_review_only','save_snapshot'].includes(key));
    node('gates').hidden = !gates.length;
    const warnings = [...gates.map(k=>label(reasons,k)), ...(s.coverage_gaps || []).map(k=>label(coverage,k))];
    node('gates').textContent = [text('Read-only'), ...warnings].join(' · ');
    node('parent').hidden = !s.parent_snapshot_id;
    const metrics = {total:'File references', eligible:'Eligible', protected:'Protected', missing:'Missing', duplicate:'Verified duplicates'};
    node('counts').innerHTML = Object.entries(metrics).map(([k,n]) =>
      '<div data-cleanup-count="'+k+'"><span>'+(k==='missing'?html('Eligible')+' · ':'')+html(n)+'</span><strong>'+num(s.counts[k])+'</strong></div>').join('');
    const drives = s.volumes || [];
    const driveName = v => (v.os === 'Unclassified' ? text('Unclassified path') : v.os) + ' · ' + v.volume;
    node('drives').innerHTML = '<table><thead><tr>'+['Drive or volume','References','Present','Missing','Protected','Eligible'].map(x=>'<th scope="col">'+html(x)+'</th>').join('')+
      '</tr></thead><tbody>'+drives.map(v=>'<tr><th scope="row">'+esc(driveName(v))+'</th>'+
        ['total','present','missing','protected','eligible'].map(k=>'<td>'+num(v[k])+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
    // Keep each drive's origin alongside its name in the request as well as the label.
    setOptions('volume','All locations',drives.map(v=>[JSON.stringify([v.os,v.volume]),driveName(v)]),node('volume').value);
    const counted = (names, counts = {}, extra = []) => [...new Set([...Object.keys(counts),...extra])]
      .map(k=>[k,label(names,k)+' · '+num(counts[k] || 0)]);
    setOptions('status','All statuses',counted(statuses,s.statuses,['missing','cloud']),node('status').value);
    setOptions('candidate','All tracks',Object.entries(candidates).map(([k,n])=>[k,text(n)]),node('candidate').value);
    setOptions('reason','Any',counted(reasons,s.reasons,['size_conflict']),node('reason').value);
    setOptions('signal','Any',counted(signals,s.signals,['same_name_size']),node('signal').value);
    setOptions('proof','Any',Object.keys(proofs).map(k=>[k,label(proofs,k)]),node('proof').value);
    setOptions('recipe','Choose a preset',Object.entries(recipes).map(([k,recipe])=>[k,recipe.labels.map(text).join(' · ')]),node('recipe').value);
    const reasonsByCount = Object.entries(s.reasons || {}).sort((a,b)=>b[1]-a[1]);
    node('evidence').hidden = !reasonsByCount.length;
    node('reasons').innerHTML = reasonsByCount.map(([k,n])=>'<dt>'+esc(label(reasons,k))+'</dt><dd>'+num(n)+'</dd>').join('');
    node('signals').textContent = Object.entries(s.signals || {}).map(([k,n])=>label(signals,k)+' · '+num(n)).join(' / ');
    node('signals').hidden = !node('signals').textContent;
    node('hash').hidden = !s.compare_bytes;
    node('hash').textContent = [text('Checked')+' · '+num(s.hashed_files),text('source bytes read')+' · '+bytes(s.hash_bytes),text('Unverified')+' · '+num(s.hash_skipped)].join(' / ');
    renderRows();
  }
  function renderRows() {
    const headers = ['Track','Drive or volume','File status','File size','Evidence'];
    const sizeText = size => Number.isInteger(size) && size >= 0 ? bytes(size) : text('Unknown / not captured');
    const detail = row => {
      const labels = [
        ...(row.proof ? [label(proofs,row.proof)] : []),
        ...(row.reasons || []).filter(k=>!['host_review_only','save_snapshot'].includes(k)).map(k=>label(reasons,k)),
        ...(row.signals || []).map(k=>label(signals,k))
      ];
      return [...new Set(labels)].filter(value=>value!==label(statuses,row.status)).join(' · ');
    };
    node('rows').innerHTML = page.rows.length ? '<table data-result-sort="off"><thead><tr>'+headers.map(n=>'<th scope="col">'+html(n)+'</th>').join('')+
      '</tr></thead><tbody>'+page.rows.map(row=>{
        const title = row.title || text('Untitled');
        const input = canCopy() && selectable(row) ? '<input type="checkbox" value="'+esc(row.id)+'" aria-label="'+esc(title+' · '+row.id)+'"> ' : '';
        const finding = row.protected ? text('Protected') : row.candidate ? label(candidates,row.candidate) : '';
        const badge = finding ? '<span class="cc-finding">'+esc(finding)+'</span>' : '';
        const keeper = row.keeper_id != null ? '<span class="cc-keeper">'+html('Keeper')+' · '+esc(row.keeper_id)+'</span><code>'+esc(row.keeper_path)+'</code>' : '';
        const sizes = '<dl class="cc-file-sizes"><dt>'+html('Recorded size')+'</dt><dd>'+esc(sizeText(row.recorded_size))+
          '</dd><dt>'+html('Observed file size')+'</dt><dd>'+esc(sizeText(row.observed_size))+'</dd></dl>';
        return '<tr data-track-id="'+esc(row.id)+'"><td>'+input+'<strong>'+esc(title)+'</strong><small> · '+esc(row.id)+'</small>'+
          (row.artist?'<br>'+esc(row.artist):'')+'<code>'+esc(row.path)+'</code></td><td>'+esc(row.volume)+'</td><td>'+esc(label(statuses,row.status))+
          '</td><td>'+sizes+'</td><td>'+badge+esc(detail(row))+keeper+'</td></tr>';
      }).join('')+'</tbody></table>' : '<p class="subtle">'+html('No matching references')+'</p>';
    node('page').textContent = num(page.total) + ' ' + text('results') + (page.total?' · '+num(page.offset+1)+'–'+num(page.offset+page.rows.length):'');
    node('prev').disabled = page.offset === 0;
    node('next').disabled = page.offset + page.rows.length >= page.total;
    refreshControls();
  }
  async function loadPage() {
    if(!report) return;
    if(!node('filters').reportValidity()) return;
    const at = generation, request = ++pageRequest;
    const [os,volume] = node('volume').value ? JSON.parse(node('volume').value) : ['',''];
    const bound = (field, round) => node(field).value ? round(node(field).valueAsNumber * bytesPerMiB) : '';
    const size_min = bound('size-min',Math.ceil), size_max = bound('size-max',Math.floor);
    if(size_min !== '' && size_max !== '' && size_min > size_max) {
      throw new Error(text('Use non-negative limits, with the minimum no greater than the maximum.'));
    }
    const args = new URLSearchParams({source,os,volume,status:node('status').value,candidate:node('candidate').value,
      reason:node('reason').value,signal:node('signal').value,proof:node('proof').value,size_min,size_max,
      q:node('search').value.trim(),offset:String(offset),limit:String(pageSize)});
    const next = await api(base+'/'+encodeURIComponent(report)+'?'+args,{feedback:false});
    if(!current(at) || request !== pageRequest || next.id !== report || next.source !== source) return;
    const sameReport = page?.id === next.id;
    page = next;
    if(sameReport) renderRows();
    else renderReport();
  }
  async function run(work) {
    if(working || !source) return;
    const at = generation;
    working = true;
    refreshControls();
    try { await work(at); }
    finally { if(current(at)) { working = false;refreshControls(); } }
  }
  node('scan').onclick = wrap(()=>run(async at=>{
    const compare = !node('compare-label').hidden && node('compare').checked;
    selected.clear();resetPreview();
    const {job} = await post('/scan',{source,compare_bytes:compare,local_only:compare});
    const made = await poll(job);
    if(current(at)) await loadSource(source,made.id);
  }));
  node('report').onchange = wrap(async()=>{
    const next = node('report').value;
    resetReport();
    report = next;
    await loadPage();
  });
  node('source').onchange = wrap(async()=>{
    const value = node('source').value;
    const loading = loadSource(value);
    const syncing = value && value !== window.Journeys?.context()?.source
      ? Journeys.selectContext(value) : Promise.resolve();
    await Promise.all([loading,syncing]);
  });
  node('save').onclick = wrap(()=>LibraryPreparation.open(source,'collection-cleanup'));
  node('recipe').onchange = wrap(()=>{
    const recipe = node('recipe').value;
    clearFilters();
    const values = recipes[recipe]?.filters || {};
    for(const [id,value] of Object.entries(values)) node(id).value = value;
    node('recipe').value = recipe;
    node('advanced').open = advancedFilters.some(id=>id in values);
    offset = 0;
    return loadPage();
  });
  node('reset-filters').onclick = wrap(()=>{
    clearFilters();
    offset = 0;
    return loadPage();
  });
  node('filters').onsubmit = wrap(event=>{event.preventDefault();offset=0;return loadPage();});
  for(const id of filters) {
    const control = node(id);
    if(control.matches('select')) control.onchange = wrap(()=>{node('recipe').value='';offset=0;return loadPage();});
    else control.oninput = ()=>{node('recipe').value='';};
  }
  node('prev').onclick = wrap(()=>{offset=Math.max(0,page.offset-pageSize);return loadPage();});
  node('next').onclick = wrap(()=>{offset=page.offset+pageSize;return loadPage();});
  node('clear').onclick = ()=>{
    selected.clear();
    resetPreview();
    refreshControls();
  };
  node('select-page').onclick = ()=>{
    if(working || !canCopy()) return;
    for(const row of addableRows().slice(0,remainingSelection())) selected.add(row.id);
    resetPreview();
    refreshControls();
  };
  node('rows').onchange = event=>{
    const box = event.target;
    if(!box.matches('input[type=checkbox]') || working || !canCopy()) return;
    if(box.checked && remainingSelection()) selected.add(box.value);
    else selected.delete(box.value);
    resetPreview();
    refreshControls();
  };
  function showPreview() {
    node('confirm-source').textContent = text('Source snapshot')+' · '+node('source').selectedOptions[0].textContent;
    node('preview-counts').textContent = I18n.t('The new snapshot will omit {selected} references and keep {remaining} of {before}. The source snapshot stays available for recovery.',
      {selected:num(preview.selected_count),remaining:num(preview.after_count),before:num(preview.before_count)});
    node('preview-rows').innerHTML = preview.selected.map(row=>'<li><strong>'+esc(row.title || text('Untitled'))+'</strong> · '+esc(row.id)+
      ' · '+esc(label(candidates,row.candidate))+'<code>'+esc(row.path)+'</code>'+
      (row.keeper_id != null?'<span>'+html('Keeper')+' · '+esc(row.keeper_id)+'</span><code>'+esc(row.keeper_path)+'</code>':'')+'</li>').join('');
    node('phrase-label').textContent = I18n.t('Type {phrase} to confirm the selected references.',{phrase:preview.confirmation});
    if(!node('confirm-dialog').open) {
      node('confirm-dialog').showModal();
      node('cancel').focus();
    }
  }
  node('review').onclick = wrap(()=>run(async at=>{
    if(!canCopy() || !selected.size) return;
    resetPreview();
    const args = {source,report_id:report,selected_ids:[...selected]};
    const {job} = await post('/preview',args);
    const checked = await poll(job);
    if(!current(at) || report !== args.report_id) return;
    preview = checked;
    showPreview();
  }));
  function allowed() {
    return Boolean(preview && canCopy() && node('original').checked && node('local').checked &&
      node('phrase').value === preview.confirmation);
  }
  node('confirm-form').oninput = ()=>{node('apply').disabled = !allowed();};
  node('cancel').onclick = resetPreview;
  node('confirm-dialog').addEventListener('cancel',resetPreview);
  node('confirm-form').onsubmit = wrap(event=>{
    event.preventDefault();
    if(!allowed()) return;
    return run(async at=>{
      const args = {source,report_id:report,selected_ids:[...selected],token:preview.token,
        confirmation:node('phrase').value,original_computer:node('original').checked,local_only:node('local').checked};
      resetPreview();
      const {job} = await post('/apply',args);
      const made = await poll(job);
      if(!current(at)) return;
      result = made;
      selected.clear();
      node('saved-name').textContent = (made.snapshot?.label || text('Saved snapshot'))+' · '+made.snapshot_id;
      node('output').hidden = false;
      node('output').scrollIntoView({block:'nearest'});
      node('open-copy').focus({preventScroll:true});
    });
  });
  async function openSnapshot(id) {
    if(!id) return;
    await Journeys.load();
    await Journeys.selectContext('snapshot:'+id,true);
    showView('statistics');
  }
  node('parent').onclick = wrap(()=>openSnapshot(page?.summary.parent_snapshot_id));
  node('open-copy').onclick = wrap(()=>openSnapshot(result?.snapshot_id));
  node('open-source').onclick = wrap(()=>openSnapshot(result?.parent_snapshot_id));
  document.addEventListener('click',event=>{
    const link=event.target.closest('[data-cleanup-from]');
    if(!link) return;
    requested = link.dataset.cleanupFrom==='file-health' ? document.getElementById('file-health-source').value : window.Journeys?.context()?.source;
    showView('collection-cleanup');
  });
  window.addEventListener('workbench-context',wrap(async event=>{
    const nextContext = contextKey(event.detail);
    if(!isOpen() || nextContext === knownContext) return;
    knownContext = nextContext;
    if(event.detail?.source === source && source !== 'workspace') return;
    requested = event.detail?.source || '';
    await openPage();
  }));
  window.addEventListener('workbench-language',()=>{
    if(!isOpen()) return;
    if(page) renderReport();
    if(preview) showPreview();
  });
  return {enter};
})();
