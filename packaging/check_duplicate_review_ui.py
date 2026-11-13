"""CI-only review layout and selection checks, using synthetic browser responses."""
from copy import deepcopy
import json
from urllib.parse import parse_qs, urlsplit
import urllib.request


def review_fixture():
    """No XML/ZIP inputs, source paths or personal records are opened by this fixture."""
    title='Synthetic extended mix · Łódź · Ελληνικά · 日本語 🎧 — a long recording title'
    tracks=[]
    for sibling in ('a','b'):
        tracks.append({
            'track_id':'synthetic-'+sibling,'title':title+(' <img src=x onerror="window.duplicateMetadataExecuted=1">' if sibling=='b' else ''),
            'album':'Synthetic album · édition longue / complete collection',
            'rating':4 if sibling=='a' else 2,
            'cue_summary':{'auto':1,'other':1},'date_added':'2026-10-17','last_played':'2026-10-20',
            'play_count':12,'size_bytes':28_000_000,'october_xml':True,'duration_seconds':360,
            'xml_location':'file://localhost/C:/Synthetic%20Music/Dropbox/Long%20collection%20folder/'+('nested%20folder/'*5)+sibling+'.flac',
            'cues':[{'Comment':'Cue(auto)','InMsec':0},{'Comment':'Synthetic manual cue','InMsec':65_000}],
        })
    pair={'id':'synthetic-pair','title':title,'artist':'Synthetic artist · Автор & Édition',
          'keeper':'synthetic-a','keeper_reason':'Synthetic manual cue evidence','cue_equal':False,
          'grid_differs':False,'tracks':tracks,'conflicts':[{'type':'rating'},{'type':'cue_slot','auto':True}]}
    session={'name':'Synthetic duplicate review','metadata':{'input_check':'Synthetic responses only','version':'7.0','import_mode':'linked',
              'zip_path':'/synthetic/not-opened/library.zip','xml_path':'/synthetic/not-opened/library.xml','playlist_options':[]},
             'counts':{'tracks':2,'xml_tracks':2,'pairs':1,'ready':0,'auto':0},'staged':0,'relocations':0,
             'metadata_override_fields':0,'policy':'newest','events':[]}
    return session,pair


def check_duplicate_review_ui(browser,base,output):
    """Exercise the real UI handlers; intercept every synthetic decision before HTTP."""
    with urllib.request.urlopen(base+'/api/status') as response:status=json.load(response)
    session,pair=review_fixture();decisions=[];evidence_queries=[];errors=[];unexpected_mutations=[]
    context=browser.new_context(locale='en-US',viewport={'width':1440,'height':1000})
    context.add_init_script("localStorage.setItem('library-workbench.language.v1','en');localStorage.setItem('library-workbench.sidebar-size.v1','standard')")
    def synthetic_api(route):
        request=route.request;url=urlsplit(request.url);path=url.path
        if path=='/api/status':route.fulfill(json={**status,'session':deepcopy(session),'example_available':False});return
        if path=='/api/pairs':
            evidence_queries.append(parse_qs(url.query).get('evidence',[''])[0])
            row={key:pair[key] for key in ('id','title','artist','cue_equal')}
            row.update(category='review',cue_a={'total':2},cue_b={'total':2},decision=pair.get('decision'))
            route.fulfill(json={'rows':[row],'total':1,'groups':1,'tracks':2,'pair_count':1,'review_groups':1,'potential_reduction':1,
                                'facets':{'files_found_both':1,'manual_present':1,'rating_conflict':1}});return
        if path=='/api/pair/synthetic-pair':route.fulfill(json=deepcopy(pair));return
        if path=='/api/statistics':
            route.fulfill(json={'counters':{'total':2,'rated':2,'analysed':2},'histogram':[],
                                'addition_dates':{'years':[{'year':2026,'tracks':2}],'unknown':0}});return
        if path=='/api/decision':
            assert request.method=='POST'
            decision=request.post_data_json;decisions.append(decision)
            pair['decision']=decision;session['staged']=1
            route.fulfill(json={'session':deepcopy(session)});return
        # A regression must never send a synthetic decision to the real application.
        if request.method!='GET':unexpected_mutations.append(path);route.abort();return
        route.continue_()
    context.route('**/api/**',synthetic_api)
    page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        page.goto(base,wait_until='networkidle')
        page.wait_for_selector('#detail-panel [data-keeper="synthetic-a"]',state='attached')
        page.locator('.nav[data-view="review"]').click()
        page.wait_for_selector('#detail-panel .sibling.chosen')
        assert page.locator('#toast').is_hidden() or not page.locator('#toast').inner_text(),page.locator('#toast').inner_text()
        assert page.locator('#detail-panel img').count()==0
        assert page.evaluate('window.duplicateMetadataExecuted') is None
        assert page.locator('[data-keeper="synthetic-b"] .title').inner_text()==pair['tracks'][1]['title']
        # Native checkbox dimensions and complete labels, rather than drawn stand-ins.
        controls=page.locator('#view-review input[type="checkbox"]')
        assert controls.count()>=4
        assert controls.evaluate_all('''els=>els.every(el=>{const r=el.getBoundingClientRect(),label=el.closest('label'),s=getComputedStyle(label);return r.width>=18 && r.height>=18 && parseFloat(s.fontSize)>=12 && label.getBoundingClientRect().height>=40 && getComputedStyle(el).opacity==='1'})''')
        evidence=page.locator('#evidence-filters label').filter(has=page.locator('[data-evidence="files_found_both"]'))
        with page.expect_response(lambda response:urlsplit(response.url).path=='/api/pairs'):
            evidence.locator('span').click()
        assert page.locator('[data-evidence="files_found_both"]').is_checked()
        assert any('files_found_both' in query.split(',') for query in evidence_queries)

        candidates=page.locator('#view-review .list-panel').bounding_box()
        detail=page.locator('#detail-panel').bounding_box()
        assert detail['width']>=candidates['width']*1.8,(candidates,detail)
        assert detail['x']<page.viewport_size['width']*.55,(candidates,detail)
        first=page.locator('[data-keeper="synthetic-a"]').bounding_box()
        second=page.locator('[data-keeper="synthetic-b"]').bounding_box()
        assert second['x']>=first['x']+first['width'] and abs(second['y']-first['y'])<2
        assert page.locator('.sibling dl').evaluate_all('els=>els.every(el=>parseFloat(getComputedStyle(el).fontSize)>=12)')
        assert page.locator('.sibling .path').evaluate_all('els=>els.every(el=>el.scrollWidth<=el.clientWidth+1 && parseFloat(getComputedStyle(el).fontSize)>=12)')
        page.locator('[data-keeper="synthetic-b"]').click()
        assert page.locator('[data-keeper="synthetic-b"]').evaluate('el=>el.classList.contains("chosen")')
        page.locator('[data-keeper="synthetic-a"]').focus();page.keyboard.press('Space')
        assert page.locator('[data-keeper="synthetic-a"]').evaluate('el=>el.classList.contains("chosen")')
        page.locator('[data-keeper="synthetic-b"]').focus();page.keyboard.press('Enter')
        assert page.locator('[data-keeper="synthetic-b"]').evaluate('el=>el.classList.contains("chosen")')
        page.locator('#accept-auto').check();page.locator('#accept-rating').check()
        for theme in ('light','dark'):
            page.select_option('#theme',theme)
            page.locator('.sibling-cards').scroll_into_view_if_needed()
            page.screenshot(path=str(output/('duplicate-review-'+theme+'.png')))
        with page.expect_response(lambda response:urlsplit(response.url).path=='/api/decision'):
            page.locator('#stage-pair').click()
        page.wait_for_selector('#undo-pair')
        page.wait_for_function('document.querySelector("#toast").textContent==="Decision saved to this workspace"')
        assert decisions==[{'pair':'synthetic-pair','action':'merge','keeper':'synthetic-b','prefer_auto':True,'prefer_rating':True}],decisions
        assert page.locator('[data-keeper="synthetic-b"]').evaluate('el=>el.classList.contains("chosen")')

        page.set_viewport_size({'width':390,'height':844})
        page.select_option('#language','de');page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
        page.locator('.review-layout').scroll_into_view_if_needed()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        candidates=page.locator('#view-review .list-panel').bounding_box();detail=page.locator('#detail-panel').bounding_box()
        assert detail['y']>=candidates['y']+candidates['height'],(candidates,detail)
        first=page.locator('[data-keeper="synthetic-a"]').bounding_box();second=page.locator('[data-keeper="synthetic-b"]').bounding_box()
        assert second['y']>=first['y']+first['height'] and abs(second['x']-first['x'])<2
        assert first['width']>=detail['width']*.8
        page.locator('.sibling-cards').scroll_into_view_if_needed()
        page.screenshot(path=str(output/'duplicate-review-narrow.png'))
        assert not errors,errors
        assert not unexpected_mutations,unexpected_mutations
        assert page.locator('#toast').is_hidden() or page.locator('#toast').inner_text()=='Decision saved to this workspace',page.locator('#toast').inner_text()
        return {'readable_native_controls':True,'comparison_width_prioritized':True,'mouse_and_keyboard_keeper':True,
                'decision_payload_preserved':True,'escaped_unicode_metadata':True,'responsive_german_layout':True,
                'transport':'synthetic browser responses; no source files or real decisions'}
    finally:
        context.close()
