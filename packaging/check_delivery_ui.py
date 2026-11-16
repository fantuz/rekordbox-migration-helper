"""GitHub browser acceptance: mount mapping, complete sorting and explicit enrichment."""
from hashlib import sha256
import json
import time
from urllib.parse import urlencode
import wave
from analyzer import analyze_folder
from test_discovery_history import native_fixture
from test_dj_insights import song
from musicbrainz_pilot import create_batch,BASE
from workbench_store import encoded

def check_delivery_ui(browser,base,store,root,output):
    mount=root/'NTFS mount 日本';music=mount/'Music';music.mkdir(parents=True)
    audio=music/'Café.wav'
    with wave.open(str(audio),'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(8000);stream.writeframes(b'\0\0'*800)
    source=root/'mapped-source';source.mkdir();dbfile=source/'master.db'
    with native_fixture(dbfile) as db:db.execute("UPDATE djmdContent SET FolderPath='D:/Music/Café.wav'")
    db.close();original=dbfile.read_bytes();capture='d'*32
    analyze_folder(dbfile,store.path.parent/'analyzers'/capture,lambda *_:None)
    tracks=[song(str(i),title=f'Mapped track {i:03}',current_path='D:/MUSIC/CAFÉ.wav') for i in range(70)]
    saved=store.save_snapshot({'scope_key':'capture:'+capture,'tracks':tracks,'playlists':[],
                              'source_kind':'Synthetic mounted collection','capabilities':{}},'Mounted Windows fixture')
    sid=saved['id'];snapshot=store.snapshot(sid)
    context=browser.new_context(locale='en-US',viewport={'width':1550,'height':1050})
    context.add_init_script("localStorage.setItem('library-workbench.language.v1','en')")
    page=context.new_page();errors=[];network=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:network.append(r.url))
    try:
        page.goto(base,wait_until='networkidle')
        page.locator('.nav[data-view="file-health"]').click()
        page.wait_for_selector('#file-health-source option[value="snapshot:'+sid+'"]',state='attached')
        page.select_option('#file-health-source','snapshot:'+sid)
        page.wait_for_selector('#file-health-audio-paths [data-audio-recorded]',state='attached')
        panel=page.locator('#file-health-audio-paths')
        panel.locator('summary').click()
        panel.locator('[data-audio-recorded]').fill('D:/')
        panel.locator('[data-audio-local]').fill(str(mount))
        panel.locator('[data-audio-preview]').click()
        page.wait_for_function('document.querySelector("#file-health-audio-paths [data-audio-examples]").textContent.includes("Playable")')
        panel.locator('[data-audio-save]').click()
        page.wait_for_function('document.querySelector("#file-health-audio-paths [data-audio-note]").textContent.includes("Audio folders saved")')
        page.locator('#file-health-scan').click()
        page.wait_for_function('document.querySelector("#file-health-state").textContent.includes("complete")',timeout=30000)
        assert '70' in page.locator('#file-health-counts').inner_text()
        page.screenshot(path=str(output/'mounted-windows-audio.png'))
        page.locator('.nav[data-view="insights"]').click()
        page.wait_for_selector('#dj-snapshot option[value="'+sid+'"]',state='attached')
        page.select_option('#dj-snapshot',sid);page.select_option('#dj-perspective','all')
        page.locator('#dj-search').fill('Mapped track');page.locator('#dj-filter-form button[type="submit"]').click()
        page.wait_for_selector('#dj-tracks [data-insight-open="0"]')
        page.locator('#dj-tracks th').first.locator('button').click()
        page.wait_for_function('document.querySelector("#dj-tracks th").getAttribute("aria-sort")==="ascending"')
        page.locator('#dj-tracks th').first.locator('button').click()
        page.wait_for_function('document.querySelector("#dj-tracks [data-insight-open]")?.dataset.insightOpen==="69"')
        page.locator('#dj-next').click()
        page.wait_for_function('document.querySelector("#dj-tracks [data-insight-open]")?.dataset.insightOpen==="19"')
        page.locator('.nav[data-view="file-health"]').click();page.go_back()
        page.wait_for_selector('#view-insights:not([hidden])')
        page.wait_for_function('document.querySelector("#dj-tracks [data-insight-open]")?.dataset.insightOpen==="19"')
        assert page.locator('#dj-search').input_value()=='Mapped track'
        assert page.locator('#dj-snapshot').input_value()==sid
        page.reload(wait_until='networkidle')
        page.wait_for_selector('#view-insights:not([hidden])')
        page.wait_for_function('document.querySelector("#dj-tracks [data-insight-open]")?.dataset.insightOpen==="69"')
        assert page.locator('#dj-search').input_value()=='Mapped track'
        assert page.locator('#dj-snapshot').input_value()==sid
        button=page.locator('#dj-tracks [data-play-track="69"]');button.scroll_into_view_if_needed()
        page.wait_for_function("""()=>document.querySelector('[data-play-track="69"]')?.dataset.available==="true" """)
        opened=[]
        page.route('**/api/playback/open',lambda route:(opened.append(route.request.post_data_json),route.fulfill(json={'opened':True})))
        button.click();page.wait_for_function('document.querySelector("#toast").textContent.includes("default media player")')
        assert opened==[{'snapshot':sid,'track_id':'69'}]
        page.screenshot(path=str(output/'collection-sorting-navigation.png'))

        # The provider is never contacted: seed one exact client cache entry.
        a='01234567-89ab-cdef-0123-456789abcdef';b='11111111-2222-3333-4444-555555555555';release='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        batch=create_batch(store,snapshot,sample_size=150,target='random')['id']
        result={'status':'candidate_needs_review','selected_mbid':a,'match_approved':False,
                'candidates':[{'mbid':a,'title':'First recording','artist':'Synthetic DJ','confidence':95},
                              {'mbid':b,'title':'Alternative recording','artist':'Synthetic DJ','confidence':90}],
                'proposal':{'year':2000,'genre':'House','community_score':None,'votes':0,'retrieved_at':'2026-01-01',
                            'year_basis':'First known release year for this recording; may differ from this file release',
                            'possible_albums':[{'mbid':release,'title':'Selected edition','date':'2003-04','country':'GB'}]}}
        with store.connection() as db:
            sample=json.loads(db.execute('SELECT sample FROM mb_batches WHERE id=?',(batch,)).fetchone()[0]);track_id=sample[0]['id']
            db.execute('INSERT INTO mb_results VALUES (?,?,?,?)',(batch,track_id,result['status'],encoded(result)))
            url=BASE+'recording/'+b+'?'+urlencode({'inc':'ratings+genres+tags+releases+isrcs+artist-credits','fmt':'json'})
            detail={'id':b,'first-release-date':'2011','genres':[{'name':'Techno','count':3}],'releases':[{'id':release,'title':'Alternative edition','date':'2012'}]}
            db.execute('INSERT OR REPLACE INTO mb_cache VALUES (?,?,?,?)',(sha256(url.encode()).hexdigest(),time.time(),time.time()+3600,encoded(detail)))
        store.set_setting('musicbrainz_enabled',True)
        page.locator('.nav[data-view="musicbrainz"]').click()
        page.wait_for_selector('#musicbrainz-library option[value="capture:'+capture+'"]',state='attached')
        page.select_option('#musicbrainz-library','capture:'+capture)
        page.select_option('#musicbrainz-snapshot',sid)
        page.evaluate('(batch)=>{labBatch=batch;labPilotOffset=0;return labLoadPilot();}',batch)
        row=page.locator('[data-mb-track="'+track_id+'"]')
        row.locator('[data-lab-approve]').click()
        page.wait_for_function("""(id)=>document.querySelector('[data-lab-approve="'+id+'"]')?.dataset.approved==="false" """,arg=track_id)
        row.locator('details').last.locator('summary').click()
        row.locator('[data-mb-release-choice]').select_option(release)
        row.locator('[data-mb-release]').click()
        page.wait_for_selector('[data-mb-stage="'+track_id+'"][data-field="album"]',state='attached')
        page.get_by_role('button',name='Unlock metadata edits',exact=True).click()
        row.locator('details').last.locator('summary').click()
        row.locator('[data-mb-stage][data-field="album"]').click()
        page.wait_for_function('document.querySelector("#toast").textContent.includes("Metadata staged locally")')
        provenance=json.loads(store.overrides(snapshot['scope_key'])[track_id]['album']['origin'])
        assert provenance['release_id']==release and provenance['recording_id']==a
        row.locator('details').first.locator('summary').click()
        row.locator('[data-mb-candidate-choice]').select_option(b)
        row.locator('[data-mb-candidate-consent]').check()
        row.locator('[data-mb-candidate]').click()
        page.wait_for_function("""(id)=>document.querySelector('[data-mb-track="'+id+'"]')?.textContent.includes("Alternative recording") && document.querySelector('[data-lab-approve="'+id+'"]')?.dataset.approved==="true" """,arg=track_id)
        assert 'album' not in store.overrides(snapshot['scope_key']).get(track_id,{})
        page.screenshot(path=str(output/'musicbrainz-candidate-release-review.png'))
        assert store.snapshot(sid)==snapshot
        assert dbfile.read_bytes()==original
        assert not any(url.startswith('https://musicbrainz.org') for url in network)
        assert not errors,errors
        return {'mapped_playback':True,'full_collection_sort':True,'back_and_reload_filters':True,
                'explicit_release_provenance':True,'alternative_resets_approval':True,'originals_unchanged':True}
    except Exception:
        page.screenshot(path=str(output/'delivery-failure.png'),full_page=True)
        (output/'delivery-failure.html').write_text(page.content(),encoding='utf-8')
        print('DELIVERY_UI_STATE '+json.dumps({'url':page.url,'toast':page.locator('#toast').text_content(),'errors':errors}))
        raise
    finally:context.close()
