"""Real-browser recovery and stacked enrichment flows with synthetic responses."""
from copy import deepcopy
from urllib.parse import urlsplit, parse_qs


def check_recovery_queue_ui(browser,base,sid,output):
    context=browser.new_context(locale='en-US',viewport={'width':1440,'height':1000})
    context.add_init_script("localStorage.setItem('library-workbench.language.v1','en')")
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    staged=False;stage_requests=[]
    session={'id':'recovery-fixture','name':'Recovery fixture','metadata':{'name':'Recovery fixture','version':'7','input_check':'synthetic'},
             'counts':{'tracks':2,'pairs':0,'xml_tracks':2,'ready':0,'auto':0},'events':[],
             'policy':'newest','staged':0,'relocations':0,'metadata_override_fields':0}
    candidate={'path':'/Synthetic/Renamed.wav','export_uri':'file:///Synthetic/Renamed.wav',
               'size':42,'mtime_ns':1,'evidence':['tags_and_duration'],
               'tags':{'title':'Synthetic song','artist':'Synthetic DJ','duration':3}}
    def inventory(route):
        status=parse_qs(urlsplit(route.request.url).query).get('status',['all'])[0]
        rows=[{'track_id':'unique','title':'Synthetic <img src=x>','artist':'DJ','status':'found','candidate_count':1,'candidates':[candidate],
               'staged_uri':candidate['export_uri'] if staged else None},
              {'track_id':'ambiguous','title':'Ambiguous','artist':'DJ','status':'ambiguous','candidate_count':2,
               'candidates':[candidate,{**candidate,'path':'/Synthetic/Another.wav'}]}]
        if status=='unresolved':rows=rows[1:]
        route.fulfill(json={'scan_id':'scan-one','advanced':True,'complete':True,'warnings':[],
                            'counts':{'found':1,'ambiguous':1},'total':len(rows),'rows':rows,'file_count':2})
    def stage(route):
        nonlocal staged
        body=route.request.post_data_json;stage_requests.append(body)
        assert body['workspace']==session['id'] and body['scan_id']=='scan-one'
        staged=not body['undo'];session['relocations']=int(staged)
        route.fulfill(json={'session':session})
    context.route('**/api/inventory?**',inventory)
    context.route('**/api/inventory/stage',stage)
    context.route('**/api/playback/availability',lambda r:r.fulfill(json={'tracks':{},'statuses':{}}))
    try:
        page.goto(base,wait_until='networkidle')
        page.locator('.workflow-library-entries').scroll_into_view_if_needed()
        cards=page.locator('.workflow-library-entries>article')
        first,second=cards.nth(0).bounding_box(),cards.nth(1).bounding_box()
        assert abs(first['y']-second['y'])<2 and abs(first['width']-second['width'])<2
        page.screenshot(path=str(output/'workflow-library-cards.png'))
        page.locator('[data-open-serato]').click()
        assert page.locator('.serato-entry').get_attribute('open') is not None
        page.evaluate('(s)=>{session=s;renderSession();showView("inventory");}',session)
        page.wait_for_selector('[data-inventory-ref="unique"]')
        assert page.locator('#inventory-list img').count()==0
        assert page.locator('[data-inventory-ref="ambiguous"]').is_disabled()
        assert 'Tags and duration' in page.locator('#inventory-list').inner_text()
        page.locator('[data-inventory-ref="unique"]').click()
        page.wait_for_function('document.querySelector("[data-inventory-ref=unique]").textContent==="Undo"')
        page.locator('[data-inventory-ref="unique"]').click()
        page.wait_for_function('document.querySelector("[data-inventory-ref=unique]").textContent==="Stage reference"')
        assert [r['undo'] for r in stage_requests]==[False,True]
        page.select_option('#inventory-status','unresolved')
        page.wait_for_function('document.querySelectorAll("[data-inventory-ref]").length===1')
        assert page.locator('[data-inventory-ref="ambiguous"]').count()==1
        assert page.locator('#inventory-report').is_visible()
        page.set_viewport_size({'width':390,'height':850})
        page.locator('#inventory-list').scroll_into_view_if_needed()
        page.screenshot(path=str(output/'recovery-narrow.png'))
        page.set_viewport_size({'width':1440,'height':1000})

        # Submit three independent previews through the actual controls.
        batches=[];connected=False;prepared=False;target_requests=[];delayed_targets=[]
        source='session:synthetic-current'
        def lab(route):
            response=route.fetch();data=response.json();data['musicbrainz_enabled']=True
            data['musicbrainz_forced_off']=False;route.fulfill(json=data)
        def musicbrainz(route):
            nonlocal prepared
            path=urlsplit(route.request.url).path;action=path.rsplit('/',1)[-1]
            if action=='context':
                route.fulfill(json={'sources':[{'id':source,'label':'Current test library','kind':'workspace'}] if connected else [],
                    'snapshots':[{'id':sid,'scope_key':source,'label':'Prepared current library','created':'2026-11-15'}] if connected and prepared else []});return
            if action=='prepare':
                assert route.request.post_data_json['source']==source
                prepared=True;route.fulfill(json={'job':'synthetic-prepare'});return
            if action=='batches':route.fulfill(json={'batches':batches});return
            if action=='preview':
                include=route.request.post_data_json['include_unavailable']
                assert include is (len(batches)==2)
                identity='synthetic-batch-'+str(len(batches)+1)
                batch={'id':identity,'snapshot_id':sid,'label':'Synthetic '+str(len(batches)+1),
                       'created':'2026-11-15T12:00:00Z','status':'preview','total':3,'rows':[],
                       'summary':{'tracks':3,'done':0,'requests':0,'cache_hits':0,'groups':[],
                                  'target':'random','target_value':'','playable_only':not include,'excluded_unplayable':2 if not include else 0}}
                batches.append(batch);route.fulfill(json=batch);return
            if action=='start':
                identity=path.split('/')[-2];batch=next(b for b in batches if b['id']==identity)
                batch['status']='running' if not any(b['status']=='running' for b in batches) else 'queued'
                batch['queue_position']=batches.index(batch)+1
                route.fulfill(json={'batch_id':identity,'job':'synthetic','background':True});return
            batch=next((b for b in batches if b['id']==action),None)
            if batch:route.fulfill(json=batch)
            else:route.fallback()
        context.route('**/api/lab',lab)
        context.route('**/api/lab/musicbrainz/**',musicbrainz)
        context.route('**/api/tasks/synthetic-prepare',lambda route:route.fulfill(json={'status':'complete','progress':100,'result':{'id':sid,'source':source}}))
        page.evaluate('session=null')
        page.locator('.nav[data-view="musicbrainz"]').click()
        page.wait_for_selector('#musicbrainz-source-note',state='visible')
        assert page.locator('#lab-pilot-preview').is_disabled()
        assert page.locator('#lab-pilot-start').is_disabled()
        connected=True;page.evaluate('()=>loadMusicBrainz()')
        assert page.locator('#musicbrainz-library').input_value()==source
        page.locator('#musicbrainz-prepare').click()
        page.wait_for_selector('#musicbrainz-snapshot option[value="'+sid+'"]',state='attached')
        # A delayed first category fetch displays loading, and switching the
        # category while it is pending shares the same request.
        target_mode='delay'
        choices={'genres':[{'value':'House','label':'House','tracks':3}],
                 'albums':[{'value':'Collection','label':'Collection','tracks':3}],'years':[],'playlists':[]}
        def targets(route):
            target_requests.append(route.request.url)
            if target_mode=='fail':route.abort('failed')
            elif target_mode=='ready':route.fulfill(json=choices)
            else:delayed_targets.append(route)
        context.route('**/api/lab/musicbrainz/targets?**',targets)
        page.select_option('#lab-pilot-target','genre')
        page.wait_for_function('document.querySelector("#lab-pilot-target-value").getAttribute("aria-busy")==="true"')
        assert page.locator('#lab-pilot-target-value').is_disabled()
        # Firefox does not expose closed native option text through innerText.
        assert page.locator('#lab-pilot-target-value').evaluate('(s)=>s.selectedOptions[0]?.text')=='Loading'
        page.select_option('#lab-pilot-target','album')
        page.wait_for_timeout(100)
        assert len(target_requests)==1
        delayed_targets[0].fulfill(json=choices)
        page.wait_for_function('document.querySelector("#lab-pilot-target-value").value==="Collection"')
        page.select_option('#lab-pilot-target','genre')
        page.wait_for_function('document.querySelector("#lab-pilot-target-value").value==="House"')
        assert len(target_requests)==1
        page.evaluate('musicBrainzTargetCache.clear()');target_mode='fail'
        page.select_option('#lab-pilot-target','year')
        page.wait_for_selector('#musicbrainz-target-retry',state='visible')
        assert page.locator('#lab-pilot-target-value').is_disabled()
        target_mode='ready';page.locator('#musicbrainz-target-retry').click()
        page.wait_for_function('document.querySelector("#lab-pilot-target-value").textContent.includes("No matching references")')
        assert page.locator('#musicbrainz-target-retry').is_hidden()
        page.select_option('#lab-pilot-target','random')
        for index in range(3):
            if index==2:page.locator('#lab-pilot-include-unavailable').check()
            page.locator('#lab-pilot-seed').fill('queue-'+str(index))
            page.locator('#lab-pilot-preview').click()
            page.wait_for_function('(id)=>labBatch===id && labPilotStatus==="preview"',arg='synthetic-batch-'+str(index+1))
            page.locator('#lab-pilot-consent').check()
            page.locator('#lab-pilot-start').click()
            page.wait_for_function('(n)=>document.querySelectorAll("[data-pilot-batch]").length===n',arg=index+1)
        assert [b['status'] for b in batches]==['running','queued','queued']
        assert '1 running' in page.locator('#pilot-background-text').inner_text()
        assert '2 queued' in page.locator('#pilot-background-text').inner_text()
        # The running batch opens first even when a newer queued batch exists.
        page.locator('#pilot-background-open').click()
        page.wait_for_function('labBatch==="synthetic-batch-1"')
        page.wait_for_function('document.querySelector("#lab-pilot-progress").getBoundingClientRect().bottom<innerHeight')
        # Wait for scrolling, then use the DOM viewport rectangle consistently.
        # WebKit's protocol box can report the pre-sticky layout position.
        page.wait_for_function('()=>{const y=document.querySelector("#pilot-background").getBoundingClientRect().top;return y>=0 && y<=10;}')
        banner_y=page.locator('#pilot-background').evaluate('(n)=>n.getBoundingClientRect().top')
        assert 0<=banner_y<=10,banner_y
        page.screenshot(path=str(output/'enrichment-running-banner.png'))
        page.locator('#pilot-background-dismiss').click();page.evaluate('()=>BackgroundPilot.refresh()')
        assert page.locator('#pilot-background').is_hidden()
        batches[0].update(status='complete',queue_position=None)
        batches[0]['summary'].update(done=3,requests=6)
        batches[1].update(status='running',queue_position=1);batches[2]['queue_position']=2
        page.evaluate('()=>BackgroundPilot.refresh()')
        assert page.locator('#pilot-background').is_visible()
        assert page.locator('[data-pilot-batch="synthetic-batch-1"]').count()==1
        assert '3 / 3' in page.locator('[data-pilot-batch="synthetic-batch-1"]').locator('..').inner_text()
        page.locator('[data-pilot-batch="synthetic-batch-3"]').click()
        page.wait_for_function('labBatch==="synthetic-batch-3" && labPilotStatus==="queued"')
        page.reload(wait_until='networkidle')
        page.locator('.nav[data-view="musicbrainz"]').click()
        page.wait_for_function('document.querySelectorAll("[data-pilot-batch]").length===3')
        assert page.locator('#lab-pilot-batches').input_value()=='synthetic-batch-3'
        assert '1 queued' in page.locator('#pilot-background-text').inner_text()
        page.locator('#lab-pilot-queue').scroll_into_view_if_needed()
        page.screenshot(path=str(output/'enrichment-stacked-batches.png'))
        connected=False;page.evaluate('()=>loadMusicBrainz()')
        assert page.locator('#lab-pilot-preview').is_disabled()
        assert page.locator('#lab-pilot-start').is_disabled()
        assert page.locator('[data-pilot-batch]').count()==3
        assert not errors,errors
        return {'recovery_staging_undo':True,'unresolved_filter':True,'candidate_escaping':True,
                'stacked_previews':3,'queue_survives_reload':True,'completed_rows_retained':True,
                'current_library_required':True,'automatic_local_preparation':True,'loading_visible':True,
                'category_request_deduplication':True,'category_retry':True,'sticky_notice_and_dismissal':True,
                'playable_default_and_opt_in':True,'workflow_cards':True}
    finally:
        context.close()
