"""CI-only destination controls and collection-wide metadata flags."""
from copy import deepcopy
import json
import wave
from audio_paths import validate
from test_dj_insights import song


def check_reference_flags_ui(browser,base,store,root,output):
    music=store.path.parent/'Windows music volume';music.mkdir()
    rows=[]
    for i in range(60):
        with wave.open(str(music/f'{i:03}.wav'),'wb') as audio:
            audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(8000);audio.writeframes(b'\0\0'*80)
        for sibling in (0,1):
            rows.append(song(f'{i:03}-{sibling}',title=f'Flag track {i:03}-{sibling}',
                current_path=f'E:/Music/{i:03}.wav',duration=0 if i>=58 and sibling==1 else 601 if i==0 and sibling==0 else 240,
                size=0 if i==59 and sibling==1 else 1000,tonality='Am',
                bpm=None if i==3 and sibling==1 else 128,manual_cues=0 if i==59 else 1,
                play_count=5 if i==59 else 0))
    scope='synthetic:reference-flags'
    sid=store.save_snapshot({'scope_key':scope,'tracks':rows,'playlists':[],'capabilities':{}},'Reference flags')['id']
    before=deepcopy(store.snapshot(sid))
    mapping=validate([{'recorded_root':'E:/Music','local_root':str(music)}], [store.path.parent])
    store.set_setting('audio_paths:'+scope,mapping)
    context=browser.new_context(locale='en-US',viewport={'width':1550,'height':1050})
    context.add_init_script("localStorage.setItem('library-workbench.language.v1','en')")
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    try:
        page.goto(base,wait_until='networkidle')
        page.wait_for_selector('#journey-context-source option[value="snapshot:'+sid+'"]',state='attached')
        page.select_option('#journey-context-source','snapshot:'+sid)
        page.wait_for_function('(sid)=>Journeys.context()?.source==="snapshot:"+sid',arg=sid)
        page.locator('.nav[data-view="review"]').click()
        page.wait_for_function('document.querySelectorAll("#view-review .native-table tbody tr").length===50')
        root_selector='#view-review .native-collection'
        page.locator(root_selector+' [data-metadata-flag="zero_duration"]').click()
        page.wait_for_function('document.querySelectorAll("#view-review .native-table tbody tr").length===2')
        page.locator(root_selector+' [data-metadata-flag="zero_size"]').click()
        page.wait_for_function('document.querySelectorAll("#view-review .native-table tbody tr").length===1')
        page.locator(root_selector+' [data-native-group]').click()
        page.wait_for_selector('.native-compare-record')
        assert page.locator('.native-compare-record').count()==2
        assert page.locator('.native-compare-record .metadata-flag-zero_duration').count()==1
        assert page.locator('.native-compare-record .metadata-flag-zero_size').count()==1
        page.wait_for_function('document.querySelectorAll(".native-compare-record .native-file-status .file-status-playable").length===2')
        assert 'E:/Music/059.wav' in page.locator('.native-detail').inner_text()
        assert str(music) not in page.locator('.native-detail').inner_text()
        page.screenshot(path=str(output/'zero-metadata-playable-review.png'))
        # Actual API mapping invalidation, followed by the playback event:
        # the duplicate badges must not retain the previous playable state.
        page.wait_for_timeout(5100)
        page.evaluate("""async source=>{
            const state=await api('/api/audio-paths?'+new URLSearchParams({source}));
            await api('/api/audio-paths',{method:'POST',body:JSON.stringify({source,revision:state.revision,mappings:[]})});
            TrackPlayback.recheck();
        }""",'snapshot:'+sid)
        page.wait_for_function('document.querySelectorAll(".native-compare-record .native-file-status .file-status-unverified").length===2')
        page.locator('.nav[data-view="insights"]').click()
        page.wait_for_selector('#dj-snapshot option[value="'+sid+'"]',state='attached')
        page.select_option('#dj-snapshot',sid);page.select_option('#dj-perspective','all')
        page.locator('#dj-filter-form button[type="submit"]').click()
        page.wait_for_selector('#dj-tracks [data-insight-open="000-0"]')
        page.locator('#dj-quality-quick [data-metadata-flag="zero_duration"]').click()
        page.wait_for_function('document.querySelectorAll("#dj-tracks [data-insight-open]").length===2')
        page.locator('#dj-quality-quick [data-metadata-flag="zero_size"]').click()
        page.wait_for_function('document.querySelectorAll("#dj-tracks [data-insight-open]").length===1 && document.querySelector("#dj-tracks [data-insight-open]").dataset.insightOpen==="059-1"')
        page.reload(wait_until='networkidle')
        page.wait_for_function('document.querySelector("#dj-quality")?.value==="zero_size" && document.querySelector("#dj-tracks [data-insight-open]")?.dataset.insightOpen==="059-1"')
        page.locator('#dj-quality-quick [data-metadata-flag=""]').click()
        page.wait_for_function('document.querySelectorAll("#dj-tracks [data-insight-open]").length===50')
        for mode,ids in [('missing_mix',['003-1']),('played_unprepared',['059-0','059-1']),
                         ('favourites_prepare',['059-0','059-1']),('long_tracks',['000-0'])]:
            page.locator('[data-dj-preset="'+mode+'"]').click()
            page.wait_for_function('(ids)=>JSON.stringify([...document.querySelectorAll("#dj-tracks [data-insight-open]")].map(e=>e.dataset.insightOpen))===JSON.stringify(ids)',arg=ids)
        page.screenshot(path=str(output/'dj-insights-automatic-filters.png'))
        page.set_viewport_size({'width':390,'height':900})
        page.locator('[data-dj-preset="missing_mix"]').click()
        page.wait_for_selector('#dj-tracks [data-insight-open="003-1"]')
        page.screenshot(path=str(output/'dj-insights-flags-narrow.png'))
        page.set_viewport_size({'width':1550,'height':1050})
        # A synthetic active workspace exercises the controls. Real API guards
        # and actual XML/encrypted ZIP writers are covered by unit regressions.
        session={'id':'reference-controls','name':'Reference controls','metadata':{'name':'Reference controls','version':'7','input_check':'synthetic'},
                 'counts':{'tracks':2,'pairs':0,'xml_tracks':2,'ready':0,'auto':0},'events':[],'policy':'newest',
                 'staged':0,'relocations':0,'metadata_override_fields':0,
                 'export_reference':{'requested':'auto','target':'windows','detected':'windows'}}
        requests=[]
        def choose(route):
            value=route.request.post_data_json['target'];requests.append(value)
            session['export_reference'].update(requested=value,target=value)
            route.fulfill(json={'session':session})
        context.route('**/api/export-target',choose)
        page.evaluate('(s)=>{session=s;renderSession();showView("exports");}',session)
        assert 'Windows' in page.locator('#export-reference-target-state').inner_text()
        page.select_option('#export-reference-target','macos')
        page.wait_for_function('document.querySelector("#export-reference-target-state").textContent.includes("macOS")')
        assert requests==['macos']
        assert 'does not convert paths' in page.locator('.export-reference-target').inner_text()
        page.screenshot(path=str(output/'exported-reference-destination.png'))
        assert store.snapshot(sid)==before
        assert not errors,errors
        return {'zero_flags_before_paging':True,'playability_independent':True,'mapping_refreshes_review_badges':True,
                'four_dj_filters':True,'filter_survives_reload':True,'target_controls':True,'captured_metadata_unchanged':True}
    except Exception:
        page.screenshot(path=str(output/'reference-flags-failure.png'),full_page=True)
        print('REFERENCE_FLAGS_UI_STATE '+json.dumps({'url':page.url,'toast':page.locator('#toast').text_content(),'errors':errors}))
        raise
    finally:context.close()
