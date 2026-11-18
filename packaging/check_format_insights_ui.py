"""Real HTTP acceptance for format/STEMS inspection, native insights and report filters."""
from ui_navigation import select_collection, open_collection_picker
from copy import deepcopy
from hashlib import sha256
import re
from urllib.parse import parse_qs,urlsplit
import zipfile


def check_format_insights_ui(browser,base,store,root,output):
    from playwright.sync_api import expect
    from test_asset_formats import anlz_bytes,stems_bytes,settings_bytes,pdb_bytes,pqt2_bytes
    from test_source_insights import native_snapshot
    source=native_snapshot();sid=store.save_snapshot(source,'Format insights 日本')['id']
    captured=store.snapshot(sid)
    folder=root/'format fixtures 日本';folder.mkdir()
    bad=bytearray(settings_bytes('DEVSETTING.DAT'));bad[104]^=1
    files={'ANLZ0000.DAT':anlz_bytes((12800,13000)),'ANLZ0000.EXT':pqt2_bytes(),
           'ANLZ0000.3EX':b'\x81\xa9embedding\x80','valid.stems':stems_bytes(),
           'broken.stems':stems_bytes()[:-1],'MYSETTING.DAT':settings_bytes(),'DEVSETTING.DAT':bytes(bad),
           'export.pdb':pdb_bytes(),'exportLibrary.db':b'opaque OneLibrary candidate','drums.rbsc':b'candidate'}
    for name,raw in files.items():(folder/name).write_bytes(raw)
    archive=root/'format fixtures.zip'
    with zipfile.ZipFile(archive,'w') as z:
        for name,raw in files.items():z.writestr('PIONEER/'+name,raw)
    original={p:sha256(p.read_bytes()).hexdigest() for p in [*folder.iterdir(),archive]}
    context=browser.new_context(locale='en-US',viewport={'width':1440,'height':1050})
    context.add_init_script("if(location.protocol==='http:')localStorage.setItem('library-workbench.language.v1','en')")
    context.tracing.start(screenshots=True,snapshots=True,sources=True)
    page=context.new_page();errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def report(kind):
        previous=page.locator('#lab-report-select').input_value()
        page.locator('#lab-'+kind).click()
        page.wait_for_function('(old)=>document.querySelector("#lab-report-select").value && document.querySelector("#lab-report-select").value!==old',arg=previous)
        identity=page.locator('#lab-report-select').input_value()
        expect(page.locator('#lab-report-download')).to_have_attribute('href',re.compile('/'+identity+'/download'))
        response=context.request.get(base+page.locator('#lab-report-download').get_attribute('href'))
        assert response.ok,response.status
        return identity,response.json()
    def filter_report(field,value):
        def matches(response):
            query=parse_qs(urlsplit(response.url).query,keep_blank_values=True)
            return '/api/lab/reports/' in response.url and query.get(field)==[value]
        with page.expect_response(matches) as pending:page.select_option('#lab-report-'+field,value)
        assert pending.value.ok
        expect(page.locator('#lab-report-download')).to_have_attribute('href',re.compile(field+'='+value))
        response=context.request.get(base+page.locator('#lab-report-download').get_attribute('href'))
        assert response.ok
        return response.json()
    try:
        page.goto(base,wait_until='networkidle');page.locator('.nav[data-view="lab"]').click()
        select_collection(page,'#lab-snapshot',sid)
        page.locator('[data-lab-tab="formats"]').click()
        expect(page.locator('#lab-formats')).to_be_visible()
        page.fill('#lab-formats-path',str(folder)+'\n'+str(archive)+'\n'+str(folder))
        page.locator('#lab-formats-verify').check()
        format_id,result=report('formats')
        summary=result['summary']['format_inspection'];evidence=[r for r in result['rows'] if 'validation' in r]
        assert summary['files']==20,summary
        assert summary['corrupt']==4,summary
        assert result['summary']['stems']['prepared_tracks'] is None
        assert all(r['checksum_status']=='computed' for r in evidence)
        caches=[r for r in evidence if r['format']=='recordbox_stems_v1' and r['validation']=='recognized']
        assert len(caches)==2 and all(r['source_association']=='unknown' and r['native_stems_readiness'] is None for r in caches)
        anlz=[r for r in evidence if r['format']=='anlz' and 'PQTZ' in r['section_counts']]
        assert all(r['section_counts']['PCOB']==2 and r['tempo_evidence'][0]['bpms']==[128,130] for r in anlz)
        grids=[r['extended_grid_evidence'][0] for r in evidence if r.get('extended_grid_evidence')]
        assert len(grids)==2 and all(g['validation']=='recognized' and g['checksum_validation']=='not_checked' for g in grids)
        embeddings=[r for r in evidence if r['format']=='anlz_3ex']
        assert len(embeddings)==2 and all(r['validation']=='unsupported' and r['asset_family']=='analysis'
                                        and r['provider']=='rekordbox' and r['embedding_signature'] for r in embeddings)
        page.screenshot(path=str(output/'formats-stems.png'),full_page=True)
        filtered=filter_report('validation','corrupt')
        assert len(filtered['rows'])==4 and all(r['validation']=='corrupt' for r in filtered['rows'])
        expect(page.locator('#lab-report-rows tbody tr')).to_have_count(4)
        empty=filter_report('severity','info');assert empty['rows']==[]
        expect(page.locator('#lab-report-count')).to_contain_text('0 findings')
        filter_report('severity','');filter_report('validation','recognized')
        stems=filter_report('section','stems_cache')
        assert len(stems['rows'])==2 and all(r['format']=='recordbox_stems_v1' for r in stems['rows'])
        # Saved reports survive navigation/reload; opening one causes no fresh disk scan.
        page.reload(wait_until='networkidle');page.locator('.nav[data-view="lab"]').click()
        page.select_option('#lab-report-select',format_id)
        expect(page.locator('#lab-report-download')).to_have_attribute('href',re.compile('/'+format_id+'/download'))
        page.locator('[data-lab-tab="source-insights"]').click()
        _,native=report('source-insights')
        assert native['summary']['resolved_artist_roles']==3
        assert native['summary']['unresolved_artist_roles']==1
        assert native['summary']['smart_rules_recognized']==1
        assert native['summary']['smart_rules_unsupported']==1
        assert native['summary']['cue_anomalies']==1
        assert page.locator('#lab-report-validation').input_value()==''
        rules=filter_report('section','smart_playlist');assert len(rules['rows'])==2
        unsupported=filter_report('validation','unsupported')
        assert len(unsupported['rows'])==1 and unsupported['rows'][0]['conditions'][0]['raw']['ValueLeft']=='keep me'
        expect(page.locator('#lab-report-rows')).to_contain_text('Unknown rule')
        page.screenshot(path=str(output/'native-source-insights.png'),full_page=True)
        page.locator('[data-lab-tab="checks"]').click()
        page.fill('#lab-backup-path',str(archive));page.locator('#lab-backup-verify').check()
        _,backup=report('backup')
        settings=next(r for r in backup['rows'] if r['section']=='backup_component' and r['title']=='settings')
        assert settings['files']==2
        invalid=next(r for r in backup['rows'] if r['section']=='backup_member' and r['title'].endswith('DEVSETTING.DAT'))
        assert invalid['verification']=='verified' and invalid['format_evidence']['validation']=='corrupt'
        page.locator('[data-lab-tab="editor"]').click()
        page.locator('[data-lab-edit="0"]').click()
        expect(page.locator('#track-native-evidence')).to_be_visible()
        page.locator('#track-native-evidence summary').click()
        expect(page.locator('#track-native-evidence pre')).to_contain_text('Synthetic writer 日本')
        page.locator('#track-detail-dialog .close-dialog').click()
        page.set_viewport_size({'width':390,'height':844})
        page.locator('[data-lab-tab="formats"]').click()
        page.locator('#lab-formats').scroll_into_view_if_needed()
        expect(page.locator('#lab-formats')).to_be_in_viewport()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        assert store.snapshot(sid)==captured
        for path,digest in original.items():assert sha256(path.read_bytes()).hexdigest()==digest
        assert not errors,errors
        return {'status':'passed','format_candidates':20,'corrupt_format_findings':4,'native_roles_resolved':3,
                'unsupported_3ex_variants':2,'extended_grids_checked':2,
                'smart_rules_recognized':1,'smart_rules_unsupported':1,'filters':'section, severity, validation',
                'zip_folder_parity':True,'sources_preserved':True,'native_readiness':'unknown',
                'real_http':True,'inference_run':False}
    except Exception:
        page.screenshot(path=str(output/'format-insights-failure.png'),full_page=True)
        raise
    finally:
        context.tracing.stop(path=str(output/'format-insights-trace.zip'));context.close()
