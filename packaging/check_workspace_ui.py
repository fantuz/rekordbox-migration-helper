"""Synthetic CI interactions: source readiness, progress, preferences and layout."""
import json
from urllib.parse import urlsplit
import urllib.request

from check_duplicate_review_ui import check_duplicate_review_ui


def check_workspace_ui(browser,page,base,sid,output,offline):
    with urllib.request.urlopen(base+'/api/lab') as response:lab=json.load(response)
    page.select_option('#language','en');page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
    assert page.locator('.nav-group').count()==4
    for size in ('compact','standard','wide'):
        page.select_option('#sidebar-size',size)
        bounds=page.locator('.sidebar').bounding_box()
        assert round(bounds['width'])=={'compact':200,'standard':240,'wide':300}[size]
    page.reload(wait_until='networkidle');assert page.locator('#sidebar-size').input_value()=='wide'
    page.select_option('#sidebar-size','standard')
    page.locator('.nav[data-view="inventory"]').click();page.wait_for_selector('#collection-metrics',state='visible')
    assert page.locator('#collection-metrics small').evaluate_all('(els)=>els.every(el=>parseFloat(getComputedStyle(el).fontSize)>=13)')
    assert page.locator('#collection-metrics article>span').evaluate_all('(els)=>els.every(el=>parseFloat(getComputedStyle(el).fontSize)>=12)')
    page.screenshot(path=str(output/'summary-cards.png'))
    # No metadata snapshot yet, despite an XML/ZIP workspace being available.
    ready=False;done=False
    def library(route):route.fulfill(json={**lab,'workspace':'synthetic-loaded-library','snapshots':lab['snapshots'] if ready else []})
    def capture(route):
        assert route.request.post_data_json['source']=='session'
        route.fulfill(json={'job':'synthetic-capture'})
    def task(route):route.fulfill(json={'status':'complete','result':{'id':sid},'progress':100,'message':'Synthetic capture complete'} if done else {'status':'running','progress':35,'message':'Preparing synthetic metadata'})
    page.route('**/api/lab',library);page.route('**/api/lab/snapshots',capture);page.route('**/api/tasks/synthetic-capture',task)
    page.locator('.nav[data-view="bubbles"]').click();page.wait_for_selector('#bubble-empty',state='visible')
    assert page.locator('#bubble-dimension option').count()>10
    assert page.locator('#bubble-dimension').is_disabled()
    assert page.locator('#bubble-empty [data-insight-capture]').is_enabled()
    page.locator('#bubble-expand').click();page.wait_for_selector('#bubble-expanded[open]')
    page.locator('#bubble-expanded [data-view="lab"]').click()
    page.wait_for_selector('#bubble-expanded',state='hidden')
    assert page.locator('#view-lab').is_visible()
    assert page.locator('#view-bubbles').is_hidden()
    page.locator('.nav[data-view="bubbles"]').click();page.wait_for_selector('#bubble-empty',state='visible')
    page.locator('#bubble-empty [data-insight-capture]').click();page.wait_for_selector('#progress[open]')
    box=page.locator('#progress').bounding_box();viewport=page.viewport_size
    assert abs(box['x']+box['width']/2-viewport['width']/2)<3
    assert abs(box['y']+box['height']/2-viewport['height']/2)<3
    page.keyboard.press('Escape');assert page.locator('#progress').is_visible()
    page.keyboard.press('Tab');assert page.locator('#progress').evaluate('(el)=>el.contains(document.activeElement)')
    page.screenshot(path=str(output/'centered-progress.png'))
    ready=True;done=True;page.wait_for_selector('#progress',state='hidden');page.wait_for_selector('#library-bubbles[data-state="ready"] circle')
    page.locator('#bubble-colour-cloud').click();page.wait_for_function('document.querySelector("#bubble-dimension").value==="colour" && document.querySelector("#library-bubbles").dataset.state==="ready"')
    assert page.locator('#bubble-metric').input_value()=='tracks'
    assert page.locator('#library-bubbles circle').count()==2
    assert page.locator('#library-bubbles').evaluate('(el)=>el.viewBox.baseVal.width>0 && el.viewBox.baseVal.height>0')
    assert page.locator('#library-bubbles').evaluate('''el=>{const circles=[...el.querySelectorAll('circle')].map(c=>{const g=c.parentNode.transform.baseVal.consolidate().matrix;return {x:g.e,y:g.f,r:Number(c.getAttribute('r'))}}),v=el.viewBox.baseVal;return circles.every((a,i)=>a.x-a.r>=v.x && a.y-a.r>=v.y && a.x+a.r<=v.x+v.width && a.y+a.r<=v.y+v.height && circles.slice(i+1).every(b=>Math.hypot(a.x-b.x,a.y-b.y)>=a.r+b.r))}''')
    assert page.locator('#bubble-empty').is_hidden()
    assert page.locator('#library-bubbles circle').evaluate_all('(els)=>els.every(el=>Number(el.getAttribute("r"))>0)')
    def inspector_bounds():
        return page.locator('#bubble-selected').evaluate('''el=>{const r=el.getBoundingClientRect(),s=document.querySelector('#library-bubbles').getBoundingClientRect(),w=el.closest('.bubble-workspace').getBoundingClientRect();return {x:r.x-w.x,y:r.y-w.y,width:r.width,height:r.height,bottom:r.bottom-w.y,svgTop:s.y-w.y,workspaceCenter:w.width/2}}''')
    def check_inspector():
        assert page.locator('#bubble-selected').is_visible()
        baseline=inspector_bounds()
        assert baseline['bottom']<=baseline['svgTop']+1
        assert abs(baseline['x']+baseline['width']/2-baseline['workspaceCenter'])<2
        assert page.locator('#library-bubbles title').count()==0
        assert page.locator('#bubble-selected p, #bubble-selected li, #bubble-selected>small').evaluate_all('(els)=>els.every(el=>parseFloat(getComputedStyle(el).fontSize)>=12)')
        group=page.locator('#bubble-groups .bubble-group-button').nth(1)
        expected=group.locator('span').inner_text();group.hover()
        page.wait_for_function('(expected)=>document.querySelector("#bubble-selected h4").textContent===expected',arg=expected)
        after_hover=inspector_bounds()
        for field in ('x','y','width','height','svgTop'):assert abs(after_hover[field]-baseline[field])<1.5,(field,baseline,after_hover)
        node=page.locator('#library-bubbles g.bubble-node').first;label=node.get_attribute('aria-label');node.focus()
        page.wait_for_function('(label)=>label.startsWith(document.querySelector("#bubble-selected h4").textContent+", ")',arg=label)
        after_focus=inspector_bounds()
        for field in ('x','y','width','height','svgTop'):assert abs(after_focus[field]-baseline[field])<1.5,(field,baseline,after_focus)
    check_inspector()
    page.locator('#library-bubbles').scroll_into_view_if_needed()
    page.locator('#bubble-expand').click();page.wait_for_selector('#bubble-expanded[open]')
    assert page.locator('#bubble-expanded').bounding_box()['width']>page.viewport_size['width']*.9
    page.wait_for_selector('#bubble-expanded #library-bubbles',state='visible')
    assert page.locator('#bubble-expanded #library-bubbles').bounding_box()['height']>=320
    assert page.locator('#bubble-expanded #library-bubbles circle').first.is_visible()
    assert page.locator('#bubble-expanded #bubble-dimension').is_visible()
    check_inspector()
    page.locator('#bubble-selected').scroll_into_view_if_needed()
    page.screenshot(path=str(output/'colour-cloud.png'))
    page.keyboard.press('Escape');page.wait_for_selector('#bubble-expanded',state='hidden')
    page.locator('#library-bubbles g.bubble-node').first.click();page.wait_for_function('document.querySelector("#library-bubbles").dataset.state==="ready" && document.querySelectorAll("#bubble-breadcrumbs button").length===2')
    page.locator('#bubble-reset').click();page.wait_for_function('document.querySelectorAll("#bubble-breadcrumbs button").length===1 && document.querySelector("#library-bubbles").dataset.state==="ready"')
    page.unroute('**/api/lab',library);page.unroute('**/api/lab/snapshots',capture);page.unroute('**/api/tasks/synthetic-capture',task)
    duplicate_review=check_duplicate_review_ui(browser,base,output)
    # Browser locale fallback, persistence and blocked local storage must not stop startup.
    for locale,blocked in [('pl-PL',False),('nl-NL',False),('fr-FR',True)]:
        context=browser.new_context(locale=locale,viewport={'width':390,'height':844})
        if blocked:context.add_init_script("Object.defineProperty(window,'localStorage',{get(){throw new DOMException('Disabled for synthetic check','SecurityError')}})")
        else:context.add_init_script("if(!sessionStorage.getItem('seeded')){localStorage.setItem('library-workbench.language.v1','unsupported');localStorage.setItem('library-workbench.sidebar-size.v1','invalid');sessionStorage.setItem('seeded','1')}")
        other=context.new_page();errors=[];other.on('pageerror',lambda e:errors.append(str(e)))
        other.goto(base,wait_until='networkidle');expected='fr' if blocked else 'pl' if locale=='pl-PL' else 'en'
        assert other.locator('html').get_attribute('lang')==expected
        assert other.locator('#sidebar-size').input_value()=='standard'
        other.select_option('#language','de');other.wait_for_function('document.documentElement.lang==="de" && document.documentElement.dataset.languageBusy!=="true"')
        assert other.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1')
        other.screenshot(path=str(output/('narrow-'+locale+'.png')))
        if not blocked:other.reload(wait_until='networkidle');assert other.locator('html').get_attribute('lang')=='de'
        assert not errors,errors
        context.close()
    return {'grouped_navigation':True,'sidebar_preference':True,'loaded_workspace_capture_ui':True,'centered_modal_progress':True,'colour_cloud_and_drilldown':True,'stable_horizontal_inspector':True,'summary_card_readability':True,'locale_fallback_and_blocked_storage':True,'narrow_layout':True,'capture_transport':'synthetic stub; no personal input files','duplicate_review':duplicate_review}
