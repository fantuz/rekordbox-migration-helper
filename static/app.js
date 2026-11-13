const preferences={get(key){try{return localStorage.getItem(key);}catch{return null;}},set(key,value){try{localStorage.setItem(key,value);}catch{}},remove(key){try{localStorage.removeItem(key);}catch{}}};
const $ = s => document.querySelector(s);
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const num = n => I18n.number(Number(n || 0));
const date = d => d ? I18n.date(d) : I18n.t("Unknown");
const bytes = value => {const n=Number(value || 0);const unit=n>=1024**3?3:n>=1024**2?2:n>=1024?1:0;return I18n.number(n/1024**unit,{maximumFractionDigits:1})+" "+["B","KiB","MiB","GiB"][unit];};
const autoCue = c => ["cue(auto)", "1.1bars"].includes((c.Comment || "").trim().toLowerCase());
let token = "", session = null, filter = "all", offset = 0, total = 0, selected = null, chosen = null, batchMode = null, busy = false;
let searchTimer;
let currentGroup=null, groupMode=false;
let workspace=null,analyzerInfo=null,storageAudit=null,storageOffset=0;
let resumeTarget=null;
const activeUploads=new Set();
let mutatingRequests=0;
const metadataFields=["album","artist","genre","label","format","bpm_min","bpm_max","bitrate_min","playlist","availability"];
function scopeValues() {return {q:$("#search").value,feature:$("#feature-filter").value,min:$("#stats-min").value || "0",max:$("#stats-max").value,cohort:$("#stats-cohort").value,evidence:evidenceValue(),...Object.fromEntries(metadataFields.map(k=>[k,$("#filter-"+k).value]))};}
const evidenceLabels={
  get files_found_both(){return I18n.t("Both files found in scanned roots");},
  get content_hash_agrees(){return I18n.t("Last file hash verification agreed");},
  get content_hash_differs(){return I18n.t("Last file hash verification differed");},
  get preview_agrees(){return I18n.t("Saved preview fingerprints agree");},
  get recorded_path_agrees(){return I18n.t("A recorded path agrees");},
  get current_path_agrees(){return I18n.t("Current recorded path agrees");},
  get metadata_agrees(){return I18n.t("Title and artist agree");},
  get cue_set_agrees(){return I18n.t("Full cue positions agree");},
  get auto_only_both(){return I18n.t("Both siblings have only auto cues");},
  get no_cues_both(){return I18n.t("Neither sibling has cues");},
  get manual_present(){return I18n.t("Other / manual cues are present");},
  get grid_agrees(){return I18n.t("Saved beat grids agree");},
  get grid_differs(){return I18n.t("Saved beat grids differ");},
  get rated(){return I18n.t("At least one sibling is starred");},
  get rating_conflict(){return I18n.t("Star ratings conflict");},
  get played(){return I18n.t("A saved play count is positive");},
  get history(){return I18n.t("A saved play history is available");},
  get recency_differs(){return I18n.t("Added dates differ");},
  get both_in_xml(){return I18n.t("Both siblings appear in the XML");},
  get input_mismatch(){return I18n.t("ZIP / XML cue versions differ");}
};
let evidenceSelected=new Set();
function evidenceValue() {return [...evidenceSelected].join(",");}
function renderEvidence(facets) {
  $("#evidence-filters").innerHTML=Object.entries(evidenceLabels).map(([key,label])=>'<label><input type="checkbox" data-evidence="'+key+'" '+(evidenceSelected.has(key)?"checked":"")+'><span>'+esc(label)+'</span><b>'+num(facets[key] || 0)+'</b></label>').join("");
  $$("[data-evidence]").forEach(el=>el.onchange=wrap(async()=>{
    if (el.checked) evidenceSelected.add(el.dataset.evidence);else evidenceSelected.delete(el.dataset.evidence);
    offset=0;await loadPairs();
  }));
}
function $$(s) {return [...document.querySelectorAll(s)];}
async function api(url, options = {}) {
  const mutation=options.method && options.method!=='GET';if(mutation)mutatingRequests++;
  try{
    const res = await fetch(url, { ...options, headers: {"Content-Type":"application/json","X-Workbench-Token":token,...(options.headers || {})}});
    const body = await res.json();
    if (!res.ok) throw new Error(body.error ? I18n.error(body.error) : I18n.t("The action could not be completed"));
    return body;
  }finally{if(mutation)mutatingRequests--;}
}
function notify(text, error=false) {
  const toast = $("#toast");
  toast.textContent = text;
  toast.style.borderColor = error ? "#a66464" : "#5b6257";
  toast.hidden = false;
  clearTimeout(toast.timeout);
  toast.timeout = setTimeout(() => toast.hidden = true, error ? 9000 : 4500);
}
function wrap(fn) { return async e => {try {await fn(e);} catch(error) {notify(error.message,true);}}; }
let progressCancel=null;
function progress(n, text, cancel) {
  const dialog=$("#progress"),value=Number.isFinite(n)?Math.max(0,Math.min(100,n)):null;
  if(cancel){progressCancel=cancel;$("#progress-cancel").hidden=false;$("#progress-cancel").disabled=false;}
  dialog.hidden=false;if(!dialog.open)dialog.showModal();
  document.documentElement.dataset.operationBusy='true';
  $("#progress-label").textContent=text;
  $("#progress-percent").textContent=value===null?'—':I18n.number(Math.round(value))+'%';
  if(value===null)$("#progress-bar").removeAttribute('value');else $("#progress-bar").value=value;
}
function finishProgress(){
  const dialog=$("#progress");if(dialog.open)dialog.close();dialog.hidden=true;
  document.documentElement.dataset.operationBusy='false';progressCancel=null;$("#progress-cancel").hidden=true;
}
$("#progress").addEventListener('cancel',event=>event.preventDefault());
$("#progress-stop").onclick=()=>openCleanupDialog();
$("#progress-cancel").onclick=wrap(async()=>{$("#progress-cancel").disabled=true;if(progressCancel)await progressCancel();});
async function poll(job) {
  const wasBusy=busy;busy=true;progress(null,I18n.t("Working"));
  try {
    while (true) {
      const state=await api("/api/tasks/"+job);
      progress(state.progress,state.message);
      if (state.status==="error") throw new Error(state.message);
      if (state.status==="complete") return state.result;
      await new Promise(resolve=>setTimeout(resolve,900));
    }
  } finally { busy=wasBusy;finishProgress(); }
}
function renderSession() {
  if (!session) return;
  const c=session.counts;
  $("#dataset-name").textContent=session.name || session.metadata.name;
  $("#dataset-check").textContent=" · "+session.metadata.input_check;
  $("#metric-tracks").textContent=num(c.tracks);
  $("#metric-pairs").textContent=num(c.pairs);
  $("#metric-xml").textContent=num(c.xml_tracks)+" "+I18n.t("tracks represented in the XML");
  $("#metric-ready").textContent=num(c.ready);
  $("#metric-auto").textContent=num(c.auto);
  $("#metric-staged").textContent=num(session.staged);
  $("#nav-staged").textContent=num(session.staged);
  $("#pair-count").textContent=num(c.pairs)+" "+I18n.t("candidate pairs");
  $("#policy").value=session.policy;
  $("#reference-count").textContent=num(session.relocations)+" "+I18n.t("reference edits staged");
  $("#activity-list").innerHTML=session.events.slice().reverse().map(e=>'<div class="event"><time>'+esc(new Date(e.time).toLocaleTimeString(I18n.language, {hour:"2-digit",minute:"2-digit"}))+'</time><span>'+esc(e.text)+'</span></div>').join("");
  renderWorkflow();
}
async function refresh() {
  const state=await api("/api/status"); token=state.token;session=state.session;
  $(".version").textContent=I18n.t('Version')+' · '+(state.version || 'development');
  renderSession();
  $("#stop-desktop").hidden=!state.desktop;$("#progress-stop").hidden=!state.desktop;
  $("#load-example").hidden=!state.example_available;
  if ($("#empty-example")) $("#empty-example").hidden=!state.example_available;
  if (session) {await loadPairs();await renderStatistics();
    const select=$("#filter-playlist"), old=select.value;
    select.innerHTML=("<option value=\"\">"+esc(I18n.t("Any playlist"))+"</option>")+(session.metadata.playlist_options || []).map(p=>'<option value="'+esc(p.id)+'">'+esc(p.name)+'</option>').join("");
    select.value=old;
  }
  await loadPresets();
  await loadWorkspace();
  await loadAnalyzer();
  await loadStorageInfo();
  await loadQuickExports();
  if (typeof loadLab === 'function') await loadLab();
}

async function loadQuickExports() {
  const info=await api("/api/quick-export"),select=$("#quick-source"),old=select.value;
  const options=[];
  if(session) options.push(("<option value=\"session\">"+esc(I18n.t("Loaded XML/ZIP workspace ·"))+" ")+num(session.counts.tracks)+(" "+esc("tracks")+"</option>"));
  options.push(...info.sources.map(s=>'<option value="'+esc(s.id)+("\">"+esc(I18n.t("Source snapshot ·"))+" "+"")+esc(new Date(s.created).toLocaleString(I18n.language))+' · '+num(s.tracks)+(" "+esc("tracks")+"</option>")));
  select.innerHTML=options.join("") || ("<option value=\"\">"+esc(I18n.t("Load a workspace or analyze a source folder first"))+"</option>");
  if([...select.options].some(o=>o.value===old))select.value=old;
  updateQuickSource();
  $("#quick-directory").textContent=info.directory;
  $("#quick-history").innerHTML=info.exports.map(e=>'<article class="export-record"><div class="export-record-heading"><strong>'+esc(e.title)+'</strong><span>'+esc(new Date(e.created).toLocaleString(I18n.language))+'</span></div><p>'+num(e.tracks)+(" "+I18n.t("tracks")+" \u00b7 ")+esc(e.source_kind)+' · '+(e.includes_paths?I18n.t("recorded paths included"):I18n.t("file paths excluded"))+'</p><div class="download-links">'+e.files.map(f=>'<a class="button secondary small" href="'+esc(f.download)+'">'+(f.kind==='html'?I18n.t("Standalone HTML"):I18n.t("Minisite ZIP"))+' ↓</a>').join("")+'<a class="text-button" href="/api/quick-export/'+esc(e.id)+("/report\">"+esc(I18n.t("Export details ↓"))+"</a></div><div class=\"folder-row\"><span>"+esc(I18n.t("Saved explorer folder"))+"</span><code>")+esc(e.directory)+'</code><button class="text-button" data-export-path="'+esc(e.directory)+("\">"+esc(I18n.t("Copy path"))+"</button></div></article>")).join("") || ("<p class=\"subtle\">"+esc(I18n.t("No offline explorers generated yet."))+"</p>");
  bindExportCopies();
}
function updateQuickSource() {
  const source=$("#quick-source").value;
  $("#quick-generate").disabled=!source || busy;
  $("#quick-scope").disabled=source!=="session";
  if(source!=="session")$("#quick-scope").value="all";
}
$("#quick-source").onchange=updateQuickSource;
$("#quick-export-form").onsubmit=wrap(async event=>{
  event.preventDefault();if(busy)return;
  const result=await api("/api/quick-export",{method:"POST",body:JSON.stringify({source:$("#quick-source").value,title:$("#quick-title").value,scope:$("#quick-scope").value,include_paths:$("#quick-paths").checked})});
  await poll(result.job);await loadQuickExports();notify(I18n.t("Standalone HTML and offline minisite saved"));
});

function renderWorkflow() {
  $("#continue-review").disabled=!session;
  const acknowledged=!!session?.backup_acknowledged;
  const nativeVersion=String(session?.metadata?.version || "").split(".")[0]==="7";
  $("#export-pair").disabled=!session || busy || !acknowledged || !nativeVersion;
  $("#export-zip").disabled=!session || busy || !acknowledged || !nativeVersion;
  $("#export-xml").disabled=!session || busy || !acknowledged;
  $("#backup-ack").checked=acknowledged;
  $("#backup-ack").disabled=!session || busy;
  $("#backup-ack-state").textContent=acknowledged?I18n.t("Acknowledged for this workspace ·")+" "+new Date(session.backup_acknowledged).toLocaleString(I18n.language):session?I18n.t("Acknowledge your separate backup to enable export. This records your statement; it does not verify restorability."):I18n.t("Load a workspace to acknowledge your backup.");
  $("#native-version-note").hidden=!session || nativeVersion;
  $("#paired-export-summary").textContent=session ? num(session.staged)+" "+I18n.t("staged merges ·")+" "+num(session.relocations)+" "+I18n.t("reference edits ·")+" "+num(session.metadata_override_fields)+" "+I18n.t("metadata fields ·")+" "+session.name : I18n.t("Load a library pair to begin.");
  if (!session) return;
  $("#workflow-session-title").textContent=session.name;
  const mode=session.metadata.import_mode;
  const note=mode==="linked"?I18n.t("Read in place · no input copy"):mode==="example"?I18n.t("Configured local rehearsal"):I18n.t("Workspace input copies");
  $("#workflow-summary").textContent=note+". "+num(session.staged)+" "+I18n.t("merges and")+" "+num(session.relocations)+" "+I18n.t("reference edits are staged for export.");
  $("#current-inputs").innerHTML=[[I18n.t("ZIP · native library"),session.metadata.zip_path],[I18n.t("XML · exported collection"),session.metadata.xml_path]]
    .map(([label,path])=>'<div><span>'+esc(label)+'</span><code>'+esc(path)+'</code></div>').join("")+
    '<p class="source-check">'+esc(session.metadata.input_check)+'</p>'+
    (mode==="example"?("<p class=\"subtle\">"+esc(I18n.t("The local shortcut reuses a configured comparison and associated files on this computer. Example libraries are not included in application downloads. Check the input notes for the scope of this example."))+"</p>"):"");
}
function exportCard(record) {
  const label=record.format==="pair"?I18n.t("XML + ZIP + report"):record.format.toUpperCase()+" "+I18n.t("+ report");
  return '<article class="export-record"><div class="export-record-heading"><strong>'+esc(label)+'</strong><span>'+esc(new Date(record.created).toLocaleString(I18n.language))+'</span></div><p>'+esc(record.session_name)+' · '+num(record.merges)+(" "+esc(I18n.t("merges · one saved decision snapshot"))+"</p><div class=\"download-links\">")+record.files.map(f=>'<a class="button secondary small" href="'+esc(f.download)+("\">"+esc(I18n.t("Download"))+" "+"")+esc(f.kind.toUpperCase())+' ↓</a>').join("")+("</div><div class=\"folder-row\"><span>"+esc(I18n.t("Saved output folder"))+"</span><code>")+esc(record.directory)+'</code><button class="text-button" data-export-path="'+esc(record.directory)+("\">"+esc(I18n.t("Copy path"))+"</button></div></article>");
}
function bindExportCopies() {
  $$("[data-export-path]").forEach(button=>button.onclick=wrap(async()=>{
    await navigator.clipboard.writeText(button.dataset.exportPath);notify(I18n.t("Output folder path copied"));
  }));
}
async function loadWorkspace() {
  workspace=await api("/api/workspace");
  for (const [id,value] of Object.entries({"workspace-root":workspace.root,"workspace-inputs":workspace.inputs,"workspace-exports":workspace.exports_root,"import-inbox":workspace.inputs,"upload-destination":workspace.temporary_root || workspace.root})) $("#"+id).textContent=value;
  for (const kind of ["zip","xml"]) $("#workspace-"+(kind==="zip"?"zips":"xmls")).innerHTML=workspace.files.filter(f=>f.kind===kind).map(f=>'<option value="'+esc(f.path)+'">'+esc(f.name)+'</option>').join("");
  const history=workspace.exports.map(exportCard).join("") || ("<p class=\"subtle\">"+esc(I18n.t("No completed exports yet. Generated files will appear here after validation."))+"</p>");
  $("#workflow-export-history").innerHTML=history;
  $("#export-history").innerHTML=history;
  bindExportCopies();renderWorkflow();
}
async function loadPairs() {
  if (!session) return;
  const scope=new URLSearchParams({...scopeValues(),filter,offset,view:groupMode?"groups":"pairs"});
  const result=await api("/api/pairs?"+scope);
  total=result.total;
  renderEvidence(result.facets);
  $("#workload").innerHTML=[
    [result.groups,I18n.t("Duplicate groups")],[result.tracks,I18n.t("Track records")],[result.pair_count || result.total,I18n.t("Pair comparisons")],
    [result.review_groups,I18n.t("Groups needing review")],[result.potential_reduction,I18n.t("Possible redundant rows")]
  ].map(([count,title])=>'<div><strong>'+num(count)+'</strong><span>'+title+'</span></div>').join("");
  $("#page-range").textContent=total ? (offset+1)+"–"+Math.min(offset+40,total)+" "+I18n.t("of")+" "+num(total)+(groupMode?" "+I18n.t("groups"):" "+I18n.t("pairs"))+" · "+num(result.groups)+" "+I18n.t("groups") : I18n.t("No pairs in this view");
  $("#prev").disabled=offset===0;$("#next").disabled=offset+40>=total;
  $("#pair-list").innerHTML=result.rows.map(r=>{
    const state=r.decision ? r.decision.action==="merge"?"staged":"skip" : r.category;
    const label={get ready(){return I18n.t("Ready");},get auto(){return I18n.t("Auto cues");},get review(){return I18n.t("Review");},get staged(){return I18n.t("Staged");},get skip(){return I18n.t("Skipped");}}[state];
    const cues=groupMode?r.track_count+" "+I18n.t("siblings"):r.cue_equal?I18n.t("Same cue set"):r.cue_a.total+" ↔ "+r.cue_b.total+" "+I18n.t("cues");
    return '<button class="pair-row '+((groupMode?currentGroup?.id:selected?.id)===r.id?"selected":"")+'" data-pair="'+esc(r.id)+'"><div style="min-width:0"><div class="pair-title">'+esc(r.title || I18n.t("Untitled"))+'</div><div class="pair-artist">'+esc(r.artist || I18n.t("Artist unknown"))+'</div></div><span class="cue-evidence">'+esc(cues)+'</span><span class="badge '+state+'">'+label+'</span></button>';
  }).join("") || ("<div class=\"empty-state\"><h3>"+esc(I18n.t("A clear view."))+"</h3><p>"+esc(I18n.t("No candidate pairs match these filters."))+"</p></div>");
  $$("#pair-list [data-pair]").forEach(b=>b.onclick=wrap(()=>groupMode?selectGroup(result.rows.find(r=>r.id===b.dataset.pair)):selectPair(b.dataset.pair)));
  const previous=groupMode?currentGroup?.id:selected?.id;
  if (groupMode && result.rows.length) {
    await selectGroup(result.rows.find(r=>r.id===previous) || result.rows[0]);
  } else if (result.rows.length && !result.rows.some(r=>r.id===previous)) {
    await selectPair(result.rows[0].id);
  } else if (!result.rows.length) {
    selected=null;currentGroup=null;
    $("#detail-panel").innerHTML=("<div class=\"detail-empty\"><h3>"+esc(I18n.t("No pair in this scope"))+"</h3><p>"+esc(I18n.t("Adjust the filters to choose another recording."))+"</p></div>");
  }
}
async function selectPair(id) {
  selected=await api("/api/pair/"+encodeURIComponent(id));
  chosen=selected.decision?.keeper || selected.keeper;
  renderDetail();
  $$(".pair-row").forEach(b=>b.classList.toggle("selected",b.dataset.pair===(groupMode?currentGroup?.id:id)));
}
function lane(track, index) {
  const duration=Math.max(1,track.duration_seconds*1000);
  const dots=track.cues.map(c=>'<i class="cue-dot '+(autoCue(c)?"auto":"")+'" style="left:'+Math.max(0,Math.min(99,100*(c.InMsec || 0)/duration))+'%" title="'+esc((c.Comment || I18n.t("Cue"))+" · "+((c.InMsec || 0)/1000).toFixed(2)+" s")+'"></i>').join("");
  return ("<div class=\"cue-lane\"><label>"+esc(I18n.t("Sibling"))+" "+"")+String.fromCharCode(65+index)+'</label><div class="cue-track">'+dots+'</div></div>';
}
function renderDetail() {
  const r=selected;
  if (!r) return;
  const names=["A","B"];
  const trackCards=r.tracks.map((t,i)=>'<article class="sibling '+(chosen===t.track_id?"chosen":"")+'" data-keeper="'+esc(t.track_id)+'" tabindex="0" role="button" aria-label="'+esc(I18n.t("Choose sibling {id}",{id:names[i]}))+("\"><div class=\"sibling-top\">"+esc(I18n.t("Sibling"))+" "+"")+names[i]+'<span>'+(chosen===t.track_id?I18n.t("◉ KEEPER"):"○")+'</span></div><div class="title">'+esc(t.title)+'</div><div class="stars" aria-label="'+esc(I18n.t("Personal stars"))+': '+num(t.rating)+'">'+("★".repeat(Math.min(5,t.rating)))+("☆".repeat(Math.max(0,5-t.rating)))+("</div><dl><dt>"+esc(I18n.t("Album"))+"</dt><dd>")+esc(t.album || I18n.t("Unknown"))+("</dd><dt>"+esc(I18n.t("Cues"))+"</dt><dd>")+t.cue_summary.auto+(" "+I18n.t("Auto cues")+" \u00b7 ")+t.cue_summary.other+(" "+esc(I18n.t("Other cues"))+"</dd><dt>"+esc(I18n.t("Added"))+"</dt><dd>")+esc(date(t.date_added))+("</dd><dt>"+esc(I18n.t("Last played"))+"</dt><dd>")+esc(date(t.last_played))+("</dd><dt>"+esc(I18n.t("Play count"))+"</dt><dd>")+num(t.play_count)+("</dd><dt>"+esc(I18n.t("File size"))+"</dt><dd>")+(t.size_bytes/1e6).toFixed(1)+(" MB</dd><dt>"+esc(I18n.t("Source"))+"</dt><dd>")+(t.october_xml?I18n.t("XML + backup"):I18n.t("Backup"))+'</dd></dl><div class="path">'+esc(t.xml_location || t.original_path || t.current_path)+'</div><button class="ref-link" data-file-detail="'+esc(t.track_id)+("\">"+esc(I18n.t("File view / comments"))+"</button><button class=\"ref-link\" data-ref=\"")+esc(t.track_id)+("\">"+esc(I18n.t("Prepare this reference ↗"))+"</button></article>")).join("");
  const ratingConflict=r.conflicts.some(c=>c.type==="rating");
  const autoConflicts=r.conflicts.filter(c=>c.type==="cue_slot" && c.auto);
  const other=r.conflicts.filter(c=>!autoConflicts.includes(c) && c.type!=="rating");
  let note=r.cue_equal?I18n.t("The saved cue positions and loop endpoints agree."):
    autoConflicts.length && !other.length?I18n.t("The conflicting donor slots have automatic labels. The keeper policy can resolve these."):
    other.length?I18n.t("Some cue differences need a choice. Swapping the keeper may preserve the preferred preparation."):I18n.t("These cue sets can be combined without a slot conflict.");
  if (r.group_note) note+=" "+I18n.t("Group review ·")+" "+r.group_note;
  if (r.grid_differs) note+=" "+I18n.t("The selected keeper's grid will be used.");
  $("#detail-panel").innerHTML=("<div class=\"detail-head\"><span class=\"eyebrow\">"+esc(I18n.t("PAIR INSPECTION"))+"</span><h3>")+esc(r.title)+'</h3><p>'+esc(r.artist)+("</p><span class=\"subtle\">"+esc(I18n.t("Suggested keeper ·"))+" ")+esc(r.keeper_reason)+'</span></div><div class="sibling-cards">'+trackCards+("</div><div class=\"cue-comparison\"><h4>"+esc(I18n.t("Saved cue positions"))+"</h4><div class=\"legend\"><span><i></i>"+" "+esc(I18n.t("Automatic labels"))+"</span><span><i class=\"manual\"></i>"+" "+esc(I18n.t("Other cues"))+"</span></div>")+r.tracks.map(lane).join("")+'<div class="cue-time"><span>0:00</span><span>'+Math.floor(Math.max(...r.tracks.map(t=>t.duration_seconds))/60)+(" "+esc("minutes")+"</span></div><div class=\"conflict-note\">")+esc(note)+'</div></div><div class="detail-actions"><label><input type="checkbox" id="accept-auto" '+(r.decision?.prefer_auto?"checked":"")+(">"+" "+esc(I18n.t("Keep selected sibling’s cue when the other cue has an automatic label"))+"</label>")+(ratingConflict?("<label><input type=\"checkbox\" id=\"accept-rating\">"+" "+esc(I18n.t("Keep selected sibling’s rating"))+"</label>"):"")+("<div class=\"action-row\"><button class=\"button\" id=\"stage-pair\">"+esc(I18n.t("Stage merge"))+"</button><button class=\"button secondary\" id=\"skip-pair\">"+esc(I18n.t("Skip"))+"</button>")+(r.decision?("<button class=\"button secondary\" id=\"undo-pair\">"+esc(I18n.t("Undo"))+"</button>"):"")+'</div></div>';
  $$("[data-file-detail]").forEach(button=>{button.onclick=wrap(async event=>{event.stopPropagation();await openWorkspaceTrack(button.dataset.fileDetail);});button.onkeydown=event=>event.stopPropagation();});
  $$("[data-keeper]").forEach(el=>{
    const choose=()=>{chosen=el.dataset.keeper;renderDetail();};
    el.onclick=e=>{if (!e.target.closest("[data-ref]")) choose();};
    el.onkeydown=e=>{if (e.key==="Enter" || e.key===" ") {e.preventDefault();choose();}};
  });
  $$("[data-ref]").forEach(el=>el.onclick=()=>{const t=r.tracks.find(t=>t.track_id===el.dataset.ref);$("#reference-track").value=t.track_id;$("#reference-uri").value=t.xml_location || "";showView("reference");});
  $("#stage-pair").onclick=wrap(()=>saveDecision("merge"));
  $("#skip-pair").onclick=wrap(()=>saveDecision("skip"));
  if ($("#undo-pair")) $("#undo-pair").onclick=wrap(()=>saveDecision("undo"));
  const verify=document.createElement("button");verify.className="text-button";verify.textContent=I18n.t("Verify local file bytes");
  verify.onclick=wrap(async()=>{const job=await api("/api/inventory/verify",{method:"POST",body:JSON.stringify({pair:r.id})});const result=await poll(job.job);notify(result.same_file_bytes?I18n.t("The local file bytes are identical"):I18n.t("The local file bytes differ"));await selectPair(r.id);});
  $("#detail-panel").append(verify);
  if (r.media_verification) {const note=document.createElement("p");note.className="hash-evidence";note.textContent=r.media_verification.same_file_bytes?I18n.t("Verified identical local file bytes"):I18n.t("Local file hashes differ");$("#detail-panel").append(note);}
  if (groupMode && currentGroup) renderGroupControls();
}
async function saveDecision(action) {
  const result=await api("/api/decision",{method:"POST",body:JSON.stringify({pair:selected.id,action,keeper:chosen,prefer_auto:$("#accept-auto")?.checked || false,prefer_rating:$("#accept-rating")?.checked || false})});
  session=result.session;renderSession();await loadPairs();await selectPair(selected.id);
  notify(action==="undo"?I18n.t("Decision undone"):I18n.t("Decision saved to this workspace"));
}
function showView(view) {
  if(view!=="bubbles" && $("#bubble-expanded").open)$("#bubble-expanded").close();
  $$(".view").forEach(v=>v.hidden=v.id!=="view-"+view);
  $$(".nav").forEach(n=>n.classList.toggle("active",n.dataset.view===view));
  if (view==="statistics") renderStatistics().catch(error=>notify(error.message,true));
  if (view==="inventory") loadInventory().catch(error=>notify(error.message,true));
  if (view==="analyzer") loadAnalyzer().catch(error=>notify(error.message,true));
  if (view==="storage") loadStorageInfo().catch(error=>notify(error.message,true));
  if (view==="quick") loadQuickExports().catch(error=>notify(error.message,true));
  if (view==="lab") loadLab().catch(error=>notify(error.message,true));
  if (view==="history") loadHistory().catch(error=>notify(error.message,true));
  if (view==="insights") loadDJInsights().catch(error=>notify(error.message,true));
  if (view==="bubbles") loadBubbleExplorer().catch(error=>notify(error.message,true));
  if (view==="tonality") loadTonalityInsights().catch(error=>notify(error.message,true));
  if (view==="docs" && typeof loadDocumentation==='function') loadDocumentation().catch(error=>notify(error.message,true));
  if (view==="files" || view==="exports") loadWorkspace().catch(error=>notify(error.message,true));
  $("#collection-metrics").hidden=["files","analyzer","storage","quick","lab","history","insights","bubbles","tonality"].includes(view);
  $(".dataset-bar").hidden=["analyzer","storage","quick","lab","history","insights","bubbles","tonality"].includes(view);
  $("#page-title").textContent={get files(){return I18n.t("Library preparation");},get analyzer(){return I18n.t("Source analysis");},get storage(){return I18n.t("Cloud and local storage");},get quick(){return I18n.t("Offline metadata export");},get review(){return I18n.t("Duplicate review");},get reference(){return I18n.t("File references");},get activity(){return I18n.t("Activity and reports");},get statistics(){return I18n.t("Collection statistics");},get inventory(){return I18n.t("Media inventory");},get exports(){return I18n.t("Library export");}}[view];
  window.scrollTo(0,0);
  if (view==='lab') $('#page-title').textContent=I18n.t("Library lab");
  if (view==='history') $('#page-title').textContent=I18n.t("Play history");
  if (view==='insights') $('#page-title').textContent=I18n.t("DJ insights");
  if (view==='bubbles') $('#page-title').textContent=I18n.t("Library bubbles");
  if (view==='tonality') $('#page-title').textContent=I18n.t("Tonality and tempo");
  if (view==='docs'){$('#page-title').textContent=I18n.t('Documentation');$('#collection-metrics').hidden=true;$('.dataset-bar').hidden=true;}
}
async function example() {
  if (busy) return;
  const result=await api("/api/example",{method:"POST",body:"{}"});
  await poll(result.job);selected=null;currentGroup=null;offset=0;await refresh();showView("review");notify(I18n.t("Configured local workspace loaded"));
}
async function uploadFile(file,url) {
  progress(null,I18n.t("Loading")+" "+file.name);
  return new Promise((resolve,reject)=>{
    const xhr=new XMLHttpRequest();
    activeUploads.add(xhr);xhr.onloadend=()=>activeUploads.delete(xhr);xhr.onabort=()=>reject(new Error(I18n.t("Upload cancelled for shutdown")));
    xhr.open("PUT",url);
    xhr.setRequestHeader("X-Workbench-Token",token);
    xhr.setRequestHeader("Content-Type","application/octet-stream");
    xhr.upload.onprogress=e=>progress(e.lengthComputable?100*e.loaded/e.total:null,I18n.t("Loading")+" "+file.name);
    xhr.onload=()=>{
      let body;
      try {body=JSON.parse(xhr.responseText);} catch {reject(new Error(I18n.t("Upload interrupted")));return;}
      if (xhr.status>=400) reject(new Error(body.error || I18n.t("Upload failed"))); else resolve(body);
    };
    xhr.onerror=()=>reject(new Error(I18n.t("Upload connection was interrupted")));
    xhr.send(file);
  });
}
$("#load-example").onclick=wrap(example);$("#empty-example").onclick=wrap(example);
$$("[data-open-import]").forEach(button=>button.onclick=wrap(async()=>{
  resumeTarget=null;$('#resume-import-note').hidden=true;
  await loadWorkspace();$("#import-dialog").showModal();
}));
$("#continue-review").onclick=()=>showView("review");
$("#backup-ack").onchange=wrap(async event=>{
  const result=await api("/api/backup/acknowledge",{method:"POST",body:JSON.stringify({confirmed:event.target.checked})});
  session=result.session;renderSession();
});
$$("[data-copy-location]").forEach(button=>button.onclick=wrap(async()=>{
  await navigator.clipboard.writeText($("#"+button.dataset.copyLocation).textContent);notify(I18n.t("Folder path copied"));
}));
$$("[data-import-mode]").forEach(button=>button.onclick=()=>{
  const local=button.dataset.importMode==="local";
  $("#import-form").hidden=local;$("#local-import-form").hidden=!local;
  $$("[data-import-mode]").forEach(b=>b.setAttribute("aria-pressed",String(b===button)));
});
$("#refresh-workspace-files").onclick=wrap(async()=>{await loadWorkspace();notify(workspace.files.length+" "+I18n.t("input files available as suggestions"));});
$$(".close-dialog").forEach(b=>b.onclick=()=>b.closest("dialog").close());
$("#import-form").onsubmit=wrap(async e=>{
  e.preventDefault();
  if (busy) return;
  const zip=$("#zip-input").files[0],xml=$("#xml-input").files[0];
  if (!zip || !xml) return;
  busy=true;$("#import-dialog").close();progress(null,I18n.t("Working"));
  try {
    const started=await api("/api/import",{method:"POST",body:JSON.stringify({zip:zip.name,xml:xml.name,resume_session:resumeTarget})});
    await uploadFile(zip,"/api/upload/"+started.session+"/zip");
    await uploadFile(xml,"/api/upload/"+started.session+"/xml");
    const result=await api("/api/import/"+started.session+"/analyze",{method:"POST",body:"{}"});
    await poll(result.job);selected=null;currentGroup=null;offset=0;await refresh();showView("review");notify(I18n.t("Input pair checked and loaded"));
  } finally {busy=false;finishProgress();}
});
$("#local-import-form").onsubmit=wrap(async e=>{
  e.preventDefault();if (busy) return;
  const started=await api("/api/import/local",{method:"POST",body:JSON.stringify({zip:$("#local-zip").value,xml:$("#local-xml").value,resume_session:resumeTarget})});
  $("#import-dialog").close();
  await poll(started.job);selected=null;currentGroup=null;offset=0;await refresh();showView("review");notify(I18n.t("Existing files analyzed · no input copy created"));
});
$$("[data-view]").forEach(b=>b.onclick=()=>showView(b.dataset.view));
$$("[data-filter]").forEach(b=>b.onclick=wrap(async()=>{filter=b.dataset.filter;offset=0;$$(".tab").forEach(t=>t.classList.toggle("active",t===b));await loadPairs();}));
$("#search").oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(wrap(async()=>{offset=0;await loadPairs();}),250);};
$("#prev").onclick=wrap(async()=>{offset=Math.max(0,offset-40);await loadPairs();});
$("#next").onclick=wrap(async()=>{offset+=40;await loadPairs();});
$("#policy").onchange=wrap(async e=>{
  if (!session) return;
  const result=await api("/api/policy",{method:"POST",body:JSON.stringify({policy:e.target.value})});
  await poll(result.job);await refresh();if (selected) await selectPair(selected.id);notify(I18n.t("Keeper suggestions updated"));
});
function batch(mode) {
  if (!session) {notify(I18n.t("Load a library first"),true);return;}
  batchMode=mode;
  $("#batch-title").textContent=mode==="ready"?I18n.t("Stage compatible pairs?"):I18n.t("Resolve differences in automatic cues?");
  $("#batch-description").textContent=mode==="ready"?I18n.t("Stage pairs with matching media evidence and compatible cues and ratings. A sibling with other cues is preferred, followed by your selected usage rule."):I18n.t("When an older cue with an automatic label conflicts with the selected keeper’s slot, retain the keeper’s cue. Other cue and rating conflicts stay in review. This batch uses the current length, cue and search selectors.");
  $("#batch-dialog").showModal();
}
$("#bulk-ready").onclick=()=>batch("ready");$("#bulk-auto").onclick=()=>batch("auto");
$("#confirm-batch").onclick=wrap(async()=>{
  $("#batch-dialog").close();
  progress(20,I18n.t("Staging batch decisions"));
  try {
    const result=await api("/api/bulk",{method:"POST",body:JSON.stringify({...scopeValues(),mode:batchMode})});
    session=result.session;renderSession();await loadPairs();notify(num(result.count)+" "+I18n.t("merges staged ·")+" "+num(result.covered)+" "+I18n.t("comparisons already covered ·")+" "+num(result.blocked)+" "+I18n.t("group choices held"));
  } finally {$("#progress").hidden=true;}
});
$("#reference-form").onsubmit=wrap(async e=>{
  e.preventDefault();
  const result=await api("/api/relocation",{method:"POST",body:JSON.stringify({track_id:$("#reference-track").value.trim(),uri:$("#reference-uri").value.trim()})});
  session=result.session;renderSession();notify(I18n.t("Reference staged for the exported copy"));
});
async function generateExport(format) {
  if (!session || busy) return;
  $("#export-pair").disabled=true;
  try {
    const started=await api("/api/export",{method:"POST",body:JSON.stringify({format})});
    const result=await poll(started.job);
    const target=$(format==="pair"?"#paired-downloads":format==="xml"?"#export-downloads":"#zip-downloads");
    target.hidden=false;target.innerHTML=exportCard(result);bindExportCopies();
    await refresh();notify(format==="pair"?I18n.t("XML + ZIP validated and saved together"):I18n.t("Export validated and saved"));
  } finally {renderWorkflow();}
}
$("#export-pair").onclick=wrap(async()=>generateExport("pair"));
$("#export-xml").onclick=wrap(async()=>generateExport("xml"));

function applyTheme(value) {
  preferences.set("workbench-theme",value);
  const actual=value==="system" ? matchMedia("(prefers-color-scheme: light)").matches?"light":"dark" : value;
  document.documentElement.dataset.theme=actual;
  $("#theme").value=value;
}
applyTheme(preferences.get("workbench-theme") || "dark");
$("#theme").onchange=e=>applyTheme(e.target.value);
matchMedia("(prefers-color-scheme: light)").addEventListener("change",()=>{if ($("#theme").value==="system") applyTheme("system");});
async function renderStatistics() {
  if (!session) return;
  const params=new URLSearchParams({min:$("#stats-min").value || "0",max:$("#stats-max").value,cohort:$("#stats-cohort").value});
  const data=await api("/api/statistics?"+params);
  $("#review-scope").textContent=I18n.t("Review scope ·")+" "+($("#stats-min").value || "0")+"–"+($("#stats-max").value || I18n.t("Unlimited"))+" "+I18n.t("Minutes")+" · "+($("#stats-cohort").value==="xml"?I18n.t("XML siblings"):I18n.t("All backup tracks"));
  const labels=[
    ["total",I18n.t("Total songs"),I18n.t("Within the selected length range")],
    ["analysed",I18n.t("Analyzed songs"),I18n.t("Saved analysis flag in the backup")],
    ["rated",I18n.t("Starred songs"),I18n.t("Saved rating above zero")],
    ["full_manual",I18n.t("Full manual cues"),I18n.t("Every cue lacks an automatic label")],
    ["mixed",I18n.t("Half-automated cues"),I18n.t("A mix of automatic and other cues")],
    ["only_auto",I18n.t("Only automatic cues"),I18n.t("Every cue has an automatic label")],
    ["no_cues_no_plays",I18n.t("No cues · zero play count"),I18n.t("Both saved counters are zero")],
    ["no_cues",I18n.t("Songs with no cues"),I18n.t("Any recorded play count")],
    ["albums",I18n.t("Albums"),I18n.t("Distinct album names in this scope")],
    ["authors",I18n.t("Authors / artists"),I18n.t("Distinct primary artist names")],
    ["composers",I18n.t("Composers"),I18n.t("Distinct saved composer names")],
    ["total_playlists",I18n.t("Playlists"),I18n.t("Active native playlists, excluding folders")],
    ["playlists",I18n.t("Playlists in this range"),I18n.t("Playlists containing a selected track")],
    ["broken_xml_targets",I18n.t("Broken XML playlist targets"),I18n.t("Targets outside the XML Collection")],
    ["broken_database_links",I18n.t("Broken database links"),I18n.t("Active native links without an active track")],
    ["orphan_analysis_folders",I18n.t("Unlinked analysis folders"),I18n.t("Folders with no active native reference")],
    ["missing_media",I18n.t("Missing audio files"),I18n.t("Not established by exports; see Media inventory")],
    ["orphan_media",I18n.t("Confirmed orphaned audio"),I18n.t("Unverified until media inventory")]];
  $("#stats-cards").innerHTML=labels.map(([key,title,note])=>'<article class="stat-card"><span>'+esc(title)+'</span><strong>'+(data.counters[key]===null?I18n.t("Unverified"):num(data.counters[key]))+'</strong><small>'+esc(note)+'</small></article>').join("");
  const max=Math.max(1,...data.histogram.map(b=>b.count));
  $("#length-histogram").innerHTML=data.histogram.map(b=>'<div class="hist-row"><span>'+esc(b.label)+'</span><div class="hist-bar"><i style="width:'+100*b.count/max+'%"></i></div><b>'+num(b.count)+'</b></div>').join("");
  $('#added-histogram').innerHTML=renderAddedYears(data.addition_dates);
}
$("#stats-apply").onclick=wrap(async()=>{await renderStatistics();offset=0;await loadPairs();});
$("#stats-cohort").onchange=wrap(async()=>{await renderStatistics();offset=0;await loadPairs();});
$("#stats-preset").onchange=wrap(async e=>{
  const range={all:["0",""],music:["1","15"],sets:["30",""],samples:["0","1"]}[e.target.value];
  $("#stats-min").value=range[0];$("#stats-max").value=range[1];
  await renderStatistics();offset=0;await loadPairs();
});
$("#export-zip").onclick=wrap(async()=>generateExport("zip"));

$("#undo-batch").onclick=wrap(async()=>{
  if (!session) return;
  const result=await api("/api/bulk/undo",{method:"POST",body:"{}"});
  session=result.session;renderSession();await loadPairs();notify(num(result.count)+" "+I18n.t("batch decisions undone"));
});

$("#feature-filter").onchange=wrap(async()=>{offset=0;await loadPairs();});

$("#clear-evidence").onclick=wrap(async()=>{evidenceSelected.clear();offset=0;await loadPairs();});
async function loadPresets() {
  const result=await api("/api/presets");
  const current=$("#saved-filter").value;
  $("#saved-filter").innerHTML=("<option value=\"\">"+esc(I18n.t("Choose a preset"))+"</option>")+Object.keys(result.presets).map(name=>'<option>'+esc(name)+'</option>').join("");
  $("#saved-filter").value=current;
  $("#saved-filter").presets=result.presets;
}
$("#save-filter").onclick=()=>$("#preset-dialog").showModal();
$("#preset-form").onsubmit=wrap(async e=>{
  e.preventDefault();
  await api("/api/presets",{method:"POST",body:JSON.stringify({name:$("#preset-name").value.trim(),criteria:scopeValues()})});
  $("#preset-dialog").close();await loadPresets();notify(I18n.t("Filter preset saved"));
});
$("#saved-filter").onchange=wrap(async e=>{
  const values=e.target.presets[e.target.value];if (!values) return;
  $("#search").value=values.q || "";$("#feature-filter").value=values.feature || "all";
  $("#stats-min").value=values.min || "0";$("#stats-max").value=values.max || "";
  $("#stats-cohort").value=values.cohort || "all";
  evidenceSelected=new Set((values.evidence || "").split(",").filter(Boolean));
  metadataFields.forEach(k=>$("#filter-"+k).value=values[k] || "");
  offset=0;await renderStatistics();await loadPairs();
});
$("#apply-metadata").onclick=wrap(async()=>{offset=0;await loadPairs();});
$("#open-sessions").onclick=wrap(async()=>{
  const result=await api("/api/sessions");
  $("#sessions-list").innerHTML=result.sessions.map(s=>'<div class="session-option"><div>'+esc(s.name)+'<small>'+num(s.staged)+(" "+I18n.t("Staged")+" \u00b7 ")+esc(new Date(s.updated*1000).toLocaleString(I18n.language))+(s.available?'':" "+I18n.t("· temporary inputs cleaned or originals unavailable"))+'</small></div><button class="button secondary small" '+(s.available?'data-resume':'data-reattach')+'="'+esc(s.id)+'">'+(s.available?I18n.t("Resume"):I18n.t("Reattach originals"))+'</button></div>').join("") || ("<p>"+esc(I18n.t("No saved workspace yet. Load a matching ZIP and XML to begin."))+"</p>");
  $$('[data-reattach]').forEach(b=>b.onclick=wrap(async()=>{
    resumeTarget=b.dataset.reattach;$('#sessions-dialog').close();await loadWorkspace();$('#resume-import-note').hidden=false;$('#import-dialog').showModal();
  }));
  $$("[data-resume]").forEach(b=>b.onclick=wrap(async()=>{
    $("#sessions-dialog").close();
    const result=await api("/api/sessions/"+b.dataset.resume+"/resume",{method:"POST",body:"{}"});
    await poll(result.job);selected=null;currentGroup=null;offset=0;await refresh();notify(I18n.t("Saved workspace resumed"));
  }));
  $("#sessions-dialog").showModal();
});
$("#review-mode").onchange=wrap(async e=>{
  groupMode=e.target.value==="groups";currentGroup=null;selected=null;offset=0;await loadPairs();
});
async function selectGroup(group) {
  const detail=await api("/api/group/details?ids="+encodeURIComponent(group.track_ids.join(",")));
  const previousKeeper=currentGroup?.id===group.id?currentGroup.keeper:null;
  currentGroup={...group,detail,keeper:group.track_ids.includes(previousKeeper)?previousKeeper:detail.keeper};
  await selectPair(group.representative);
}
function renderGroupControls() {
  const group=currentGroup;
  const box=document.createElement("div");box.className="group-toolbar";
  box.innerHTML=("<h4>"+esc(I18n.t("Recording group ·"))+" ")+group.track_count+(" "+esc("siblings")+"</h4><label>"+esc(I18n.t("Keep this sibling"))+"<select id=\"group-keeper\">")+group.detail.tracks.map(t=>'<option value="'+esc(t.track_id)+'" '+(group.keeper===t.track_id?"selected":"")+'>'+esc(t.track_id+" · "+t.cue_summary.other+" "+I18n.t("other cues ·")+" "+date(t.date_added)+" · "+(t.bitrate || "?")+" kbps")+'</option>').join("")+("</select></label><label>"+esc(I18n.t("Inspect a pair"))+"<select id=\"group-comparison\">")+group.pair_ids.map(id=>'<option value="'+esc(id)+'" '+(selected.id===id?"selected":"")+'>'+esc(id.replace("~"," ↔ "))+'</option>').join("")+("</select></label><button class=\"button secondary\" id=\"stage-group\">"+esc(I18n.t("Stage this recording group"))+"</button>");
  $("#detail-panel").prepend(box);
  $("#group-keeper").onchange=e=>currentGroup.keeper=e.target.value;
  $("#group-comparison").onchange=wrap(async e=>selectPair(e.target.value));
  $("#stage-group").onclick=wrap(async()=>{
    const result=await api("/api/group/stage",{method:"POST",body:JSON.stringify({track_ids:group.track_ids,keeper:group.keeper,
        prefer_auto:$("#accept-auto")?.checked || false,prefer_rating:$("#accept-rating")?.checked || false})});
    session=result.session;renderSession();await loadPairs();notify(result.count+" "+I18n.t("siblings staged ·")+" "+Object.keys(result.held).length+" "+I18n.t("held for review"));
  });
}
let inventoryOffset=0;
function addMediaRoot(root={}) {
  const row=document.createElement("div");row.className="media-root";
  row.innerHTML=("<label>"+esc(I18n.t("Folder on this computer"))+"<input class=\"media-folder\" placeholder=\"/home/you/Music or D:\\Music\" value=\"")+esc(root.root || "")+("\"></label><label>"+esc(I18n.t("Recorded prefix · optional"))+"<input class=\"media-prefix\" placeholder=\"C:/Users/you/Music\" value=\"")+esc(root.recorded_prefix || "")+("\"></label><label>"+esc(I18n.t("Export root URI · optional"))+"<input class=\"media-export\" placeholder=\"file://localhost/D:/Music\" value=\"")+esc(root.export_uri || "")+'"></label>';
  $("#media-roots").append(row);
}
addMediaRoot();
$("#add-media-root").onclick=()=>addMediaRoot();
$("#scan-media").onclick=wrap(async()=>{
  if (!session) return;
  const roots=$$(".media-root").map(r=>({root:r.querySelector(".media-folder").value.trim(),recorded_prefix:r.querySelector(".media-prefix").value.trim(),export_uri:r.querySelector(".media-export").value.trim()})).filter(r=>r.root);
  const result=await api("/api/inventory/scan",{method:"POST",body:JSON.stringify({roots})});
  const done=await poll(result.job);
  inventoryOffset=0;await refresh();await loadInventory();
  notify(num(done.files)+" "+I18n.t("media files indexed")+(done.warnings.length?" "+I18n.t("· some folders need attention"):""));
});
async function loadInventory() {
  if (!session) return;
  const result=await api("/api/inventory?"+new URLSearchParams({offset:inventoryOffset,status:$("#inventory-status").value,q:$("#inventory-search").value}));
  $("#inventory-counts").innerHTML=Object.entries(result.counts).map(([name,n])=>'<article><span>'+esc(name.replaceAll("_"," ").toUpperCase())+'</span><strong>'+num(n)+'</strong></article>').join("");
  $("#inventory-list").innerHTML=result.rows.map(r=>'<div class="inventory-row"><div>'+esc(r.title)+'<small>'+esc(r.artist)+'</small></div><span>'+esc(r.status.replaceAll("_"," "))+'</span><div><small>'+esc(r.candidates[0]?.path || I18n.t("Absent from scanned roots"))+'</small><small>'+esc(r.evidence || "")+'</small></div><button class="button secondary small" data-inventory-ref="'+esc(r.track_id)+'" '+(r.status==="found" && r.candidates[0]?.export_uri?"":"disabled")+(">"+esc(I18n.t("Stage reference"))+"</button></div>")).join("") || ("<p>"+esc(I18n.t("No inventory items in this view."))+"</p>");
  $$("[data-inventory-ref]").forEach(b=>b.onclick=wrap(async()=>{
    const done=await api("/api/inventory/stage",{method:"POST",body:JSON.stringify({track_id:b.dataset.inventoryRef})});
    session=done.session;renderSession();notify(I18n.t("Verified-root candidate staged for the prepared copy"));
  }));
  $("#inventory-range").textContent=result.total?num(inventoryOffset+1)+"–"+num(Math.min(inventoryOffset+50,result.total))+" "+I18n.t("of")+" "+num(result.total)+(" "+I18n.t("References")+""):I18n.t("No matching references");
  $("#inventory-more").disabled=inventoryOffset+50>=result.total;
}
$("#inventory-more").onclick=wrap(async()=>{inventoryOffset+=50;await loadInventory();});
$("#inventory-status").onchange=wrap(async()=>{inventoryOffset=0;await loadInventory();});
$("#inventory-search").onchange=wrap(async()=>{inventoryOffset=0;await loadInventory();});
$('#stop-desktop').onclick=wrap(()=>openCleanupDialog());
async function loadAnalyzer() {
  const data=await api("/api/analyzer");
  analyzerInfo=data;
  if(typeof renderDiscoveryHints==='function')await renderDiscoveryHints(data.discovery);
  $("#analyzer-directory").textContent=data.directory;
  $("#analyzer-sources").innerHTML=data.suggestions.map(path=>'<option value="'+esc(path)+'"></option>').join("");
  $("#analyzer-location-guide").innerHTML='<p class="subtle">'+esc(data.discovery.help)+'</p>'+data.discovery.found.map(row=>'<div class="detected-source"><code>'+esc(row.path)+'</code><small>'+esc(row.origin)+'</small><button class="text-button" data-use-source="'+esc(row.path)+("\">"+esc(I18n.t("Use this folder"))+"</button></div>")).join("")+(data.discovery.found.length?"":("<p class=\"subtle\">"+esc(I18n.t("No local database was detected in the standard locations. Enter any accessible source-folder path below."))+"</p>"));
  $$("[data-use-source]").forEach(button=>button.onclick=()=>{$("#analyzer-path").value=button.dataset.useSource;});
  $("#compatibility-matrix").innerHTML=data.compatibility.map(row=>'<div class="compatibility-row"><strong>'+esc(row.version)+'</strong><div><b>'+esc(row.format)+'</b><span>'+esc(row.status)+'</span><small>'+esc(row.detail)+'</small></div></div>').join("");
  $("#analyzer-history").innerHTML=data.reports.map(report=>'<article class="analyzer-history-record"><div><strong>'+esc(report.format)+'</strong><span>'+esc(new Date(report.created).toLocaleString(I18n.language))+' · '+esc(report.read_status.replaceAll("_"," "))+'</span><code>'+esc(report.source)+'</code></div><button class="button secondary small" data-open-analysis="'+esc(report.id)+("\">"+esc(I18n.t("Open report"))+"</button></article>")).join("") || ("<p class=\"subtle\">"+esc(I18n.t("No saved source-folder reports yet."))+"</p>");
  $$("[data-open-analysis]").forEach(button=>button.onclick=wrap(async()=>{renderAnalysis(await api("/api/analyzer/"+button.dataset.openAnalysis));$("#analyzer-result").scrollIntoView({behavior:"smooth",block:"start"});}));
}
function renderAnalysis(report) {
  const target=$("#analyzer-result");target.hidden=false;
  const db=report.database, inventory=report.footprint;
  const status={get checked(){return I18n.t("Read completed");},get needs_review(){return I18n.t("Needs review");},get unsupported(){return I18n.t("Database unreadable");},get inventory_only(){return I18n.t("File inventory only");}}[report.read_status];
  const metric=(label,value,note="")=>'<article class="stat-card"><span>'+esc(label)+'</span><strong>'+(value===null || value===undefined?I18n.t("Unavailable"):num(value))+'</strong><small>'+esc(note)+'</small></article>';
  const counters=db?.counters || report.xml?.counters || {};
  const health=db?.health || {};
  target.innerHTML=("<article class=\"wide-card analysis-report\"><div class=\"section-heading\"><div><span class=\"eyebrow\">"+esc(I18n.t("READ-ONLY REPORT ·"))+" ")+esc(status)+'</span><h2>'+esc(report.format)+'</h2><p>'+esc(new Date(report.created).toLocaleString(I18n.language))+' · '+(report.version_hint?(report.xml?I18n.t("XML product version")+" ":I18n.t("User-supplied version")+" ")+esc(report.version_hint):I18n.t("Exact application version not inferred"))+'</p></div><a class="button secondary" href="/api/analyzer/'+esc(report.id)+("/report\">"+esc(I18n.t("Download JSON report ↓"))+"</a></div><code class=\"report-source\">")+esc(report.source)+'</code><p class="read-only-confirmation">'+(report.xml?I18n.t("The XML was read without changing it. No native database conversion was performed."):I18n.t("No changes were written to the source folder. Database queries ran on a temporary private snapshot."))+'</p><div class="analyzer-messages">'+report.messages.map(message=>'<p class="analysis-message '+esc(message.level)+'">'+esc(message.text)+'</p>').join("")+'</div>'+
    (db?("<div class=\"database-status\"><span>"+esc(I18n.t("Database integrity"))+" "+"<b>")+esc(db.integrity_ok?I18n.t("Passed"):db.integrity.join('; '))+("</b></span><span>"+esc(I18n.t("Storage"))+" "+"<b>")+esc(db.encryption)+("</b></span><span>"+esc(I18n.t("Schema"))+" "+"<b>")+num(db.table_count)+' tables</b></span></div><div class="stats-cards">'+[[I18n.t("Tracks"),"tracks"],[I18n.t("Analyzed tracks"),'analysed'],[I18n.t("Starred tracks"),'rated'],[I18n.t("Playlists"),'playlists'],[I18n.t("Albums"),'albums'],[I18n.t("Artists"),'artists'],[I18n.t("Native cue rows"),'cue_rows'],[I18n.t("Only auto cues"),'only_auto'],[I18n.t("Full manual cues"),'full_manual'],[I18n.t("Half-automated cues"),'mixed'],[I18n.t("No cues"),'no_cues'],[I18n.t("No cues · zero plays"),'no_cues_no_plays']].map(([label,key])=>metric(label,counters[key])).join("")+("</div><h3>"+esc(I18n.t("References and candidate issues"))+"</h3><div class=\"stats-cards\">")+[[I18n.t("Broken track links"),'broken_track_links'],[I18n.t("Repeated recorded-path groups"),'duplicate_recorded_path_groups'],[I18n.t("Tracks in repeated paths"),'tracks_in_duplicate_paths'],[I18n.t("Analysis folders found"),'analysis_folders_found'],[I18n.t("Analysis folders without active links"),'unlinked_analysis_folders'],[I18n.t("Referenced analysis folders absent here"),'analysis_folders_not_found_here']].map(([label,key])=>metric(label,health[key])).join("")+'</div><ul class="analysis-notes">'+db.notes.map(note=>'<li>'+esc(note)+'</li>').join("")+'</ul>':"")+
    (report.xml?("<h3>"+esc(I18n.t("Exported XML metadata"))+"</h3><div class=\"stats-cards\">")+[[I18n.t("Tracks"),"tracks"],[I18n.t("Artists"),'artists'],[I18n.t("Albums"),'albums'],[I18n.t("Genres"),'genres'],[I18n.t("Playlists"),'playlists'],[I18n.t("Tracks with BPM"),'bpm_known'],[I18n.t("Tracks with duration"),'duration_known']].map(([label,key])=>metric(label,counters[key])).join('')+("</div><p class=\"subtle\">"+esc(I18n.t("Title, artist, BPM, duration and other available tags can be browsed in Quick export. These counts describe this XML, rather than native .edb records. Unexported fields remain unknown."))+"</p>"):'')+
    ("<h3>"+esc(I18n.t("Selected-source footprint"))+"</h3><div class=\"footprint-summary\"><strong>")+esc(bytes(inventory.bytes))+'</strong><span>'+num(inventory.files)+" "+I18n.t("files · logical file sizes ·")+" "+num(inventory.cloud_placeholders)+(" "+esc(I18n.t("cloud placeholders"))+"</span></div><div class=\"footprint-table\"><div class=\"footprint-row footprint-header\"><span>"+esc(I18n.t("File type"))+"</span><span>"+esc(I18n.t("Files"))+"</span><span>"+esc(I18n.t("Size"))+"</span><span>"+esc(I18n.t("Share of footprint"))+"</span></div>")+inventory.extensions.map(row=>'<div class="footprint-row"><code>'+esc(row.extension)+'</code><span>'+num(row.files)+'</span><span>'+esc(bytes(row.bytes))+'</span><div class="hist-bar"><i style="width:'+Math.max(0,Math.min(100,100*row.bytes/Math.max(1,inventory.bytes)))+'%"></i></div></div>').join("")+'</div>'+(report.track_paths_available?("<button class=\"button secondary\" id=\"audit-report-storage\">"+esc(I18n.t("Compare music locations for this report →"))+"</button>"):'')+'</article>';
  if ($("#audit-report-storage")) $("#audit-report-storage").onclick=wrap(async()=>{
    await loadAnalyzer();await loadStorageInfo();$("#storage-source-report").value=report.id;showView("storage");
  });
}
$("#analyzer-form").onsubmit=wrap(async event=>{
  event.preventDefault();if (busy) return;
  const button=event.target.querySelector('button[type="submit"]');button.disabled=true;
  try {
    const started=await api("/api/analyzer",{method:"POST",body:JSON.stringify({path:$("#analyzer-path").value,version:$("#analyzer-version").value})});
    const report=await poll(started.job);renderAnalysis(report);await loadAnalyzer();
    notify(I18n.t("Read-only source report saved"));$("#analyzer-result").scrollIntoView({behavior:"smooth",block:"start"});
  } finally {button.disabled=false;}
});
$("#refresh-source-locations").onclick=wrap(async()=>{await loadAnalyzer();notify(I18n.t("Default locations and saved database paths checked"));});

const storageNames={get local(){return I18n.t("Other local folders");},get dropbox(){return I18n.t("Dropbox-visible files");},get google_drive(){return I18n.t("Google Drive-visible files");}};
function addStorageRoot(value={}) {
  const row=document.createElement("div");row.className="storage-root";
  row.innerHTML=("<label>"+esc(I18n.t("Folder on this computer"))+"<input class=\"storage-root-path\" value=\"")+esc(value.root || "")+("\" placeholder=\""+esc(I18n.t("Full path to a music folder"))+"\"></label><label>"+esc(I18n.t("Location type"))+"<select class=\"storage-root-kind\"><option value=\"local\">"+esc(I18n.t("Other local folder"))+"</option><option value=\"dropbox\">"+esc(I18n.t("Dropbox folder"))+"</option><option value=\"google_drive\">"+esc(I18n.t("Google Drive folder"))+"</option></select></label><label>"+esc(I18n.t("Recorded prefix · optional"))+"<input class=\"storage-root-prefix\" value=\"")+esc(value.recorded_prefix || "")+("\" placeholder=\""+esc(I18n.t("Old database path, e.g. C:/Music"))+"\"></label><button type=\"button\" class=\"text-button\" aria-label=\""+esc(I18n.t("Remove music folder"))+"\">"+esc(I18n.t("Remove"))+"</button>");
  row.querySelector("select").value=value.kind || "local";
  row.querySelector("button").onclick=()=>row.remove();$("#storage-roots").append(row);
}
addStorageRoot();addStorageRoot({kind:"dropbox"});
$("#add-storage-root").onclick=()=>addStorageRoot();
async function loadStorageInfo() {
  const data=await api("/api/storage");
  const selected=$("#storage-source-report").value;
  $("#storage-source-report").innerHTML=("<option value=\"\">"+esc(I18n.t("Compare folders without a source report"))+"</option>")+(analyzerInfo?.reports || []).filter(row=>row.track_paths_available).map(row=>'<option value="'+esc(row.id)+'">'+esc(new Date(row.created).toLocaleString(I18n.language)+" · "+row.source)+'</option>').join("");
  $("#storage-source-report").value=selected;
  $("#storage-suggestions").innerHTML=data.suggestions.length?("<p class=\"subtle\">"+esc(I18n.t("Detected cloud folders · choose only those containing the music you want to compare"))+"</p>")+data.suggestions.map((row,index)=>'<button class="button secondary small" type="button" data-storage-suggestion="'+index+'">'+esc(row.kind==="dropbox"?"Dropbox":"Google Drive")+' · '+esc(row.root)+'</button>').join(""): ("<p class=\"subtle\">"+esc(I18n.t("You can enter any accessible cloud or local folder. Google Drive may use a custom drive letter or mount point."))+"</p>");
  $$("[data-storage-suggestion]").forEach(button=>button.onclick=()=>addStorageRoot(data.suggestions[Number(button.dataset.storageSuggestion)]));
  $("#storage-history").innerHTML=data.reports.map(row=>'<article class="analyzer-history-record"><div><strong>'+num(row.file_locations)+" "+I18n.t("file locations ·")+" "+num(row.totals.cloud_local_candidate_groups)+(" "+esc(I18n.t("cloud/local candidate groups"))+"</strong><span>")+esc(new Date(row.created).toLocaleString(I18n.language))+" "+I18n.t("· policy hint:")+" "+esc(row.policy_hint)+'</span></div><button class="button secondary small" data-storage-open="'+esc(row.id)+("\">"+esc(I18n.t("Open comparison"))+"</button></article>")).join("") || ("<p class=\"subtle\">"+esc(I18n.t("No saved comparisons yet."))+"</p>");
  $$("[data-storage-open]").forEach(button=>button.onclick=wrap(async()=>{storageOffset=0;await loadStorageAudit(button.dataset.storageOpen);$("#storage-result").scrollIntoView({behavior:"smooth",block:"start"});}));
}
function storageBar(locations,key) {
  const total=locations.reduce((sum,row)=>sum+row[key],0);
  return '<div class="storage-bar">'+locations.map(row=>'<span class="storage-color-'+row.kind+'" style="width:'+100*row[key]/Math.max(1,total)+'%" title="'+esc(storageNames[row.kind]+": "+bytes(row[key]))+'"></span>').join("")+'</div><div class="storage-legend">'+locations.map(row=>'<span><i class="storage-color-'+row.kind+'"></i>'+esc(storageNames[row.kind])+' · '+esc(bytes(row[key]))+'</span>').join("")+'</div>';
}
async function loadStorageAudit(id) {
  const scope=$("#storage-scope")?.value || "all";
  storageAudit=await api("/api/storage/"+id+"?"+new URLSearchParams({offset:storageOffset,scope}));
  const audit=storageAudit,t=audit.totals,target=$("#storage-result");target.hidden=false;
  const cloudBytes=audit.locations.filter(row=>row.kind!=="local").reduce((sum,row)=>sum+row.logical_bytes,0);
  const allocated=audit.locations.reduce((sum,row)=>sum+row.known_allocated_bytes,0);
  target.innerHTML=("<article class=\"wide-card storage-overview\"><div class=\"section-heading\"><div><span class=\"eyebrow\">"+esc(I18n.t("READ-ONLY COMPARISON ·"))+" ")+esc(new Date(audit.created).toLocaleString(I18n.language))+("</span><h2>"+esc(I18n.t("Visible files and possible copies"))+"</h2><p>"+esc(I18n.t("User policy hint:"))+" ")+esc(audit.policy_hint)+' · '+num(audit.matched_database_tracks)+" "+I18n.t("database tracks matched")+(audit.source_report?'':" "+I18n.t("· no database report linked"))+'</p></div><a class="button secondary" href="/api/storage/'+esc(id)+("/report\">"+esc(I18n.t("Download JSON report ↓"))+"</a></div><div class=\"storage-metrics\">")+[[I18n.t("Cloud-folder logical bytes"),bytes(cloudBytes)],[I18n.t("Known local disk allocation"),bytes(allocated)],[I18n.t("Cloud/local candidate groups"),num(t.cloud_local_candidate_groups)],[I18n.t("Possible extra logical bytes"),bytes(t.potential_extra_logical_bytes)],[I18n.t("Last verified extra identical bytes"),bytes(t.last_verified_extra_logical_bytes)],[I18n.t("Repeated DB reference groups"),num(t.database_reference_groups)]].map(([label,value])=>'<article class="stat-card"><span>'+esc(label)+'</span><strong>'+esc(value)+'</strong></article>').join("")+("</div><h3>"+esc(I18n.t("Logical media size by visible location"))+"</h3>")+storageBar(audit.locations,"logical_bytes")+("<h3>"+esc(I18n.t("Known disk allocation by location"))+"</h3>")+storageBar(audit.locations,"known_allocated_bytes")+("<p class=\"subtle\">"+esc(I18n.t("Cloud-folder logical bytes can also occupy local disk. These measures overlap; they are not account quota usage. Allocation is OS-reported and may be partial on some filesystems."))+"</p><div class=\"storage-location-table\"><div class=\"storage-location-row storage-location-header\"><span>"+esc(I18n.t("Location"))+"</span><span>"+esc(I18n.t("Files"))+"</span><span>"+esc(I18n.t("Logical size"))+"</span><span>"+esc(I18n.t("Known disk allocation"))+"</span><span>"+esc(I18n.t("Detected placeholders"))+"</span></div>")+audit.locations.map(row=>'<div class="storage-location-row"><strong>'+esc(storageNames[row.kind])+'</strong><span>'+num(row.files)+'</span><span>'+esc(bytes(row.logical_bytes))+'</span><span>'+esc(bytes(row.known_allocated_bytes))+(row.unknown_allocation_files?' · '+num(row.unknown_allocation_files)+(" "+I18n.t("Unknown")+""):'')+'</span><span>'+num(row.cloud_placeholders)+'</span></div>').join("")+'</div>'+audit.warnings.map(warning=>'<p class="analysis-message warning">'+esc(warning)+'</p>').join("")+'<ul class="analysis-notes">'+audit.notes.map(note=>'<li>'+esc(note)+'</li>').join("")+("</ul></article><div class=\"section-heading storage-group-heading\"><div><h2>"+esc(I18n.t("Evidence to review"))+"</h2><p>"+esc(I18n.t("Hash verification reads the selected group’s local bytes. No file is deleted or moved."))+"</p></div><select id=\"storage-scope\" aria-label=\""+esc(I18n.t("Storage group scope"))+"\"><option value=\"all\">"+esc(I18n.t("All candidate and reference groups"))+"</option><option value=\"cloud_local\">"+esc(I18n.t("Cloud / local groups only"))+"</option></select></div><div class=\"storage-groups\">")+audit.groups.map(group=>{
    const verified=group.verification;
    const label=verified?(verified.same_file_bytes?I18n.t("Identical bytes verified"):I18n.t("Hash differences found")):group.physical_files===1?(group.files.length>1?I18n.t("Link aliases · one physical file"):I18n.t("Repeated DB references · one file")):group.cloud_local?I18n.t("Possible cloud/local copies"):I18n.t("Possible extra files");
    const held=group.files.some(file=>file.cloud_only);
    return '<article class="wide-card storage-group"><div class="storage-group-header"><strong>'+esc(label)+'</strong><span>'+num(group.physical_files)+" "+I18n.t("physical files ·")+" "+num(group.track_ids.length)+(" "+esc(I18n.t("matched DB records"))+"</span></div><p class=\"subtle\">")+esc(group.evidence.join(" + ").replaceAll("_"," ") || I18n.t("Multiple database references to one scanned path"))+'</p>'+group.files.map(file=>'<div class="storage-file"><span>'+esc(file.kind==="local"?I18n.t("Local"):file.kind==="dropbox"?"Dropbox":"Google Drive")+'</span><code>'+esc(file.path)+'</code><span>'+esc(bytes(file.size))+(file.cloud_only?" "+I18n.t("· placeholder"):'')+'</span></div>').join("")+'<div class="storage-group-actions"><button class="button secondary small" data-storage-verify="'+esc(group.id)+'" '+(held || group.physical_files<2?'disabled':'')+(">"+esc(I18n.t("Verify this group’s file bytes"))+"</button><span class=\"subtle\">")+(held?I18n.t("Download cloud-only files outside this tool first."):verified?I18n.t("Last checked")+" "+esc(new Date(verified.created).toLocaleString(I18n.language))+'. '+I18n.t('Re-scan after file changes.'):I18n.t("Filename/size and path evidence remain unverified until hashing."))+'</span></div></article>';
  }).join("")+'</div><div class="pagination"><span>'+num(audit.group_total?storageOffset+1:0)+'–'+num(Math.min(storageOffset+30,audit.group_total))+" "+I18n.t("of")+" "+num(audit.group_total)+(" "+esc("groups")+"</span><div><button class=\"button secondary small\" id=\"storage-prev\" ")+(storageOffset?'':'disabled')+(">"+esc(I18n.t("← Previous"))+"</button><button class=\"button secondary small\" id=\"storage-next\" ")+(storageOffset+30<audit.group_total?'':'disabled')+(">"+esc(I18n.t("Next →"))+"</button></div></div>");
  $("#storage-scope").value=scope;
  $("#storage-scope").onchange=wrap(async()=>{storageOffset=0;await loadStorageAudit(id);});
  $("#storage-prev").onclick=wrap(async()=>{storageOffset=Math.max(0,storageOffset-30);await loadStorageAudit(id);});
  $("#storage-next").onclick=wrap(async()=>{storageOffset+=30;await loadStorageAudit(id);});
  $$("[data-storage-verify]").forEach(button=>button.onclick=wrap(async()=>{
    if (busy) return;
    const started=await api("/api/storage/"+id+"/verify",{method:"POST",body:JSON.stringify({group:button.dataset.storageVerify})});
    const verified=await poll(started.job);await loadStorageAudit(id);await loadStorageInfo();notify(verified.same_file_bytes?I18n.t("Identical file bytes confirmed"):I18n.t("File contents differ · review this group"));
  }));
}
$("#storage-form").onsubmit=wrap(async event=>{
  event.preventDefault();if (busy) return;
  const roots=$$(".storage-root").map(row=>({root:row.querySelector("input").value.trim(),kind:row.querySelector("select").value,recorded_prefix:row.querySelector(".storage-root-prefix").value.trim()})).filter(row=>row.root);
  const started=await api("/api/storage/scan",{method:"POST",body:JSON.stringify({roots,policy:$("#storage-policy").value,source_report:$("#storage-source-report").value})});
  const result=await poll(started.job);storageOffset=0;await loadStorageAudit(result.id);await loadStorageInfo();$("#storage-result").scrollIntoView({behavior:"smooth",block:"start"});notify(I18n.t("Folder comparison saved · no media content read"));
});
refresh().catch(error=>notify(error.message,true));
