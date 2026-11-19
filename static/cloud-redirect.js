/* Copy the exact callback; provider registration rules are shown beside it. */
async function copyCloudRedirect(input){
  const value=input.value;if(!value)return;
  if(navigator.clipboard?.writeText){
    try{await navigator.clipboard.writeText(value);notify(I18n.t('Copied'));return;}catch{}
  }
  input.focus();input.select();
  if(document.execCommand('copy'))notify(I18n.t('Copied'));
}
