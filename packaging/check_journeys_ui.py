"""Real-browser journey interactions using only the CI server's synthetic snapshot."""


def check_journeys_ui(page, base, sid, output):
    page.select_option('#language', 'en')
    page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
    page.locator('.nav[data-view="files"]').click()
    page.wait_for_selector('#journey-panel .journey-goal')
    assert page.locator('#journey-panel .journey-goal').count() == 4
    page.select_option('#journey-context-source', 'snapshot:' + sid)
    page.wait_for_function('(sid)=>window.Journeys.context()?.snapshot===sid', arg=sid)
    page.locator('[data-journey="integrity"]').click()
    page.wait_for_selector('#journey-health-form')
    page.locator('#journey-health-form button[type="submit"]').click()
    page.wait_for_selector('.journey-report .journey-findings>div')
    assert page.locator('.journey-status.not_checked').count() > 0
    assert 'No finding in scope does not mean' in page.locator('#journey-panel').inner_text()
    page.screenshot(path=str(output / 'integrity-journey.png'))

    page.locator('[data-journey="migration"]').click()
    page.wait_for_selector('#journey-migration-form')
    page.locator('#journey-destination').fill('D:\\Music 日本 🎵')
    page.locator('#journey-notes').fill('Keep copies — Ελληνικά, русский, café')
    page.select_option('#journey-cloud', 'copy')
    with page.expect_response(lambda r: r.request.method == 'POST' and '/api/journeys/' in r.url and (r.request.post_data_json or {}).get('step') == 'backup'):
        page.locator('[data-journey-step="backup"]').check()
    page.wait_for_function('document.querySelector("#journey-notes").value.includes("Ελληνικά") && document.querySelector("[data-journey-step=backup]").checked')
    page.reload(wait_until='networkidle')
    page.wait_for_selector('#journey-migration-form')
    assert page.locator('#journey-destination').input_value() == 'D:\\Music 日本 🎵'
    assert page.locator('#journey-notes').input_value() == 'Keep copies — Ελληνικά, русский, café'
    assert page.locator('#journey-cloud').input_value() == 'copy'
    assert page.locator('[data-journey-step="backup"]').is_checked()
    assert 'Confirmed by you' in page.locator('.journey-steps').inner_text()
    # A language refresh must keep drafts without writing them to the plan.
    page.locator('#journey-notes').fill('Unsaved draft — Καλημέρα 🎵')
    page.select_option('#language', 'it')
    page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
    assert page.locator('#journey-notes').input_value() == 'Unsaved draft — Καλημέρα 🎵'
    page.select_option('#language', 'en')
    page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
    assert page.locator('#journey-notes').input_value() == 'Unsaved draft — Καλημέρα 🎵'
    assert page.locator('.journey-steps [data-help-doc="inputs-and-restore"]').count() == 1
    page.screenshot(path=str(output / 'migration-journey.png'))
    return {'goal_cards': True, 'quick_integrity_scope': True, 'resume_unicode_notes': True,
            'confirmations_labelled': True, 'collection_context': True,
            'source': 'synthetic snapshot only; no provider requests or source scans'}
