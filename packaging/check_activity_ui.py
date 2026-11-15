"""CI browser checks for pending work, using held local responses only."""


def check_activity_ui(browser,base,output):
    context=browser.new_context(locale='en-US',viewport={'width':1440,'height':1000})
    context.add_init_script("localStorage.setItem('library-workbench.language.v1','en')")
    page=context.new_page();errors=[];held={}
    page.on('pageerror',lambda error:errors.append(str(error)))
    def hold(route):
        held[route.request.url.split('wait-check=')[-1]]=route
    context.route('**/*wait-check=*',hold)
    try:
        page.goto(base,wait_until='networkidle')
        page.wait_for_selector('#request-activity',state='hidden')
        page.select_option('#theme','light')
        # A real navigation stays interactive while its documentation is loading.
        context.route('**/api/docs',lambda route:held.update(docs=route))
        page.locator('.nav[data-view="docs"]').click()
        page.wait_for_function('!document.querySelector("#request-activity").hidden',timeout=2000)
        assert page.locator('dialog[open]').count()==0
        assert page.evaluate('document.activeElement.matches(".nav[data-view=docs]")')
        page.wait_for_function('document.querySelector("#request-activity strong").textContent==="Waiting…"',timeout=2500)
        assert page.locator('#request-activity small').inner_text().startswith('Elapsed: ')
        page.screenshot(path=str(output/'activity-waiting-light.png'))
        # A second in-flight request must survive the first one's completion.
        page.evaluate('''() => {window.waitResults={};void api('/api/status?wait-check=second').then(()=>waitResults.second=true);}''')
        page.wait_for_timeout(300)
        held['docs'].continue_()
        page.wait_for_selector('#docs-content h1')
        assert page.locator('#request-activity').is_visible()
        held['second'].continue_()
        page.wait_for_function('window.waitResults.second && document.querySelector("#request-activity").hidden')
        # Fast responses never flash the indicator; background polling stays quiet.
        page.evaluate('''async () => {window.activityFlashed=false;window.activityObserver=new MutationObserver(()=>{if(!document.querySelector('#request-activity').hidden)window.activityFlashed=true;});activityObserver.observe(document.querySelector('#request-activity'),{attributes:true,attributeFilter:['hidden']});await api('/api/status');}''')
        page.wait_for_timeout(350)
        assert page.evaluate('!window.activityFlashed')
        page.evaluate('activityObserver.disconnect()')
        page.evaluate("() => {void api('/api/status?wait-check=quiet',{feedback:false}).then(()=>waitResults.quiet=true);}")
        page.wait_for_timeout(1200)
        assert page.locator('#request-activity').is_hidden()
        held['quiet'].continue_();page.wait_for_function('window.waitResults.quiet')
        # Failure and abort settle the indicator without hiding another request.
        page.evaluate("() => {void api('/api/status?wait-check=error').catch(()=>waitResults.error=true);}")
        page.wait_for_selector('#request-activity',state='visible')
        held['error'].fulfill(status=503,json={'error':'The action could not be completed'})
        page.wait_for_function('window.waitResults.error && document.querySelector("#request-activity").hidden')
        page.evaluate("() => {window.waitAbort=new AbortController();void api('/api/status?wait-check=abort',{signal:waitAbort.signal}).catch(()=>waitResults.abort=true);}")
        page.wait_for_selector('#request-activity',state='visible')
        page.evaluate('waitAbort.abort()')
        page.wait_for_function('window.waitResults.abort && document.querySelector("#request-activity").hidden')
        # Unchanged backend reports must not restart the waiting clock. A genuine
        # update does, while total elapsed time continues and cancellation works.
        page.evaluate('''() => {window.activityCancelled=false;progress(40,'Synthetic analysis step',()=>{activityCancelled=true;finishProgress();});window.repeatProgress=setInterval(()=>progress(40,'Synthetic analysis step'),300);}''')
        page.wait_for_function('document.querySelector("#progress #request-activity strong")?.textContent==="Waiting…"',timeout=2500)
        assert page.locator('#progress-label').inner_text()=='Synthetic analysis step'
        assert page.locator('#progress-bar').get_attribute('value')=='40'
        page.wait_for_function('document.querySelector("#request-activity p").textContent.startsWith("This is taking longer.")',timeout=35000)
        assert page.locator('#progress-cancel').is_enabled()
        page.screenshot(path=str(output/'activity-long-operation.png'))
        page.evaluate("clearInterval(repeatProgress);progress(60,'Synthetic next step')")
        assert page.locator('#request-activity strong').inner_text()=='Working'
        assert page.locator('#progress-bar').get_attribute('value')=='60'
        page.locator('#progress-cancel').click()
        page.wait_for_function('window.activityCancelled && !document.querySelector("#progress").open && document.querySelector("#request-activity").hidden')
        # Generic modal feedback stays in the top layer, fits mobile/RTL, and
        # honours reduced motion without moving keyboard focus.
        page.set_viewport_size({'width':390,'height':844});page.emulate_media(reduced_motion='reduce')
        page.select_option('#theme','dark');page.select_option('#language','ar')
        page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
        page.wait_for_selector('#request-activity',state='hidden')
        page.evaluate('''() => {document.querySelector('#sessions-dialog').showModal();window.activityFocus=document.activeElement;void api('/api/status?wait-check=modal').then(()=>waitResults.modal=true);}''')
        page.wait_for_selector('#sessions-dialog #request-activity',state='visible')
        page.wait_for_function('document.querySelector("#request-activity").dataset.waiting==="true"')
        assert page.locator('#request-activity strong').inner_text()=='جارٍ الانتظار…'
        assert page.evaluate('document.activeElement===window.activityFocus')
        metrics=page.locator('#request-activity').evaluate('e=>({width:e.clientWidth,scroll:e.scrollWidth,animation:getComputedStyle(e.querySelector(".spinner")).animationName})')
        assert metrics['scroll']<=metrics['width']+1 and metrics['animation']=='none',metrics
        page.screenshot(path=str(output/'activity-modal-arabic-mobile.png'))
        held['modal'].continue_();page.wait_for_function('window.waitResults.modal && document.querySelector("#request-activity").hidden')
        page.evaluate('document.querySelector("#sessions-dialog").close()')
        assert not errors,errors
        return {'navigation':True,'concurrent_requests':True,'fast_requests_quiet':True,'background_quiet':True,'error_and_abort_cleanup':True,'unchanged_progress_waits':True,'progress_updates_reset_wait':True,'long_wait_notice':True,'cancellation':True,'modal_mobile_rtl':True,'reduced_motion':True,'show_after_ms':200,'wait_after_ms':1000,'synthetic':True}
    finally:
        context.close()
