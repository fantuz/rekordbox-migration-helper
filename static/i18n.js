/* Explicit interface messages. Never translate arbitrary DOM text or library data. */
"use strict";
window.I18n=(() => {
  const data=window.WORKBENCH_LOCALES || {languages:{en:'English'},messages:{en:{}}};
  const storageKey='library-workbench.language.v1';
  const supported=code=>Object.hasOwn(data.languages,code);
  const normalize=code=>String(code || '').toLowerCase().split('-')[0];
  const browserLanguage=()=>[...(navigator.languages || []),navigator.language].map(normalize).find(supported) || 'en';
  const readPreference=()=>{try{return localStorage.getItem(storageKey);}catch{return null;}};
  let language=supported(readPreference())?readPreference():browserLanguage();
  const missing=new Set(),rich=new WeakMap(),numberFormats=new Map();
  const escape=value=>String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number=(value,options={})=>{const key=language+JSON.stringify(options);if(!numberFormats.has(key))numberFormats.set(key,new Intl.NumberFormat(language,options));return numberFormats.get(key).format(Number(value));};
  function message(key,params={}){
    key=String(key ?? '');
    let text=data.messages[language]?.[key] ?? data.messages.en?.[key];
    if(text===undefined){missing.add(key);text=key;}
    if(text && typeof text==='object')text=text[new Intl.PluralRules(language).select(Number(params.count))] ?? text.other;
    return String(text ?? key);
  }
  const parameter=value=>typeof value==='number'?number(value):String(value ?? '');
  function t(key,params={}){return message(key,params).replace(/\{([a-zA-Z][a-zA-Z0-9_]*)\}/g,(token,name)=>Object.hasOwn(params,name)?parameter(params[name]):token);}
  const error=value=>Object.hasOwn(data.messages.en || {},String(value))?t(String(value)):t('Technical detail: {detail}',{detail:String(value)});
  const fieldNames={title:'Title',artist:'Artist',album:'Album',genre:'Genre',year:'Year',rating:'Personal stars',comment:'Comments',bpm:'BPM',duration:'Duration',format:'Format',label:'Record label',composer:'Composer',play_count:'Play count',date_added:'Date added',last_played:'Last played',analysed:'Analyzed',manual_cues:'Manual cues',auto_cues:'Auto cues',bitrate:'Bitrate',sample_rate:'Sample rate',bit_depth:'Bit depth',playlists:'Playlists',tonality:'Tonality',current_path:'Current path',original_path:'Original path',color_name:'Track colour',color_hex:'RGB',color_status:'Colour status'};
  const field=key=>Object.hasOwn(fieldNames,key)?t(fieldNames[key]):String(key).replaceAll('_',' ');
  function date(value,options={}){
    if(!value)return t('Unknown');
    const d=new Date(value);return Number.isNaN(d.getTime())?String(value):new Intl.DateTimeFormat(language,options).format(d);
  }
  function apply(root=document){
    const nodes=[...(root.nodeType===1&&root.matches('[data-i18n],[data-i18n-placeholder],[data-i18n-title],[data-i18n-aria]')?[root]:[]),...(root.querySelectorAll?.('[data-i18n],[data-i18n-placeholder],[data-i18n-title],[data-i18n-aria]') || [])];
    for(const node of nodes){
      for(const [attribute,target] of [['placeholder','placeholder'],['title','title'],['aria','aria-label']]){
        const key=node.dataset['i18n'+attribute[0].toUpperCase()+attribute.slice(1)];if(key)node.setAttribute(target,t(key));
      }
      if(!node.dataset.i18n)continue;
      let params={};try{params=JSON.parse(node.dataset.i18nParams || '{}');}catch{}
      const key=node.dataset.i18n,signature=language+'\0'+key+'\0'+JSON.stringify(params);
      let state=rich.get(node);
      if(state?.signature===signature)continue;
      if(!state || state.key!==key){state={key,slots:[...node.children],signature:null};rich.set(node,state);}
      state.signature=signature;
      const parts=message(key,params).split(/(\{[a-zA-Z][a-zA-Z0-9_]*\})/g),children=[];
      for(const part of parts){
        const slot=part.match(/^\{slot(\d+)\}$/),field=part.match(/^\{([a-zA-Z][a-zA-Z0-9_]*)\}$/);
        if(slot && state.slots[Number(slot[1])] && key.includes(part))children.push(state.slots[Number(slot[1])]);
        else children.push(document.createTextNode(field&&Object.hasOwn(params,field[1])?parameter(params[field[1]]):part));
      }
      node.replaceChildren(...children);
    }
  }
  function html(key,params={}){return '<span data-i18n="'+escape(key)+'" data-i18n-params="'+escape(JSON.stringify(params))+'">'+escape(t(key,params))+'</span>';}
  function text(node,key,params={}){node.dataset.i18n=key;node.dataset.i18nParams=JSON.stringify(params);rich.delete(node);apply(node);}
  function setLanguage(code){
    if(!supported(code))code='en';
    language=code;try{localStorage.setItem(storageKey,code);}catch{}
    document.documentElement.lang=code;document.documentElement.dir='ltr';
    for(const select of document.querySelectorAll('[data-language-select],#language'))select.value=code;
    apply();window.dispatchEvent(new CustomEvent('workbench-language',{detail:{language:code}}));
  }
  function start(){
    document.documentElement.lang=language;document.documentElement.dir='ltr';
    for(const select of document.querySelectorAll('[data-language-select],#language')){select.value=language;select.addEventListener('change',()=>setLanguage(select.value));}
    apply();
    new MutationObserver(records=>{for(const record of records){if(record.type==='attributes')apply(record.target);else for(const node of record.addedNodes)if(node.nodeType===1)apply(node);}}).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['data-i18n','data-i18n-params']});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
  return {t,html,text,apply,setLanguage,number,date,error,field,escape,missing,get language(){return language;},get languages(){return data.languages;}};
})();
