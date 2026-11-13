"""CI-only file-view quick edits, using synthetic responses and no input files."""
from copy import deepcopy
import json
from urllib.parse import urlsplit
import urllib.request

from track_tags import PALETTE


def check_track_details_ui(browser,base,output):
    with urllib.request.urlopen(base+'/api/status') as response:status=json.load(response)
    sid='synthetic-quick-edit-snapshot';tid='synthetic-quick-edit-track'
    original={'id':tid,'title':'Synthetic file view · Łódź Ελληνικά 🎧','artist':'Synthetic artist',
              'album':'Synthetic album','genre':'House','year':2026,'rating':3,'bpm':124,'duration':300,
              'comment':'Captured private comment','colour':'#FF007F','color_hex':'#FF007F',
              'color_name':'Opening · custom label','color_status':'assigned','play_count':12}
    edits={};writes=[];errors=[];unexpected=[];fail_colour=False
    palette=[{'name':name,'value':hex_value,'hex':hex_value,'supported':name!='Violet',
              'reason':'Synthetic missing native mapping' if name=='Violet' else '',
              'native_name':'Closing <img src=x onerror="window.quickEditExecuted=1">' if name=='Blue' else None}
             for name,hex_value in PALETTE]
    palette.append({'name':'No assigned colour','value':'','hex':None,'supported':True,'reason':''})
    def record():
        return {'original':deepcopy(original),'overrides':deepcopy(edits),'unlocked':False,
                'editable_fields':['title','artist','album','genre','year','rating'],'scope':'capture:synthetic-quick-edits',
                'snapshot_label':'Synthetic quick edits','comment_captured':True,'colour_palette':palette,
                'colour_editable':True,'colour_edit_reason':'','export_scope':'snapshot sidecar only'}
    context=browser.new_context(locale='en-US',viewport={'width':1440,'height':1000})
    context.add_init_script("localStorage.setItem('library-workbench.language.v1','en')")
    def synthetic_api(route):
        nonlocal fail_colour
        request=route.request;path=urlsplit(request.url).path
        if path=='/api/status':route.fulfill(json={**status,'session':None,'example_available':False});return
        if path=='/api/lab':
            route.fulfill(json={'snapshots':[{'id':sid,'label':'Synthetic quick edits','scope_key':'capture:synthetic-quick-edits','created':'2026-11-01T12:00:00Z'}],
                                'sources':[],'reports':[],'workspace':None,'musicbrainz_enabled':False,
                                'musicbrainz_forced_off':True,'speeds':{},'fields':['title','artist','album','genre','year','rating']});return
        if path=='/api/lab/tracks':
            route.fulfill(json={'rows':[{'original':deepcopy(original),'overrides':deepcopy(edits)}],
                                'unlocked':False,'scope':'capture:synthetic-quick-edits','override_fields':len(edits),'total':1,'offset':0});return
        if path=='/api/lab/track':route.fulfill(json=record());return
        if path=='/api/lab/overrides':
            payload=request.post_data_json;writes.append((request.method,deepcopy(payload)))
            assert payload['snapshot']==sid and payload['track_id']==tid
            field=payload['field'];assert field in ('comment','colour')
            if field=='colour' and fail_colour:
                fail_colour=False;route.fulfill(status=400,json={'error':'Synthetic rejected colour edit'});return
            if request.method=='DELETE':
                edits.pop(field,None);route.fulfill(json={'reset':True,'overrides':deepcopy(edits)});return
            assert request.method=='POST'
            edits[field]={'value':payload['value'],'baseline':original[field],'origin':'user','updated':'synthetic'}
            route.fulfill(json={'value':payload['value'],'overrides':deepcopy(edits)});return
        # Never submit synthetic edits, unlocks or other mutations to the real app.
        if request.method!='GET':unexpected.append(path);route.abort();return
        route.continue_()
    context.route('**/api/**',synthetic_api)
    page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        page.goto(base,wait_until='networkidle')
        page.locator('.nav[data-view="lab"]').click()
        page.locator('[data-lab-tab="editor"]').click()
        page.locator('[data-lab-edit="0"]').click()
        page.wait_for_selector('#track-detail-dialog[open]')
        assert page.locator('#track-comment-text').is_visible()
        assert page.locator('#track-comment-text').input_value()==original['comment']
        assert not page.locator('#track-detail-unlock').is_checked()
        assert page.locator('[data-track-edit-field]').evaluate_all('els=>els.every(el=>el.disabled)')
        assert page.locator('.track-colour-choice').count()==9
        assert page.locator('[data-track-colour="#660099"]').is_disabled()
        assert page.locator('[data-track-colour="#FF007F"]').get_attribute('aria-pressed')=='true'
        assert original['color_name'] in page.locator('#track-colour-original').inner_text()
        assert page.locator('#track-colour-palette img').count()==0
        assert page.evaluate('window.quickEditExecuted') is None
        assert page.locator('.track-colour-choice').evaluate_all('els=>els.every(el=>el.innerText.trim() && el.getAttribute("aria-pressed")!==null && el.getBoundingClientRect().height>=40)')

        draft='Unsaved private comment · Ελληνικά Łódź 🎧 <mix> {slot0}'
        page.fill('#track-comment-text',draft)
        assert page.locator('#track-working-count').inner_text()=='0'
        page.locator('[data-track-colour="#0000FF"]').click()
        page.wait_for_function('document.querySelector("[data-track-colour=\\"#0000FF\\"]").getAttribute("aria-pressed")==="true" && !document.querySelector("[data-track-colour=\\"#0000FF\\"]").disabled')
        assert page.locator('#track-detail-dialog').evaluate('el=>el.open')
        assert page.locator('#track-comment-text').input_value()==draft
        assert page.locator('#track-working-count').inner_text()=='1'
        assert 'Comments' not in page.locator('#track-working-list').inner_text()
        assert writes==[('POST',{'snapshot':sid,'track_id':tid,'field':'colour','value':'#0000FF'})]

        # Keyboard activation, clear and reset must preserve the comment draft.
        page.locator('[data-track-colour="#00FF00"]').focus();page.keyboard.press('Enter')
        page.wait_for_function('document.querySelector("[data-track-colour=\\"#00FF00\\"]").getAttribute("aria-pressed")==="true" && !document.querySelector("[data-track-colour=\\"#00FF00\\"]").disabled')
        assert page.locator('#track-detail-dialog').evaluate('el=>el.open')
        assert page.locator('#track-comment-text').input_value()==draft
        assert page.locator('[data-track-colour="#00FF00"]').evaluate('el=>document.activeElement===el')
        page.locator('[data-track-colour=""]').click()
        page.wait_for_function('document.querySelector("[data-track-colour=\\"\\"]").getAttribute("aria-pressed")==="true" && !document.querySelector("[data-track-colour=\\"\\"]").disabled')
        assert page.locator('#track-detail-dialog').evaluate('el=>el.open')
        assert page.locator('#track-comment-text').input_value()==draft
        page.locator('#track-colour-reset').click()
        page.wait_for_function('document.querySelector("#track-working-count").textContent==="0" && document.querySelector("#track-colour-palette").getAttribute("aria-busy")==="false"')
        assert page.locator('#track-detail-dialog').evaluate('el=>el.open')
        assert page.locator('#track-comment-text').input_value()==draft

        # A rejected save cannot appear as a stored edit or disable future choices.
        fail_colour=True
        page.locator('[data-track-colour="#FF0000"]').click()
        page.wait_for_function('document.querySelector("#toast").textContent.includes("Synthetic rejected colour edit") && !document.querySelector("[data-track-colour=\\"#FF0000\\"]").disabled')
        assert page.locator('#track-detail-dialog').evaluate('el=>el.open')
        assert page.locator('#track-working-count').inner_text()=='0'
        assert page.locator('[data-track-colour="#FF007F"]').get_attribute('aria-pressed')=='true'
        assert page.locator('#track-comment-text').input_value()==draft

        page.locator('[data-track-colour="#0000FF"]').click()
        page.wait_for_function('document.querySelector("#track-working-count").textContent==="1" && !document.querySelector("#track-comment-save").disabled')
        assert page.locator('#track-detail-dialog').evaluate('el=>el.open')
        assert page.locator('#track-comment-text').input_value()==draft
        page.locator('#track-comment-save').click()
        page.wait_for_function('document.querySelector("#track-working-count").textContent==="2" && document.querySelector("#track-colour-palette").getAttribute("aria-busy")==="false"')
        assert edits['comment']['value']==draft
        assert draft in page.locator('#track-working-list').inner_text()
        assert 'Closing <img' in page.locator('#track-working-list').inner_text()
        assert not page.locator('#track-detail-unlock').is_checked()
        for theme in ('light','dark'):
            page.select_option('#theme',theme);page.locator('#track-colour-palette').scroll_into_view_if_needed()
            page.screenshot(path=str(output/('file-view-quick-edits-'+theme+'.png')))
        page.set_viewport_size({'width':390,'height':844})
        assert page.locator('#track-detail-dialog').evaluate('el=>el.scrollWidth<=el.clientWidth+1')
        page.locator('#track-colour-palette').scroll_into_view_if_needed()
        page.screenshot(path=str(output/'file-view-quick-edits-narrow.png'))
        page.locator('#track-detail-dialog .close-dialog').click()
        page.locator('[data-lab-edit="0"]').click();page.wait_for_selector('#track-detail-dialog[open]')
        assert page.locator('#track-comment-text').input_value()==draft
        assert page.locator('#track-working-count').inner_text()=='2'
        page.locator('#track-comment-reset').click()
        page.wait_for_function('(comment)=>document.querySelector("#track-working-count").textContent==="1" && document.querySelector("#track-comment-text").value===comment',arg=original['comment'])
        assert page.locator('#track-comment-text').input_value()==original['comment']
        assert not errors,errors
        assert not unexpected,unexpected
        return {'comments_visible_without_click':True,'colour_palette_without_unlock':True,'keyboard_colour_selection':True,
                'draft_preserved_during_colour_save':True,'stored_edit_recap_and_reset':True,'failed_save_not_staged':True,
                'custom_colour_labels_escaped':True,'narrow_palette_layout':True,
                'transport':'synthetic intercepted responses; no original files or real edits'}
    finally:
        context.close()
