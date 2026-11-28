"""Shared opt-in filename filtering, without scanning or cloud operations."""
from copy import deepcopy

from ui_navigation import select_collection


def check_metadata_sidecars_ui(browser, base, store, output):
    from playwright.sync_api import expect
    from metadata_export import track
    from metadata_sidecars import is_sidecar

    paths=[('normal','/invented/contents_123/song.mp3'),('contents','/invented/contents_123/song.mp3'),
           ('apple','/invented/._song.mp3'),('ds','/invented/.DS_Store'),
           ('desktop',r'C:\Invented\desktop.ini'),('thumbs','/invented/Thumbs.db'),('unknown',None)]
    rows=[track({'id':identity,'title':'Invented sidecar comparison','artist':'Synthetic artist','current_path':path,
                 'rating':2,'play_count':0,'duration':240,'genre':'House','tonality':'Am','bpm':120})
          for identity,path in paths]
    sid=store.save_snapshot({'schema':1,'scope_key':'synthetic:metadata-sidecars','tracks':rows,
                            'playlists':[],'capabilities':{}},'Invented metadata sidecars')['id']
    other=store.save_snapshot({'schema':1,'scope_key':'synthetic:metadata-sidecars-other','tracks':[rows[0]],
                              'playlists':[],'capabilities':{}},'Another captured collection')['id']
    source='snapshot:'+sid;before=deepcopy(store.snapshot(sid))
    with store.connection() as db:
        db.execute('INSERT OR REPLACE INTO file_health_scans (source,total,done,checked_at,state) VALUES (?,?,?,?,?)',(source,len(rows),len(rows),1,'complete'))
        for row in rows:
            db.execute('INSERT OR REPLACE INTO file_health_records (source,track_id,title,artist,genre,status,checked_at,search_text,filename,metadata_sidecar) VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (source,row['id'],row['title'],row['artist'],'House','unverified',1,row['title'],'',int(is_sidecar(row))))
    context=browser.new_context(locale='en-US',viewport={'width':1440,'height':1050})
    context.add_init_script("localStorage.setItem('library-workbench.language.v1','en')")
    # Playback status is unrelated to this display test. Answer bounded metadata
    # requests without probing invented paths on the host filesystem.
    context.route('**/api/playback/availability',lambda route:route.fulfill(json={
        'tracks':{identity:False for identity in route.request.post_data_json.get('track_ids',[])},
        'statuses':{identity:'unverified' for identity in route.request.post_data_json.get('track_ids',[])}}))
    page=context.new_page();errors=[];requests=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('request',lambda request:requests.append((request.method,request.url)))
    def navigate(view):page.locator('.nav[data-view="'+view+'"]').click()
    try:
        page.goto(base,wait_until='networkidle')
        select_collection(page,'#journey-context-source',source)
        navigate('statistics')
        toggle=page.locator('#view-statistics [data-hide-metadata-sidecars]')
        expect(toggle).not_to_be_checked()
        expect(page.locator('#stats-cards .stat-card strong').first).to_have_text('7')
        toggle.check()
        expect(page.locator('#stats-cards .stat-card strong').first).to_have_text('3')
        expect(page.locator('#stats-omitted')).to_contain_text('4 metadata sidecars hidden')
        page.screenshot(path=str(output/'metadata-sidecar-statistics.png'))

        navigate('insights');select_collection(page,'#dj-snapshot',sid)
        page.select_option('#dj-perspective','all');page.locator('#dj-filter-form [type="submit"]').click()
        expect(page.locator('#dj-tracks tbody tr')).to_have_count(3)
        expect(page.locator('#view-insights [data-hide-metadata-sidecars]')).to_be_checked()
        expect(page.locator('#dj-evidence')).to_contain_text('4 metadata sidecars hidden')
        navigate('bubbles');select_collection(page,'#bubble-snapshot',sid)
        expect(page.locator('#bubble-tracks tbody tr')).to_have_count(3)
        expect(page.locator('#bubble-evidence')).to_contain_text('4 metadata sidecars hidden')
        navigate('tonality');select_collection(page,'#tonal-snapshot',sid)
        expect(page.locator('#tonal-tracks tbody tr')).to_have_count(3)

        navigate('review')
        page.select_option('#view-review .native-filter [name="mode"]','metadata')
        page.locator('#view-review .native-filter .button').click()
        expect(page.locator('#view-review .native-result-count')).to_contain_text('3 tracks')
        expect(page.locator('#view-review .cloud-analysis-note')).to_contain_text('4 metadata sidecars hidden')
        page.locator('[data-native-group]').first.click()
        expect(page.locator('.native-compare-record')).to_have_count(3)
        navigate('reference')
        expect(page.locator('#view-reference .native-table tbody tr')).to_have_count(3)
        expect(page.locator('#view-reference .cloud-analysis-note')).to_contain_text('4 metadata sidecars hidden')

        # An explicit cloud-tool handoff must win over a different Collection
        # context, and opens the existing mapping panel rather than another page.
        page.evaluate('''async args=>{
            await Journeys.selectContext('snapshot:'+args.other);
            FileHealth.forSource(args.source,{audioFolders:true});showView('file-health');
        }''',{'other':other,'source':source})
        expect(page.locator('#file-health-source')).to_have_value(source)
        expect(page.locator('#file-health-audio-paths .audio-path-panel')).to_have_attribute('open','')
        expect(page.locator('#file-health-results tbody tr')).to_have_count(3)
        expect(page.locator('#file-health-state')).to_contain_text('4 metadata sidecars hidden')
        health_toggle=page.locator('#view-file-health [data-hide-metadata-sidecars]')
        expect(health_toggle).to_be_checked();health_toggle.uncheck()
        expect(page.locator('#file-health-results tbody tr')).to_have_count(7)
        assert page.locator('#file-health-results [data-file-track="contents"]').count()==1
        health_toggle.check();expect(page.locator('#file-health-results tbody tr')).to_have_count(3)
        page.set_viewport_size({'width':390,'height':900})
        health_toggle.scroll_into_view_if_needed()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path=str(output/'metadata-sidecar-file-health-narrow.png'))
        page.reload(wait_until='networkidle')
        expect(page.locator('#view-file-health [data-hide-metadata-sidecars]')).to_be_checked()
        assert store.snapshot(sid)==before
        blocked=('/api/file-health/scan','/api/dropbox/check','/api/google-drive/check',
                 '/api/dropbox/download','/api/google-drive/download','/api/cloud-setup/preview',
                 '/api/cloud-setup/attach','/api/playback/open')
        assert not [(method,url) for method,url in requests if method!='GET' and any(part in url for part in blocked)]
        assert errors==[],errors
        return {'shared_opt_in_default_off':True,'statistics_and_insights':True,
                'captured_duplicates_and_references':True,'file_health_full_index':True,
                'excluded_counts_visible':True,'contents_audio_preserved':True,
                'source_unchanged':True,'no_scan_download_or_launch':True,
                'preference_survives_reload':True,'explicit_file_health_source_handoff':True,
                'audio_folders_opened':True,'narrow_layout':True}
    except Exception:
        page.screenshot(path=str(output/'metadata-sidecar-failure.png'),full_page=True)
        raise
    finally:
        context.close()
