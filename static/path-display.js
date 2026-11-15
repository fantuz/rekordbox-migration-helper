/* Break opportunities are elements, so copying still yields the original path. */
(()=>{
  const selectors='#cleanup-path,.detected-source code,.report-source,#workspace-root,#workspace-inputs,#workspace-exports,#upload-destination';
  function formatPaths(){
    for(const node of document.querySelectorAll(selectors)){
      const path=node.textContent;if(!path || (node.dataset.formattedPath===path && (node.querySelector('wbr') || Number(node.dataset.pathParts)<=2)))continue;
      node.dataset.formattedPath=path;node.classList.add('workbench-path');node.replaceChildren();
      const parts=path.match(/[^\\/]+[\\/]?|[\\/]/gu) || [path];
      node.dataset.pathParts=parts.length;
      parts.forEach((part,index)=>{if(index>1)node.append(document.createElement('wbr'));node.append(document.createTextNode(part));});
    }
  }
  let pending=false;
  new MutationObserver(()=>{if(pending)return;pending=true;queueMicrotask(()=>{pending=false;formatPaths();});}).observe(document.body,{childList:true,subtree:true,characterData:true});
  formatPaths();
})();
