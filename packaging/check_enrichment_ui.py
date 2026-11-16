"""GitHub-only synthetic UI verification and reproducible README screenshots."""
from copy import deepcopy
import json
import wave

from metadata_export import track
from musicbrainz_pilot import create_batch
from workbench_store import encoded
from track_tags import xml_colour_support


def check_enrichment_ui(page,base,original_id,output,store,root):
    previous_viewport=page.viewport_size;previous_theme=page.locator('#theme').input_value()
    page.set_viewport_size({'width':1600,'height':1100});page.select_option('#theme','light')
    audio=root/'Synthetic preview.wav'
    with wave.open(str(audio),'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(8000);stream.writeframes(b'\0\0'*800)
    tracks=[]
    for i in range(12):
        tracks.append({**track({'id':'demo'+str(i),'title':'Test Track '+str(i+1).zfill(2)+' · '+['Ω','Ł','🎧'][i%3]+(' (Dub)' if i>=6 else ''),
            'artist':'Test Artist '+str(i%4+1),'album':'Generated test collection','genre':['Deep House','Dub Techno','Ambient'][i%3],
            'bpm':116+i%16,'duration':240+i*3,'rating':i%6,'play_count':i*3,'manual_cues':i%5,'auto_cues':0,'analysed':True,
            'tonality':['8A','9A','10A','11A'][i%4],'comment':'Synthetic fixture. No personal music or library data.',
            'current_path':str(audio) if i==0 else '/Synthetic music/missing-'+str(i)+'.flac',
            'color_status':'assigned','color_key':'blue','color_name':'Blue','color_hex':'#0000FF'}),'cues':[]})
    source={'schema':1,'scope_key':'synthetic:readme','source_kind':'Synthetic demonstration','tracks':tracks,'colour_edit_support':xml_colour_support(),
        'playlists':[{'id':'warmup','name':'Warm-up selection','tracks':['demo'+str(i) for i in range(8)]},
                     {'id':'late','name':'Late session','tracks':['demo'+str(i) for i in range(4,12)]}],
        'histories':[{'id':'set1','name':'Test session A','date':'2026-01-10','entries':[{'track_id':'demo'+str(i),'position':i+1} for i in range(8)]},
                     {'id':'set2','name':'Test session B','date':'2026-02-14','entries':[{'track_id':'demo'+str(i),'position':i-3} for i in range(4,10)]}],
        'capabilities':{'playlist_order':True,'history_details':True,'history_order':True,'cue_positions':True},'asset_references':[]}
    inventory={'records':len(tracks),'serialized_metadata_bytes':len(encoded(source).encode('utf-8')),
               'generated_silence_bytes':audio.stat().st_size,'audio_seconds':0.1,
               'distributed_catalogue_records':0,'distributed_audio_bytes':0}
    print('SYNTHETIC_DATA_INVENTORY '+json.dumps(inventory))
    sid=store.save_snapshot(source,'Demo collection · synthetic data')['id'];before=store.snapshot(sid)
    page.evaluate('()=>Journeys.load()')
    page.evaluate('(id)=>Journeys.selectContext("snapshot:"+id,true)',sid)
    page.locator('.nav[data-view="insights"]').click()
    page.wait_for_selector('#dj-snapshot option[value="'+sid+'"]',state='attached')
    page.select_option('#dj-snapshot',sid);page.select_option('#dj-perspective','all')
    page.locator('#dj-filter-form button[type="submit"]').click()
    page.wait_for_selector('#dj-tracks [data-insight-open="demo0"]')
    page.wait_for_function('()=>{const b=document.querySelector(\'#dj-tracks [data-play-track="demo0"]\');if(!b)return false;b.scrollIntoView({block:"center"});return b.dataset.available==="true";}')
    page.wait_for_function('()=>{const b=document.querySelector(\'#dj-tracks [data-play-track="demo1"]\');if(!b)return false;b.scrollIntoView({block:"center"});return b.dataset.available==="false";}')
    play=page.locator('#dj-tracks [data-play-track="demo0"]')
    assert play.evaluate('(b)=>b.nextElementSibling?.dataset.insightOpen==="demo0"')
    assert play.bounding_box()['width']<=25
    launches=[]
    def launch(route):
        launches.append(route.request.post_data_json)
        route.fulfill(json={'opened':True})
    page.route('**/api/playback/open',launch)
    page.locator('#dj-tracks [data-play-track="demo0"]').click()
    page.wait_for_function('document.querySelector("#toast").textContent.includes("default media player")')
    assert launches==[{'snapshot':sid,'track_id':'demo0'}]
    assert not page.locator('#track-detail-dialog').is_visible()
    page.locator('#toast').wait_for(state='hidden')
    page.evaluate('document.querySelector("#dj-evidence").scrollIntoView({block:"start"})')
    page.screenshot(path=str(output/'readme-library-insights.png'))

    page.locator('#dj-tracks [data-insight-open="demo0"]').click()
    page.wait_for_selector('#track-detail-dialog[open]')
    assert page.locator('#track-detail-title [data-play-track="demo0"]').count()==1
    assert page.locator('#track-detail-title').evaluate('(e)=>e.firstChild.matches("[data-play-track]")')
    page.screenshot(path=str(output/'readme-track-editor.png'))
    page.locator('#track-detail-dialog .close-dialog').click()
    page.unroute('**/api/playback/open',launch)

    page.locator('.nav[data-view="intelligence"]').click()
    page.wait_for_selector('#intelligence-playlist option[value="warmup"]',state='attached')
    page.select_option('#intelligence-playlist','warmup');page.locator('#intelligence-contents').click()
    page.wait_for_function('document.querySelectorAll("#intelligence-results tbody tr").length===8')
    assert page.locator('#intelligence-results [data-play-track]').count()==8
    page.locator('#intelligence-results').scroll_into_view_if_needed()
    page.wait_for_function('Array.from(document.querySelectorAll("#intelligence-results [data-play-track]")).every(b=>b.dataset.available!==undefined)')
    page.screenshot(path=str(output/'readme-playlist-explorer.png'))
    page.select_option('#intelligence-lens','recurring');page.locator('#intelligence-lenses').click()
    page.wait_for_function('document.querySelectorAll("#intelligence-results tbody tr").length===4')
    assert page.locator('#intelligence-results [data-play-track="demo4"]').count()==1

    chart={'report_id':'synthetic-report','snapshot_id':sid,'period':'week','retrieved_at':'2026-02-15T12:00:00Z',
           'basis':'Synthetic chart fixture; no provider request.', 'summary':{'exact_tags':1,'unmatched':1},
           'rows':[{'rank':1,'title':tracks[0]['title'],'artist':tracks[0]['artist'],'status':'exact_tags','candidates':[tracks[0]]},
                   {'rank':2,'title':'Remote recording without local match','artist':'Synthetic artist','status':'unmatched','candidates':[]}]}
    page.route('**/api/intelligence/chart',lambda route:route.fulfill(json=chart))
    assert page.locator('.intelligence-tools>.tool-entry').count()==6
    page.locator('#chart-consent').check();page.locator('#chart-fetch').click()
    page.wait_for_selector('[data-chart-rank="1"]')
    assert page.locator('[data-chart-rank="1"]').input_value()=='demo0'
    assert page.locator('[data-chart-rank="2"]').input_value()==''
    assert page.locator('#chart-reviewed').is_checked() is False
    page.locator('#chart-reviewed').check();page.select_option('[data-chart-rank="1"]','')
    assert page.locator('#chart-reviewed').is_checked() is False
    page.unroute('**/api/intelligence/chart')

    page.locator('.serato-entry summary').click()
    assert page.locator('#serato-export').is_disabled()
    page.locator('#serato-volume').fill('Z:/');page.locator('#serato-preview').click()
    page.wait_for_function('document.querySelector("#serato-report").textContent.includes("No tracks can be exported")')
    assert page.locator('#serato-export').is_disabled()
    page.locator('#serato-volume').fill('/');page.locator('#serato-preview').click()
    page.wait_for_function('document.querySelector("#serato-report").textContent.includes("Readback passed")')
    assert page.locator('#serato-export').is_disabled()
    page.locator('#serato-ack').check()
    with page.expect_download() as download:page.locator('#serato-export').click()
    target=output/'synthetic-serato-draft.zip';download.value.save_as(target)
    from io import BytesIO
    import zipfile
    with zipfile.ZipFile(target) as archive:
        manifest=json.loads(archive.read('manifest.json'))
        assert manifest['validation']['status']=='passed'
        # The real playback fixture has a drive letter on Windows and is
        # intentionally outside the POSIX / volume used for this draft.
        assert manifest['tracks_written']==(11 if audio.drive else 12) and manifest['serato_import_verified'] is False
    page.screenshot(path=str(output/'serato-preview.png'))
    page.locator('#serato-volume').fill('/Volumes/Changed')
    assert page.locator('#serato-report').inner_text()==''
    assert page.locator('#serato-export').is_disabled() and not page.locator('#serato-ack').is_checked()


    page.locator('#serato-volume').fill('C:/')
    page.locator('#serato-platform').select_option('macos')
    assert page.locator('#serato-target-root').input_value()=='/Volumes/DJ'
    page.locator('#serato-volume').fill('/')
    page.locator('#serato-preview').click()
    page.wait_for_function('document.querySelector("#serato-report").textContent.includes("/Volumes/DJ")')
    assert 'Target path examples' in page.locator('#serato-report').inner_text()
    page.locator('#serato-platform').select_option('windows')
    assert page.locator('#serato-target-root').input_value()=='C:/'
    assert page.locator('#serato-report').inner_text()==''
    page.locator('#serato-target-root').fill('D:/')
    page.locator('#serato-platform').select_option('auto')
    page.locator('#serato-preview').click()
    page.wait_for_function('document.querySelector("#serato-report").textContent.includes("D:/")')
    assert 'Windows paths' in page.locator('#serato-report').inner_text()
    assert page.locator('#serato-export').is_disabled()
    page.locator('#serato-ack').check()
    page.locator('#serato-target-root').fill('E:/')
    assert page.locator('#serato-export').is_disabled() and not page.locator('#serato-ack').is_checked()
    page.locator('#serato-platform').select_option('auto')
    page.locator('#serato-target-root').fill('')

    batch=create_batch(store,before,sample_size=1000)
    def start(route):
        with store.connection() as db:db.execute("UPDATE mb_batches SET status='complete' WHERE id=?",(batch['id'],))
        route.fulfill(json={'job':'synthetic-background','batch_id':batch['id'],'background':True})
    page.route('**/api/lab/musicbrainz/'+batch['id']+'/start',start)
    # This existing page fixture supplies an available current collection.
    # The real absence/reconnect guard has separate API and browser tests.
    page.route('**/api/lab/musicbrainz/context',lambda route:route.fulfill(json={
        'sources':[{'id':'session:synthetic','label':'Synthetic current library','kind':'workspace'}],
        'snapshots':[{'id':i,'scope_key':'session:synthetic','label':'Synthetic','created':'2026-11-15'} for i in (sid,original_id)]}))
    page.locator('.nav[data-view="musicbrainz"]').click()
    page.wait_for_selector('#musicbrainz-snapshot option[value="'+sid+'"]',state='attached')
    assert page.locator('#musicbrainz-snapshot').input_value()==sid
    assert page.locator('#view-lab #lab-panel-pilot').count()==0
    assert page.locator('.nav[data-view="musicbrainz"]').evaluate('e=>e.closest(".nav-group").dataset.navSection==="enrich"')
    page.evaluate('(id)=>{labBatch=id;return labLoadPilot();}',batch['id'])
    page.locator('[data-lab-pilot-sort="title"]').click()
    page.wait_for_function('document.querySelector("#lab-pilot-results th[aria-sort=ascending] [data-lab-pilot-sort=title]")!==null')
    page.evaluate('() => BackgroundPilot.refresh()')
    page.wait_for_function('document.querySelector("#lab-pilot-results th[aria-sort=ascending] [data-lab-pilot-sort=title]")!==null')
    page.locator('[data-lab-pilot-sort="title"]').click()
    page.wait_for_function('document.querySelector("#lab-pilot-results th[aria-sort=descending] [data-lab-pilot-sort=title]")!==null')
    assert page.locator('#lab-pilot-results table[data-sort-scope="server"]').count()==1
    page.locator('#lab-pilot-enabled').check();page.locator('#lab-pilot-consent').check();page.locator('#lab-pilot-start').click()
    page.wait_for_function('document.querySelector("#pilot-background-text").textContent.includes("complete")')
    # A finished, persisted batch must relabel its status and counters when
    # the user changes language, without starting another provider request.
    from pathlib import Path
    from localization import catalogues
    translations=catalogues(Path(__file__).resolve().parents[1]/'static')
    for language in ('de','fr','it'):
        page.select_option('#language',language)
        page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
        expected=translations[language]['complete']
        page.wait_for_function('(label)=>document.querySelector("#lab-pilot-progress")?.textContent.startsWith(label)',arg=expected)
        assert page.locator('#lab-pilot-progress').inner_text().find(translations[language]['requests'])>=0
        assert page.locator('#lab-pilot-progress').inner_text().find(translations[language]['cached'])>=0
    page.select_option('#language','en')
    page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
    assert page.evaluate('busy') is False
    assert page.locator('#lab-pilot-start').is_disabled()
    page.locator('.nav[data-view="intelligence"]').click()
    assert page.locator('#pilot-background').is_visible()
    page.locator('#pilot-background-open').click();page.wait_for_selector('#view-musicbrainz',state='visible')
    page.wait_for_function('(sid)=>document.querySelector("#musicbrainz-snapshot").value===sid',arg=sid)
    assert page.locator('#lab-pilot-progress').inner_text().startswith('complete')
    page.screenshot(path=str(output/'musicbrainz-enrichment-page.png'))
    page.locator('.nav[data-view="files"]').click();page.locator('[data-open-lab="pilot"]').click()
    page.wait_for_selector('#view-musicbrainz',state='visible')
    assert page.locator('#page-title').inner_text()=='MusicBrainz'
    page.locator('.musicbrainz-source details summary').click()
    page.select_option('#musicbrainz-snapshot',original_id)
    page.wait_for_function('(sid)=>Journeys.context()?.snapshot===sid',arg=original_id)
    assert page.locator('#lab-pilot-consent').is_checked() is False
    assert page.locator('#lab-pilot-start').is_disabled()
    page.unroute('**/api/lab/musicbrainz/'+batch['id']+'/start')
    page.unroute('**/api/lab/musicbrainz/context')

    # Exercise the union of both PRs against real saved rows, with no provider calls.
    previous_sort=page.evaluate('()=>[labBatch,labPilotOffset,labPilotSort,labPilotDirection]')
    sorted_tracks=[track({'id':'sort-'+str(i),'title':f'Title {124-i:03}',
                         'artist':'Synthetic artist','genre':'House','duration':200}) for i in range(125)]
    sort_sid=store.save_snapshot({'schema':1,'scope_key':'synthetic:combined-sort',
                                 'tracks':sorted_tracks,'playlists':[]},'Combined sorting')['id']
    sorted_batch=create_batch(store,store.snapshot(sort_sid),target='random',sample_size=150,seed='stable-sort')
    with store.connection() as db:
        for identity,status in [('sort-0','missing'),('sort-1','playable'),('sort-2','inaccessible')]:
            db.execute('INSERT INTO file_health_records VALUES (?,?,?,?,?,?,?,?)',
                       ('snapshot:'+sort_sid,identity,'Title','Artist','House',status,123.0,''))
    page.evaluate('(id)=>{labBatch=id;labPilotOffset=0;labPilotSort="sample";labPilotDirection="asc";return labLoadPilot();}',sorted_batch['id'])
    assert page.locator('#lab-pilot-sort option').count()==10
    assert page.locator('#lab-pilot-results [data-sort-column]').count()==0
    page.locator('#lab-pilot-results [data-lab-pilot-sort="title"]').click()
    page.wait_for_function('document.querySelector("#lab-pilot-results tbody tr td:first-child").textContent.includes("Title 000")')
    page.locator('#lab-pilot-next').click()
    page.wait_for_function('document.querySelector("#lab-pilot-count").textContent.includes("51")')
    assert 'Title 050' in page.locator('#lab-pilot-results tbody tr td:first-child').first.inner_text()
    page.evaluate('()=>labLoadPilot(false)')
    assert 'Title 050' in page.locator('#lab-pilot-results tbody tr td:first-child').first.inner_text()
    page.locator('#lab-pilot-results [data-lab-pilot-sort="title"]').click()
    page.wait_for_function('document.querySelector("#lab-pilot-results tbody tr td:first-child").textContent.includes("Title 124")')
    page.select_option('#lab-pilot-sort','file_status')
    page.select_option('#lab-pilot-direction','asc')
    page.wait_for_function('document.querySelector("#lab-pilot-results tbody tr").dataset.mbTrack==="sort-1"')
    cell=page.locator('#lab-pilot-results tr[data-mb-track="sort-1"] .lab-pilot-file-status')
    assert cell.inner_text()=='Playable'
    page.evaluate('()=>document.querySelector(\'#lab-pilot-results [data-play-track="sort-1"]\').dispatchEvent(new CustomEvent("workbench-file-status",{bubbles:true,detail:{status:"missing"}}))')
    assert cell.inner_text()=='Playable'
    page.evaluate('()=>labLoadPilot(false)')
    assert page.locator('#lab-pilot-sort').input_value()=='file_status'
    assert page.locator('#lab-pilot-direction').input_value()=='asc'
    assert page.evaluate('()=>preferences.get("workbench-mb-sort")')=='file_status'
    page.select_option('#lab-pilot-direction','desc')
    page.wait_for_function('document.querySelector("#lab-pilot-results tbody tr").dataset.mbTrack==="sort-2"')
    assert page.locator('#lab-pilot-results tbody tr').nth(3).locator('.lab-pilot-file-status').inner_text()=='Unchecked'
    page.evaluate('(s)=>{[labBatch,labPilotOffset,labPilotSort,labPilotDirection]=s;rememberPilotSort();return labLoadPilot();}',previous_sort)

    assert store.snapshot(sid)==before
    page.select_option('#theme',previous_theme);page.set_viewport_size(previous_viewport)
    page.evaluate('(id)=>Journeys.selectContext("snapshot:"+id,true)',original_id)
    return {'playback_identity':True,'unavailable_audio':True,'playlist_contents':True,'recurring_sessions':True,
            'serato_preview_and_readback':True,'chart_review':True,'background_completion':True,'dedicated_musicbrainz_page':True,'source_scope_guard':True,'enrich_navigation':True,'immutable_capture':True,'screenshots':'synthetic','fixture_inventory':inventory}
