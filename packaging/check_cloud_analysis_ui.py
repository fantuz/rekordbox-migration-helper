"""Live cloud-location filters over invented paths; never contact a provider."""
from copy import deepcopy
from types import SimpleNamespace
from ui_navigation import select_collection


def check_cloud_analysis_ui(browser,base,store,output):
    from playwright.sync_api import expect
    from audio_paths import signature
    from collection_storage import capture_revision
    tracks=[]
    for identity,path,genre,size in (
        ('dropbox','C:/Users/Invented/DJ team Dropbox/Customer/a.mp3','House',1024),
        ('drive','/Invented/Google Drive/My Drive/b.mp3','Techno',2048),
        ('ordinary','/Invented/Music/Dropbox.mp3','House',4096),
        ('unknown',None,None,None),
    ):
        tracks.append({'id':identity,'title':'Shared title' if identity in ('dropbox','ordinary') else identity,
                       'artist':'Invented artist','genre':genre,'duration':240,'bpm':125,'rating':3,
                       'play_count':1,'manual_cues':1,'auto_cues':0,'analysed':True,'current_path':path,'size':size})
    sid=store.save_snapshot({'scope_key':'synthetic:cloud-location-ui','source_kind':'Invented cloud paths',
                             'tracks':tracks,'playlists':[],'capabilities':{}},'Invented cloud location UI')['id']
    before=deepcopy(store.snapshot(sid));requests=[]
    source='snapshot:'+sid
    revision=capture_revision(SimpleNamespace(DATA=store.path.parent),source)
    with store.connection() as db:
        db.execute('INSERT INTO file_health_scans (source,total,done,checked_at,state,mapping_revision,source_revision) VALUES (?,?,?,?,?,?,?)',
                   (source,4,2,1,'partial',signature([]),revision))
        db.executemany('INSERT INTO file_health_records (source,track_id,title,artist,genre,status,checked_at,search_text,cloud_state,logical_size,observed_location) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       [(source,'dropbox','Shared title','Invented artist','House','playable',1,'shared','local',2048,'mapped'),
                        (source,'drive','drive','Invented artist','Techno','unverified',1,'drive','online_only',2048,'current')])
    context=browser.new_context(locale='en-US',viewport={'width':1440,'height':1050})
    context.add_init_script("localStorage.setItem('library-workbench.language.v1','en')")
    page=context.new_page();page.on('request',lambda request:requests.append(request.url))
    def navigate(view):
        page.locator('.nav[data-view="'+view+'"]').click()
        page.wait_for_function('(view)=>document.querySelector(".nav.active")?.dataset.view===view',arg=view)
    try:
        page.goto(base,wait_until='networkidle')
        page.wait_for_selector('#journey-context-source option[value="snapshot:'+sid+'"]',state='attached')
        select_collection(page,'#journey-context-source','snapshot:'+sid)
        page.wait_for_function('(id)=>Journeys.context()?.snapshot===id',arg=sid)
        navigate('statistics')
        expect(page.locator('#stats-cards [data-cloud-provider=dropbox] strong')).to_have_text('1')
        expect(page.locator('#stats-cards [data-cloud-provider=google_drive] strong')).to_have_text('1')
        expect(page.locator('[data-storage-card="recorded"] strong')).to_have_text('7 KiB')
        expect(page.locator('[data-storage-card="cloud"] strong')).to_have_text('3 KiB')
        expect(page.locator('[data-storage-location="mapped"]')).to_contain_text('1 / 1')
        expect(page.locator('[data-storage-location="placeholder"]')).to_contain_text('2 KiB')
        with page.expect_response(lambda r:'/api/collection/statistics?' in r.url and 'provider=dropbox' in r.url):
            page.select_option('#stats-provider','dropbox')
        expect(page.locator('#stats-cards .stat-card').first.locator('strong')).to_have_text('1')
        expect(page.locator('#stats-provider')).to_have_class('cloud-provider-dropbox')
        expect(page.locator('#genre-histogram')).to_contain_text('House')
        expect(page.locator('[data-storage-card="recorded"] strong')).to_have_text('1 KiB')
        expect(page.locator('[data-storage-location="placeholder"]')).to_contain_text('Unknown')
        page.screenshot(path=str(output/'cloud-location-statistics.png'))
        with page.expect_response(lambda r:'/api/collection/statistics?' in r.url and 'provider=all' in r.url):
            page.select_option('#stats-provider','all')
        page.locator('#stats-file-health').click()
        expect(page.locator('#file-health-source')).to_have_value(source)
        for view,prefix,state in [('insights','dj','dj'),('bubbles','bubble','bubble'),('tonality','tonal','tonal')]:
            navigate(view)
            page.wait_for_function('(args)=>insightState[args.state].result?.snapshot.id===args.sid',arg={'state':state,'sid':sid})
            if prefix=='dj':page.select_option('#dj-perspective','all')
            panel=page.locator('#'+prefix+'-provider').locator('xpath=ancestor::details[1]')
            if panel.count() and not page.locator('#'+prefix+'-provider').is_visible():panel.locator('summary').first.click()
            page.select_option('#'+prefix+'-provider','google_drive')
            page.locator('#'+prefix+'-filter-form [type=submit]').click()
            page.wait_for_function('(args)=>insightState[args.state].result?.context.provider==="google_drive"',arg={'state':state})
            expect(page.locator('#'+prefix+'-provider')).to_have_class('cloud-provider-google_drive')
            assert page.evaluate('(state)=>insightState[state].result.context.provider_counts.all',state)==4
            rows=page.locator('#'+prefix+'-tracks tbody tr')
            expect(rows).to_have_count(1)
            expect(rows.first).to_contain_text('drive')
        navigate('review')
        page.locator('#view-review .native-review-more summary').press('Enter')
        page.wait_for_selector('#native-review-provider')
        page.select_option('#view-review .native-filter [name=mode]','metadata')
        page.select_option('#native-review-provider','dropbox')
        page.locator('#view-review .native-filter button[type=submit],#view-review .native-filter button:not([type])').click()
        expect(page.locator('#view-review [data-native-group]')).to_have_count(1)
        expect(page.locator('#view-review .native-count').last).to_have_text('2')
        page.locator('#view-review [data-native-group]').click()
        expect(page.locator('#view-review .native-compare-record')).to_have_count(2)
        navigate('reference')
        page.wait_for_selector('#native-reference-provider')
        page.select_option('#native-reference-provider','unknown')
        page.locator('#view-reference .native-filter button').click()
        expect(page.locator('#view-reference .native-table tbody tr')).to_have_count(1)
        expect(page.locator('#view-reference .native-table tbody tr')).to_contain_text('unknown')
        assert not any('/api/'+provider+'/'+action in url for url in requests for provider in ('dropbox','google-drive') for action in ('scan','download','connect','authorize'))
        assert not any('/api/file-health/scan' in url for url in requests)
        assert store.snapshot(sid)==before
        return {'statistics_provider_counters':True,'statistics_provider_filter':True,'insights_bubbles_tonality_filters':True,
                'native_group_keeps_all_siblings':True,'references_unknown_filter':True,
                'storage_evidence_and_file_health_link':True,'cloud_queries_and_downloads':0,'source_preserved':True}
    finally:
        context.close()
