/* Display choices only. Never write library fields or retain playback consent. */
window.DisplayPreferences=(()=>{
  const storage='library-workbench.display.v1',data=window.WORKBENCH_KEY_NOTATION;
  let state={key_notation:'alpha',hide_unknown:false};
  try{const saved=JSON.parse(localStorage.getItem(storage)||'{}');if(['alpha','camelot','open_key'].includes(saved.key_notation))state.key_notation=saved.key_notation;if(typeof saved.hide_unknown==='boolean')state.hide_unknown=saved.hide_unknown;}catch{}
  const text=key=>I18n.t(key);
  function normalized(value){
    let raw=String(value??'').normalize('NFKC').trim().replaceAll('♯','#').replaceAll('♭','b');
    if(/^[A-Ga-g][#b]?M$/.test(raw))raw=raw.slice(0,-1)+'major';
    return raw.replace(/\s+/gu,'').toLowerCase();
  }
  function keyGroup(raw){const value=normalized(raw);return Object.hasOwn(data.aliases,value)?data.aliases[value]:null;}
  function group(raw){if(Object.hasOwn(data.keys,raw)||['key:missing','key:unrecognized'].includes(raw))return raw;return keyGroup(raw)||(data.unknown.includes(String(raw??'').normalize('NFKC').trim().replace(/\s+/gu,' ').toLowerCase())?'key:missing':'key:unrecognized');}
  function key(raw){const identity=keyGroup(raw);return identity?data.keys[identity][state.key_notation]:String(raw??'');}
  function groupLabel(identity){return Object.hasOwn(data.keys,identity)?data.keys[identity][state.key_notation]:text(identity==='key:missing'?'Unknown / not captured':'Unrecognized key');}
  function sync(){
    for(const node of document.querySelectorAll('[data-key-notation]'))node.value=state.key_notation;
    for(const node of document.querySelectorAll('[data-hide-unknown]'))node.checked=state.hide_unknown;
  }
  function update(patch){
    if(patch.key_notation!==undefined&&!['alpha','camelot','open_key'].includes(patch.key_notation))return;
    state={...state,...patch};try{localStorage.setItem(storage,JSON.stringify(state));}catch{}
    sync();window.dispatchEvent(new CustomEvent('workbench-display-preferences',{detail:{...state}}));
  }
  function controls({keys=true,unknown=true}={}){
    return '<div class="display-preferences">'+(keys?'<label class="key-display-choice"><span data-i18n="Key notation">'+esc(text('Key notation'))+'</span><select data-key-notation data-i18n-aria="Key notation" aria-label="'+esc(text('Key notation'))+'"><option value="alpha" data-i18n="Alphabetical">'+esc(text('Alphabetical'))+'</option><option value="camelot">Camelot · 8A / 8B</option><option value="open_key">Open Key · 1m / 1d</option></select></label>':'')+(unknown?'<label class="unknown-display-choice"><input type="checkbox" data-hide-unknown><span data-i18n="Hide unknown">'+esc(text('Hide unknown'))+'</span></label>':'')+'</div>';
  }
  document.addEventListener('change',event=>{
    if(event.target.matches('[data-key-notation]'))update({key_notation:event.target.value});
    if(event.target.matches('[data-hide-unknown]'))update({hide_unknown:event.target.checked});
  });
  window.addEventListener('workbench-language',()=>{sync();});
  return {controls,sync,key,keyGroup,group,groupLabel,update,get:()=>({...state}),args:()=>({key_notation:state.key_notation,hide_unknown:state.hide_unknown?'1':'0'})};
})();
