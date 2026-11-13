"use strict";
(() => {
  const data=window.METADATA_SNAPSHOT, $=s=>document.querySelector(s);
  if (!data || data.schema!==1) {$("#scope-note").textContent=I18n.t("This file has no supported metadata snapshot. Generate an explorer from Library Workbench.");return;}
  let number=new Intl.NumberFormat(I18n.language), collator=new Intl.Collator(I18n.language,{numeric:true,sensitivity:"base"});
  const pages={get index(){return I18n.t("Overview");},get tracks(){return I18n.t("Tracks");},get genres(){return I18n.t("Genres");},get years(){return I18n.t("Release years");},get added(){return I18n.t("Added by year");},get artists(){return I18n.t("Artists");},get albums(){return I18n.t("Albums");},get bpm(){return I18n.t("BPM ranges");},get ratings(){return I18n.t("Ratings");},get duration(){return I18n.t("Duration");},get formats(){return I18n.t("Formats");},get playlists(){return I18n.t("Playlists");},get tonality(){return I18n.t("Tonality");},get colours(){return I18n.t("Track colours");}};
  const facet={genres:"genre",years:"year",added:"added_year",artists:"artist",albums:"album",bpm:"bpm_group",ratings:"rating_group",duration:"duration_group",formats:"format",playlists:"playlist",tonality:"tonality",colours:"color_group"};
  const bpmBins=[[80,'Under 80'],[100,"80–99.99"],[120,"100–119.99"],[130,"120–129.99"],[140,"130–139.99"],[160,"140–159.99"],[180,"160–179.99"],[Infinity,"180+"]];
  const durationBins=[[60,'Under 1 min'],[180,'1–2.99 min'],[360,'3–5.99 min'],[600,'6–9.99 min'],[1800,'10–29.99 min'],[Infinity,'30 min+']];
  const missing="missing", empty=v=>v===null || v===undefined || v==="", folded=v=>String(v).normalize("NFKC").toLocaleLowerCase();
  const canonical=v=>empty(v)?missing:"v:"+folded(v), label=v=>empty(v)?I18n.t("Unknown / not captured"):String(v);
  const totalDuration=rows=>rows.reduce((s,r)=>s+(r.duration || 0),0);
  function duration(s){if(empty(s))return I18n.t("Unknown");const n=Math.round(s);return Math.floor(n/60)+":"+String(n%60).padStart(2,"0");}
  function hours(s){return number.format(Math.round(s/3600*10)/10)+" h";}
  function rating(v){return empty(v)?I18n.t("Unknown"):v===0?I18n.t("Unrated"):v+" / 5";}
  const tracks=data.rows.map(row=>Object.fromEntries(data.columns.map((name,i)=>[name,row[i]])));
  for(const r of tracks){
    r.added_year=String(r.date_added || '').match(/^([1-9]\d{3})(?:\D|\d{4}|$)/)?.[1] || null;
    r.color_group=r.color_status==='assigned'?(r.color_name || r.color_hex || 'Assigned colour'):r.color_status==='unassigned'?'No assigned colour':null;
    r.bpm_group=empty(r.bpm)?null:bpmBins.find(([max])=>r.bpm<max)[1];
    r.duration_group=empty(r.duration)?null:durationBins.find(([max])=>r.duration<max)[1];
    r.rating_group=empty(r.rating)?null:r.rating===0?'Unrated':r.rating+" stars";
    r._search=folded([r.id,r.title,r.artist,r.album,r.genre,r.label,r.composer].join(" "));
  }
  let state={}, view="index", page=0, pageSize=50, sortField="", ascending=true, shown=[], tableColumns=[];
  const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
  const single=document.body.dataset.mode==="single";
  function href(next, filters=state){const params=new URLSearchParams(filters);if(single)params.set("view",next);return (single?"":next+".html")+(params.size?"#"+params.toString():"");}
  function go(next,filters){location.href=href(next,filters);}
  function applyFilters(){
    const next={...state};
    for(const [id,key] of [["search","q"],["rating-filter","rating"],["format-filter","format_filter"],["bpm-min","bpm_min"],["bpm-max","bpm_max"],["duration-min","duration_min"],["duration-max","duration_max"]]){
      const value=$("#"+id).value.trim();if(value)next[key]=value;else delete next[key];
    }
    if(single)next.view=view;
    const hash=new URLSearchParams(next).toString();
    if(location.hash.slice(1)===hash){page=0;render();}else location.hash=hash;
  }
  function filtered(){
    const ranges=[["bpm_min","bpm_max"],["duration_min","duration_max"]];
    const invalid=ranges.some(([a,b])=>(state[a]!==undefined && (!Number.isFinite(Number(state[a])) || Number(state[a])<0)) || (state[b]!==undefined && (!Number.isFinite(Number(state[b])) || Number(state[b])<0)) || (state[a]!==undefined && state[b]!==undefined && Number(state[a])>Number(state[b])));
    $("#filter-error").hidden=!invalid;$("#filter-error").textContent=I18n.t("Use non-negative limits, with the minimum no greater than the maximum.");
    if(invalid)return [];
    const query=folded(state.q || "");
    return tracks.filter(r=>{
      if(query && !r._search.includes(query))return false;
      for(const field of Object.values(facet))if(state[field]!==undefined){
        const values=field==="playlist"?(r.playlists.length?r.playlists:[null]):[r[field]];
        if(!values.some(v=>canonical(v)===state[field]))return false;
      }
      if(state.rating && (state.rating==="unrated"?r.rating!==0:state.rating==="unknown"?!empty(r.rating):r.rating!==Number(state.rating)))return false;
      if(state.format_filter && r.format!==state.format_filter)return false;
      for(const [key,field,scale,lower] of [["bpm_min","bpm",1,true],["bpm_max","bpm",1,false],["duration_min","duration",60,true],["duration_max","duration",60,false]])if(state[key]!==undefined){
        if(empty(r[field]) || (lower?r[field]<Number(state[key])*scale:r[field]>Number(state[key])*scale))return false;
      }
      return true;
    });
  }
  function groups(rows,field){
    const result=new Map();
    for(const r of rows){const values=field==="playlist"?(r.playlists.length?r.playlists:[null]):[r[field]];
      for(const value of values){const key=canonical(value),derived=['bpm_group','duration_group'].includes(field)||field==='rating_group'&&value==='Unrated';if(!result.has(key))result.set(key,{key,label:derived&&!empty(value)?I18n.t(String(value)):label(value),count:0,duration:0,rated:0,plays:0,bpm_total:0,bpm_count:0});
        const g=result.get(key);g.count++;g.duration+=r.duration || 0;g.rated+=r.rating>0;g.plays+=r.play_count || 0;if(!empty(r.bpm)){g.bpm_total+=r.bpm;g.bpm_count++;}
      }
    }
    return Array.from(result.values()).map(g=>({...g,average_bpm:g.bpm_count?Math.round(g.bpm_total/g.bpm_count*10)/10:null}));
  }
  function details(r){
    $("#detail-title").textContent=r.title || I18n.t("Untitled track");const dl=$("#detail-fields");dl.replaceChildren();
    for(const field of data.columns){dl.append(node("dt",I18n.field(field)),node("dd",field==="rating"?rating(r[field]):field==="duration"?duration(r[field]):Array.isArray(r[field])?(r[field].join(", ") || I18n.t("None saved")):empty(r[field])?I18n.t("Unknown / not captured"):typeof r[field]==="boolean"?(r[field]?I18n.t("Yes"):I18n.t("No")):String(r[field])));}
    $("#track-detail").showModal();
  }
  function metric(title,value,note){const card=node("article",undefined,"metric");card.append(node("span",title),node("strong",value),node("small",note));return card;}
  function overview(rows){
    const target=$("#overview");target.replaceChildren();target.hidden=view!=="index";if(target.hidden)return;
    const genres=groups(rows,"genre").sort((a,b)=>b.count-a.count).slice(0,7), max=genres[0]?.count || 1;
    const top=node("article");top.append(node("span",I18n.t("THE SHAPE OF THE COLLECTION"),"eyebrow"),node("h3",I18n.t("Genres at a glance")));
    for(const g of genres){const button=node("button",undefined,"bar-row"),rail=node("span",undefined,"bar-track"),fill=node("span",undefined,"bar-fill");fill.style.width=(100*g.count/max)+"%";rail.append(fill);button.append(node("span",g.label),rail,node("small",number.format(g.count)));button.onclick=()=>go("tracks",{...state,genre:g.key});top.append(button);}
    const quality=node("article");quality.append(node("span",I18n.t("METADATA COVERAGE"),"eyebrow"),node("h3",I18n.t("What is still unknown?")));const dl=node("dl",undefined,"quality");
    for(const [name,count] of [[I18n.t("Without a genre"),rows.filter(r=>!r.genre).length],[I18n.t("Without a release year"),rows.filter(r=>empty(r.year)).length],[I18n.t("Without a saved BPM"),rows.filter(r=>empty(r.bpm)).length],[I18n.t("No personal star rating"),rows.filter(r=>r.rating===0).length],[I18n.t("Duration not saved"),rows.filter(r=>empty(r.duration)).length],[I18n.t("Analysis status unknown"),rows.filter(r=>empty(r.analysed)).length]])dl.append(node("dt",name),node("dd",number.format(count)));
    quality.append(dl,node("p",I18n.t("An unknown tag is a review opportunity, not proof of a damaged track."),"muted"));target.append(top,quality);
  }
  function render(){
    const rows=filtered();const metrics=$("#metrics");metrics.replaceChildren(
      metric(I18n.t("Tracks in view"),number.format(rows.length),number.format(tracks.length)+" "+I18n.t("in this snapshot")),
      metric(I18n.t("Personal stars"),number.format(rows.filter(r=>r.rating>0).length),I18n.t("Tracks with a saved rating")),
      metric(I18n.t("Saved as analyzed"),number.format(rows.filter(r=>r.analysed===true).length),I18n.t("Status from captured metadata")),
      metric(I18n.t("Recorded duration"),hours(totalDuration(rows)),I18n.t("Sum of available track lengths")));
    overview(rows);const category=facet[view];
    shown=category?groups(rows,category):rows.slice();
    tableColumns=category?[["label",pages[view],false],["count",I18n.t("Tracks"),true],["duration",I18n.t("Recorded duration"),true],["rated",I18n.t("Starred tracks"),true],["average_bpm",I18n.t("Mean saved BPM"),true],["plays",I18n.t("Saved plays"),true]]:
      [["title",I18n.t("Track"),false],["artist",I18n.t("Artist"),false],["album",I18n.t("Album"),false],["genre",I18n.t("Genre"),false],["year",I18n.t("Year"),true],["bpm","BPM",true],["rating",I18n.t("Personal stars"),true],["duration",I18n.t("Duration"),true],["format",I18n.t("Format"),false],["play_count",I18n.t("Plays"),true]];
    const order=sortField || (category?"count":"title"),direction=sortField?(ascending?1:-1):(category?-1:1);
    shown.sort((a,b)=>{const av=a[order],bv=b[order];if(empty(av))return empty(bv)?0:1;if(empty(bv))return -1;return direction*(typeof av==="number" && typeof bv==="number"?av-bv:collator.compare(String(av),String(bv)));});
    page=Math.min(page,Math.max(0,Math.ceil(shown.length/pageSize)-1));
    $("#view-title").textContent=view==="index"?I18n.t("Collection index"):pages[view];
    $("#view-description").textContent=category?(view==="playlists"?I18n.t("Tracks can belong to several playlists, so category totals may overlap. Select a name to browse its tracks."):I18n.t("Select a category to browse its tracks. Missing values remain visible as unknown.")):I18n.t("Search, sort and browse saved metadata. Select a track for its full details.");
    const table=$("#metadata-table"),head=table.querySelector("thead"),body=table.querySelector("tbody"),header=node("tr");table.classList.toggle("track-table",!category);head.replaceChildren();body.replaceChildren();
    for(const [key,title] of tableColumns){const th=node("th"),button=node("button",title+(order===key?(direction===1?" ↑":" ↓"):""));th.scope="col";th.setAttribute("aria-sort",order===key?(direction===1?"ascending":"descending"):"none");button.onclick=()=>{ascending=sortField===key?!ascending:true;sortField=key;page=0;render();};th.append(button);header.append(th);}head.append(header);
    for(const r of shown.slice(page*pageSize,(page+1)*pageSize)){const tr=node("tr");for(const [field,,numeric] of tableColumns){const td=node("td",undefined,numeric?"numeric":"");
      if(field==="title" || field==="label"){const button=node("button",r[field] || I18n.t("Untitled track"),"cell-link");button.onclick=()=>category?go("tracks",{...state,[category]:r.key}):details(r);td.append(button);}
      else td.textContent=field==="duration"?(category?hours(r[field]):duration(r[field])):field==="rating"?rating(r[field]):empty(r[field])?I18n.t("Unknown"):field==="year"?String(r[field]):typeof r[field]==="number"?number.format(r[field]):r[field];tr.append(td);
    }body.append(tr);}
    if(!shown.length){const tr=node("tr"),td=node("td",I18n.t("No metadata matches these filters. Reset filters to see the full snapshot."));td.colSpan=tableColumns.length;tr.append(td);body.append(tr);}
    $("#results").textContent=shown.length?number.format(page*pageSize+1)+"–"+number.format(Math.min((page+1)*pageSize,shown.length))+" "+I18n.t("of")+" "+number.format(shown.length)+(category?" categories":" "+I18n.t("tracks")):I18n.t("0 results");
    $("#previous").disabled=page===0;$("#next").disabled=(page+1)*pageSize>=shown.length;
    const chips=$("#active-filters");chips.replaceChildren();for(const field of new Set(Object.values(facet)))if(state[field]!==undefined){const button=node("button",field.replace("_group","")+": "+(state[field]===missing?I18n.t("Unknown"):state[field].slice(2))+" ×","chip");button.onclick=()=>{const next={...state};delete next[field];go(view,next);};chips.append(button);}
    for(const a of document.querySelectorAll("#navigation a"))a.href=href(a.dataset.view);
  }
  function route(){state=Object.fromEntries(new URLSearchParams(location.hash.slice(1)));view=single?(state.view || "index"):document.body.dataset.view;if(!pages[view])view="index";delete state.view;page=0;sortField="";
    const theme=["system","dark","light"].includes(state.theme)?state.theme:"system";$("#theme").value=theme;document.body.dataset.theme=theme;
    for(const [id,key] of [["search","q"],["rating-filter","rating"],["format-filter","format_filter"],["bpm-min","bpm_min"],["bpm-max","bpm_max"],["duration-min","duration_min"],["duration-max","duration_max"]])$("#"+id).value=state[key] || "";
    for(const a of document.querySelectorAll("#navigation a")){if(a.dataset.view===view)a.setAttribute("aria-current","page");else a.removeAttribute("aria-current");}render();
  }
  for(const [key,title] of Object.entries(pages)){const a=node("a",title);a.dataset.view=key;a.href=href(key,{});$("#navigation").append(a);}
  for(const format of Array.from(new Set(tracks.map(r=>r.format).filter(Boolean))).sort()){const option=node("option",format);option.value=format;$("#format-filter").append(option);}
  $("#library-title").textContent=data.title;document.title=data.title+" "+I18n.t("· Offline library explorer");
  $("#snapshot-info").textContent=number.format(tracks.length)+" tracks · "+data.source_kind+" "+I18n.t("· captured")+" "+new Date(data.captured || data.created).toLocaleString(I18n.language);
  $("#scope-note").textContent=I18n.t("Captured library tags ·")+" "+(data.scope==="xml"?I18n.t("XML collection scope"):I18n.t("full captured library"))+". "+(data.metadata_overrides_applied?data.metadata_overrides_applied+" "+I18n.t("explicit working metadata fields applied.")+" ":"")+I18n.t("Merge and relocation decisions are not applied.")+" "+(data.includes_paths?I18n.t("Recorded file paths are included by your choice."):I18n.t("File paths are excluded."))+" "+I18n.t("No audio, artwork or waveform data.");
  $("#provenance").textContent=I18n.t("Generated by Library Workbench ·")+" "+new Date(data.created).toLocaleString(I18n.language)+" · "+(data.version?"rekordbox "+data.version:I18n.t("application version not supplied"));$("#cue-note").textContent=data.cue_basis;
  $("#theme").onchange=()=>{const next={...state,theme:$("#theme").value};if(single)next.view=view;location.hash=new URLSearchParams(next).toString();};document.body.dataset.theme="system";
  let debounce;$("#search").oninput=()=>{clearTimeout(debounce);debounce=setTimeout(applyFilters,180);};
  for(const id of ["rating-filter","format-filter","bpm-min","bpm-max","duration-min","duration-max"])$("#"+id).onchange=applyFilters;
  $("#reset").onclick=()=>go(view,{});$("#page-size").onchange=()=>{pageSize=Number($("#page-size").value);page=0;render();};$("#previous").onclick=()=>{page--;render();};$("#next").onclick=()=>{page++;render();};$("#close-detail").onclick=()=>$("#track-detail").close();
  $("#download-csv").onclick=()=>{const safe=v=>{let s=empty(v)?"":String(v);if(/^[=+\-@\t\r]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';};const csv="\ufeff"+[tableColumns.map(c=>safe(c[0]==="duration"?I18n.t("Duration (seconds)"):c[1])).join(","),...shown.map(r=>tableColumns.map(([key])=>safe(r[key])).join(","))].join("\r\n");const url=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"}));const a=node("a");a.href=url;a.download="library-"+view+".csv";a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);};
  window.addEventListener("hashchange",route);route();
  window.addEventListener('workbench-language',()=>{number=new Intl.NumberFormat(I18n.language);collator=new Intl.Collator(I18n.language,{numeric:true,sensitivity:'base'});for(const link of document.querySelectorAll('#navigation a'))link.textContent=pages[link.dataset.view];render();});
})();
