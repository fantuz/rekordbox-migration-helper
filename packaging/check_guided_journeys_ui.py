"""Synthetic saved journey flow, capability labels and unrestricted navigation."""

def check_guided_journeys_ui(page,base,sid,output):
    def start_journey():
        # Headed Firefox can miss native pointer events near the viewport's
        # bottom edge. Scroll the real button inward, then use a normal click.
        button=page.locator('#guide-start')
        button.evaluate('el=>el.scrollIntoView({block:"center",inline:"nearest"})')
        button.click();page.wait_for_selector('#guide-notes')
    page.locator('.nav[data-view="journeys"]').click()
    # Navigation refreshes saved plans. Await that render before a pointer click
    # can target a button which the pending response is about to replace.
    page.evaluate('()=>GuidedJourneys.load()')
    page.wait_for_selector('[data-guide="guide-rb-serato"]')
    assert page.locator('[data-guide]').count()==8
    page.locator('[data-guide="guide-serato-rb"]').click()
    assert 'not implemented' in page.locator('.guided-plan').inner_text()
    start_journey()
    page.locator('#guide-notes').fill('Synthetic migration notes · 日本 🎧')
    with page.expect_response(lambda r:'/api/journeys/' in r.url and r.request.method=='POST' and (r.request.post_data_json or {}).get('step')=='backup'):
        page.locator('[data-guide-step="backup"]').check()
    page.wait_for_function('document.querySelector("[data-guide-step=backup]").checked')
    page.locator('.nav[data-view="bubbles"]').click()
    page.locator('.nav[data-view="journeys"]').click();page.evaluate('()=>GuidedJourneys.load()');page.wait_for_selector('#guide-notes')
    assert '日本' in page.locator('#guide-notes').input_value()
    assert page.locator('[data-guide-step="backup"]').is_checked()
    page.locator('#guide-notes').fill('Unsaved multilingual note Ελληνικά')
    page.select_option('#language','it');page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
    assert page.locator('#guide-notes').input_value()=='Unsaved multilingual note Ελληνικά'
    page.select_option('#language','en');page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
    page.locator('[data-guide="guide-rb-serato"]').click();start_journey()
    assert 'draft' in page.locator('.guided-plan .callout').inner_text()
    page.screenshot(path=str(output/'guided-migration.png'))
    page.locator('[data-guide-open="4"]').click();page.wait_for_selector('#view-intelligence',state='visible')
    page.wait_for_selector('.serato-entry[open]',state='visible')
    page.locator('.serato-entry summary').click()  # Restore the next test's initial panel state.
    page.locator('.nav[data-view="journeys"]').click();page.evaluate('()=>GuidedJourneys.load()');page.wait_for_selector('[data-guide="guide-sharing"]')
    page.locator('[data-guide="guide-sharing"]').click()
    assert 'audio files are not included' in page.locator('.guided-plan').inner_text()
    return {'eight_guides':True,'external_reverse_migration_label':True,'saved_progress':True,'free_navigation':True,'language_preserves_draft':True}
