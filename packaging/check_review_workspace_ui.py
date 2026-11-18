"""Long-list interaction checks with intercepted, entirely invented native records."""
from ui_navigation import select_collection, open_collection_picker
from urllib.parse import urlsplit


def check_review_workspace_ui(browser,base,source,output):
    context=browser.new_context(locale='en-US',viewport={'width':1715,'height':1000})
    context.add_init_script("localStorage.setItem('library-workbench.language.v1','en')")
    reviews={};writes=[];errors=[];held=[];hold_save=False
    def duplicates(route):
        request=route.request;path=urlsplit(request.url).path
        if path.endswith('/review'):
            value=request.post_data_json;writes.append(value);reviews[path.split('/')[-2]]=value['status']
            if hold_save:
                held.append(route);return
            route.fulfill(json={'saved':True});return
        if path=='/api/collection/duplicates':
            route.fulfill(json={'note':'Synthetic long list; no library files are opened.', 'groups':50,'tracks':100,'total':50,'offset':0,
                'rows':[{'id':'g'+str(i),'title':'Synthetic recording '+str(i),'artist':'Synthetic artist',
                         'count':2,'duration_spread':0,'review':reviews.get('g'+str(i),'unreviewed')} for i in range(50)]});return
        identity=path.split('/')[-1]
        route.fulfill(json={'total':50,'offset':0,'review':reviews.get(identity,'unreviewed'),
            'rows':[{'id':'synthetic-member-'+str(i),'title':'Synthetic sibling '+str(i),'artist':'Synthetic artist',
                     'duration':240,'rating':4,'play_count':1,'manual_cues':2,'auto_cues':1,
                     'current_path':'/Synthetic/Music/'+('long-folder/'*6)+str(i)+'.flac'} for i in range(50)]})
    context.route('**/api/collection/duplicates**',duplicates)
    context.route('**/api/playback/availability',lambda route:route.fulfill(json={'tracks':{i:False for i in route.request.post_data_json['track_ids']}}))
    page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        page.goto(base,wait_until='networkidle')
        page.select_option('#theme','light')
        select_collection(page,'#journey-context-source',source)
        page.wait_for_function('(source)=>Journeys.context()?.source===source',arg=source)
        page.locator('.nav[data-view=review]').click();page.wait_for_selector('[data-native-group="g49"]')
        page.locator('.native-review-workspace').scroll_into_view_if_needed()
        density=page.locator('.review-candidates>.native-table').evaluate('''e=>{
            const bounds=e.getBoundingClientRect(),head=e.querySelector('thead').getBoundingClientRect();
            return {visible:[...e.querySelectorAll('tbody tr')].filter(row=>{const r=row.getBoundingClientRect();return r.top>=head.bottom && r.bottom<=bounds.bottom;}).length,
                height:e.clientHeight,scrollWidth:e.scrollWidth,width:e.clientWidth,
                rows:[...e.querySelectorAll('tbody tr')].slice(0,2).map(row=>({height:row.getBoundingClientRect().height,cells:[...row.cells].map(cell=>({text:cell.textContent,width:cell.clientWidth,padding:getComputedStyle(cell).padding,font:getComputedStyle(cell).fontSize}))}))};
        }''')
        page.screenshot(path=str(output/'native-duplicate-candidate-density.png'))
        assert density['visible']>=12,density
        assert density['scrollWidth']<=density['width']+1,density
        assert page.locator('.native-review-note').get_attribute('open') is None
        page.locator('[data-native-group="g0"]').click();page.wait_for_selector('.native-compare-record')
        assert page.locator('.native-compare-record').count()==50
        assert page.locator('.native-compare-record').first.locator('dd').all_text_contents()==['240','Unknown','4','1','2','1']
        assert '/Synthetic/Music/' in page.locator('.native-record-path code').first.inner_text()
        assert page.locator('.native-save').bounding_box()['y']<page.locator('.native-compare-record').first.bounding_box()['y']
        page.screenshot(path=str(output/'native-duplicate-review-dense.png'))
        page.locator('[data-native-group="g49"]').click();page.wait_for_selector('.native-save')
        left=page.locator('.native-review-workspace>.review-candidates').bounding_box()
        right=page.locator('.native-detail').bounding_box()
        assert right['x']>=left['x']+left['width'] and abs(right['y']-left['y'])<2,(left,right)
        assert left['width']>right['width'],(left,right)
        assert page.locator('.native-detail .review-close').is_hidden()
        table=page.locator('.native-review-workspace>.review-candidates>.native-table')
        assert table.evaluate('(e)=>e.scrollTop')>0
        assert page.locator('[data-native-group="g49"]').evaluate('(e)=>{const r=e.getBoundingClientRect(),p=e.closest(".native-table").getBoundingClientRect();return r.left>=p.left && r.right<=p.right && r.top>=p.top && r.bottom<=p.bottom}')
        for position in ('start','end'):
            page.locator('.native-detail .review-inspector-body').evaluate('(e,end)=>e.scrollTop=end?e.scrollHeight:0',position=='end')
            assert page.locator('.native-save').evaluate('(e)=>{const r=e.getBoundingClientRect();return r.top>=0 && r.bottom<=innerHeight}'),position
        old_scroll=table.evaluate('(e)=>e.scrollTop')
        page.select_option('.native-status','keep_separate');page.locator('.native-save').click()
        page.wait_for_function('document.querySelector(".native-status")?.value==="keep_separate"')
        assert writes==[{'source':source,'basis':'path','status':'keep_separate'}],writes
        assert table.evaluate('(e)=>e.scrollTop')>=old_scroll-2
        page.screenshot(path=str(output/'native-duplicate-review-split.png'))
        for width in (768,390):
            page.set_viewport_size({'width':width,'height':844})
            page.locator('[data-native-group="g49"]').click();page.wait_for_selector('.review-drawer[open] .native-save')
            page.locator('.review-drawer[open]').evaluate('(e)=>Promise.all(e.getAnimations().map(a=>a.finished))')
            assert page.locator('.native-save').evaluate('(e)=>{const r=e.getBoundingClientRect();return r.left>=0 && r.right<=innerWidth && r.bottom<=innerHeight}')
            assert page.locator('.native-status').input_value()=='keep_separate'
            for key in ('Tab','Shift+Tab'):
                for _ in range(8):
                    page.keyboard.press(key)
                    assert page.evaluate('Boolean(document.activeElement.closest(".review-drawer"))')
            page.screenshot(path=str(output/('native-review-drawer-'+str(width)+'.png')))
            page.keyboard.press('Escape');page.wait_for_selector('.review-drawer[open]',state='hidden')
            assert page.locator('[data-native-group="g49"]').evaluate('(e)=>e===document.activeElement')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.keyboard.press('Enter');page.wait_for_selector('.review-drawer[open]')
        page.set_viewport_size({'width':1715,'height':1000});page.wait_for_selector('.review-drawer[open]',state='hidden')
        assert page.locator('.native-status').input_value()=='keep_separate'
        # A delayed save may finish after the user navigates elsewhere. It must
        # not reopen the inspector or move keyboard focus back into Review.
        hold_save=True
        with page.expect_request(lambda request:urlsplit(request.url).path.endswith('/review')):
            page.locator('.native-save').click()
        page.locator('.nav[data-view=intelligence]').click();page.wait_for_selector('#view-intelligence',state='visible')
        assert len(held)==1
        with page.expect_response(lambda response:urlsplit(response.url).path.endswith('/review')):
            held.pop().fulfill(json={'saved':True})
        page.wait_for_load_state('networkidle')
        assert page.locator('.review-drawer[open]').count()==0
        assert page.locator('#view-review').is_hidden()
        assert not page.evaluate('Boolean(document.activeElement.closest("#view-review"))')
        # Long result areas must not push their actions out of reach. These
        # invented paragraphs exercise layout only; no remote chart is fetched.
        for results,action in (('#intelligence-results','#intelligence-save'),('#chart-results','#chart-export')):
            page.locator(results).evaluate('''e=>{
                if(e.closest('details'))e.closest('details').open=true;
                e.replaceChildren(...Array.from({length:100},(_,i)=>{
                    const p=document.createElement('p');p.textContent='Synthetic result '+i;return p;
                }));
            }''')
            page.locator(results+' p').nth(40).scroll_into_view_if_needed()
            assert page.locator(action).evaluate('(e)=>{const r=e.getBoundingClientRect();return r.top>=0 && r.bottom<=innerHeight}'),action
            page.screenshot(path=str(output/('visible-actions-'+results[1:]+'.png')))
        assert not errors,errors
        return {'long_list':50,'long_comparison':50,'visible_candidate_rows':density['visible'],'wider_candidates':True,'compact_record_cards':True,'save_above_records':True,'split_panes':True,'persistent_save_action':True,
                'list_scroll_preserved_after_save':True,'drawer_widths':[768,390],
                'keyboard_focus_trap_and_return':True,'resize_preserves_review':True,'late_save_respects_navigation':True,
                'chart_and_intelligence_actions_visible_during_scroll':True,'synthetic':True}
    finally:
        context.close()
