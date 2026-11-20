"""Cloud path suggestions remain explicit and preserve the selected source."""
from copy import deepcopy
from urllib.parse import parse_qs,urlsplit


def check_cloud_root_suggestions_ui(browser,base,fixture,output):
    from playwright.sync_api import expect
    old='C:/Users/OLD/Cloud Option DJ team Dropbox/Invented member'
    tail='electrobuzz_2026/Invented album/Track.mp3'
    snapshot={'scope_key':'synthetic:cloud-root-suggestions-ui','tracks':[
        {'id':'normal-root','title':'Invented normal song','current_path':'/'+tail,'original_path':old+'/'+tail},
        {'id':'contents-root','title':'Invented storage song','current_path':'/contents_invented/Album/Cloud.mp3',
         'original_path':'E:/Unrelated/._Earlier.mp3'}],'playlists':[]}
    sid=fixture.store.save_snapshot(snapshot,'Invented cloud-relative suggestions')['id'];source='snapshot:'+sid
    before=deepcopy(fixture.store.snapshot(sid));attachment=deepcopy(fixture.store.setting('dropbox_mapping',None))
    previous=fixture.store.setting('collection_context','');fixture.store.set_setting('collection_context',fixture.source)
    downloads=sum(len(value.downloads) for value in fixture.providers.values())
    context=browser.new_context(locale='en-US',viewport={'width':1440,'height':1050},
                                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) PRIVATE-UA-MARKER')
    context.add_init_script("localStorage.setItem('library-workbench.language.v1','en');Object.defineProperty(navigator,'platform',{get:()=> 'Win32'});Object.defineProperty(navigator,'userAgentData',{get:()=>({platform:'Windows'})});")
    page=context.new_page();errors=[];actions=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('request',lambda request:actions.append(request.url) if request.method=='POST' and
            any('/api/cloud-setup/'+suffix in request.url for suffix in ('preview','attach')) else None)
    try:
        page.goto(base,wait_until='networkidle')
        page.wait_for_function('(source)=>Journeys.context()?.source===source',arg=fixture.source)
        page.evaluate('(source)=>{CloudConnections.forSource(source,"dropbox");showView("cloud-connect");}',source)
        expect(page.locator('#cloud-setup-source')).to_have_value(source)
        # A refresh reads one authoritative status for the selected collection.
        requests=[]
        def record_status(request):
            url=urlsplit(request.url)
            if url.path in ('/api/cloud-setup/status','/api/dropbox/status','/api/google-drive/status'):
                requests.append((url.path,parse_qs(url.query)))
        page.on('request',record_status)
        try:
            page.evaluate('() => CloudConnections.load()')
        finally:
            page.remove_listener('request',record_status)
        assert requests==[('/api/cloud-setup/status',{'source':[source]})],requests
        page.locator('#cloud-setup-next').click();page.locator('#cloud-setup-next').click()
        expect(page.locator('#cloud-setup-local-root')).to_be_visible()
        host=context.request.get(base+'/api/cloud-setup/status').json()['host_platform']
        expect(page.locator('[data-cloud-host-platform]')).to_have_attribute('data-cloud-host-platform',host)
        expect(page.locator('[data-cloud-browser-platform]')).to_have_attribute('data-cloud-browser-platform','windows')
        styles=page.locator('[data-cloud-source-styles]').get_attribute('data-cloud-source-styles').split(',')
        assert 'windows' in styles and 'cloud_relative' in styles
        assert 'mac' not in styles and 'linux' not in styles
        platform_cases=[({'userAgentData':{'platform':'Windows'},'platform':'Linux','userAgent':'Linux'},'windows'),
                        ({'userAgentData':{'platform':'macOS'},'platform':'Win32'},'mac'),
                        ({'platform':'MacIntel'},'mac'),({'platform':'Win32'},'windows'),
                        ({'userAgent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'},'windows'),
                        ({'userAgent':'Mozilla/5.0 (X11; Linux x86_64)'},'linux'),
                        ({'userAgentData':{'platform':'Android'},'platform':'Linux','userAgent':'Android'},'unknown'),
                        ({'platform':'Unknown','userAgent':'Unknown'},'unknown')]
        for values,expected in platform_cases:
            assert page.evaluate('(hints)=>CloudConnections.browserPlatform(hints)',values)==expected
        source_styles=page.evaluate('()=>CloudConnections.capturedPathStyles([{samples:["/contents_invented/Album/Track.mp3"]},{samples:["/electrobuzz_2026/Album/Track.mp3"]}])')
        assert source_styles==['posix_unknown']
        mixed_styles=page.evaluate('()=>CloudConnections.capturedPathStyles([{samples:["/Users/OLD/Dropbox/Track.mp3"]},{samples:["/Volumes/Music/Track.mp3"]},{samples:["/home/old/Music/Track.mp3"]},{samples:["C:/Users/OLD/Dropbox/Track.mp3"]}])')
        assert mixed_styles==['windows','mac','linux']
        ranking={'provider_configuration':0,'correlated_cloud_paths':1,'cloud_relative_reference':2,'folder_hint':3}
        choices=page.locator('#cloud-setup-suggestions .cloud-location-option').evaluate_all('(nodes)=>nodes.map(node=>node.dataset.cloudEvidence)')
        ranks=[ranking.get(value,4) for value in choices]
        assert ranks==sorted(ranks),choices
        assert page.locator('#cloud-setup-local-root').is_editable()
        assert page.locator('#cloud-setup-recorded-root').is_editable()
        page.fill('#cloud-setup-local-root',str(fixture.dropbox_cache))
        candidate=page.locator('#cloud-setup-suggestions .cloud-location-option').filter(has_text='Matching full relative path in saved references').first
        expect(candidate).to_contain_text('OLD');candidate.click()
        assert page.locator('#cloud-setup-recorded-root').input_value().replace('\\','/')==old
        expect(page.locator('#cloud-setup-local-root')).to_have_value(str(fixture.dropbox_cache))
        logical=page.locator('#cloud-setup-suggestions .cloud-location-option').filter(has_text='Recorded library root · /')
        expect(logical).to_have_count(1)
        expect(logical).to_contain_text('not this computer’s filesystem root');logical.click()
        expect(page.locator('#cloud-setup-recorded-root')).to_have_value('/')
        expect(page.locator('#cloud-setup-local-root')).to_have_value(str(fixture.dropbox_cache))
        assert not actions;assert fixture.store.setting('dropbox_mapping',None)==attachment
        page.locator('[data-cloud-panel="2"]').screenshot(path=str(output/'cloud-recorded-root-suggestions.png'))
        page.locator('#cloud-setup-path-help>summary').click()
        page.locator('#cloud-setup-audio-mappings').click()
        expect(page.locator('.nav[data-view="file-health"]')).to_have_attribute('aria-current','page')
        expect(page.locator('#file-health-source')).to_have_value(source)
        expect(page.locator('#file-health-audio-paths .audio-path-panel')).to_have_attribute('open','')
        page.wait_for_function('(source)=>Journeys.context()?.source===source',arg=fixture.source)
        assert fixture.store.snapshot(sid)==before
        assert sum(len(value.downloads) for value in fixture.providers.values())==downloads
        assert 'PRIVATE-UA-MARKER' not in page.locator('body').inner_text()
        assert page.evaluate('()=>[...Object.values(localStorage),...Object.values(sessionStorage)].every(value=>!value.includes("PRIVATE-UA-MARKER"))')
        assert not errors,errors
        return {'all_reference_prefix_suggestion':True,'logical_root_never_selects_physical_root':True,
                'preview_and_attach_not_automatic':True,'audio_folders_link_keeps_tool_source':True,
                'collection_context_preserved':True,'source_unchanged':True,'downloads':0,
                'coarse_browser_platform_cases':len(platform_cases),'separate_host_browser_path_hints':True,
                'plain_root_relative_paths_do_not_imply_host_os':True,'confidence_ranked_multiple_choices':True,
                'manual_inputs_retained':True,'raw_user_agent_not_displayed_or_persisted':True}
    finally:
        fixture.store.set_setting('collection_context',previous);context.close()
