"""Browser regressions using a tiny, invented native SQLite collection only."""
from ui_navigation import select_collection, open_collection_picker
from pathlib import Path
import json

from analyzer import analyze_folder
from test_discovery_history import native_fixture


def check_native_collection_ui(browser, base, data, output, root):
    folder = root / 'native-fixture'
    folder.mkdir()
    original = folder / 'master.db'
    with native_fixture(original) as db:
        db.execute("INSERT INTO djmdContent VALUES('copy','Track A','/Music/a.mp3','artist',243,'2023-03-01',0)")
        db.executescript("""CREATE TABLE djmdPlaylist(ID TEXT,Name TEXT,Attribute INTEGER);
            CREATE TABLE djmdSongPlaylist(ID TEXT,PlaylistID TEXT,ContentID TEXT,TrackNo INTEGER);
            INSERT INTO djmdPlaylist VALUES('p','Synthetic set',0),('q','Related set',0);
            INSERT INTO djmdSongPlaylist VALUES('1','p','a',1),('2','p','b',2),('3','p','a',3),('4','q','b',1),('5','q','a',2);""")
    db.close()
    before = original.read_bytes()
    identity = 'e' * 32
    analyze_folder(original, data / 'analyzers' / identity, lambda *_: None)
    context = browser.new_context(locale='en-US', viewport={'width':1715, 'height':1000})
    context.add_init_script("localStorage.setItem('library-workbench.language.v1','en')")
    page = context.new_page()
    errors = []
    failures = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('response', lambda r: failures.append(r.status) if '/api/' in r.url and r.status >= 400 else None)
    try:
        page.goto(base, wait_until='networkidle')
        open_collection_picker(page,'#journey-context-source')
        select_collection(page,'#journey-context-source', 'capture:' + identity)
        page.wait_for_function('(id)=>window.Journeys.context()?.source==="capture:"+id', arg=identity)
        assert page.locator('#session-cleanup-note').inner_text() == 'Analysis copies are temporary. Originals stay unchanged.'
        assert page.locator('#session-cleanup-note summary').count() == 0
        action = page.locator('[data-journey-context-capture]')
        assert action.evaluate('(e)=>getComputedStyle(e).borderStyle') == 'solid'
        for width in (1715, 768, 390):
            page.set_viewport_size({'width':width, 'height':1000})
            open_collection_picker(page,'#journey-context-source')
            label = page.locator('.journey-context-row>label>span').bounding_box()
            select = page.locator('#journey-context-source').bounding_box()
            assert select['x'] >= label['x'] + label['width'] + 8 or select['y'] >= label['y'] + label['height'] + 8
        page.locator('#journey-context-source').press('Escape')
        page.set_viewport_size({'width':1715, 'height':1000})
        page.locator('.nav[data-view=intelligence]').click()
        page.wait_for_function('(id)=>document.querySelector("#intelligence-source").value==="capture:"+id',arg=identity)
        page.wait_for_selector('#intelligence-playlist option[value="p"]',state='attached')
        assert page.locator('#intelligence-duplicates').is_disabled()
        page.select_option('#intelligence-playlist','p');page.locator('#intelligence-contents').click()
        page.wait_for_function('document.querySelectorAll("#intelligence-results tbody tr").length===3')
        page.locator('#intelligence-playlists').click()
        page.wait_for_function('document.querySelector("#intelligence-results").textContent.includes("Related set")')
        page.select_option('#intelligence-history','h');page.locator('#intelligence-session').click()
        page.wait_for_function('document.querySelectorAll("#intelligence-results tbody tr").length===5')
        page.locator('#intelligence-save').click();page.wait_for_selector('#intelligence-download',state='visible')
        assert page.context.request.get(base+page.locator('#intelligence-download').get_attribute('href')).ok
        # Remove this temporary test report so the later archive test has no dependency blocker.
        saved=page.locator('#intelligence-download').get_attribute('href').split('/')[4]
        from workbench_store import Store
        with Store(data/'workbench-sidecar.sqlite3').connection() as db:
            db.execute('DELETE FROM report_rows WHERE report_id=?',(saved,));db.execute('DELETE FROM reports WHERE id=?',(saved,))
        page.select_option('#intelligence-lens','all');page.locator('#intelligence-lenses').click()
        page.wait_for_function('document.querySelectorAll("#intelligence-results tbody tr").length===3')
        page.screenshot(path=str(output/'native-library-intelligence.png'))
        page.locator('.nav[data-view=statistics]').click()
        page.wait_for_selector('#stats-cards .stat-card')
        page.wait_for_function("document.querySelector('#stats-cards .stat-card strong').textContent==='3'")
        assert page.locator('#stats-cohort').is_disabled()
        page.locator('.nav[data-view=review]').click()
        page.wait_for_selector('[data-native-group]')
        page.locator('[data-native-group]').first.click()
        page.wait_for_selector('.native-detail .native-compare-record')
        assert page.locator('.native-detail .native-compare-record').count() == 2
        page.wait_for_selector('.native-file-summary .file-status-unverified')
        assert page.locator('.native-detail .native-file-status .file-status-unverified').count() == 2
        page.select_option('.native-file-filter','playable')
        assert page.locator('.native-detail .native-compare-record:visible').count() == 0
        page.select_option('.native-file-filter','all')
        assert page.locator('.native-detail .native-compare-record:visible').count() == 2
        page.locator('.native-file-refresh').click()
        page.wait_for_function('!document.querySelector(".native-file-refresh").disabled')
        assert page.locator('.native-file-summary .file-status-unverified').count() == 1
        # Focus refreshes must explicitly bypass the persistent SQLite
        # evidence cache, not just the short-lived browser cache.
        # Wait beyond the 5-second focus throttle for deterministic CI.
        page.wait_for_timeout(5200)
        with page.expect_request(
            lambda request: request.url.endswith('/api/playback/availability')
            and request.method == 'POST'
            and isinstance(request.post_data_json, dict)
            and request.post_data_json.get('refresh') is True,
            timeout=10000
        ):
            page.evaluate("window.dispatchEvent(new Event('focus'))")
        page.select_option('.native-status', 'keep_separate')
        page.locator('.native-save').click()
        page.wait_for_function("document.querySelector('.native-status')?.value==='keep_separate'")
        page.locator('.nav[data-view=reference]').click()
        page.wait_for_selector('#view-reference .native-table tbody tr')
        assert page.locator('#view-reference .native-table tbody tr').count() == 3
        assert page.locator('#reference-form').is_hidden()
        page.locator('.nav[data-view=history]').click()
        page.wait_for_selector('[data-history-id="h"]')
        page.locator('[data-history-id="h"]').click()
        page.wait_for_selector('#history-tracks tbody tr')
        assert page.locator('#history-tracks tbody tr').count() == 5
        page.screenshot(path=str(output / 'native-collection-context.png'))
        # Explicit snapshot action captures the chosen source and updates the shared context.
        open_collection_picker(page,'[data-journey-context-capture]')
        action.click()
        page.wait_for_selector('#preparation-dialog[open]')
        assert not page.locator('#preparation-scan').is_checked()
        page.locator('#preparation-form button[type="submit"]').click()
        page.wait_for_function('Boolean(window.Journeys.context()?.snapshot)')
        assert page.locator('[data-journey-context-capture]').count() == 0
        page.locator('.nav[data-view=investigations]').click()
        page.wait_for_selector('[data-investigation="captures"]')
        page.locator('[data-investigation="captures"][value="captures:' + identity + '"]').check()
        page.locator('#investigations-preview').click()
        page.wait_for_selector('#investigations-confirm')
        page.locator('#investigations-confirm').click()
        page.wait_for_selector('[data-restore-investigations]')
        assert page.locator('[data-investigation="captures"][value="captures:' + identity + '"]').count() == 0
        page.locator('[data-restore-investigations]').first.click()
        page.wait_for_selector('[data-investigation="captures"][value="captures:' + identity + '"]')
        page.screenshot(path=str(output / 'saved-investigations.png'))
        from check_review_workspace_ui import check_review_workspace_ui
        review_workspace=check_review_workspace_ui(browser,base,'capture:'+identity,output)
        assert original.read_bytes() == before

        # A second disposable collection checks that native column headers
        # reorder ALL groups, rather than only the first 50 visible rows.
        many = []
        for i in range(60):
            for sibling in range(2):
                many.append({'id': f'sort-{i:03}-{sibling}', 'title': f'Sort {59-i:03}',
                             'artist': 'Synthetic', 'current_path': f'/Synthetic/{i:03}.mp3',
                             'duration': 120 + sibling})
        sorted_snapshot = Store(data/'workbench-sidecar.sqlite3').save_snapshot(
            {'schema':1, 'scope_key':'synthetic:native-global-sort', 'tracks': many,
             'playlists': [], 'source_kind': 'test', 'capabilities': {}}, 'Browser sort fixture')
        # Refresh the collection selector without reloading the whole page:
        # the saved fixture is created while the SPA is already open.
        page.evaluate('() => Journeys.load()')
        page.wait_for_selector('#journey-context-source option[value="snapshot:' + sorted_snapshot['id'] + '"]',state='attached')
        select_collection(page,'#journey-context-source', 'snapshot:' + sorted_snapshot['id'])
        page.wait_for_function('(id)=>window.Journeys.context()?.source==="snapshot:"+id',arg=sorted_snapshot['id'])
        page.locator('.nav[data-view=review]').click()
        page.wait_for_function('document.querySelectorAll("#view-review .native-collection .native-table tbody tr").length===50')
        page.locator('#view-review .native-collection [data-native-sort="title"]').click()
        page.wait_for_function('document.querySelector("#view-review .native-collection th[aria-sort=ascending] [data-native-sort=title]")!==null')
        assert page.locator('#view-review .native-collection .native-table tbody tr td:first-child strong').first.inner_text() == 'Sort 000'
        assert page.locator('#view-review .native-collection [data-native-sort]').count() == 4
        assert page.locator('#view-review .native-collection [data-sort-column]').count() == 0
        assert '1–50' in page.locator('#view-review .native-collection .native-page-range').inner_text()
        page.locator('#view-review .native-collection [data-native-next="review"]').click()
        page.wait_for_function('document.querySelector("#view-review .native-collection .native-page-range")?.textContent.includes("51")')
        assert page.locator('#view-review .native-collection .native-table tbody tr td:first-child strong').first.inner_text() == 'Sort 050'
        page.locator('#view-review .native-collection [data-native-sort="title"]').click()
        page.wait_for_function('document.querySelector("#view-review .native-collection th[aria-sort=descending] [data-native-sort=title]")!==null')
        assert page.locator('#view-review .native-collection .native-table tbody tr td:first-child strong').first.inner_text() == 'Sort 059'
        page.locator('.nav[data-view=reference]').click()
        page.wait_for_selector('#view-reference .native-collection [data-native-sort=current_path]')
        page.locator('#view-reference .native-collection [data-native-sort=current_path]').click()
        page.wait_for_function('document.querySelector("#view-reference .native-collection th[aria-sort=ascending] [data-native-sort=current_path]")!==null')
        assert not errors, errors
        assert not failures, failures
        return {'direct_intelligence':True,'native_statistics':True, 'candidate_review':True, 'recorded_references':True,
                'direct_history':True, 'snapshot_action':True, 'archive_restore':True,
                'context_spacing':True, 'source_unchanged':True, 'synthetic':True,'review_workspace':review_workspace}
    finally:
        context.close()
