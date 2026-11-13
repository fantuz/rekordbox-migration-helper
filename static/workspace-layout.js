/* Local appearance preferences; no library data or API requests. */
(() => {
  const widths={compact:200,standard:240,wide:300},key='library-workbench.sidebar-size.v1',select=document.getElementById('sidebar-size');
  const apply=value=>{const size=Object.hasOwn(widths,value)?value:'standard';document.documentElement.style.setProperty('--sidebar-width',widths[size]+'px');select.value=size;};
  let saved;try{saved=localStorage.getItem(key);}catch{}
  apply(saved);
  select.addEventListener('change',()=>{apply(select.value);try{localStorage.setItem(key,select.value);}catch{}});
})();
