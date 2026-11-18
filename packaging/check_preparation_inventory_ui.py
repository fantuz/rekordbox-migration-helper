"""Real HTTP preparation, native/paired inputs and scoped inventory; no API stubs."""
from ui_navigation import select_collection, open_collection_picker
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import shutil
import wave

from localization import LANGUAGES, catalogues
from test_export_verification import IndependentExportTests


def check_preparation_inventory_ui(browser, base, store, root, output):
    from playwright.sync_api import expect
    fixture = IndependentExportTests()
    fixture.setUp()
    from contextlib import closing
    from native_export import mutable_copy
    import zipfile
    with closing(mutable_copy(fixture.master)) as database:
        for field,kind in (('AnalysisDataPath','TEXT'),('ImagePath','TEXT'),('DeviceID','TEXT'),
                           ('created_at','TEXT'),('Analysed','INTEGER'),('BitDepth','INTEGER'),
                           ('ComposerID','TEXT'),('LabelID','TEXT')):
            database.execute('ALTER TABLE djmdContent ADD COLUMN '+field+' '+kind)
        database.executescript('''CREATE TABLE djmdLabel(ID TEXT,Name TEXT);
            ALTER TABLE djmdPlaylist ADD COLUMN Attribute INTEGER;
            CREATE TABLE contentFile(Path TEXT,rb_local_deleted INTEGER);
            CREATE TABLE djmdHistory(ID TEXT,DateCreated TEXT,rb_local_deleted INTEGER);
            CREATE TABLE djmdSongHistory(ContentID TEXT,HistoryID TEXT,rb_local_deleted INTEGER);''')
        database.commit()
    with zipfile.ZipFile(fixture.backup,'w') as archive:
        archive.write(fixture.master,'master.db')
        archive.writestr('contents.xml','<ROOT><VALUE name="CONTENT_NUM" val="2"/></ROOT>')
    # The export fixture deliberately omits XML lengths; real import correctly
    # rejects that mismatch. Supply matching evidence for this input workflow.
    from lxml import etree
    xml=etree.parse(str(fixture.xml))
    for record in xml.findall('.//COLLECTION/TRACK'):
        record.set('Size','100');record.set('TotalTime','180')
    xml.write(str(fixture.xml),encoding='utf-8')
    source = root / 'preparation source'
    source.mkdir()
    shutil.copyfile(fixture.master, source / 'master.db')
    music = root / 'preparation music'
    music.mkdir()
    with wave.open(str(music / 'a.wav'), 'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(8000)
        stream.writeframes(b'\0\0' * 28)  # Exactly 100 bytes, like the fixture's saved size.
    watched = [source / 'master.db', fixture.backup, fixture.xml, music / 'a.wav']
    before = {str(p): sha256(p.read_bytes()).hexdigest() for p in watched}
    context = browser.new_context(locale='en-US', viewport={'width':1550, 'height':1080})
    context.add_init_script("localStorage.setItem('library-workbench.language.v1','en')")
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page();errors=[];scans=[];searches=[]
    page.on('pageerror', lambda error: errors.append(str(error)))
    def request_sent(request):
        if request.method == 'POST' and request.url.endswith('/api/file-health/scan'):
            scans.append(request.post_data_json)
        if request.method == 'POST' and request.url.endswith('/api/inventory/scan'):
            searches.append(request.post_data_json)
    page.on('request', request_sent)
    messages = catalogues(Path(__file__).resolve().parents[1] / 'static')
    def prompt():
        page.wait_for_selector('#preparation-dialog[open]')
        assert not page.locator('#preparation-scan').is_checked()
    def import_pair():
        page.locator('.nav[data-view="files"]').click()
        page.locator('#view-files [data-open-import]').click()
        page.locator('[data-import-mode="local"]').click()
        page.fill('#local-zip', str(fixture.backup));page.fill('#local-xml', str(fixture.xml))
        page.locator('#local-import-form button[type="submit"]').click()
        prompt()
        identity = page.evaluate('session.id')
        page.locator('#preparation-later').click()
        return identity
    try:
        page.goto(base, wait_until='networkidle')
        assert page.locator('#view-start').is_visible()
        assert page.locator('.workflow-column').count() == 5
        assert page.locator('.workflow-map button').count() >= 14
        assert page.locator('.workflow-map button').evaluate_all('els=>els.every(e=>e.type==="button")')
        page.screenshot(path=str(output / 'workflow-map.png'), full_page=True)
        # Every advertised route has a real destination. Special actions are
        # checked below without creating state just by traversing the map.
        for view in ('analyzer', 'review', 'reference', 'musicbrainz', 'bubbles', 'file-health', 'inventory', 'exports', 'quick', 'intelligence'):
            page.locator('.nav[data-view="start"]').click()
            page.locator('#view-start [data-view="'+view+'"]').first.click()
            assert page.locator('#view-' + view).is_visible()
        page.locator('.nav[data-view="start"]').click()
        for code in LANGUAGES:
            page.select_option('#language', code)
            page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
            expect(page.locator('#view-start .eyebrow')).to_have_text(messages[code]['Workflow map'])
        page.select_option('#language', 'en')
        page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
        page.set_viewport_size({'width':390, 'height':900})
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.screenshot(path=str(output / 'workflow-map-narrow.png'), full_page=True)
        page.set_viewport_size({'width':1550, 'height':1080})

        # Capture a real generated native database through the actual form.
        page.locator('.nav[data-view="analyzer"]').click()
        page.fill('#analyzer-path', str(source))
        page.locator('#analyzer-form button[type="submit"]').click()
        prompt()
        capture = page.evaluate('Journeys.context().source')
        assert capture.startswith('capture:')
        assert scans == []
        assert 'no extra Rekordbox export' in page.locator('#preparation-dialog').inner_text()
        page.locator('#preparation-form button[type="submit"]').click()
        page.wait_for_selector('#library-bubbles[data-state="ready"] circle')
        saved = page.evaluate('Journeys.context().snapshot')
        immutable = deepcopy(store.snapshot(saved))
        assert immutable['scope_key'] == capture
        assert scans == []
        with store.connection() as db:
            original_count = db.execute('SELECT count(*) FROM snapshots WHERE scope_key=?', (capture,)).fetchone()[0]
        # Explicitly prepare again: reuse the metadata, then opt into audio inspection.
        page.locator('.nav[data-view="start"]').click()
        page.locator('#preparation-open').click();prompt()
        page.locator('#preparation-scan').check()
        page.screenshot(path=str(output / 'library-preparation.png'))
        page.locator('#preparation-form button[type="submit"]').click()
        page.wait_for_selector('#view-file-health:not([hidden])')
        expect(page.locator('#file-health-source')).to_have_value('snapshot:' + saved)
        page.wait_for_function('document.querySelector("#file-health-state").textContent.includes("complete")')
        assert scans == [{'source':'snapshot:' + saved, 'force':True}]
        with store.connection() as db:
            assert db.execute('SELECT count(*) FROM snapshots WHERE scope_key=?', (capture,)).fetchone()[0] == original_count
        assert store.snapshot(saved) == immutable

        workspace = import_pair()
        page.locator('.nav[data-view="inventory"]').click()
        page.wait_for_function('document.querySelectorAll("#media-roots .media-root").length===1')
        name = page.evaluate('session.name')
        expect(page.locator('#inventory-library')).to_have_text(name)
        assert page.locator('#scan-media').is_disabled()
        page.locator('.media-folder').fill(str(music))
        page.locator('#add-media-root').click()
        page.locator('.media-folder').nth(1).fill(str(root / 'wrong folder'))
        page.locator('.media-remove').nth(1).click()
        assert page.locator('.media-root').count() == 1
        assert page.locator('.media-folder').input_value() == str(music)
        page.locator('.media-root summary').click()
        page.locator('.media-prefix').fill('D:/Music')
        page.locator('.media-export').fill('file:///E:/Relocated')
        page.locator('#scan-media').click()
        page.wait_for_selector('[data-inventory-ref="a"]')
        assert len(searches) == 1 and searches[0]['workspace'] == workspace
        assert [r['root'] for r in searches[0]['roots']] == [str(music)]
        expect(page.locator('[data-inventory-ref="a"]')).to_be_enabled()
        page.locator('[data-inventory-ref="a"]').click()
        expect(page.locator('[data-inventory-ref="a"]')).to_have_text('Undo')
        response = context.request.get(base + page.locator('#inventory-report').get_attribute('href'))
        assert response.ok
        page.screenshot(path=str(output / 'media-inventory.png'), full_page=True)
        # Removing a path edits only the next scan. Prior evidence stays labelled.
        page.locator('.media-remove').click()
        expect(page.locator('#inventory-settings-note')).to_contain_text('last scan')
        assert page.locator('#scan-media').is_disabled()
        assert page.locator('[data-inventory-ref="a"]').is_visible()
        page.locator('#add-media-root').click();page.locator('.media-folder').fill(str(music))
        page.reload(wait_until='networkidle')
        expect(page.locator('.media-folder')).to_have_value(str(music))
        # The shared snapshot does not silently change the inventory's library.
        select_collection(page,'#journey-context-source', 'snapshot:' + saved)
        page.wait_for_function('(s)=>Journeys.context()?.snapshot===s', arg=saved)
        expect(page.locator('#inventory-library')).to_have_text(name)
        expect(page.locator('#inventory-context-note')).not_to_be_empty()
        page.set_viewport_size({'width':390, 'height':900})
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.screenshot(path=str(output / 'media-inventory-narrow.png'), full_page=True)
        page.set_viewport_size({'width':1550, 'height':1080})
        second = import_pair()
        assert second != workspace
        page.locator('.nav[data-view="inventory"]').click()
        expect(page.locator('#inventory-scan-state')).to_have_text('Not checked')
        expect(page.locator('.media-folder')).to_have_value('')
        assert page.locator('[data-inventory-ref]').count() == 0
        assert before == {str(p):sha256(p.read_bytes()).hexdigest() for p in watched}
        assert not errors, errors
        return {'real_http':True, 'mocked_api_responses':False, 'clickable_landing_map':True,
                'native_preparation_and_reuse':True, 'explicit_file_scan':True,
                'actual_xml_zip_import':True, 'root_removal_and_reload':True,
                'inventory_scope_and_staging':True, 'workspace_isolation':True,
                'source_preserved':True, 'languages':len(LANGUAGES), 'narrow_layout':True}
    except Exception:
        page.screenshot(path=str(output / 'preparation-inventory-failure.png'), full_page=True)
        raise
    finally:
        context.tracing.stop(path=str(output / 'preparation-inventory-trace.zip'))
        context.close()
        fixture.doCleanups()
