"""Real HTTP/SQLite STEMS acceptance using generated metadata, without inference."""
from hashlib import sha256
from pathlib import Path
import json
import re
from urllib.parse import parse_qs,urlsplit
import zipfile


def check_stems_workflows_ui(browser,base,store,root,output):
    from playwright.sync_api import expect
    from localization import LANGUAGES
    from test_stems_followup import MODEL,KEY,ni_bytes,manifest,write_cache
    folder=root/'stems workflow 日本';folder.mkdir()
    source=folder/'Invented audio.wav';source.write_bytes(b'synthetic metadata association only; no audio')
    cache=write_cache(folder/'RB Stems Plus Cache.noindex')
    meta=folder/'metadata';meta.mkdir();(meta/'test.manifest').write_bytes(manifest(source))
    (meta/'test.kept').write_text(f'rbstemsplus-kept 1\nuntil 1\n{MODEL} {KEY}\n')
    (meta/'producer.stem.m4a').write_bytes(ni_bytes())
    archive=folder/'containers.zip'
    with zipfile.ZipFile(archive,'w') as z:z.writestr('unicode 日本/producer.stem.mp4',ni_bytes())
    captured_source={'scope_key':'synthetic:stems:followup','capabilities':{},'tracks':[
        {'id':str(i),'title':f'STEM example {i:03} 日本 <mix>','artist':'Invented artist',
         'current_path':'spotify:track:invented' if i%2==0 else str(source)} for i in range(125)]}
    sid=store.save_snapshot(captured_source,'STEMS workflows 日本')['id'];original=store.snapshot(sid)
    originals={p:sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*') if p.is_file()}
    context=browser.new_context(locale='en-US',viewport={'width':1440,'height':1050})
    context.add_init_script("if(location.protocol==='http:')localStorage.setItem('library-workbench.language.v1','en')")
    context.tracing.start(screenshots=True,snapshots=True,sources=True)
    page=context.new_page();errors=[];external=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    origin=urlsplit(base)
    context.on('request',lambda r:external.append(r.url) if urlsplit(r.url).scheme not in ('data','blob','file') and
               (urlsplit(r.url).scheme,urlsplit(r.url).netloc)!=(origin.scheme,origin.netloc) else None)
    def download():
        response=context.request.get(base+page.locator('#lab-report-download').get_attribute('href'))
        assert response.ok,response.text()
        return response.json()
    def run():
        previous=page.locator('#lab-report-select').input_value()
        page.locator('#lab-stems').click()
        page.wait_for_function('(old)=>document.querySelector("#lab-report-select").value && document.querySelector("#lab-report-select").value!==old',arg=previous)
        identity=page.locator('#lab-report-select').input_value()
        expect(page.locator('#lab-report-download')).to_have_attribute('href',re.compile('/'+identity+'/download'))
        return identity,download()
    def apply_filter(field,value):
        def matches(response):
            return '/api/lab/reports/' in response.url and parse_qs(urlsplit(response.url).query,keep_blank_values=True).get(field)==[value]
        with page.expect_response(matches) as pending:page.select_option('#lab-report-'+field,value)
        assert pending.value.ok,pending.value.text()
        expect(page.locator('#lab-report-download')).to_have_attribute('href',re.compile(field+'='+value))
        return download()
    try:
        page.goto(base,wait_until='networkidle');page.locator('.nav[data-view="lab"]').click();page.select_option('#lab-snapshot',sid)
        page.locator('[data-lab-tab="stems"]').click()
        page.select_option('#lab-stems-target','rbstemsplus');page.select_option('#lab-stems-enabled','enabled')
        page.select_option('#lab-stems-mode','performance');page.select_option('#lab-stems-quality','quality')
        page.select_option('#lab-stems-parts','4')
        page.locator('#lab-panel-stems details summary').click()
        page.select_option('#lab-stems-platform','macos');page.select_option('#lab-stems-architecture','arm64')
        for field,value in {'app_version':'7.2.19','engine_version':'0002','runtime_version':'1.18.0','model_sha256':MODEL}.items():
            page.fill('#lab-stems-'+field,value)
        page.fill('#lab-stems-path','\n'.join(map(str,(cache,meta,folder,archive))))
        page.locator('#lab-stems-verify').check()
        identity,result=run();summary=result['summary']
        assert summary['stems_eligibility']['blocked']==63 and summary['stems_eligibility']['eligible_candidates']==62
        assert summary['format_inspection']['recognized_ni_containers']==2
        assert summary['format_inspection']['provider_cache']['manifest_associations_consistent']==1
        assert summary['stems']['prepared_tracks'] is None
        prep=next(r for r in result['rows'] if r['section']=='stems_preparation')
        assert prep['cache_state']=='consistent' and prep['model_status']=='matches_declared_model'
        assert prep['cache_profile_status']=='matches_declared_profile' and prep['source_association']=='metadata_match'
        assert all(r.get('native_stems_readiness') is None for r in result['rows'])
        assert not page.locator('#lab-report-rows img').count()
        page.locator('#lab-panel-stems').screenshot(path=str(output/'stems-workflows.png'))
        filtered=apply_filter('asset_family','preparation_manifest')
        filtered=apply_filter('provider','rbstemsplus');filtered=apply_filter('cache_state','consistent')
        assert len(filtered['rows'])==1 and filtered['rows'][0]['section']=='stems_preparation'
        # Facets describe the whole saved report, so an empty intersection is reversible.
        empty=apply_filter('source_provider','spotify');assert empty['rows']==[]
        expect(page.locator('#lab-report-count')).to_contain_text('0 findings')
        for field in ('asset_family','provider','cache_state'):apply_filter(field,'')
        blocked=apply_filter('eligibility','blocked');assert len(blocked['rows'])==63
        expect(page.locator('#lab-report-rows tbody tr')).to_have_count(50)
        with page.expect_response(lambda r:'/api/lab/reports/' in r.url and 'offset=50' in r.url) as pending:
            page.locator('#lab-report-next').click()
        assert pending.value.ok;expect(page.locator('#lab-report-rows tbody tr')).to_have_count(13)
        assert len(download()['rows'])==63
        with page.expect_download() as pending:page.locator('#lab-report-download').click()
        downloaded=output/'stems-filtered-report.json';pending.value.save_as(downloaded)
        assert json.loads(downloaded.read_text())['rows']==blocked['rows']
        # No scan is necessary to reopen a persisted report.
        page.reload(wait_until='networkidle');page.locator('.nav[data-view="lab"]').click()
        page.select_option('#lab-report-select',identity)
        expect(page.locator('#lab-report-download')).to_have_attribute('href',re.compile('/'+identity+'/download'))
        assert download()['summary']==summary
        page.locator('[data-lab-tab="stems"]').click()
        page.fill('#lab-stems-path','')
        _,source_only=run();assert source_only['summary']['stems_eligibility']['tracks']==125
        assert 'format_inspection' not in source_only['summary']
        page.locator('#lab-panel-stems details summary').click()
        page.fill('#lab-stems-model_sha256','short')
        with page.expect_response(lambda r:r.url.endswith('/api/lab/check') and r.request.method=='POST') as pending:
            page.locator('#lab-stems').click()
        assert pending.value.status==400
        expect(page.locator('#toast')).to_contain_text('64-digit SHA-256')
        page.fill('#lab-stems-model_sha256',MODEL)
        # Both absence and stale associations are visible through the same workflow.
        page.fill('#lab-stems-path','\n'.join(map(str,(cache,meta,folder))))
        source.write_bytes(b'changed synthetic source');originals[source]=sha256(source.read_bytes()).hexdigest()
        _,stale=run();assert any(r.get('cache_state')=='stale' for r in stale['rows'])
        detached=cache.with_name('detached-cache');cache.rename(detached)
        _,unavailable=run();assert unavailable['summary']['unavailable_scopes']==1
        assert any(r.get('cache_state')=='unavailable' for r in unavailable['rows'])
        detached.rename(cache)
        _,reconnected=run();assert reconnected['summary']['unavailable_scopes']==0
        descriptor=cache/MODEL/KEY[:2]/(KEY+'.desc');descriptor.unlink();originals.pop(descriptor)
        _,incomplete=run();assert any(r.get('cache_state')=='incomplete' for r in incomplete['rows'])
        # Language changes update the new tab and its controls in the existing session.
        messages=json.loads((Path(__file__).resolve().parents[1]/'static/locales.json').read_text())['messages']
        for language in LANGUAGES:
            page.select_option('#language',language)
            expect(page.locator('[data-lab-tab="stems"]')).to_have_text(messages['STEMS workflows'].get(language,'STEMS workflows'))
        page.select_option('#language','en')
        page.set_viewport_size({'width':390,'height':844})
        page.locator('#lab-stems').scroll_into_view_if_needed();expect(page.locator('#lab-stems')).to_be_in_viewport()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        page.screenshot(path=str(output/'stems-workflows-mobile.png'),full_page=True)
        assert store.snapshot(sid)==original
        for path,digest in originals.items():assert sha256(path.read_bytes()).hexdigest()==digest
        assert not errors,errors;assert not external,external
        return {'status':'passed','saved_report_id':identity,'tracks':125,'blocked_sources':63,'candidate_sources':62,
                'ni_containers':2,'cache_states':['consistent','stale','incomplete','unavailable'],'source_only':True,'reconnect':True,
                'filters':'asset_family, provider, cache_state, eligibility, source_provider',
                'pagination_and_full_download':True,'languages':len(LANGUAGES),'sources_preserved':True,
                'native_prepared_tracks':None,'inference_run':False,'real_http':True}
    except Exception:
        page.screenshot(path=str(output/'stems-workflows-failure.png'),full_page=True)
        raise
    finally:
        context.tracing.stop(path=str(output/'stems-workflows-trace.zip'));context.close()
