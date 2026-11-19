"""Real HTTP regression flows for display, compact navigation and cloud consent."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from ui_navigation import select_collection, open_collection_picker


def fake_player_environment(root):
    """Replace only Linux OS dispatch; application APIs remain real and unmodified."""
    log=root/'synthetic-player.jsonl'
    if sys.platform!='linux':return {},log
    directory=root/'synthetic-bin';directory.mkdir()
    script=directory/'xdg-open'
    script.write_text('#!'+sys.executable+'\nimport json,sys\nwith open('+repr(str(log))+',"a",encoding="utf-8") as stream:stream.write(json.dumps(sys.argv[1:])+"\\n")\n')
    script.chmod(0o700)
    import os
    return {'PATH':str(directory)+os.pathsep+os.environ.get('PATH','')},log


def check_display_workflows_ui(browser,base,store,root,output,opener_log,original_sid):
    from playwright.sync_api import expect
    folder=root/'Dropbox (Invented team)'/'Example customer';folder.mkdir(parents=True)
    audio=folder/'Synthetic resident.mp3';audio.write_bytes(b'Invented fixture, not real audio')
    keys=['Am','8A','1m','C# minor','12A','','C/D']
    tracks=[]
    for i,key in enumerate(keys):
        tracks.append({'id':'display-'+str(i),'title':'Synthetic track '+str(i),'artist':'Invented artist',
                       'tonality':key,'genre':'House' if i in (0,1) else 'Techno' if i==2 else '' if i==3 else 'Unknown' if i==4 else '日本語 <tag>',
                       'year':2020 if i<2 else 2022 if i==2 else 1999 if i==3 else None,'date_added':'2021-01-01' if i%2 else None,
                       'duration':None if i==1 else 0 if i==2 else 240,'bpm':None if i==6 else 120,
                       'play_count':None if i==1 else i,'rating':0,'manual_cues':0,'auto_cues':0,
                       'current_path':str(audio) if i==0 else str(folder/'Absent.mp3') if i==1 else
                           str(root/'GoogleDrive-invented'/'My Drive'/'Absent.mp3') if i==2 else None})
    sid=store.save_snapshot({'scope_key':'synthetic:display-flows','source_kind':'Synthetic UI fixture','tracks':tracks,
                             'playlists':[],'histories':[{'id':'demo','name':'Invented session','entries':[{'track_id':'display-0','position':1},{'track_id':'display-1','position':2}]}],
                             'capabilities':{'history_details':True,'history_order':True}},'Invented display workflows')['id']
    before=deepcopy(store.snapshot(sid));page_context=browser.new_context(locale='en-US',viewport={'width':1440,'height':1050})
    page_context.add_init_script("localStorage.setItem('library-workbench.language.v1','en');localStorage.removeItem('library-workbench.display.v1')")
    page=page_context.new_page();errors=[];requests=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('request',lambda request:requests.append({'url':request.url,'method':request.method,'body':request.post_data_json if request.method=='POST' and '/api/playback/' in request.url else None}))
    def navigate(view):page.locator('.nav[data-view="'+view+'"]').click()
    try:
        page.goto(base,wait_until='networkidle')
        page.wait_for_selector('#journey-context-source option[value="snapshot:'+sid+'"]',state='attached')
        assert not page.locator('#collection-context-toggle').evaluate('node=>node.open')
        assert not page.locator('#collection-snapshot-toggle').evaluate('node=>node.open')
        assert page.locator('#collection-navigation').bounding_box()['y'] < page.locator('.topbar').bounding_box()['y']
        select_collection(page,'#journey-context-source','snapshot:'+sid)
        page.wait_for_function('(id)=>Journeys.context()?.snapshot===id',arg=sid)
        expect(page.locator('#collection-context-current')).to_contain_text('Invented display workflows')
        # Native details keyboard operation, exclusive expansion and outside closing.
        summary=page.locator('#collection-context-toggle>summary');summary.focus();summary.press('Enter')
        expect(page.locator('#journey-context-source')).to_be_visible()
        page.locator('#collection-snapshot-toggle>summary').click()
        expect(page.locator('#journey-context-source')).to_be_hidden()
        page.locator('.sidebar').click(position={'x':5,'y':5})
        assert not page.locator('#collection-snapshot-toggle').evaluate('node=>node.open')
        navigate('bubbles')
        page.wait_for_function('(id)=>insightState.bubble.result?.snapshot.id===id',arg=sid)
        assert page.locator('#bubble-snapshot').locator('xpath=ancestor::details[1]').get_attribute('id')=='collection-snapshot-toggle'
        select_collection(page,'#bubble-snapshot',sid)
        assert page.locator('#bubble-filter-form details').count()==0
        expected=['basis','family','genre','tone','colour','usage','search','preparation','bpm-min','bpm-max','min','max','rating-min','from','to']
        assert all(page.locator('#bubble-'+name).count()==1 for name in expected)
        panel=page.locator('#bubble-filter-panel');panel.locator('summary').click() if not panel.evaluate('node=>node.open') else None
        page.fill('#bubble-search','Synthetic track');page.locator('#bubble-filter-form [type=submit]').click()
        expect(panel).not_to_have_attribute('open','')
        expect(page.locator('#bubble-filter-summary')).to_contain_text('Synthetic track')
        panel.locator('summary').click();page.fill('#bubble-bpm-min','180');page.fill('#bubble-bpm-max','100')
        with page.expect_response(lambda response:'/api/insights/bubbles?' in response.url and response.status==400):
            page.locator('#bubble-filter-form [type=submit]').click()
        expect(panel).to_have_attribute('open','')
        page.locator('#bubble-filter-reset').click();expect(panel).not_to_have_attribute('open','')
        page.select_option('#bubble-dimension','tone')
        page.wait_for_function('insightState.bubble.result?.dimension==="tone"')
        expected_groups=page.evaluate('Object.fromEntries(insightState.bubble.result.groups.map(g=>[g.key,g.entries]))')
        for mode,minor_label in [('alpha','Am'),('camelot','8A'),('open_key','1m')]:
            page.select_option('#view-bubbles [data-key-notation]',mode)
            page.wait_for_function('(mode)=>insightState.bubble.result?.key_notation===mode',arg=mode)
            assert page.evaluate('Object.fromEntries(insightState.bubble.result.groups.map(g=>[g.key,g.entries]))')==expected_groups
            assert page.evaluate('(label)=>insightState.bubble.result.groups.some(g=>g.label===label&&g.entries===3)',minor_label)
            assert page.evaluate('DisplayPreferences.key("constructor")==="constructor" && DisplayPreferences.key("__proto__")==="__proto__"')
            assert page.evaluate('DisplayPreferences.keyGroup("C M")===DisplayPreferences.keyGroup("8B") && DisplayPreferences.keyGroup("B♭ M")===DisplayPreferences.keyGroup("6B")')
        expect(page.locator('#bubble-key-sources')).to_contain_text('Numerical · 3')
        page.locator('#view-bubbles [data-hide-unknown]').check()
        page.wait_for_function('insightState.bubble.result?.excluded_unknown===2')
        assert page.evaluate('insightState.bubble.result.summary.entries')==7
        assert page.locator('#bubble-groups button').count()==2
        page.select_option('#view-bubbles [data-key-notation]','camelot')
        page.wait_for_function('insightState.bubble.result?.key_notation==="camelot"')
        page.locator('#bubble-groups button').filter(has_text='8A').click()
        page.wait_for_function('insightState.bubble.result?.context.breadcrumbs.some(p=>p.dimension==="tone"&&p.label==="8A")')
        # Changing notation updates an existing key breadcrumb and preserves its tracks.
        page.select_option('#view-bubbles [data-key-notation]','alpha')
        page.wait_for_function('insightState.bubble.result?.context.breadcrumbs.some(p=>p.dimension==="tone"&&p.label==="Am")')
        assert page.evaluate('insightState.bubble.result.summary.entries')==3
        page.locator('#bubble-reset').click()
        page.wait_for_function('insightState.bubble.result?.context.breadcrumbs.length===0')
        page.locator('#bubble-filter-panel>summary').click()
        # New input during a pending successful apply must keep the panel expanded.
        page.evaluate('''() => {const form=document.querySelector('#bubble-filter-form');form.requestSubmit();const input=document.querySelector('#bubble-search');input.value='Changed while applying';input.dispatchEvent(new Event('input',{bubbles:true}));}''')
        page.wait_for_function('!document.querySelector("#bubble-filter-form").hasAttribute("aria-busy")')
        expect(panel).to_have_attribute('open','')
        expect(page.locator('#bubble-filter-feedback')).to_contain_text('Changes not applied')
        page.select_option('#view-bubbles [data-key-notation]','open_key')
        page.wait_for_function('insightState.bubble.result?.key_notation==="open_key"')
        expect(page.locator('#bubble-search')).to_have_value('Changed while applying')
        assert page.evaluate('insightState.bubble.result.summary.entries')==7
        expect(page.locator('#bubble-filter-feedback')).to_contain_text('Changes not applied')
        page.locator('#bubble-filter-reset').click();expect(panel).not_to_have_attribute('open','')
        panel.locator('summary').click()
        expect(page.locator('#toast')).to_be_hidden(timeout=12000)
        page.screenshot(path=str(output/'compact-bubble-filters.png'))
        for width in (1440,820,430):
            page.set_viewport_size({'width':width,'height':1050})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            # Both collection controls fit the content row, even at phone width.
            open_collection_picker(page,'#bubble-snapshot')
            assert page.locator('#bubble-snapshot').bounding_box()['width']>100
            page.locator('#bubble-snapshot').press('Escape')
        page.set_viewport_size({'width':1440,'height':1050})
        page.locator('#bubble-expand').click();page.wait_for_selector('#bubble-expanded[open]')
        assert page.locator('#bubble-expanded #collection-navigation').count()==1
        assert page.locator('#bubble-expanded .header-actions').count()==0
        assert page.locator('#bubble-expanded #header-information').count()==0
        open_collection_picker(page,'#bubble-snapshot')
        expect(page.locator('#bubble-snapshot')).to_have_value(sid)
        page.locator('#bubble-snapshot').press('Escape')
        assert page.locator('#bubble-expanded').evaluate('node=>node.open')
        page.keyboard.press('Escape');page.wait_for_selector('#bubble-expanded',state='hidden')
        expect(page.locator('main>.workspace-toolbar>#collection-navigation')).to_have_count(1)
        panel.locator('summary').click()
        navigate('statistics');page.wait_for_selector('#genre-histogram .hist-row')
        expect(page.locator('#view-statistics [data-hide-unknown]')).to_be_checked()
        assert page.locator('#release-histogram [data-chart-unknown=true]').count()==0
        expect(page.locator('#release-histogram .chart-exclusion-note')).to_contain_text('4 / 7')
        expect(page.locator('#statistics-release-order')).to_have_value('year_desc')
        assert page.locator('#release-histogram .hist-row>span').all_text_contents()==['2022','2020','1999']
        before_sort=sum('/statistics?' in request['url'] for request in requests)
        page.select_option('#statistics-release-order','count_desc')
        assert page.locator('#release-histogram .hist-row>span').all_text_contents()==['2020','2022','1999']
        assert sum('/statistics?' in request['url'] for request in requests)==before_sort
        expect(page.locator('#genre-histogram .chart-exclusion-note')).to_contain_text('5 / 7')
        expect(page.locator('#length-histogram .chart-exclusion-note')).to_contain_text('6 / 7')
        assert '<tag>' in page.locator('#genre-histogram').inner_text() and page.locator('#genre-histogram tag').count()==0
        page.locator('#view-statistics [data-hide-unknown]').uncheck()
        page.wait_for_selector('#release-histogram [data-chart-unknown=true]')
        expect(page.locator('#statistics-release-order')).to_have_value('count_desc')
        assert page.locator('#release-histogram .hist-row').last.get_attribute('data-chart-unknown')=='true'
        page.select_option('#statistics-release-order','year_desc')
        assert page.locator('#genre-histogram [data-chart-unknown=true]').count()==1
        page.locator('.statistics-chart-grid').screenshot(path=str(output/'collection-statistics-distributions.png'))
        navigate('tonality');page.wait_for_function('(id)=>insightState.tonal.result?.snapshot.id===id',arg=sid)
        page.select_option('#view-tonality [data-key-notation]','open_key')
        page.wait_for_function('insightState.tonal.result?.key_notation==="open_key"')
        expect(page.locator('#tonal-keys')).to_contain_text('1m')
        page.locator('#tonal-tracks [data-insight-open="display-0"]').click();page.wait_for_selector('#track-detail-dialog[open]')
        expect(page.locator('#track-key-value b')).to_have_text('1m')
        page.fill('#track-comment-text','Unsaved local draft')
        page.select_option('#track-key-preferences [data-key-notation]','camelot')
        expect(page.locator('#track-key-value b')).to_have_text('8A')
        expect(page.locator('#track-comment-text')).to_have_value('Unsaved local draft')
        assert not page.locator('#track-detail-unlock').is_checked()
        page.locator('#track-detail-dialog .close-dialog').click()
        navigate('intelligence');page.wait_for_selector('#intelligence-history option[value=demo]',state='attached')
        page.select_option('#intelligence-history','demo');page.locator('#intelligence-session').click()
        page.wait_for_selector('#intelligence-results tbody tr')
        assert page.locator('#intelligence-results tbody tr td:nth-child(6)').all_inner_texts()==['8A','8A']
        page.select_option('#intelligence-results [data-key-notation]','alpha')
        assert page.locator('#intelligence-results tbody tr td:nth-child(6)').all_inner_texts()==['Am','Am']
        for view,selector in [('insights','#dj-snapshot'),('bubbles','#bubble-snapshot'),('tonality','#tonal-snapshot'),('lab','#lab-snapshot'),('history','#history-snapshot'),('file-health','#file-health-source')]:
            navigate(view);page.wait_for_selector(selector,state='attached')
            assert page.locator(selector).locator('xpath=ancestor::details[1]').get_attribute('id')=='collection-snapshot-toggle'
            assert not page.locator('#collection-snapshot-toggle').evaluate('node=>node.open')
            select_collection(page,selector,'snapshot:'+sid if view=='file-health' else sid)
            assert page.locator(selector).count()==1
        # A provider-only filter is useful without connecting an account or opening media.
        page.locator('#file-health-scan').click()
        page.wait_for_function('document.querySelector("#file-health-state").textContent.includes("complete")')
        page.locator('[data-file-provider="dropbox"]').click()
        expect(page.locator('#file-health-results tbody tr')).to_have_count(2)
        expect(page.locator('#file-health-results')).to_contain_text('Not available locally')
        assert not opener_log.exists()
        page.screenshot(path=str(output/'cloud-file-health-filters.png'))
        play=page.locator('#file-health-results [data-play-track="display-0"]')
        expect(play).to_be_enabled();play.click();page.wait_for_selector('#cloud-playback-dialog[open]')
        expect(page.locator('#cloud-playback-cancel')).to_be_focused()
        page.locator('#cloud-playback-cancel').click()
        expect(page.locator('#cloud-playback-dialog')).not_to_have_attribute('open','')
        assert not opener_log.exists()
        expect(play).to_be_enabled();play.click();page.wait_for_selector('#cloud-playback-dialog[open]')
        page.locator('#cloud-playback-dialog').press('Escape')
        assert not opener_log.exists()
        expect(play).to_be_enabled();play.click();page.wait_for_selector('#cloud-playback-dialog[open]')
        page.screenshot(path=str(output/'cloud-track-confirmation.png'))
        confirmed=False
        if sys.platform=='linux':
            with page.expect_response(lambda response:response.url.endswith('/api/playback/open') and response.request.post_data_json.get('confirm_cloud_open') is True) as response:
                page.locator('#cloud-playback-confirm').click()
            assert response.value.ok and response.value.json()['opened']
            assert [json.loads(line) for line in opener_log.read_text().splitlines()]==[[str(audio.resolve())]]
            confirmed=True
        else:page.locator('#cloud-playback-cancel').click()
        confirmed_requests=[r for r in requests if r['body'] and r['body'].get('confirm_cloud_open')]
        assert len(confirmed_requests)==int(confirmed)
        page.locator('[data-file-provider="google_drive"]').click()
        expect(page.locator('#file-health-results tbody tr')).to_have_count(1)
        assert all(r['url'].startswith(base) or r['url'].startswith('blob:') for r in requests)
        assert not errors,errors
        assert store.snapshot(sid)==before and store.overrides('synthetic:display-flows')=={}
        return {'real_http':True,'source_unchanged':True,'canonical_key_groups':True,'key_formats':3,
                'independent_unknown_charts':4,'compact_filters_all_controls':15,'autocollapse_success_only':True,
                'navigation_default_closed':True,'snapshot_views':6,'narrow_layout':True,'provider_filters':True,
                'cancel_and_escape_no_dispatch':True,'one_track_explicit_dispatch':confirmed,'provider_network_requests':0}
    except Exception:
        print('Display workflow diagnostic:',page.evaluate('''() => ({view:document.querySelector('.nav.active')?.dataset.view,toast:document.querySelector('#toast')?.textContent,source:document.querySelector('#bubble-snapshot')?.value,result:insightState.bubble.result?.dimension,options:insightState.bubble.options?.key_notation,errors:window.metadataExecuted})'''),flush=True)
        page.screenshot(path=str(output/'display-workflow-failure.png'))
        raise
    finally:
        if not page.is_closed():
            page.evaluate('(id)=>Journeys.selectContext("snapshot:"+id,true)',original_sid)
        page_context.close()
