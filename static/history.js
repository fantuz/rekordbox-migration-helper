/* Histories are immutable native snapshot data; never reconstructed from counts. */
let historyOffset=0,historyEntryOffset=0,historySelected=null;
async function loadHistory(){
  const info=await api('/api/lab');
  labSelect('#history-snapshot',info.snapshots,r=>r.label+' · '+date(r.created),I18n.t("Choose a saved snapshot"));
  if(!$('#history-snapshot').value && info.snapshots.length)$('#history-snapshot').value=info.snapshots[0].id;
  const sources=[...(info.workspace?[{id:'session',get label(){return I18n.t("Loaded XML + ZIP workspace");}}]:[]),...info.sources.map(r=>({id:r.id,label:I18n.t("Source capture ·")+" "+date(r.created)+' · '+r.label}))];
  labSelect('#history-source',sources,r=>r.label,I18n.t("Choose a native input capture"));$('#history-capture').disabled=!sources.length;
  historyOffset=0;historySelected=null;$('#history-session').hidden=true;await loadHistoryList();
}
async function loadHistoryList(){
  const snapshot=$('#history-snapshot').value;
  if(!snapshot){$('#history-status').textContent=I18n.t("Load a native ZIP workspace or capture a source folder, then save a history snapshot. XML alone does not contain the native History tab.");$('#history-list').innerHTML='';$('#history-summary').innerHTML='';return;}
  const r=await api('/api/lab/history?'+new URLSearchParams({snapshot,year:$('#history-year').value,q:$('#history-search').value,offset:historyOffset}));
  const oldYear=$('#history-year').value;
  $('#history-year').innerHTML=("<option value=\"\">"+esc(I18n.t("All session years"))+"</option>")+r.years.map(y=>'<option value="'+esc(y.year)+'">'+esc(y.year)+' · '+num(y.sessions)+(" "+esc(I18n.t("sessions"))+"</option>")).join('')+(r.unknown_dates?("<option value=\"unknown\">"+esc(I18n.t("Date not captured ·"))+" ")+num(r.unknown_dates)+'</option>':'');$('#history-year').value=oldYear;
  $('#history-status').textContent=r.available?r.note:I18n.t("History was not decoded in this snapshot. XML-only and legacy .edb inputs do not supply native session history. For older native captures, capture the original ZIP workspace or source folder again.");
  $('#history-summary').innerHTML=labSummary({saved_sessions:r.available?r.sessions_total:null,saved_entries:r.available?r.entries_total:null,track_order_captured:r.available?r.order_available:null});
  $('#history-added').innerHTML=renderAddedYears(r.addition_dates);
  $('#history-list').innerHTML=r.available?("<table><thead><tr><th>"+esc(I18n.t("Saved session"))+"</th><th>"+esc(I18n.t("Recorded date"))+"</th><th>"+esc(I18n.t("Entries"))+"</th><th></th></tr></thead><tbody>")+r.rows.map(h=>'<tr><td>'+esc(h.name)+'</td><td>'+esc(h.date || I18n.t("Unknown"))+'</td><td>'+num(h.tracks)+'</td><td><button class="button secondary small" data-history-id="'+esc(h.id)+("\">"+esc(I18n.t("Browse tracks →"))+"</button></td></tr>")).join('')+'</tbody></table>':'';
  $('#history-count').textContent=num(r.total)+(" "+I18n.t("sessions")+" \u00b7 ")+(r.total?num(historyOffset+1)+'–'+num(Math.min(historyOffset+30,r.total)):'0');
  $('#history-prev').disabled=!historyOffset;$('#history-next').disabled=historyOffset+30>=r.total;
  $$('[data-history-id]').forEach(b=>b.onclick=wrap(async()=>{historySelected=b.dataset.historyId;historyEntryOffset=0;$('#history-track-search').value='';await loadHistorySession();$('#history-session').scrollIntoView({behavior:'smooth',block:'start'});}));
}
async function loadHistorySession(){
  if(!historySelected)return;
  const params=new URLSearchParams({snapshot:$('#history-snapshot').value,offset:historyEntryOffset,q:$('#history-track-search').value});
  const r=await api('/api/lab/history/'+encodeURIComponent(historySelected)+'?'+params);$('#history-session').hidden=false;
  $('#history-session-title').textContent=r.session.name;
  $('#history-session-note').textContent=(r.session.date || I18n.t("Date unavailable"))+' · '+num(r.recorded_entries)+" "+I18n.t("recorded entries ·")+" "+num(r.missing_track_metadata)+" "+I18n.t("outside the active collection.")+" "+r.note+(r.order_available?'':" "+I18n.t("Saved track order is unavailable."));
  $('#history-tracks').innerHTML=("<table><thead><tr><th>"+esc(I18n.t("Saved order"))+"</th><th>"+esc(I18n.t("Title / artist"))+"</th><th>"+esc(I18n.t("Genre"))+"</th><th>BPM</th><th>"+esc(I18n.t("Duration"))+"</th><th>"+esc(I18n.t("Collection"))+"</th></tr></thead><tbody>")+r.rows.map(t=>'<tr><td>'+esc(t.position ?? I18n.t("Unknown"))+'</td><td><strong>'+esc(t.title)+'</strong><br>'+esc(t.artist || I18n.t("Artist unavailable"))+'</td><td>'+esc(t.genre || I18n.t("Unknown"))+'</td><td>'+esc(t.bpm ?? I18n.t("Unknown"))+'</td><td>'+esc(t.duration==null?I18n.t("Unknown"):Math.floor(t.duration/60)+':'+String(Math.round(t.duration)%60).padStart(2,'0'))+'</td><td>'+esc(t.missing_from_active_collection?I18n.t("Absent from active collection"):I18n.t("In captured collection"))+'</td></tr>').join('')+'</tbody></table>';
  $('#history-track-count').textContent=num(r.total)+(" "+I18n.t("entries")+" \u00b7 ")+(r.total?num(historyEntryOffset+1)+'–'+num(Math.min(historyEntryOffset+50,r.total)):'0');
  $('#history-tracks-prev').disabled=!historyEntryOffset;$('#history-tracks-next').disabled=historyEntryOffset+50>=r.total;
  $('#history-download').href='/api/lab/history/'+encodeURIComponent(historySelected)+'/download?'+new URLSearchParams({snapshot:$('#history-snapshot').value});
}
function renderAddedYears(data){
  const max=Math.max(1,...data.years.map(y=>y.tracks));
  return data.years.map(y=>'<div class="hist-row"><span>'+esc(y.year)+'</span><div class="hist-bar"><i style="width:'+100*y.tracks/max+'%"></i></div><b>'+num(y.tracks)+'</b></div>').join('')+'<p class="subtle">'+num(data.unknown)+(" "+esc(I18n.t("tracks without a usable date added. Recorded library addition dates differ from release years and may reflect earlier migrations."))+"</p>");
}
$('#history-capture').onclick=wrap(async()=>{
  const r=await labPost('snapshots',{source:$('#history-source').value,label:$('#history-label').value || I18n.t("Play history snapshot")});const result=await poll(r.job);await loadHistory();$('#history-snapshot').value=result.id;await loadHistoryList();notify(I18n.t("History and collection metadata saved locally"));
});
$('#history-snapshot').onchange=wrap(async()=>{historyOffset=0;historySelected=null;$('#history-session').hidden=true;await loadHistoryList();});
for(const id of ['history-find','history-year'])$('#'+id)[id==='history-year'?'onchange':'onclick']=wrap(async()=>{historyOffset=0;await loadHistoryList();});
$('#history-prev').onclick=wrap(async()=>{historyOffset=Math.max(0,historyOffset-30);await loadHistoryList();});
$('#history-next').onclick=wrap(async()=>{historyOffset+=30;await loadHistoryList();});
$('#history-track-find').onclick=wrap(async()=>{historyEntryOffset=0;await loadHistorySession();});
$('#history-tracks-prev').onclick=wrap(async()=>{historyEntryOffset=Math.max(0,historyEntryOffset-50);await loadHistorySession();});
$('#history-tracks-next').onclick=wrap(async()=>{historyEntryOffset+=50;await loadHistorySession();});
