"""Synthetic CI interactions: source readiness, progress, preferences and layout."""
import json
from urllib.parse import urlsplit
import urllib.request


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
    assert page.locator('#library-bubbles').get_attribute('viewBox')=='0 0 940 680'
    assert page.locator('#bubble-empty').is_hidden()
    assert page.locator('#library-bubbles circle').evaluate_all('(els)=>els.every(el=>Number(el.getAttribute("r"))>0)')
    page.locator('#library-bubbles').scroll_into_view_if_needed()
    page.screenshot(path=str(output/'colour-cloud.png'))
    page.locator('#library-bubbles g.bubble-node').first.click();page.wait_for_function('document.querySelector("#library-bubbles").dataset.state==="ready" && document.querySelectorAll("#bubble-breadcrumbs button").length===2')
    page.locator('#bubble-reset').click();page.wait_for_function('document.querySelectorAll("#bubble-breadcrumbs button").length===1 && document.querySelector("#library-bubbles").dataset.state==="ready"')
    page.unroute('**/api/lab',library);page.unroute('**/api/lab/snapshots',capture);page.unroute('**/api/tasks/synthetic-capture',task)
    # Browser locale fallback, persistence and blocked local storage must not stop startup.
    for locale,blocked in [('pl-PL',False),('nl-NL',False),('fr-FR',True)]:
        context=browser.new_context(locale=locale,viewport={'width':390,'height':844})
        if blocked:context.add_init_script("Object.defineProperty(window,'localStorage',{get(){throw new DOMException('Disabled for synthetic check','SecurityError')}})")
        else:context.add_init_script("if(!sessionStorage.getItem('seeded')){localStorage.setItem('library-workbench.language.v1','unsupported');localStorage.setItem('library-workbench.sidebar-size.v1','invalid');sessionStorage.setItem('seeded','1')}")
        other=context.new_page();errors=[];other.on('pageerror',lambda e:errors.append(str(e)))
        other.goto(base,wait_until='networkidle');expected='fr' if blocked else 'pl' if locale=='pl-PL' else 'en'
        assert other.locator('html').get_attribute('lang')==expected
        assert other.locator('#sidebar-size').input_value()=='standard'
        other.select_option('#language','de');other.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
        assert other.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1')
        other.screenshot(path=str(output/('narrow-'+locale+'.png')))
        if not blocked:other.reload(wait_until='networkidle');assert other.locator('html').get_attribute('lang')=='de'
        assert not errors,errors
        context.close()
    return {'grouped_navigation':True,'sidebar_preference':True,'loaded_workspace_capture_ui':True,'centered_modal_progress':True,'colour_cloud_and_drilldown':True,'locale_fallback_and_blocked_storage':True,'narrow_layout':True,'capture_transport':'synthetic stub; no personal input files'}
