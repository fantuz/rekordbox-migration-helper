"""Browser regressions using a tiny, invented native SQLite collection only."""
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
        page.wait_for_selector('#journey-context-source')
        page.select_option('#journey-context-source', 'capture:' + identity)
        page.wait_for_function('(id)=>window.Journeys.context()?.source==="capture:"+id', arg=identity)
        assert page.locator('#session-cleanup-note').inner_text() == 'Analysis copies are temporary. Originals stay unchanged.'
        assert page.locator('#session-cleanup-note summary').count() == 0
        action = page.locator('[data-journey-context-capture]')
        assert action.evaluate('(e)=>getComputedStyle(e).borderStyle') == 'solid'
        for width in (1715, 768, 390):
            page.set_viewport_size({'width':width, 'height':1000})
            label = page.locator('.journey-context-row>label>span').bounding_box()
            select = page.locator('#journey-context-source').bounding_box()
            assert select['x'] >= label['x'] + label['width'] + 8 or select['y'] >= label['y'] + label['height'] + 8
        page.set_viewport_size({'width':1715, 'height':1000})
        page.locator('.nav[data-view=statistics]').click()
        page.wait_for_selector('#stats-cards .stat-card')
        page.wait_for_function("document.querySelector('#stats-cards .stat-card strong').textContent==='3'")
        assert page.locator('#stats-cohort').is_disabled()
        page.locator('.nav[data-view=review]').click()
        page.wait_for_selector('[data-native-group]')
        page.locator('[data-native-group]').first.click()
        page.wait_for_selector('.native-detail tbody tr')
        assert page.locator('.native-detail tbody tr').count() == 2
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
        action.click()
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
        assert original.read_bytes() == before
        assert not errors, errors
        assert not failures, failures
        return {'native_statistics':True, 'candidate_review':True, 'recorded_references':True,
                'direct_history':True, 'snapshot_action':True, 'archive_restore':True,
                'context_spacing':True, 'source_unchanged':True, 'synthetic':True}
    finally:
        context.close()
