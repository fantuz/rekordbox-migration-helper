"""Real-server acceptance and bounded-table performance on synthetic snapshots."""
from hashlib import sha256
from time import perf_counter
import math
import zipfile


def check_migration_readiness_ui(browser,base,store,root,output):
    from playwright.sync_api import expect
    count=5000
    tracks=[{'id':str(i),'title':f'Perf {i:05d}','artist':'Synthetic artist','format':'WAV',
             'size':1000,'bpm':128,'xml_bpm':128,'tonality':'Am','comment':'Original',
             'current_path':f'/Synthetic/{i}.wav'} for i in range(count)]
    tracks[0].update(format='OGG',size=2**32,bpm=87,xml_bpm=174,current_path='C:/Music/CON.ogg')
    source={'scope_key':'synthetic:readiness-browser','source_kind':'Synthetic readiness','tracks':tracks,
            'asset_references':['PIONEER/USBANLZ/P001/ABC/ANLZ0000.DAT']}
    sid=store.save_snapshot(source,'Readiness browser')['id'];original=store.snapshot(sid)
    backup=root/'readiness-backup.zip'
    with zipfile.ZipFile(backup,'w') as archive:
        archive.writestr('master.db',b'synthetic database')
        archive.writestr('PIONEER/USBANLZ/P001/ABC/ANLZ0000.DAT',b'synthetic analysis')
        archive.writestr('artwork/test.jpg',b'synthetic artwork')
    original_zip=sha256(backup.read_bytes()).hexdigest()
    context=browser.new_context(locale='en-US',viewport={'width':1440,'height':1000})
    context.add_init_script("if(location.protocol==='http:')localStorage.setItem('library-workbench.language.v1','en')")
    context.tracing.start(screenshots=True,snapshots=True,sources=True)
    page=context.new_page();errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def run_report(kind):
        previous=page.locator('#lab-report-select').input_value()
        page.locator('#lab-'+kind).click()
        page.wait_for_function('(previous)=>document.querySelector("#lab-report-select").value && document.querySelector("#lab-report-select").value!==previous',arg=previous)
        expect(page.locator('#lab-report-download')).to_be_visible()
        identity=page.locator('#lab-report-select').input_value()
        # Wait for the report body/download to match the newly selected identity.
        expect(page.locator('#lab-report-download')).to_have_attribute('href',__import__('re').compile('/'+identity+'/download'))
        response=context.request.get(base+page.locator('#lab-report-download').get_attribute('href'))
        assert response.ok,response.status
        return response.json()
    try:
        page.goto(base,wait_until='networkidle')
        page.locator('.nav[data-view="lab"]').click()
        started=perf_counter()
        page.select_option('#lab-snapshot',sid)
        page.locator('[data-lab-tab="editor"]').click()
        page.wait_for_selector('[data-lab-edit="0"]')
        first_ms=1000*(perf_counter()-started)
        assert page.locator('#lab-tracks tbody tr').count()<=30
        timings=[]
        for query in ('Perf 001','Perf 002','Perf 003','Perf 004','Perf 005'):
            started=perf_counter();page.fill('#lab-track-search',query)
            with page.expect_response(lambda r:'/api/lab/tracks?' in r.url and 'q='+query.replace(' ','+') in r.url):
                page.locator('#lab-track-find').click()
            page.wait_for_function('(query)=>[...document.querySelectorAll("#lab-tracks tbody tr")].length>0 && [...document.querySelectorAll("#lab-tracks tbody tr")].every(e=>e.textContent.includes(query))',arg=query)
            timings.append(1000*(perf_counter()-started))
            assert page.locator('#lab-tracks tbody tr').count()<=30
        p95=sorted(timings)[math.ceil(.95*len(timings))-1]
        # Deliberately generous runner-portable ceilings; retain actual measurements.
        assert first_ms<10000,first_ms
        assert p95<5000,p95
        page.fill('#lab-track-search','Perf 00000');page.locator('#lab-track-find').click()
        expect(page.locator('#lab-tracks tbody tr')).to_have_count(1)
        page.locator('[data-lab-edit="0"]').click()
        page.locator('#track-advanced-panel summary').click()
        page.locator('#track-detail-unlock').check()
        expect(page.locator('[data-track-edit-field="title"]')).to_be_enabled()
        before=store.edit_state(source['scope_key'],history=True)
        page.fill('[data-track-edit-field="title"]','Invalid\ufffe title')
        with page.expect_response(lambda r:r.url.endswith('/api/lab/overrides') and r.request.method=='POST') as invalid:
            page.locator('#track-detail-save').click()
        assert invalid.value.status==400
        expect(page.locator('#toast')).to_contain_text('XML-compatible')
        assert store.edit_state(source['scope_key'],history=True)==before
        expect(page.locator('[data-track-edit-field="title"]')).to_have_value('Invalid\ufffe title')
        page.locator('#track-detail-unlock').uncheck()
        page.locator('#track-detail-dialog .close-dialog').click()
        page.locator('[data-lab-tab="checks"]').click()
        page.fill('#lab-backup-path',str(backup));page.locator('#lab-backup-verify').check()
        manifest=run_report('backup')
        assert manifest['summary']['verified_members']==3
        assert manifest['summary']['checksum_status']=='verified'
        assert manifest['summary']['missing_analysis_references']==0
        assert any(r.get('sha256')==sha256(b'synthetic database').hexdigest() for r in manifest['rows'])
        page.select_option('#lab-readiness-profile','cdj-2000nxs2');page.select_option('#lab-readiness-filesystem','fat32')
        ready=run_report('readiness')
        assert ready['summary']['tracks']==count
        assert ready['summary']['tracks_with_findings']==1
        issue=next(r for r in ready['rows'] if r.get('track_id')=='0')
        assert 'FAT32' in issue['detail'] and 'OGG' in issue['detail'] and 'Windows-reserved' in issue['detail']
        tempo=run_report('tempo')
        assert tempo['summary']['tempo_disagreements']==1
        assert any(r.get('half_double') for r in tempo['rows'])
        for width in (390,768,1440):
            page.set_viewport_size({'width':width,'height':1000})
            page.locator('#migration-readiness').scroll_into_view_if_needed()
            assert page.locator('#migration-readiness').evaluate('''card=>{
                const bounds=card.getBoundingClientRect();
                return [...card.querySelectorAll('input,select,button')].every(el=>{
                    const box=el.getBoundingClientRect();return box.left>=bounds.left && box.right<=bounds.right;
                });
            }''')
            page.screenshot(path=str(output/f'migration-readiness-{width}.png'))
        assert store.snapshot(sid)==original
        assert store.edit_state(source['scope_key'])['overrides']=={}
        assert sha256(backup.read_bytes()).hexdigest()==original_zip
        assert not errors,errors
        return {'status':'passed','tracks':count,'first_table_ms':round(first_ms,2),'search_p95_ms':round(p95,2),
                'search_samples_ms':[round(v,2) for v in timings],
                'budgets_ms':{'first_table':10000,'search_p95':5000},'max_dom_rows':30,
                'backup_checksums':True,'fat32_and_player_profile':True,'tempo_key_advisories':True,
                'invalid_xml_edit_rejected_without_mutation':True,'source_unchanged':True}
    except Exception:
        page.screenshot(path=str(output/'readiness-failure.png'))
        raise
    finally:
        context.tracing.stop(path=str(output/'readiness-trace.zip'));context.close()
