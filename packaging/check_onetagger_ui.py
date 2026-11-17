"""Exercise the OneTagger handoff/review using invented tags and silent WAV."""
import json
from pathlib import Path
import struct
from urllib.parse import quote,unquote
import wave

from audio_paths import validate
from onetagger_bridge import read_tags
from onetagger_results import FIELDS

CAPTURED_TITLE='<img src=x onerror="window.bridgeInjected=true"> & DJ'
TAGGED_TITLE='<svg onload="window.bridgeInjected=true">Retagged</svg>'


def add_tags(path):
    fields=[]
    for key,value in ((b'INAM',TAGGED_TITLE.encode()+b'\0'),(b'IGNR',b'Techno\0')):
        fields.append(key+struct.pack('<I',len(value))+value+(b'\0' if len(value)%2 else b''))
    info=b'INFO'+b''.join(fields);chunk=b'LIST'+struct.pack('<I',len(info))+info
    original=path.read_bytes();path.write_bytes(original[:4]+struct.pack('<I',len(original)-8+len(chunk))+original[8:]+chunk)


def check_onetagger_ui(browser,base,store,root,output):
    folder=root/'onetagger-synthetic';folder.mkdir();audio=folder/'100%20 Synthetic.wav'
    with wave.open(str(audio),'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(8000);stream.writeframes(b'\0\0'*800)
    scope='synthetic:onetagger'
    source={'scope_key':scope,'tracks':[{'id':'bridge-one','title':CAPTURED_TITLE,'artist':'A < B & "Producer"','genre':'House','rating':5,
            'current_path':'D:/Music/'+audio.name,'xml_location':'file://localhost/D:/Music/100%2520%20Synthetic.wav'}]}
    sid=store.save_snapshot(source,'OneTagger synthetic selection')['id'];before=store.snapshot(sid)
    store.set_setting('audio_paths:'+scope,validate([{'recorded_root':'D:/Music','local_root':str(folder)}],[root]))
    context=browser.new_context(locale='en-US',viewport={'width':1500,'height':1050})
    context.add_init_script("localStorage.setItem('library-workbench.language.v1','en')")
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    try:
        page.goto(base,wait_until='networkidle');page.locator('.nav[data-view="musicbrainz"]').click()
        page.wait_for_selector('#onetagger-snapshot option[value="'+sid+'"]',state='attached')
        page.select_option('#onetagger-snapshot',sid)
        page.wait_for_selector('[data-onetagger-track="bridge-one"]')
        assert CAPTURED_TITLE in page.locator('#onetagger-tracks').inner_text()
        assert page.locator('#onetagger-tracks img, #onetagger-tracks svg').count()==0
        page.locator('[data-onetagger-track="bridge-one"]').check();page.locator('#onetagger-create').click()
        page.wait_for_function('document.querySelector("#onetagger-selections").value.length===32')
        identity=page.locator('#onetagger-selections').input_value()
        with page.expect_download() as downloaded:page.locator('#onetagger-playlist').click()
        destination=output/'synthetic-onetagger-selection.m3u';downloaded.value.save_as(destination)
        assert unquote(destination.read_text().splitlines()[1])==str(audio.resolve())
        manifest=json.loads(page.request.get(base+'/api/onetagger/'+identity+'/manifest').text())
        assert manifest['tracks'][0]['recorded_references']['current_path']=='D:/Music/'+audio.name
        add_tags(audio);retagged=audio.read_bytes()
        page.locator('#onetagger-rescan').click()
        page.wait_for_selector('[data-onetagger-field="genre"]')
        assert TAGGED_TITLE in page.locator('#onetagger-review').inner_text()
        assert CAPTURED_TITLE in page.locator('#onetagger-review').inner_text()
        assert page.locator('#onetagger-review img, #onetagger-review svg').count()==0
        assert page.evaluate('window.bridgeInjected') is None
        # Import a producer-contract report and independently compare it to the
        # real WAV before exposing the same explicit, initially unchecked review.
        report=json.loads((Path(__file__).resolve().parents[1]/'docs/fixtures/onetagger-results-v1.json').read_text(encoding='utf-8'))
        report['selection']={k:manifest[k] for k in ('id','snapshot','snapshot_digest','scope_key','mapping_revision')}
        row=report['tracks'][0];row.update(track_id='bridge-one',local_path=str(audio.resolve()),final_path=str(audio.resolve()))
        actual,state,_=read_tags(audio);row['after']={f:actual.get(f) for f in FIELDS}
        row['file_state']={'size':state[2],'modified_ns':str(state[3])}
        page.locator('#onetagger-report-file').set_input_files({'name':'results.json','mimeType':'application/json','buffer':json.dumps(report).encode()})
        page.wait_for_selector('#onetagger-review details')
        assert 'OneTagger report' in page.locator('#onetagger-review').inner_text()
        assert store.overrides(scope)=={}
        assert not page.locator('[data-onetagger-field="genre"]').is_checked()
        assert page.locator('#onetagger-stage').is_disabled()
        page.locator('[data-onetagger-field="genre"]').check();page.locator('#onetagger-reviewed').check()
        page.locator('#onetagger-unlock').click();page.wait_for_function('document.querySelector("#toast").textContent.includes("Staging unlocked")')
        page.locator('#onetagger-bridge').scroll_into_view_if_needed();page.screenshot(path=str(output/'onetagger-bridge.png'))
        page.locator('#onetagger-stage').click();page.wait_for_function('document.querySelector("#toast").textContent.includes("Metadata staged locally")')
        edits=store.overrides(scope)['bridge-one'];assert set(edits)=={'genre'},edits
        assert edits['genre']['value']=='Techno';assert store.snapshot(sid)==before
        assert json.loads(edits['genre']['origin'])['report']['run_id']==report['run_id']
        assert audio.read_bytes()==retagged;assert not errors,errors
        # Selection IDs read from the DOM stay a single URL component, even
        # if a compromised response supplies quotes, markup or separators.
        hostile='"><img src=x onerror="window.bridgeInjected=true">/../other'
        choices=page.request.get(base+'/api/onetagger?snapshot='+sid).json()
        choices['selections'].append({'id':hostile,'created':'2026-01-01T12:00:00Z','tracks':1})
        page.route('**/api/onetagger?*',lambda route:route.fulfill(json=choices))
        page.route('**/api/onetagger/*/review',lambda route:route.fulfill(json={'scan':None}))
        page.evaluate('()=>OneTaggerBridge.load()')
        with page.expect_response(lambda response:response.url.endswith('/review')):
            page.select_option('#onetagger-selections',hostile)
        for kind,suffix in (('playlist','playlist'),('manifest','manifest')):
            assert page.locator('#onetagger-'+kind).get_attribute('href')=='/api/onetagger/'+quote(hostile,safe='')+'/'+suffix
        assert page.evaluate('window.bridgeInjected') is None
        assert not errors,errors
        from check_onetagger_results_ui import check_onetagger_results_ui
        results=check_onetagger_results_ui(browser,base,store,root,output)
        return {'m3u_roundtrip':True,'original_references_preserved':True,'tag_rescan':True,'results_json_review':True,'results_workflow':results,
                'explicit_field_selection':True,'snapshot_unchanged':True,'no_audio_writes':True,
                'metadata_rendered_as_text':True,'selection_urls_encoded':True,'no_page_errors':True}
    finally:context.close()

