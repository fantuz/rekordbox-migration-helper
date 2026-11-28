"""Real HTTP/SQLite STEMS acceptance using generated metadata, without inference."""
from ui_navigation import select_collection, open_collection_picker
from hashlib import sha256
from pathlib import Path
import json
import re
from urllib.parse import parse_qs,urlsplit
import zipfile


def check_stems_workflows_ui(browser,base,store,root,output):
    from playwright.sync_api import expect
    from analysis_audit import audit_assets
    from localization import LANGUAGES
    from test_asset_formats import stems_bytes
    from test_stems_followup import MODEL,KEY,ni_bytes,manifest,write_cache
    from test_stems_workflows import recordbox_fixture_key
    folder=root/'stems workflow 日本';folder.mkdir()
    source=folder/'Invented audio.wav';source.write_bytes(b'synthetic metadata association only; no audio')
    mp3=folder/'Invented clock 日本.MP3';mp3.write_bytes(b'synthetic MP3 path metadata only')
    cache=write_cache(folder/'RB Stems Plus Cache.noindex')
    meta=folder/'metadata';meta.mkdir();(meta/'test.manifest').write_bytes(manifest(source))
    (meta/'test.kept').write_text(f'rbstemsplus-kept 1\nuntil 1\n{MODEL} {KEY}\n')
    (meta/'producer.stem.m4a').write_bytes(ni_bytes())
    saved=folder/'Recordbox'/'stems';saved.mkdir(parents=True)
    key='0123456789abcdef01234567'
    speed_name=key+'-htdemucs.stems';quality_name=key+'-htdemucs_ft.stems'
    for filename,frames in ((speed_name,8),(quality_name,8),('renamed.stems',2)):
        (saved/filename).write_bytes(stems_bytes(frames))
    recordbox_zip=folder/'Recordbox.zip'
    with zipfile.ZipFile(recordbox_zip,'w') as z:
        z.writestr('stems/'+speed_name,stems_bytes(8))
        z.writestr('stems/'+quality_name,stems_bytes(9))
        z.writestr('ambiguous/'+speed_name,stems_bytes(8))
        z.writestr('ambiguous//'+speed_name,stems_bytes(8)[:-1])
        z.writestr('ambiguous/'+quality_name,stems_bytes(8))
    archive=folder/'containers.zip'
    with zipfile.ZipFile(archive,'w') as z:z.writestr('unicode 日本/producer.stem.mp4',ni_bytes())
    captured_source={'scope_key':'synthetic:stems:followup','capabilities':{},'tracks':[
        {'id':str(i),'title':f'STEM example {i:03} 日本 <mix>','artist':'Invented artist',
         'current_path':'spotify:track:invented' if i%2==0 else str(mp3 if i==1 else source)} for i in range(125)]}
    sid=store.save_snapshot(captured_source,'STEMS workflows 日本')['id'];original=store.snapshot(sid)
    # Persist the first two ZIP members under a small inventory budget.
    partial_summary,partial_rows=audit_assets(original,str(recordbox_zip),lambda *_:None,max_files=3,inspect=True)
    partial_id=store.save_report('formats',[sid],partial_summary,partial_rows)['id']
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
    def run(button='#lab-stems'):
        previous=page.locator('#lab-report-select').input_value()
        page.locator(button).click()
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
        page.goto(base,wait_until='networkidle');page.locator('.nav[data-view="lab"]').click();select_collection(page,'#lab-snapshot',sid)
        page.select_option('#lab-report-select',partial_id)
        card=page.locator('#lab-recordbox-stems')
        partial_count=card.locator('.lab-summary > div').filter(has_text='Unconfirmed pairs (partial ZIP scan)')
        expect(partial_count.locator('b')).to_have_text('1')
        expect(page.locator('#lab-report-section option[value="recordbox_stems_pair"]')).to_have_count(0)
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
        recordbox=summary['format_inspection']['recordbox_saved_stems']
        assert (recordbox['speed_files'],recordbox['quality_files'],recordbox['unidentified_files'],
                recordbox['paired_keys'],recordbox['recognized_bytes'])==(1,1,1,1,336)
        expect(partial_count).to_have_count(0)
        for label,value in [('Speed files','1'),('Sound quality files','1'),('Files with unknown variant','1'),
                            ('Keys with both variants','1'),('Total size of recognized files','336 B')]:
            expect(card.locator('.lab-summary > div').filter(has_text=label).locator('b')).to_have_text(value)
        card.screenshot(path=str(output/'recordbox-saved-stems.png'))
        files=apply_filter('provider','recordbox')
        assert {row['section'] for row in files['rows']}=={'stems_cache','recordbox_stems_pair'}
        findings=page.locator('#lab-report-rows')
        expect(findings).to_contain_text('Filename indicates Speed (htdemucs).',use_inner_text=True)
        expect(findings).to_contain_text('Filename indicates Sound quality (htdemucs_ft).',use_inner_text=True)
        pair=apply_filter('section','recordbox_stems_pair')
        assert len(pair['rows'])==1 and pair['rows'][0]['recordbox_key']==key
        expect(findings.locator('tbody tr')).to_have_count(1)
        expect(findings).to_contain_text('Speed 144 B · Sound quality 144 B · Total 288 B',use_inner_text=True)
        apply_filter('section','');apply_filter('provider','')
        quality=apply_filter('recordbox_variant','quality')
        assert [r['title'] for r in quality['rows']]==[quality_name]
        apply_filter('recordbox_variant','')
        page.locator('#lab-stems-path').evaluate('el=>{el.scrollTop=0;el.scrollLeft=0}')
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
        expect(card).to_be_visible()
        page.locator('[data-lab-tab="stems"]').click()
        page.fill('#lab-stems-path','')
        _,source_only=run();assert source_only['summary']['stems_eligibility']['tracks']==125
        assert 'format_inspection' not in source_only['summary']
        expect(card).to_have_count(0)
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
        # The latest Recordbox filename includes a distinct MP3 clock key. Use
        # a separate source scope and confirm both clocks without reading audio.
        clock_cache=root/'timeline stem cache';clock_cache.mkdir()
        for rekordbox_clock,model in ((False,'htdemucs'),(True,'htdemucs_ft')):
            clock_file=clock_cache/(recordbox_fixture_key(mp3,rekordbox_clock)+'-'+model+'.stems')
            clock_file.write_bytes(stems_bytes())
        page.fill('#lab-stems-path',str(clock_cache))
        page.fill('#lab-stems-recordbox-sources',str(folder))
        _,clock_report=run()
        matches=clock_report['summary']['format_inspection']['recordbox_source_matches']
        assert matches['source_paths_checked']==2 and matches['matched_cache_files']==2 and matches['source_bytes_read']==0
        linked=[r for r in clock_report['rows'] if r.get('source_association')=='metadata_match']
        assert {r['recordbox_source_timeline'] for r in linked}=={'legacy','rekordbox'}
        assert all(r['track_id']=='1' and r['native_stems_readiness'] is None for r in linked)
        expect(page.locator('#lab-recordbox-source-matches')).to_contain_text('Matched cache files')
        quality=apply_filter('recordbox_variant','quality')
        assert len(quality['rows'])==1 and quality['rows'][0]['recordbox_source_timeline']=='rekordbox'
        expect(findings).to_contain_text('Source metadata match: STEM example 001 日本 <mix> · Invented artist (Rekordbox MP3 timeline)')
        apply_filter('recordbox_variant','')
        page.locator('[data-lab-tab="formats"]').click()
        page.fill('#lab-formats-path',str(recordbox_zip))
        _,zipped=run('#lab-formats')
        inventory=zipped['summary']['format_inspection']['recordbox_saved_stems']
        assert (inventory['paired_keys'],inventory['ambiguous_keys'])==(1,1)
        expect(card.locator('.lab-summary > div').filter(has_text='Ambiguous keys').locator('b')).to_have_text('1')
        expect(findings).to_contain_text('Multiple files name the same model in this folder.',use_inner_text=True)
        expect(findings).to_contain_text('Invalid STEMS frame count or body length',use_inner_text=True)
        pair=apply_filter('section','recordbox_stems_pair')['rows'][0]
        assert pair['severity']=='review' and pair['matching_frame_counts'] is False
        expect(findings).to_contain_text('Frame counts differ (Speed 8, Sound quality 9).',use_inner_text=True)
        page.locator('[data-lab-tab="stems"]').click()
        # Language changes update the new tab and its controls in the existing session.
        messages=json.loads((Path(__file__).resolve().parents[1]/'static/locales.json').read_text())['messages']
        for language in LANGUAGES:
            page.select_option('#language',language)
            page.wait_for_function("document.documentElement.dataset.languageBusy !== 'true'")
            expect(page.locator('[data-lab-tab="stems"]')).to_have_text(messages['STEMS workflows'].get(language,'STEMS workflows'))
            expect(card.locator('h3')).to_have_text(messages['Recordbox saved STEMS'].get(language,'Recordbox saved STEMS'))
            expect(findings.locator('tbody tr td').first).to_have_text(messages['Speed and quality pair'].get(language,'Speed and quality pair'))
        page.select_option('#language','en')
        page.wait_for_function("document.documentElement.dataset.languageBusy !== 'true'")
        page.set_viewport_size({'width':390,'height':844})
        page.locator('#lab-stems').scroll_into_view_if_needed();expect(page.locator('#lab-stems')).to_be_in_viewport()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        page.screenshot(path=str(output/'stems-workflows-mobile.png'),full_page=True)
        assert store.snapshot(sid)==original
        for path,digest in originals.items():assert sha256(path.read_bytes()).hexdigest()==digest
        assert not errors,errors;assert not external,external
        return {'status':'passed','saved_report_id':identity,'tracks':125,'blocked_sources':63,'candidate_sources':62,
                'ni_containers':2,'cache_states':['consistent','stale','incomplete','unavailable'],'source_only':True,'reconnect':True,
                'recordbox_saved_variants':['speed','quality'],'recordbox_pair_and_frame_mismatch':True,
                'recordbox_ambiguous_zip_members':True,'recordbox_partial_zip_report':True,
                'filters':'asset_family, provider, cache_state, eligibility, source_provider',
                'pagination_and_full_download':True,'languages':len(LANGUAGES),'sources_preserved':True,
                'native_prepared_tracks':None,'inference_run':False,'real_http':True}
    except Exception:
        page.screenshot(path=str(output/'stems-workflows-failure.png'),full_page=True)
        raise
    finally:
        context.tracing.stop(path=str(output/'stems-workflows-trace.zip'));context.close()
