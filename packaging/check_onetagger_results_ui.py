"""Real HTTP results exchange: synthetic ID3 files, explicit review and persistence."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urlsplit

from audio_paths import validate
from localization import LANGUAGES
from test_onetagger_results import mp3_tags


def check_onetagger_results_ui(browser,base,store,root,output):
    from playwright.sync_api import expect
    folder=root/'onetagger-results-synthetic';folder.mkdir()
    before={'title':'Disk original','artist':'Invented artist','album':'Disk album','genre':'House','year':2010}
    paths=[folder/f'100%20 Café 日本 {i}.mp3' for i in range(4)]
    for path in paths:mp3_tags(path,before)
    tracks=[{'id':f'result-{i}','title':f'Result {i:03} <mix>','artist':'Captured artist','album':'Captured album',
             'genre':'House','year':2000,'rating':5,'bpm':128,'tonality':'8A','play_count':17,
             'current_path':'D:/Music/'+paths[i if i<4 else 0].name,
             'xml_location':'file://localhost/D:/Music/original.mp3','cues':[{'kind':1,'in_ms':1000}],
             'playlists':['Keep this set']} for i in range(64)]
    scope='synthetic:onetagger-results'
    sid=store.save_snapshot({'scope_key':scope,'tracks':tracks},'OneTagger results synthetic')['id']
    original=deepcopy(store.snapshot(sid))
    store.set_setting('audio_paths:'+scope,validate([{'recorded_root':'D:/Music','local_root':str(folder)}],[root]))
    context=browser.new_context(locale='en-US',viewport={'width':1440,'height':1050})
    context.add_init_script("if(location.protocol==='http:')localStorage.setItem('library-workbench.language.v1','en')")
    context.tracing.start(screenshots=True,snapshots=True,sources=True)
    page=context.new_page();errors=[];external=[];origin=urlsplit(base)
    page.on('pageerror',lambda e:errors.append(str(e)))
    context.on('request',lambda r:external.append(r.url) if urlsplit(r.url).scheme not in ('data','blob','file') and
               (urlsplit(r.url).scheme,urlsplit(r.url).netloc)!=(origin.scheme,origin.netloc) else None)
    def upload(data,status=200):
        def send():
            with page.expect_response(lambda r:r.url.endswith('/import-results') and r.request.method=='POST') as pending:
                page.locator('#onetagger-report-file').set_input_files({'name':'tagging-results.json','mimeType':'application/json','buffer':data})
            return pending.value
        if status==200:
            with page.expect_response(lambda r:r.url==base+'/api/onetagger/'+identity+'/review' and r.request.method=='GET') as reviewed:
                response=send()
            assert reviewed.value.ok,reviewed.value.text()
        else:response=send()
        assert response.status==status,response.text()
        if status==200:
            expect(page.locator('#onetagger-report-summary')).to_contain_text('Imported OneTagger report')
            expect(page.locator('#progress')).not_to_be_visible()
        return response
    def saved(identity):return store.setting('onetagger:'+identity)['scan']
    try:
        page.goto(base,wait_until='networkidle');page.locator('.nav[data-view="musicbrainz"]').click()
        page.wait_for_selector('#onetagger-snapshot option[value="'+sid+'"]',state='attached')
        page.select_option('#onetagger-snapshot',sid)
        for i in range(4):page.locator('[data-onetagger-track="result-'+str(i)+'"]').check()
        page.locator('#onetagger-next').click();page.locator('[data-onetagger-track="result-51"]').check()
        expect(page.locator('#onetagger-selected')).to_contain_text('5 / 500')
        page.locator('#onetagger-create').click()
        page.wait_for_function('document.querySelector("#onetagger-selections").value.length===32')
        identity=page.locator('#onetagger-selections').input_value()
        with page.expect_download() as pending:page.locator('#onetagger-manifest').click()
        target=output/'onetagger-results-selection.json';pending.value.save_as(target)
        manifest=json.loads(target.read_text());assert {r['track_id'] for r in manifest['tracks']}=={'result-0','result-1','result-2','result-3','result-51'}
        after={'title':'<svg onload="window.resultsInjected=true">Tagged Café</svg>',
               'artist':'DJ, Producer','album':'New album','genre':'Techno','year':2020,
               'label':'Independent label','composer':'Composer'}
        mp3_tags(paths[0],{**after,'year':'2020-12-31'})
        expected_audio={path:sha256(path.read_bytes()).hexdigest() for path in paths}
        fixture=json.loads((Path(__file__).resolve().parents[1]/'docs/fixtures/onetagger-results-v2.json').read_text())
        report={**fixture,'cancelled':True,'selection':{k:manifest[k] for k in ('id','snapshot','snapshot_digest','scope_key','mapping_revision')},'tracks':[]}
        for item in manifest['tracks']:
            written=item['track_id'] in ('result-0','result-51');path=Path(item['local_path']);state=path.stat()
            status='written' if written else {'result-1':'failed','result-2':'skipped','result-3':'unprocessed'}[item['track_id']]
            attempts=[] if status=='unprocessed' else [{**fixture['tracks'][0]['attempts'][0],'status':status}]
            if written:
                attempts=[{**attempts[0],'provider':'first-provider','status':'failed','score':None},
                          {**attempts[0],'provider':'fallback-provider','score':91.5}]
            report['tracks'].append({**fixture['tracks'][0],'track_id':item['track_id'],'local_path':str(path),
                                    'final_path':str(path),'before':before,'after':after if written else before,
                                    'file_state':{'size':state.st_size,'modified_ns':str(state.st_mtime_ns)},
                                    'status':status,'attempts':attempts})
        data=json.dumps(report,ensure_ascii=False,indent=2).encode()
        (output/'onetagger-producer-shaped-results.json').write_bytes(data)
        upload(data)
        first=saved(identity);assert first['summary']=={'tracks':5,'verified':2,'not_written':3,'unreadable':0,'changes':14},first['summary']
        assert first['report']['digest']==sha256(data).hexdigest()
        expect(page.locator('#onetagger-report-summary')).to_contain_text('Cancelled run')
        expect(page.locator('[data-onetagger-field="genre"]')).to_have_count(2)
        assert not page.locator('#onetagger-review input:checked').count()
        expect(page.locator('#onetagger-stage')).to_be_disabled()
        assert store.overrides(scope)=={}
        page.locator('#onetagger-review details').first.locator('summary').click()
        expect(page.locator('#onetagger-review details').first).to_contain_text('fallback-provider')
        assert not page.locator('#onetagger-review img,#onetagger-review svg').count()
        assert page.evaluate('window.resultsInjected') is None
        with page.expect_download() as pending:page.locator('#onetagger-evidence').click()
        evidence=output/'onetagger-review.json';pending.value.save_as(evidence)
        assert json.loads(evidence.read_text())['scan']==first
        expect(page.locator('#toast')).not_to_be_visible(timeout=10000)
        page.locator('#onetagger-results').screenshot(path=str(output/'onetagger-results.png'))
        duplicate=data.replace(b'"version": 2',b'"version": 1, "version": 2',1)
        upload(duplicate,400);expect(page.locator('#toast')).to_contain_text('Duplicate JSON keys')
        assert saved(identity)==first
        # All paths remain unchanged; only the reported file state is stale.
        stale=deepcopy(report)
        for row in stale['tracks']:
            if row['status']=='written':row['file_state']['modified_ns']='1'
        upload(json.dumps(stale).encode());assert saved(identity)['summary']['verified']==0
        assert saved(identity)['summary']['unreadable']==2
        expect(page.locator('#onetagger-review input')).to_have_count(0)
        expect(page.locator('#onetagger-stage')).to_be_disabled()
        upload(data);current=saved(identity)
        page.locator('#onetagger-unlock').click();expect(page.locator('#toast')).to_contain_text('Staging unlocked')
        token=context.request.get(base+'/api/status').json()['token']
        response=context.request.post(base+'/api/onetagger/'+identity+'/stage',headers={'X-Workbench-Token':token},data={
            'reviewed':True,'review_revision':first['review_revision'],'edit_revision':first['edit_revision'],
            'changes':[{'track_id':'result-0','field':'genre'}]})
        assert response.status==409,response.text()
        page.locator('[data-onetagger-field="label"][data-track="result-0"]').check()
        page.locator('#onetagger-reviewed').check()
        with page.expect_response(lambda r:r.url.endswith('/stage') and r.request.method=='POST') as pending:
            page.locator('#onetagger-stage').click()
        assert pending.value.status==200,pending.value.text()
        expect(page.locator('#toast')).to_contain_text('Metadata staged locally')
        edits=store.overrides(scope);assert set(edits)=={'result-0'} and set(edits['result-0'])=={'label'}
        assert edits['result-0']['label']['value']=='Independent label'
        provenance=json.loads(edits['result-0']['label']['origin'])
        assert provenance['report']['digest']==sha256(data).hexdigest() and len(provenance['attempts'])==2
        expect(page.locator('#onetagger-report-summary')).to_contain_text('Review is outdated')
        expect(page.locator('#onetagger-stage')).to_be_disabled()
        assert page.locator('#onetagger-review input').evaluate_all('nodes=>nodes.every(n=>n.disabled)')
        page.reload(wait_until='networkidle');page.locator('.nav[data-view="musicbrainz"]').click()
        page.select_option('#onetagger-snapshot',sid)
        page.wait_for_selector('#onetagger-selections option[value="'+identity+'"]',state='attached')
        page.select_option('#onetagger-selections',identity)
        expect(page.locator('#onetagger-report-summary')).to_contain_text('Review is outdated')
        messages=json.loads((Path(__file__).resolve().parents[1]/'static/locales.json').read_text())['messages']
        for language in LANGUAGES:
            page.select_option('#language',language)
            page.wait_for_function("document.documentElement.dataset.languageBusy !== 'true'")
            expect(page.locator('#onetagger-report-summary h4')).to_have_text(messages['Imported OneTagger report'].get(language,'Imported OneTagger report'))
            expect(page.locator('#onetagger-stage')).to_be_disabled()
        page.select_option('#language','en');page.wait_for_function("document.documentElement.dataset.languageBusy !== 'true'")
        page.set_viewport_size({'width':390,'height':844})
        page.locator('#onetagger-report-file').scroll_into_view_if_needed()
        expect(page.locator('#onetagger-report-file')).to_be_in_viewport()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        assert store.snapshot(sid)==original
        for path,digest in expected_audio.items():assert sha256(path.read_bytes()).hexdigest()==digest
        assert not errors,errors;assert not external,external
        return {'status':'passed','selection_id':identity,'review_revision':current['review_revision'],
                'report_digest':sha256(data).hexdigest(),'selected_tracks':5,'verified_tracks':2,'not_written':3,
                'extended_label_composer_review':True,'raw_upload_digest':True,'date_year_readback':True,'provider_fallback_retained':True,
                'duplicate_json_rejected':True,'stale_report_held':True,'stale_review_rejected':True,
                'explicit_staged_fields':1,'snapshot_and_audio_preserved':True,'languages':len(LANGUAGES),
                'mobile_controls':True,'real_http':True,'mocked_api_responses':False}
    except Exception:
        page.screenshot(path=str(output/'onetagger-results-failure.png'),full_page=True)
        raise
    finally:
        context.tracing.stop(path=str(output/'onetagger-results-trace.zip'));context.close()

