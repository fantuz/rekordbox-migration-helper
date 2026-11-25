"""Exercise the cleanup report on a disposable server with invented Rekordbox XML exports."""
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import sys
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from uuid import uuid4
import xml.etree.ElementTree as ET

from ui_navigation import select_collection
from xml_analysis import analyze_xml


def check_collection_cleanup_ui(browser, base, store, output):
    from playwright.sync_api import expect

    specimens = [
        ('local', 'Night Signal', r'C:\Users\FixtureDJ\Music\Night Signal.wav'),
        ('cloud', 'Cloud Echo', r'C:\Users\FixtureDJ\Dropbox\Sessions\Cloud Echo.wav'),
        ('external', 'Road Set', '/Volumes/Synthetic Tour SSD/DJ/Road Set.wav'),
        ('other', 'Mac Edit', '/Users/FixtureDJ/Music/Mac Edit.wav'),
        ('share', '<img data-cleanup-fixture> Café 🎧', r'\\fixture-server\archive\Mix.wav'),
    ]

    def snapshot(label, rows):
        library = ET.Element('DJ_PLAYLISTS', Version='1.0.0')
        collection = ET.SubElement(library, 'COLLECTION', Entries=str(len(rows)))
        for identity, title, path in rows:
            location = PurePosixPath(path) if path.startswith('/') else PureWindowsPath(path)
            ET.SubElement(collection, 'TRACK', TrackID=identity, Name=title, Size='512',
                          Rating='0', PlayCount='0', Location=location.as_uri())
        with TemporaryDirectory(prefix='cleanup-fixture-') as scratch:
            source_file = Path(scratch) / 'rekordbox.xml'
            capture = Path(scratch) / uuid4().hex
            ET.ElementTree(library).write(source_file, encoding='utf-8', xml_declaration=True)
            analyze_xml(source_file, capture, lambda *_: None)
            source_data = json.loads((capture / 'metadata.json').read_text(encoding='utf-8'))
        return store.save_snapshot(source_data, label)['id']

    primary = snapshot('Cleanup mixed drives', specimens)
    second = snapshot('Cleanup other collection', [('local', 'Another collection', '/Volumes/Other/Track.wav')])
    source, other_source = 'snapshot:'+primary, 'snapshot:'+second
    originals = {sid:store.snapshot(sid) for sid in (primary,second)}
    context = browser.new_context(locale='en-US', viewport={'width':1440, 'height':950})
    context.add_init_script("localStorage.setItem('library-workbench.language.v1','en')")
    page = context.new_page()
    errors, external, scans = [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))

    def request_seen(request):
        uri = urlsplit(request.url)
        if uri.scheme in ('http','https') and uri.netloc != urlsplit(base).netloc:
            external.append(uri.netloc)
        if uri.path == '/api/collection-cleanup/scan' and request.method == 'POST':
            scans.append(request.post_data_json)

    page.on('request', request_seen)
    try:
        page.goto(base, wait_until='networkidle')
        page.locator('.nav[data-view="collection-cleanup"]').click()
        picker = page.locator('#cc-source')
        expect(picker.locator('option[value="'+source+'"]')).to_have_count(1)
        select_collection(page, '#cc-source', source)
        expect(page.locator('#cc-scan')).to_be_enabled()
        assert not scans, 'Opening or choosing a collection must not start a scan'
        page.locator('#cc-scan').click()
        rows = page.locator('#cc-rows tbody tr')
        expect(rows).to_have_count(len(specimens))
        expect(page.locator('#cc-rows')).to_contain_text(specimens[-1][1])
        expect(page.locator('img[data-cleanup-fixture]')).to_have_count(0)
        assert len(scans) == 1 and scans[0]['source'] == source and not scans[0]['compare_bytes']
        drives = page.locator('#cc-drives')
        for text in ('Windows','C:','macOS','/Volumes/Synthetic Tour SSD','//fixture-server/archive'):
            expect(drives).to_contain_text(text)

        report = next(r for r in store.reports() if r['kind']=='collection cleanup' and r['sources']==[primary])
        facts = report['summary']
        assert facts['counts']['total']==5 and facts['counts']['eligible']==0
        assert facts['statuses']['cloud'] == 1 and facts['statuses']['external'] == 2
        assert sum(v['total'] for v in facts['volumes'] if v['os']=='Windows')==3
        assert sum(v['total'] for v in facts['volumes'] if v['os']=='macOS')==2
        # The guide illustrates the real source and drive summary without including any track paths.
        page.locator('#page-title').scroll_into_view_if_needed()
        title = page.locator('header.topbar').bounding_box()
        drive_table = drives.bounding_box()
        assert title and drive_table
        page.screenshot(path=str(output/'collection-cleanup-overview.png'),clip={
            'x':title['x'], 'y':title['y'], 'width':title['width'],
            'height':drive_table['y']+drive_table['height']-title['y']+4})
        # Filtering existing evidence must never launch another filesystem operation.
        page.locator('#cc-search').fill('Cloud Echo')
        page.locator('#cc-filters button').click()
        expect(rows).to_have_count(1)
        expect(rows).to_contain_text('Cloud Echo')
        page.locator('#cc-search').fill('')
        page.select_option('#cc-status','external')
        page.locator('#cc-filters button').click()
        expect(rows).to_have_count(2)
        expect(page.locator('#cc-rows')).to_contain_text('Road Set')
        page.screenshot(path=str(output/'collection-cleanup-drives.png'))
        assert len(scans) == 1

        if sys.platform.startswith('linux'):
            expect(page.locator('#cc-host-note')).to_be_visible()
            expect(page.locator('#cc-selection')).to_be_hidden()
            expect(page.locator('#cc-compare')).to_be_hidden()
            expect(page.locator('#cc-confirm-dialog')).to_be_hidden()
            # Use a real local action token to test the server boundary independently of disabled controls.
            status = context.request.get(base+'/api/status').json()
            response = context.request.post(base+'/api/collection-cleanup/apply',
                headers={'X-Workbench-Token':status['token']},
                data={'source':source,'report_id':report['id'],'selected_ids':['cloud'],
                      'original_computer':True,'local_only':True,'confirmation':'COPY 1','token':'forged'})
            assert response.status == 403 and 'host' in response.json()['error'].lower()
        select_collection(page, '#cc-source', other_source)
        expect(page.locator('#cc-results')).to_be_hidden()
        expect(page.locator('#cc-confirm-dialog')).to_be_hidden()
        expect(rows).to_have_count(0)
        page.locator('#cc-scan').click()
        expect(rows).to_have_count(1)
        expect(rows).to_contain_text('Another collection')
        assert [scan['source'] for scan in scans]==[source, other_source]
        if sys.platform.startswith('linux'):
            _check_confirmation_controls(page, base, source, report['id'], output)
        assert all(store.snapshot(sid)==before for sid,before in originals.items())
        assert not errors and not external, (errors,external)
        return {'sources':2,'mixed_references':5,'windows_references':3,'macos_references':2,
                'cloud_references':1,'external_references':2,'originals_preserved':True,
                'linux_apply_refused':sys.platform.startswith('linux'),
                'supported_host_preview_simulated':sys.platform.startswith('linux')}
    finally:
        context.close()


def _check_confirmation_controls(page, base, source, report_id, output):
    """Simulate a Windows preview in the browser; leave Apply connected to real Linux."""
    from playwright.sync_api import expect

    api = base+'/api/collection-cleanup'
    job = 'c'*32
    keeper = r'C:\Users\FixtureDJ\Music\Keep\Mix.wav'
    redundant = r'C:\Users\FixtureDJ\Music\Copy\Mix.wav'
    choice = {'id':'copy','title':'Mix','path':redundant,'candidate':'duplicate',
              'keeper_id':'keep','keeper_path':keeper,'proof':'sha256'}

    def present_windows(route):
        response = route.fetch()
        data = response.json()
        if data['source'] == source:
            if 'rows' in data:
                data['summary'].update(host='Windows', can_apply=True, gates=[])
                data['summary']['counts'].update(total=2, eligible=1, protected=0, duplicate=1, missing=0)
                data.update(total=2,rows=[{**choice,'status':'present','volume':'C:','protected':False},
                                          {'id':'keep','title':'Mix','path':keeper,'status':'present','volume':'C:'}])
            else:
                data.update(host='Windows', can_apply=True)
        route.fulfill(response=response,json=data)

    page.route(api+'?*',present_windows)
    page.route(api+'/'+report_id+'?*',present_windows)
    page.route(api+'/preview',lambda r:r.fulfill(json={'job':job}))
    preview = {'token':'d'*32,'selected':[choice],'selected_count':1,'before_count':2,
               'after_count':1,'confirmation':'COPY 1'}
    page.route(base+'/api/tasks/'+job,lambda r:r.fulfill(json={'status':'complete','result':preview}))
    select_collection(page,'#cc-source',source)
    check = page.locator('#cc-rows input[value="copy"]')
    expect(check).to_be_visible()
    expect(check).not_to_be_checked()
    expect(page.locator('#cc-review')).to_be_disabled()
    check.check()
    page.locator('#cc-review').click()
    dialog = page.locator('#cc-confirm-dialog')
    expect(dialog).to_be_visible()
    for path in (redundant,keeper):
        expect(page.locator('#cc-preview-rows')).to_contain_text(path)
    apply = page.locator('#cc-apply')
    page.locator('#cc-phrase').fill('COPY 1')
    expect(apply).to_be_disabled()
    page.locator('#cc-original').check()
    expect(apply).to_be_disabled()
    page.locator('#cc-local').check()
    page.locator('#cc-phrase').fill('COPY 2')
    expect(apply).to_be_disabled()
    page.locator('#cc-phrase').fill('COPY 1')
    expect(apply).to_be_enabled()
    page.set_viewport_size({'width':550,'height':670})
    box = dialog.bounding_box()
    assert box and box['x']>=0 and box['x']+box['width']<=551,box
    page.screenshot(path=str(output/'collection-cleanup-confirmation-simulated.png'))
    # Cancel must discard both declarations and the phrase, even with the same selection.
    page.locator('#cc-cancel').click()
    page.locator('#cc-review').click()
    expect(dialog).to_be_visible()
    expect(page.locator('#cc-phrase')).to_have_value('')
    expect(page.locator('#cc-original')).not_to_be_checked()
    expect(page.locator('#cc-local')).not_to_be_checked()
    expect(apply).to_be_disabled()
    page.locator('#cc-original').check()
    page.locator('#cc-local').check()
    page.locator('#cc-phrase').fill('COPY 1')
    with page.expect_response(lambda r:r.url == api+'/apply') as submitted:
        apply.click()
    assert submitted.value.status == 403
    sent = submitted.value.request.post_data_json
    assert sent == {'source':source,'report_id':report_id,'selected_ids':['copy'],'token':preview['token'],
                    'confirmation':'COPY 1','original_computer':True,'local_only':True}
    expect(page.locator('#cc-output')).to_be_hidden()
