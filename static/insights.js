/* Immutable snapshot insights. Charts, sampling and exports stay on this computer. */
const insightState={dj:{options:null,offset:0,revision:0,result:null},bubble:{options:null,offset:0,groupOffset:0,path:[],dimension:'family',revision:0,result:null},tonal:{options:null,offset:0,revision:0,result:null}};
const insightModes={most:'Most played',least:'Least played · positive counts',zero:'No recorded plays',ready:'Prepared, no recorded plays',gems:'Highly rated, underplayed',rediscover:'Rediscover past rotation',recent:'Recently added',last_used:'Recently used',preparation:'Preparation opportunities',random:'Random discovery',all:'All matching tracks'};
const insightDims={family:'Genre family',genre:'Saved genre tag',year:'Release year',added:'Addition year',initial:'Artist initial',artist:'Artist',bpm:'BPM band',rating:'Personal stars',usage:'Recorded usage',preparation:'Cue preparation',format:'Format',tone:'Saved tonality',colour:'Saved track colour',tracks:'Tracks'};
const insightUnknown=value=>value===null || value===undefined;
const insightValue=value=>insightUnknown(value)?'Unknown':num(value);
const insightDuration=value=>{if(insightUnknown(value))return 'Unknown';const seconds=Math.round(value);return Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');};
const insightOptions=(values)=>Object.entries(values).map(([key,label])=>'<option value="'+esc(key)+'">'+esc(label)+'</option>').join('');
let insightLastSnapshot='';

function insightFilterMarkup(prefix){
  const field=(name,label,input,cls='')=>'<label class="'+cls+'">'+label+input.replaceAll('@@ID@@',prefix+'-'+name)+'</label>';
  const select='<select id="@@ID@@">',input='<input id="@@ID@@"';
  return '<form id="'+prefix+'-filter-form">'+(prefix==='dj'?field('perspective','Perspective',select+insightOptions(insightModes)+'</select>'):'')+
    field('basis','Usage evidence',select+'<option value="saved">Saved play count</option><option value="history">Captured history entries</option><option value="sessions">Distinct captured sessions</option></select>')+
    field('family','Genre family',select+'<option value="">All families</option></select>')+
    field('genre','Saved genre tag',select+'<option value="">All saved tags</option></select>')+
    field('tone','Saved tonality',select+'<option value="">All keys / unknown</option></select>')+
    field('colour','Saved track colour',select+'<option value="">All colours / unknown</option></select>')+
    field('usage','Recorded usage',select+'<option value="">Any / unknown</option><option value="zero">Known zero</option><option value="low">Low · 1–3</option><option value="played">Positive count</option><option value="unknown">Unknown count</option></select>')+
    field('search','Title, artist, album or genre',input+' placeholder="Search captured tags" autocomplete="off">','insight-filter-wide')+
    field('preparation','Preparation',select+'<option value="">Any preparation</option><option value="manual">Manual cues</option><option value="mixed">Mixed manual / auto cues</option><option value="auto">Only automatic cues</option><option value="none">No cues</option><option value="unknown">Cue status unknown</option><option value="analysed">Saved as analyzed</option></select>')+
    '<div class="insight-filter-actions"><button type="submit" class="button">Apply filters</button><button type="button" class="text-button" id="'+prefix+'-filter-reset">Reset</button></div>'+
    '<details><summary>More criteria · BPM, length, stars and session dates</summary><div class="insight-extra-grid">'+
    field('bpm-min','Minimum BPM',input+' type="number" min="0" step="0.1" placeholder="Any">')+
    field('bpm-max','Maximum BPM',input+' type="number" min="0" step="0.1" placeholder="Any">')+
    field('min','Minimum minutes',input+' type="number" min="0" step="0.1" placeholder="Any">')+
    field('max','Maximum minutes',input+' type="number" min="0" step="0.1" placeholder="Any">')+
    field('rating-min','Minimum personal stars',select+'<option value="">Any / unknown</option><option value="1">1+</option><option value="2">2+</option><option value="3">3+</option><option value="4">4+</option><option value="5">5</option></select>')+
    field('from','History sessions from',input+' type="date" disabled>')+field('to','History sessions through',input+' type="date" disabled>')+
    (prefix==='dj'?field('stars','Underplayed: minimum stars',input+' type="number" min="0" max="5" value="3">')+
      field('max-plays','Underplayed: maximum plays',input+' type="number" min="0" value="3">')+
      field('days','Rediscover: days since recorded use',input+' type="number" min="1" max="36500" value="180">')+
      field('random-mode','Random selection',select+'<option value="balanced">Balance genre families</option><option value="uniform">Uniform across entries</option></select>')+
      field('sample','Random sample size',input+' type="number" min="1" max="100" value="20">')+
      field('seed','Repeatable random seed',input+' value="next-set-1" maxlength="100">'):'')+
    '</div><p class="subtle">Session dates apply only to captured-history evidence. Least played excludes zero and unknown counts. Prepared means a saved analyzed flag and at least one manual cue. Captured metadata is used; staged edits remain separate.</p></details></form>';
}
for(const prefix of ['dj','bubble','tonal']){
  $('#'+prefix+'-filters').innerHTML=insightFilterMarkup(prefix);
  $('#'+prefix+'-filter-form').onsubmit=wrap(async event=>{event.preventDefault();await applyInsightFilters(prefix);});
  $('#'+prefix+'-filter-reset').onclick=wrap(async()=>{$('#'+prefix+'-filter-form').reset();insightBasisControls(prefix);await applyInsightFilters(prefix);});
  $('#'+prefix+'-basis').onchange=()=>insightBasisControls(prefix);
  $('#'+prefix+'-family').onchange=()=>{$('#'+prefix+'-genre').value='';};
  $('#'+prefix+'-snapshot').onchange=wrap(async()=>{insightLastSnapshot=$('#'+prefix+'-snapshot').value;await insightSnapshotOptions(prefix);await applyInsightFilters(prefix);});
}
function insightBasisControls(prefix){const saved=$('#'+prefix+'-basis').value==='saved';for(const name of ['from','to'])$('#'+prefix+'-'+name).disabled=saved;}
async function insightSource(prefix){
  const info=await api('/api/lab'),select=$('#'+prefix+'-snapshot'),old=select.value || insightLastSnapshot;
  labSelect('#'+prefix+'-snapshot',info.snapshots,r=>r.label+' · '+date(r.created),'Choose a saved collection snapshot');
  if(info.snapshots.some(s=>s.id===old))select.value=old;
  if(!select.value && info.snapshots.length)select.value=info.snapshots[0].id;
  $('[data-insight-capture="'+prefix+'"]').disabled=!info.workspace;
  await insightSnapshotOptions(prefix);
}
async function insightSnapshotOptions(prefix){
  const state=insightState[prefix],identity=$('#'+prefix+'-snapshot').value;
  if(!identity){state.options=null;$('#'+prefix+'-snapshot-note').textContent='Save a collection snapshot in Library lab or capture a loaded XML + ZIP workspace. Saved snapshots remain available after temporary inputs are removed.';return;}
  const options=await api('/api/insights/options?'+new URLSearchParams({snapshot:identity}));
  if($('#'+prefix+'-snapshot').value!==identity)return;
  state.options=options;insightLastSnapshot=identity;
  const family=$('#'+prefix+'-family'),oldFamily=family.value,genre=$('#'+prefix+'-genre'),oldGenre=genre.value;
  family.innerHTML='<option value="">All families</option>'+options.families.map(g=>'<option value="'+esc(g.key)+'">'+esc(g.key)+' · '+num(g.tracks)+'</option>').join('');
  if(options.families.some(g=>g.key===oldFamily))family.value=oldFamily;
  genre.innerHTML='<option value="">All saved tags</option>'+options.genres.map(g=>'<option value="'+esc(JSON.stringify(g))+'">'+esc(g || '(blank tag)')+'</option>').join('');
  if(options.genres.some(g=>JSON.stringify(g)===oldGenre))genre.value=oldGenre;
  const tone=$('#'+prefix+'-tone'),oldTone=tone.value,colour=$('#'+prefix+'-colour'),oldColour=colour.value;
  tone.innerHTML='<option value="">All keys / unknown</option>'+options.tonalities.map(key=>'<option value="'+esc(JSON.stringify(key))+'">'+esc(key || 'Unknown / not captured')+'</option>').join('');
  if(options.tonalities.some(key=>JSON.stringify(key)===oldTone))tone.value=oldTone;
  colour.innerHTML='<option value="">All colours / unknown</option>'+options.colours.map(c=>'<option value="'+esc(JSON.stringify(c.key))+'">'+esc(c.label)+' · '+num(c.tracks)+'</option>').join('');
  if(options.colours.some(c=>JSON.stringify(c.key)===oldColour))colour.value=oldColour;
  for(const basis of ['history','sessions'])$('#'+prefix+'-basis option[value="'+basis+'"]').disabled=!options.history_available;
  if(!options.history_available)$('#'+prefix+'-basis').value='saved';insightBasisControls(prefix);
  $('#'+prefix+'-snapshot-note').textContent=num(options.entries)+' captured entries · '+(options.snapshot.captured?'Snapshot '+date(options.snapshot.captured):'Capture date unavailable')+' · '+(options.reference_date?'Rediscovery reference '+options.reference_date:'Rediscovery date unavailable')+' · '+(options.history_available?num(options.history_sessions)+' saved sessions':'Native session history unavailable')+'. Captured metadata; originals stay unchanged.';
  if(prefix==='bubble'){
    $('#bubble-genre-rules').innerHTML='<dl>'+options.genre_rules.families.map(r=>'<dt>'+esc(r.family)+'</dt><dd>'+esc(r.aliases.join(', '))+'</dd>').join('')+'</dl><p class="subtle">'+esc(options.genre_rules.fallback)+'</p>';
  }
}
async function loadDJInsights(){await insightSource('dj');await applyInsightFilters('dj');}
async function loadBubbleExplorer(){await insightSource('bubble');await applyInsightFilters('bubble');}
async function loadTonalityInsights(){await insightSource('tonal');await applyInsightFilters('tonal');}
$$('[data-insight-capture]').forEach(button=>button.onclick=wrap(async()=>{
  if(busy)return;const prefix=button.dataset.insightCapture;
  const start=await labPost('snapshots',{source:'session',label:'DJ insights · loaded collection'});const result=await poll(start.job);
  insightLastSnapshot=result.id;await insightSource(prefix);$('#'+prefix+'-snapshot').value=result.id;await insightSnapshotOptions(prefix);await applyInsightFilters(prefix);notify('Saved collection snapshot for local insights');
}));
function insightArgs(prefix){
  const args={snapshot:$('#'+prefix+'-snapshot').value,basis:$('#'+prefix+'-basis').value};
  for(const [name,key] of [['search','q'],['family','family'],['usage','usage_filter'],['preparation','preparation'],['bpm-min','bpm_min'],['bpm-max','bpm_max'],['min','min'],['max','max'],['rating-min','rating_min']]){
    const value=$('#'+prefix+'-'+name).value;if(value!=='')args[key]=value;
  }
  if($('#'+prefix+'-genre').value!=='')args.genre=JSON.parse($('#'+prefix+'-genre').value);
  for(const name of ['tone','colour'])if($('#'+prefix+'-'+name).value!=='')args[name]=JSON.parse($('#'+prefix+'-'+name).value);
  if(args.basis!=='saved')for(const name of ['from','to'])if($('#'+prefix+'-'+name).value)args[name]=$('#'+prefix+'-'+name).value;
  if(prefix==='dj')for(const [name,key] of [['perspective','perspective'],['stars','stars'],['max-plays','max_plays'],['days','days'],['random-mode','random_mode'],['sample','sample'],['seed','seed']])args[key]=$('#dj-'+name).value;
  else {if(prefix==='bubble')args.path=JSON.stringify(insightState.bubble.path);args.perspective='all';}
  return args;
}
async function applyInsightFilters(prefix){
  const state=insightState[prefix];state.offset=0;
  if(prefix==='bubble'){state.path=[];state.groupOffset=0;$('#bubble-track-detail').hidden=true;await loadBubbleData();}
  else if(prefix==='tonal')await loadTonalData();
  else await loadDJData();
}
function insightEvidence(context){
  return context.basis_label+(context.selected_sessions!==null?' · '+num(context.selected_sessions)+' sessions'+(context.from?' from '+context.from:'')+(context.to?' through '+context.to:''):' · Lifetime scope of the saved counter; reset history may be incomplete')+
    (context.history_unresolved_entries && context.basis!=='saved'?' · '+num(context.history_unresolved_entries)+' history entries outside the captured collection are excluded':'')+
    (context.history_undated_entries && context.basis!=='saved'?' · '+num(context.history_undated_entries)+' undated entries are excluded when a session-date filter is active':'');
}
function insightCards(stats,bubble=false){
  const cards=bubble?[
    ['Tracks in branch',num(stats.entries),'Individual library entries'],['Recorded usage',num(stats.recorded_plays),num(stats.known_usage)+' known counters'],
    ['Full track duration',num(Math.round(stats.full_track_seconds/360)/10)+' h','Sum of lengths, not time played'],['Unknown usage',num(stats.unknown_usage),'Kept separate from zero']]:[
    ['Tracks in this view',num(stats.entries),'Within the selected perspective'],['Recorded usage',num(stats.recorded_plays),num(stats.known_usage)+' known counters'],
    ['No recorded plays',num(stats.zero_usage),'In the selected evidence'],['Unknown usage',num(stats.unknown_usage),'Kept separate from zero'],['With personal stars',num(stats.rated),'Saved ratings above zero']];
  return cards.map(([title,value,note])=>'<div><span>'+esc(title)+'</span><strong>'+esc(value)+'</strong><small>'+esc(note)+'</small></div>').join('');
}
function insightTempoLine(stats){
  const decimal=v=>insightUnknown(v)?'Unknown':Number(v).toLocaleString(undefined,{maximumFractionDigits:1});
  return [['Mean BPM',decimal(stats.bpm_mean)],['Median BPM',decimal(stats.bpm_median)],['BPM range',insightUnknown(stats.bpm_min)?'Unknown':decimal(stats.bpm_min)+'–'+decimal(stats.bpm_max)],['Average length',insightDuration(stats.duration_mean)],['Median length',insightDuration(stats.duration_median)]].map(([label,value])=>'<div><span>'+esc(label)+'</span><b>'+esc(value)+'</b></div>').join('')+'<small>'+num(stats.bpm_known)+' known BPM · '+num(stats.bpm_unknown)+' unknown. Each entry has equal weight; full track length is not time played.</small>';
}
function insightTrackTable(rows,basis){
  if(!rows.length)return '<p class="subtle">No entries match this perspective and these filters. Unknown usage, dates and preparation are not silently treated as known zero.</p>';
  return '<table><thead><tr><th>Track / artist</th><th>Saved genre</th><th>'+esc(basis)+'</th><th>Personal stars</th><th>Preparation</th><th>BPM / length</th><th>Recorded dates</th></tr></thead><tbody>'+rows.map(t=>'<tr><td><button class="insight-track-title text-button" data-insight-open="'+esc(t.id)+'">'+esc(t.title || 'Untitled track')+'</button><span class="insight-track-artist">'+esc(t.artist || 'Artist unavailable')+'</span>'+(t.reason && !['All matching tracks','Most played','Least played · positive counts'].includes(t.reason)?'<small class="insight-reason">'+esc(t.reason)+'</small>':'')+'</td><td>'+esc(t.genre || '(blank)')+'<span class="insight-track-note">'+esc(t.family)+'</span></td><td><span class="insight-play-value">'+esc(insightValue(t.plays))+'</span></td><td>'+esc(t.rating===null?'Unknown':t.rating===0?'Unrated':t.rating+' / 5')+'</td><td>'+esc({manual:'Manual cues',mixed:'Manual + auto',auto:'Only auto',none:'No cues',unknown:'Unknown'}[t.preparation])+'<span class="insight-track-note">'+insightValue(t.manual_cues)+' manual · '+(t.analysed===true?'Analyzed':t.analysed===false?'Not marked analyzed':'Analysis unknown')+'</span></td><td>'+esc(insightValue(t.bpm))+' BPM<span class="insight-track-note">'+esc(insightDuration(t.duration))+'</span></td><td>Last evidence: '+esc(t.evidence_last_date || 'Unknown')+(t.evidence_date_after_snapshot?'<span class="insight-track-note">Date is after snapshot · review</span>':'')+'<span class="insight-track-note">Added: '+esc(t.date_added || 'Unknown')+'</span></td></tr>').join('')+'</tbody></table>';
}
async function loadDJData(){
  const state=insightState.dj,revision=++state.revision;if(!state.options){state.result=null;$('#dj-tracks').innerHTML='<p>Save or choose a collection snapshot to begin.</p>';$('#dj-summary').innerHTML='';$('#dj-balance').innerHTML='';$('#dj-evidence').textContent='';$('#dj-csv').hidden=true;$('#dj-save-report').disabled=true;return;}
  const args={...insightArgs('dj'),offset:state.offset};$('#dj-tracks').classList.add('insight-loading');
  try{
    const r=await api('/api/insights/tracks?'+new URLSearchParams(args));if(revision!==state.revision)return;state.result=r;
    $('#dj-result-title').textContent=r.title;$('#dj-evidence').textContent=insightEvidence(r.context);
    $('#dj-summary').innerHTML=insightCards(r.result_stats);$('#dj-tempo-stats').innerHTML=insightTempoLine(r.result_stats);$('#dj-tracks').innerHTML=insightTrackTable(r.rows,r.context.basis_label);bindTrackDetails('#dj-tracks',args.snapshot);
    $('#dj-result-note').textContent=num(r.scope_stats.entries)+' entries in the filtered collection · '+num(r.eligible)+' eligible for this perspective'+(r.seed?' · '+num(r.total)+' sampled using seed “'+r.seed+'”':'')+(r.scope_stats.top_ten_play_share!==null?' · Top ten entries account for '+r.scope_stats.top_ten_play_share+'% of recorded usage in that filtered collection.':'.')+(r.perspective==='rediscover' && !r.rediscovery_date_available?' A reliable snapshot reference date is unavailable.':'');
    $('#dj-count').textContent=num(r.total)+' entries · '+(r.total?num(state.offset+1)+'–'+num(Math.min(state.offset+50,r.total)):'0');$('#dj-prev').disabled=!state.offset;$('#dj-next').disabled=state.offset+50>=r.total;
    $('#dj-csv').hidden=false;$('#dj-csv').href='/api/insights/tracks.csv?'+new URLSearchParams(insightArgs('dj'));$('#dj-save-report').disabled=false;
    $$('[data-dj-preset]').forEach(b=>b.classList.toggle('selected',b.dataset.djPreset===r.perspective));renderGenreBalance();
  }finally{if(revision===state.revision)$('#dj-tracks').classList.remove('insight-loading');}
}
function renderGenreBalance(){
  const r=insightState.dj.result;if(!r)return;const groups=r.genre_balance.slice(),order=$('#dj-balance-order').value;
  if(order==='gap')groups.sort((a,b)=>(b.exploration_gap ?? -Infinity)-(a.exploration_gap ?? -Infinity) || b.entries-a.entries);
  if(order==='collection')groups.sort((a,b)=>b.entries-a.entries);
  $('#dj-balance').innerHTML=groups.slice(0,10).map(g=>'<button class="balance-row" data-balance-family="'+esc(g.family)+'"><span>'+esc(g.family)+'<b>'+num(g.entries)+'</b></span><div class="balance-rails"><i class="balance-library" style="width:'+Math.min(100,g.library_share || 0)+'%"></i><i class="balance-plays" style="width:'+Math.min(100,g.play_share || 0)+'%"></i></div><small>'+num(g.recorded_plays)+' recorded · '+num(g.known_usage)+' known / '+num(g.entries)+' entries'+(order==='gap'?(g.exploration_gap===null?' · insufficient play data':' · gap '+g.exploration_gap.toFixed(1)+' percentage points'):'')+'</small></button>').join('') || '<p class="subtle">No groups in this scope.</p>';
  $$('[data-balance-family]').forEach(b=>b.onclick=wrap(async()=>{$('#dj-family').value=b.dataset.balanceFamily;$('#dj-genre').value='';await applyInsightFilters('dj');}));
}
$$('[data-dj-preset]').forEach(b=>b.onclick=wrap(async()=>{
  $('#dj-perspective').value=b.dataset.djPreset;
  if(b.dataset.djPreset==='random')$('#dj-seed').value=Array.from(crypto.getRandomValues(new Uint32Array(2))).map(v=>v.toString(16)).join('-');
  await applyInsightFilters('dj');
}));
$('#dj-perspective').onchange=wrap(()=>applyInsightFilters('dj'));
$('#dj-prev').onclick=wrap(async()=>{insightState.dj.offset=Math.max(0,insightState.dj.offset-50);await loadDJData();});
$('#dj-next').onclick=wrap(async()=>{insightState.dj.offset+=50;await loadDJData();});
$('#dj-balance-order').onchange=renderGenreBalance;
$('#dj-save-report').onclick=wrap(async()=>{
  const args=insightArgs('dj'),r=await api('/api/insights/report',{method:'POST',body:JSON.stringify({snapshot:args.snapshot,filters:args})});
  $('#dj-saved-report').innerHTML='Saved locally with '+num(r.rows)+' ranked rows. <a class="text-button" href="'+esc(r.download)+'">Download JSON ↓</a>';notify('Insight report retained with your Library lab reports');
});

function bubbleDimensionOptions(){
  const state=insightState.bubble,used=new Set(state.path.map(p=>p.dimension));
  if(used.has(state.dimension))state.dimension=Object.keys(insightDims).find(k=>!used.has(k)) || 'tracks';
  $('#bubble-dimension').innerHTML=Object.entries(insightDims).map(([key,label])=>'<option value="'+key+'"'+(used.has(key)?' disabled':'')+'>'+esc(label)+'</option>').join('');$('#bubble-dimension').value=state.dimension;
}
async function loadBubbleData(){
  const state=insightState.bubble,revision=++state.revision;if(!state.options){state.result=null;$('#bubble-evidence').textContent='Save or choose a collection snapshot to draw the map.';$('#bubble-svg').disabled=true;$('#library-bubbles').replaceChildren();for(const id of ['bubble-groups','bubble-summary','bubble-tracks','bubble-breadcrumbs'])$('#'+id).innerHTML='';$('#bubble-csv').hidden=true;return;}
  bubbleDimensionOptions();const args=insightArgs('bubble');$('#library-bubbles').setAttribute('aria-busy','true');
  try{
    const [r,tracks]=await Promise.all([api('/api/insights/bubbles?'+new URLSearchParams({...args,dimension:state.dimension,metric:$('#bubble-metric').value,group_offset:state.groupOffset})),api('/api/insights/tracks?'+new URLSearchParams({...args,offset:state.offset}))]);
    if(revision!==state.revision)return;state.result=r;
    $('#bubble-summary').innerHTML=insightCards(r.summary,true);$('#bubble-evidence').textContent=insightEvidence(r.context);
    renderBubbleBreadcrumbs(r.context.breadcrumbs);renderColourLegend();renderBubbleMap();
    $('#bubble-tracks').innerHTML=insightTrackTable(tracks.rows,tracks.context.basis_label);$('#bubble-track-count').textContent=num(tracks.total)+' entries · '+(tracks.total?num(state.offset+1)+'–'+num(Math.min(state.offset+50,tracks.total)):'0');
    bindTrackDetails('#bubble-tracks',args.snapshot);
    $('#bubble-tracks-prev').disabled=!state.offset;$('#bubble-tracks-next').disabled=state.offset+50>=tracks.total;
    $('#bubble-csv').hidden=false;$('#bubble-csv').href='/api/insights/tracks.csv?'+new URLSearchParams(args);
  }finally{if(revision===state.revision)$('#library-bubbles').removeAttribute('aria-busy');}
}
function renderBubbleBreadcrumbs(crumbs){
  $('#bubble-breadcrumbs').innerHTML='<button data-bubble-back="0">Collection</button>'+crumbs.map((p,i)=>'<span>›</span><button data-bubble-back="'+(i+1)+'">'+esc(p.dimension==='colour'?colourDisplayLabel(p.key,p.label):p.label)+'</button>').join('');
  $$('[data-bubble-back]').forEach(b=>b.onclick=wrap(async()=>{const s=insightState.bubble,n=Number(b.dataset.bubbleBack);s.dimension=s.path[n]?.dimension || s.dimension;s.path=s.path.slice(0,n);s.offset=0;s.groupOffset=0;$('#bubble-track-detail').hidden=true;await loadBubbleData();}));
}
const bubblePalette=['#a8d9d0','#b8d8ee','#c7d3f0','#c2e2bd','#b9dfe6','#d7c9ed','#9fcedf','#ccded0','#bed0e1','#b5d4bf'];
function bubbleColor(group){
  const mode=$('#bubble-color').value;
  if(mode==='saved')return group.color_hex || '#d7e1e8';
  if(mode==='preparation')return group.manual_cue_percent===null?'#d7e1e8':group.manual_cue_percent>=75?'#9fd5c5':group.manual_cue_percent>=25?'#b9ddec':'#d1e1f3';
  if(mode==='rating')return group.mean_personal_rating===null?'#d7e1e8':group.mean_personal_rating>=4?'#a6d9c7':group.mean_personal_rating>=2?'#bad7ed':'#d1cae6';
  let h=2166136261;for(const c of group.key || group.label)h=Math.imul(h^c.charCodeAt(0),16777619);return bubblePalette[(h>>>0)%bubblePalette.length];
}
function bubbleTextColor(group){
  if($('#bubble-color').value!=='saved')return '#17344c';
  const hex=bubbleColor(group).replace('#',''),values=[0,2,4].map(i=>parseInt(hex.slice(i,i+2),16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);
  const luminance=values[0]*.2126+values[1]*.7152+values[2]*.0722;
  return (luminance+.05)/.05>=1.05/(luminance+.05)?'#000000':'#ffffff';
}
function bubbleWeight(value,metric){return metric==='duration'?(value<3600?num(Math.round(value/60))+' min':num(Math.round(value/360)/10)+' h'):num(value);}
function bubbleSelected(group){
  const r=insightState.bubble.result;
  $('#bubble-selected').innerHTML='<h4>'+esc(group.label)+'</h4><p><b>'+esc(bubbleWeight(group.value,r.metric))+'</b> · '+esc(r.metric_label)+'</p><p>'+num(group.entries)+' entries · '+num(group.unknown_usage)+' unknown usage counts · '+num(group.weight_unknown_entries)+' unknown size inputs</p><p>Mean BPM: '+esc(group.bpm_mean===null?'Unknown':group.bpm_mean.toFixed(1))+'</p><small>Saved tags behind this category'+(group.saved_tags_total>8?' · first 8 of '+num(group.saved_tags_total):'')+'</small><ul>'+group.saved_tags.map(t=>'<li>'+esc(t.tag)+' · '+num(t.tracks)+'</li>').join('')+'</ul>';
}
const svgNode=(name,attrs={})=>{const element=document.createElementNS('http://www.w3.org/2000/svg',name);for(const [key,value] of Object.entries(attrs))element.setAttribute(key,value);return element;};
function renderBubbleMap(){
  const state=insightState.bubble,r=state.result;if(!r)return;const svg=$('#library-bubbles');svg.replaceChildren();
  if(r.dimension==='colour')for(const group of r.groups){group.original_label=group.original_label || group.label;group.label=colourDisplayLabel(group.key,group.original_label);}
  const title=svgNode('title');title.textContent='Library bubbles · '+insightDims[r.dimension];svg.append(title);
  const positive=r.groups.filter(g=>g.value>0);
  if(positive.length){
    const root=d3.hierarchy({children:positive}).sum(d=>d.value || 0).sort((a,b)=>b.value-a.value);
    d3.pack().size([940,680]).padding(10)(root);
    for(const node of root.children || []){
      const group=node.data,g=svgNode('g',{class:'bubble-node',transform:'translate('+node.x+','+node.y+')',role:'button',tabindex:'0','aria-label':group.label+', '+bubbleWeight(group.value,r.metric)+', '+group.entries+' entries. '+(r.dimension==='tracks'?'Inspect track':'Drill down')});
      const circle=svgNode('circle',{r:node.r,fill:bubbleColor(group),stroke:'#ffffff','stroke-width':2});g.append(circle);
      const tooltip=svgNode('title');tooltip.textContent=group.label+' · '+num(group.entries)+' entries · '+num(group.recorded_plays)+' recorded usage';g.append(tooltip);
      if(node.r>=20){
        const font=Math.max(10,Math.min(23,node.r/4.5)),chars=Math.max(6,Math.floor(node.r*1.6/(font*.56))),label=group.label;
        const lines=label.length<=chars?[label]:[label.slice(0,chars),label.slice(chars,chars*2-1)+(label.length>chars*2-1?'…':'')];
        const text=svgNode('text',{'text-anchor':'middle','font-family':'system-ui,sans-serif','font-size':font,fill:bubbleTextColor(group)});
        lines.forEach((line,i)=>{const span=svgNode('tspan',{x:0,y:(i-(lines.length-1)/2)*font*1.15-font*.45});span.textContent=line;text.append(span);});
        const count=svgNode('tspan',{x:0,y:font*(lines.length>1?1.7:1.1),'font-size':font*1.12,'font-weight':'700',class:'bubble-number'});count.textContent=bubbleWeight(group.value,r.metric);text.append(count);g.append(text);
      }
      g.addEventListener('mouseenter',()=>bubbleSelected(group));g.addEventListener('focus',()=>bubbleSelected(group));
      g.addEventListener('click',wrap(()=>drillBubble(group)));
      g.addEventListener('keydown',wrap(async event=>{if(event.key==='Enter' || event.key===' '){event.preventDefault();await drillBubble(group);$('#bubble-breadcrumbs button:last-child')?.focus();}}));svg.append(g);
    }
  }else{const message=svgNode('text',{x:470,y:320,'text-anchor':'middle',fill:'currentColor','font-size':20});message.textContent=r.groups.length?'No positive weights · try sizing by track count':'No entries in this branch';svg.append(message);}
  $('#bubble-svg').disabled=!r.groups.length;
  $('#bubble-group-title').textContent=insightDims[r.dimension];$('#bubble-group-count').textContent=num(r.groups_total)+' categories · '+(r.groups_total?num(r.group_offset+1)+'–'+num(Math.min(r.group_offset+60,r.groups_total)):'0');
  $('#bubble-groups').innerHTML=r.groups.map((g,i)=>'<button class="bubble-group-button" data-bubble-index="'+i+'"><i class="bubble-swatch" style="background:'+bubbleColor(g)+'"></i><span>'+esc(g.label)+'</span><b>'+esc(bubbleWeight(g.value,r.metric))+'</b></button>').join('');
  $$('[data-bubble-index]').forEach(button=>{const group=r.groups[Number(button.dataset.bubbleIndex)];button.onclick=wrap(()=>drillBubble(group));button.onmouseenter=()=>bubbleSelected(group);button.onfocus=()=>bubbleSelected(group);});
  $('#bubble-groups-prev').disabled=!r.group_offset;$('#bubble-groups-next').disabled=r.group_offset+60>=r.groups_total;
  $('#bubble-map-note').textContent='Area: '+r.metric_label+'. Showing '+num(r.groups.length)+' of '+num(r.groups_total)+' categories'+(r.groups_total>60?' on this page; use Next groups to see the rest':'')+'. '+num(r.zero_weight_groups)+' categories have zero/unknown weight and remain in the list. Compare circle areas within this page; full track length is not time played.';
  $('#bubble-color-note').textContent={group:'Color identifies categories. Exact counts remain in the list.',preparation:'Manual-cue coverage among entries with known cue status: blue <25%, pale cyan 25–74%, green 75%+. Gray = unknown. Analysis readiness is separate.',rating:'Mean personal stars among rated entries: lavender <2, blue 2–3.99, green 4+. Gray = no captured ratings. Unrated zeros are excluded.',saved:'Saved track colour. Gray = no single known colour for this category. Native RGB may use the standard palette inferred from SortKey. Track colours have personal meanings and are separate from cue colours.'}[$('#bubble-color').value];
  if(r.groups.length)bubbleSelected(r.groups[0]);
}
async function drillBubble(group){
  const state=insightState.bubble,dimension=state.dimension;
  if(dimension==='tracks'){
    await openTrackDetails($('#bubble-snapshot').value,group.key);return;
  }
  if(state.path.length>=8)throw new Error('This branch has reached eight levels. Use a breadcrumb to change direction.');
  state.path.push({dimension,key:group.key});const used=new Set(state.path.map(p=>p.dimension));
  const preferred={family:'genre',genre:'initial',initial:'artist',artist:'tracks',year:'genre',added:'genre',bpm:'genre',rating:'genre',usage:'genre',preparation:'genre',format:'genre',tone:'genre',colour:'family'}[dimension];
  state.dimension=[preferred,'family','genre','initial','artist','tracks'].find(d=>d && !used.has(d)) || 'tracks';state.groupOffset=0;state.offset=0;$('#bubble-track-detail').hidden=true;await loadBubbleData();
}
$('#bubble-dimension').onchange=wrap(async()=>{insightState.bubble.dimension=$('#bubble-dimension').value;insightState.bubble.groupOffset=0;await loadBubbleData();});
$('#bubble-metric').onchange=wrap(()=>loadBubbleData());$('#bubble-color').onchange=()=>{renderColourLegend();renderBubbleMap();};
$('#bubble-reset').onclick=wrap(async()=>{insightState.bubble.path=[];insightState.bubble.dimension='family';insightState.bubble.offset=0;insightState.bubble.groupOffset=0;$('#bubble-track-detail').hidden=true;await loadBubbleData();});
$('#bubble-groups-prev').onclick=wrap(async()=>{insightState.bubble.groupOffset=Math.max(0,insightState.bubble.groupOffset-60);await loadBubbleData();});
$('#bubble-groups-next').onclick=wrap(async()=>{insightState.bubble.groupOffset+=60;await loadBubbleData();});
$('#bubble-tracks-prev').onclick=wrap(async()=>{insightState.bubble.offset=Math.max(0,insightState.bubble.offset-50);await loadBubbleData();});
$('#bubble-tracks-next').onclick=wrap(async()=>{insightState.bubble.offset+=50;await loadBubbleData();});
$('#bubble-svg').onclick=()=>{
  const svg=$('#library-bubbles').cloneNode(true);svg.setAttribute('xmlns','http://www.w3.org/2000/svg');svg.setAttribute('width','940');svg.setAttribute('height','680');svg.removeAttribute('aria-busy');
  const description=svgNode('desc');description.textContent='Static visible bubble-map snapshot. '+$('#bubble-map-note').textContent+' Branch: '+$('#bubble-breadcrumbs').textContent+'. '+$('#bubble-color-note').textContent;svg.prepend(description);
  const content=new XMLSerializer().serializeToString(svg),blob=new Blob([content],{type:'image/svg+xml;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='library-bubbles.svg';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};

function colourDisplayLabel(key,fallback){
  const options=insightState.bubble.options,colour=options?.colours.find(c=>c.key===key),meaning=colour && options.colour_meanings?.[colour.hex || colour.key];
  return meaning?meaning+' · '+fallback:fallback;
}
function renderColourLegend(){
  const options=insightState.bubble.options;if(!options)return;
  $('#bubble-colour-meanings').hidden=!($('#bubble-color').value==='saved' || insightState.bubble.dimension==='colour' || insightState.bubble.path.some(p=>p.dimension==='colour'));
  $('#colour-meanings-fields').innerHTML=options.colours.filter(c=>c.status==='assigned').map(c=>'<label>'+esc(c.label)+' · '+num(c.tracks)+' entries<input data-colour-legend="'+esc(c.hex || c.key)+'" value="'+esc(options.colour_meanings?.[c.hex || c.key] || '')+'" maxlength="120" placeholder="Optional: opener, banger, finale…"></label>').join('') || '<p class="subtle">No assigned colours were captured. Unknown colour data needs a fresh native capture or an XML containing Colour fields.</p>';
}
$('#colour-meanings-form').onsubmit=wrap(async event=>{
  event.preventDefault();const meanings=Object.fromEntries($$('[data-colour-legend]').map(input=>[input.dataset.colourLegend,input.value]));
  const r=await api('/api/insights/colour-meanings',{method:'POST',body:JSON.stringify({snapshot:$('#bubble-snapshot').value,meanings})});insightState.bubble.options.colour_meanings=r.meanings;
  $('#colour-meanings-state').textContent=r.note;renderBubbleMap();renderBubbleBreadcrumbs(insightState.bubble.result.context.breadcrumbs);
});
$('#bubble-colour-cloud').onclick=wrap(async()=>{const s=insightState.bubble;s.path=[];s.dimension='colour';s.offset=0;s.groupOffset=0;$('#bubble-color').value='saved';await loadBubbleData();});

async function loadTonalData(){
  const state=insightState.tonal,revision=++state.revision;if(!state.options){$('#tonal-evidence').textContent='Choose or save a collection snapshot to inspect its keys and tempo.';return;}
  const args=insightArgs('tonal'),[r,tracks]=await Promise.all([api('/api/insights/tonality?'+new URLSearchParams(args)),api('/api/insights/tracks?'+new URLSearchParams({...args,offset:state.offset}))]);
  if(revision!==state.revision)return;state.result=r;
  $('#tonal-evidence').textContent=insightEvidence(r.context);$('#tonal-tempo-stats').innerHTML=insightTempoLine(r.summary);
  $('#tonal-summary').innerHTML=[['Tracks',r.summary.entries],['Known tonality',r.summary.tonality_known],['Unknown tonality',r.summary.tonality_unknown],['Colour tagged',r.summary.coloured],['Colour not captured',r.summary.colour_unknown]].map(([label,value])=>'<div><span>'+esc(label)+'</span><strong>'+num(value)+'</strong></div>').join('');
  const max=Math.max(1,...r.bpm_histogram.map(b=>b.tracks));
  $('#tonal-histogram').innerHTML=r.bpm_histogram.map((b,i)=>'<button class="tempo-band" data-tempo-band="'+i+'"><span>'+esc(b.minimum+'–'+b.maximum)+'</span><span class="hist-bar"><i style="width:'+100*b.tracks/max+'%"></i></span><b>'+num(b.tracks)+'</b></button>').join('')+'<p class="subtle">'+num(r.summary.bpm_unknown)+' entries without known BPM.'+(r.bpm_bands_total>200?' First 200 bands shown; narrow the BPM range to inspect unusual values.':'')+'</p>';
  $('#tonal-keys').innerHTML='<table><thead><tr><th>Saved tonality</th><th>Entries</th><th>Recorded usage</th><th>Mean / median BPM</th></tr></thead><tbody>'+r.tonalities.map((key,i)=>'<tr><td><button class="text-button" data-tonality-index="'+i+'">'+esc(key.label)+'</button></td><td>'+num(key.entries)+'</td><td>'+num(key.recorded_plays)+'</td><td>'+esc(key.bpm_mean===null?'Unknown':key.bpm_mean.toFixed(1))+' / '+esc(key.bpm_median===null?'Unknown':Number(key.bpm_median).toFixed(1))+'</td></tr>').join('')+'</tbody></table>';
  $('#tonal-note').textContent=r.note;$('#tonal-tracks').innerHTML=insightTrackTable(tracks.rows,tracks.context.basis_label);bindTrackDetails('#tonal-tracks',args.snapshot);
  $('#tonal-count').textContent=num(tracks.total)+' entries · '+(tracks.total?num(state.offset+1)+'–'+num(Math.min(state.offset+50,tracks.total)):'0');$('#tonal-prev').disabled=!state.offset;$('#tonal-next').disabled=state.offset+50>=tracks.total;
  $('#tonal-csv').hidden=false;$('#tonal-csv').href='/api/insights/tracks.csv?'+new URLSearchParams(args);
  $$('[data-tonality-index]').forEach(b=>b.onclick=wrap(async()=>{$('#tonal-tone').value=JSON.stringify(r.tonalities[Number(b.dataset.tonalityIndex)].tonality);await applyInsightFilters('tonal');}));
  $$('[data-tempo-band]').forEach(b=>b.onclick=wrap(async()=>{const band=r.bpm_histogram[Number(b.dataset.tempoBand)];$('#tonal-bpm-min').value=band.minimum;$('#tonal-bpm-max').value=band.maximum;await applyInsightFilters('tonal');}));
}
$('#tonal-prev').onclick=wrap(async()=>{insightState.tonal.offset=Math.max(0,insightState.tonal.offset-50);await loadTonalData();});
$('#tonal-next').onclick=wrap(async()=>{insightState.tonal.offset+=50;await loadTonalData();});
