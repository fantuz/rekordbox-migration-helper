/* Group captured references and expose the existing evidence and staging tools. */
window.FileReferences=(()=>{
  const text=key=>esc(I18n.t(key));
  const filterLabels={
    all:'All references',changed:'Original path differs',missing_path:'No recorded current path',
    shared_path:'Shared current path',missing_analysis:'No recorded analysis path',
    cross_platform:'Different path platforms'
  };
  const groupLabels={
    none:'No grouping',folder:'Recorded folder',volume:'Recorded volume',
    format:'Format',cloud:'Cloud location',platform:'Path platform'
  };
  const groupValues={
    windows_drive:'Windows drive',network_share:'Network share',posix:'POSIX path',
    unrecognized:'Relative or unrecognized path',unknown:'Unknown',other:'No cloud match',
    dropbox:'Dropbox',google_drive:'Google Drive',multiple:'Multiple cloud hints'
  };
  const state={offset:0,provider:'all',mode:'all',group_by:'none',q:'',sort:'title',direction:'asc'};
  let revision=0,previousScope='';

  const scope=()=>window.Journeys?.context()?.source || (session?'workspace':'');
  const identity=source=>source==='workspace'?'session:'+(session?.id||''):source;
  function setup(host){
    if(host.querySelector('.reference-browser'))return;
    const form=document.createElement('div');
    form.className='workspace-collection';
    while(host.firstChild)form.append(host.firstChild);
    host.append(form);
    const panel=document.createElement('div');
    panel.className='native-collection reference-browser';
    panel.hidden=true;
    host.append(panel);
  }

  function options(labels,selected){
    return Object.entries(labels).map(([value,label])=>'<option value="'+value+'"'+
      (value===selected?' selected':'')+'>'+text(label)+'</option>').join('');
  }

  function heading(field,label){
    const order=field===state.sort?(state.direction==='asc'?'ascending':'descending'):'none';
    return '<th scope="col" aria-sort="'+order+'"><button type="button" class="result-sort-button native-global-sort"'+
      ' data-native-sort="'+field+'" aria-label="'+text('Sort all results by')+' '+text(label)+'">'+text(label)+'</button></th>';
  }

  function quickFilters(counts){
    return '<div class="metadata-quick-filters reference-quick-filters" role="group" aria-label="'+text('Evidence')+'">'+
      Object.entries(filterLabels).map(([value,label])=>{
        const count=counts[value];
        return '<button type="button" class="metadata-flag-filter" data-reference-mode="'+value+'" aria-pressed="'+
          (value===state.mode)+'"'+(count===null?' disabled':'')+'>'+text(label)+' · '+(count===null?text('Not captured'):num(count))+'</button>';
      }).join('')+'</div>';
  }

  function trackRow(row,source){
    const saved=source.startsWith('snapshot:')?source.slice(9):source;
    const play=source==='workspace'?TrackPlayback.button('',row.id,session?.id):TrackPlayback.button(saved,row.id);
    const flags=row.flags.map(flag=>'<span class="metadata-flag">'+text(filterLabels[flag])+'</span>').join('');
    const action=source==='workspace'?'<button type="button" class="text-button" data-reference-editor="'+esc(row.id)+'">'+
      text('Use in export reference form')+'</button>':'';
    const paths=['current_path','original_path','analysis_path'].map(field=>'<td><code dir="ltr">'+
      (row[field]?esc(row[field]):text('Unknown'))+'</code></td>').join('');
    const size=Number.isSafeInteger(row.size)&&row.size>=0?num(row.size):text('Unknown');
    return '<tr data-reference-track="'+esc(row.id)+'"><td>'+play+'<strong>'+esc(row.title||I18n.t('Untitled'))+'</strong><br>'+
      '<span>'+esc(row.artist||'')+'</span><br><small class="subtle"><bdi>'+esc(row.id)+'</bdi></small>'+
      (flags?'<div class="reference-row-flags">'+flags+'</div>':'')+action+'</td>'+paths+'<td>'+size+'</td></tr>';
  }

  function tableBodies(rows,source){
    if(!rows.length)return '<tbody><tr><td colspan="5">'+text('No matching references')+'</td></tr></tbody>';
    if(state.group_by==='none')return '<tbody>'+rows.map(row=>trackRow(row,source)).join('')+'</tbody>';
    const groups=new Map();
    for(const row of rows){
      const key=row.group.key;
      if(!groups.has(key))groups.set(key,[]);
      groups.get(key).push(row);
    }
    return [...groups.values()].map(group=>{
      const {label,translated,count}=group[0].group;
      const title=translated?text(groupValues[label]||'Unknown'):label?esc(label):text('Unknown');
      return '<tbody><tr class="reference-group-row"><th scope="rowgroup" colspan="5" data-reference-group>'+
        '<bdi>'+title+'</bdi> · '+num(count)+' '+text('tracks')+'</th></tr>'+
        group.map(row=>trackRow(row,source)).join('')+'</tbody>';
    }).join('');
  }

  function pager(data){
    const first=data.total?data.offset+1:0;
    const last=Math.min(data.offset+50,data.total);
    return '<nav class="native-pagination" aria-label="'+text('Results pages')+'">'+
      '<button type="button" class="button secondary" data-native-prev="reference"'+(!data.offset?' disabled':'')+'>'+text('Previous')+'</button>'+
      '<span class="native-page-range" aria-live="polite">'+num(first)+'–'+num(last)+' '+text('of')+' '+num(data.total)+' '+text('results')+'</span>'+
      '<button type="button" class="button secondary" data-native-next="reference"'+(data.offset+50>=data.total?' disabled':'')+'>'+text('Next')+'</button></nav>';
  }

  function render(panel,data,source){
    const workspace=source==='workspace';
    const title=workspace?'File references':'Captured file references';
    const action=workspace?'Open Media inventory':'File health';
    const columns=[['title','Track'],['current_path','Current path'],['original_path','Original path'],['analysis_path','Analysis path']];
    panel.innerHTML='<article class="wide-card"><div class="section-heading"><h2>'+text(title)+'</h2>'+
      '<button type="button" class="button secondary" data-reference-evidence>'+text(action)+'</button></div>'+
      '<form class="native-filter" id="reference-filters"><label>'+text('Quick search')+
      '<input type="search" name="query" value="'+esc(state.q)+'" placeholder="'+text('Search by title, artist, track ID or path')+'"></label>'+
      '<label>'+text('Evidence')+'<select name="mode">'+options(filterLabels,state.mode)+'</select></label>'+
      '<label>'+text('Group by')+'<select name="group_by">'+options(groupLabels,state.group_by)+'</select></label>'+
      CloudAnalysis.control('native-reference-provider',state.provider)+
      DisplayPreferences.controls({keys:false,unknown:false,sidecars:true})+
      '<button type="submit" class="button">'+text('Apply')+'</button></form>'+
      quickFilters(data.counts)+
      '<p class="subtle cloud-analysis-note">'+[I18n.t(CloudAnalysis.note),DisplayPreferences.sidecarNote(data)].filter(Boolean).map(esc).join(' · ')+'</p>'+
      '<div class="native-table"><table data-sort-scope="server"><thead><tr>'+columns.map(args=>heading(...args)).join('')+
      '<th scope="col">'+text('Recorded size (bytes)')+'</th></tr></thead>'+tableBodies(data.rows,source)+'</table></div>'+
      pager(data)+'</article>';
    CloudAnalysis.paint(panel.querySelector('[data-cloud-analysis-provider]'),data.cloud.counts);
    DisplayPreferences.sync();
    const form=panel.querySelector('form');
    function capture(){
      state.q=form.elements.query.value.trim();
      state.mode=form.elements.mode.value;
      state.group_by=form.elements.group_by.value;
      state.provider=form.elements.provider.value;
      state.offset=0;
    }
    form.onsubmit=wrap(async event=>{event.preventDefault();capture();await load();panel.querySelector('[type=submit]')?.focus({preventScroll:true});});
    for(const button of panel.querySelectorAll('[data-reference-mode]')){
      button.onclick=wrap(async()=>{
        const mode=button.dataset.referenceMode;
        form.elements.mode.value=mode;
        capture();
        await load();
        panel.querySelector('[data-reference-mode="'+mode+'"]')?.focus({preventScroll:true});
      });
    }
    for(const button of panel.querySelectorAll('[data-native-sort]')){
      button.onclick=wrap(async()=>{
        const field=button.dataset.nativeSort;
        state.direction=state.sort===field&&state.direction==='asc'?'desc':'asc';
        state.sort=field;
        state.offset=0;
        await load();
        panel.querySelector('[data-native-sort="'+field+'"]')?.focus({preventScroll:true});
      });
    }
    panel.querySelector('[data-native-prev]').onclick=wrap(async()=>{state.offset=Math.max(0,state.offset-50);await load();});
    panel.querySelector('[data-native-next]').onclick=wrap(async()=>{state.offset+=50;await load();});
    panel.querySelector('[data-reference-evidence]').onclick=()=>{
      if(!workspace)FileHealth.forSource(source);
      showView(workspace?'inventory':'file-health');
    };
    for(const button of panel.querySelectorAll('[data-reference-editor]')){
      button.onclick=()=>{
        const row=data.rows.find(row=>String(row.id)===button.dataset.referenceEditor);
        if(!row || identity(scope())!==previousScope)return;
        const track=$('#reference-track'),uri=$('#reference-uri');
        if(track.value!==String(row.id))uri.value=row.xml_location?.startsWith('file:')?row.xml_location:'';
        track.value=row.id;
        uri.focus();
      };
    }
  }

  async function load(){
    const host=$('#view-reference');
    setup(host);
    const panel=host.querySelector('.reference-browser');
    const source=scope(),current=identity(source),request=++revision;
    host.querySelector('.workspace-collection').hidden=Boolean(source&&source!=='workspace');
    panel.hidden=!source;
    if(!source)return;
    if(current!==previousScope){
      state.offset=0;
      panel.innerHTML='<p role="status">'+text('Loading')+'</p>';
      previousScope=current;
    }
    panel.setAttribute('aria-busy','true');
    try{
      const data=await api('/api/collection/references?'+new URLSearchParams({source,...state,...DisplayPreferences.args()}));
      if(request===revision&&current===identity(scope()))render(panel,data,source);
    }finally{
      if(request===revision)panel.removeAttribute('aria-busy');
    }
  }
  window.addEventListener('workbench-display-preferences',()=>{
    if(!$('#view-reference').hidden){state.offset=0;void load().catch(error=>notify(error.message,true));}
  });
  return {load};
})();
