"""Synthetic browser regressions for result sorting and file-health browsing."""
from pathlib import Path


def check_results_sort_file_health_ui(browser,base,sid,output):
    context=browser.new_context(locale='en-US',viewport={'width':1440,'height':980})
    context.add_init_script("localStorage.setItem('library-workbench.language.v1','en')")
    page=context.new_page()
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    try:
        page.goto(base,wait_until='networkidle')
        page.locator('.nav[data-view="file-health"]').click()
        page.wait_for_selector('#file-health-source option[value="snapshot:'+sid+'"]',state='attached')
        page.select_option('#file-health-source','snapshot:'+sid)
        page.wait_for_function('document.querySelector("#file-health-counts").textContent.includes("Unchecked")')
        before=page.locator('#file-health-counts').inner_text()
        assert 'Unchecked' in before

        # Explicit scan exercises the background worker and does not run
        # on initial navigation. Synthetic fixture has no real audio paths.
        page.locator('#file-health-scan').click()
        page.wait_for_function('document.querySelector("#file-health-state").textContent.includes("complete")',timeout=30000)
        page.wait_for_selector('#file-health-results tbody tr')
        rows=page.locator('#file-health-results tbody tr').count()
        assert rows>1,rows
        page.select_option('#file-health-status','unverified')
        page.wait_for_function('document.querySelector("#file-health-status").value==="unverified"')
        page.wait_for_function('document.querySelector("#file-health-results tbody tr")!==null')
        page.locator('#file-health-results [data-file-health-sort="title"] button').click()
        page.wait_for_function('document.querySelector("#file-health-results th[data-file-health-sort=title]")?.getAttribute("aria-sort")==="ascending"')
        assert 'source=' not in page.locator('#file-health-state').inner_text()
        page.screenshot(path=str(output/'file-health-explorer.png'))

        # Reusable column sorting works for any bounded result table.
        # These labels and counts are invented; no external files are read.
        page.evaluate('''() => {
          const fixture=document.createElement('div');fixture.id='synthetic-result-sort-fixture';
          fixture.innerHTML='<table><thead><tr><th>Title</th><th data-sort-type="number">Count</th></tr></thead>'+
            '<tbody><tr><td>Zulu</td><td>12</td></tr><tr><td>Alpha</td><td>3</td></tr><tr><td>Echo</td><td>8</td></tr></tbody></table>';
          document.querySelector('#view-file-health').append(fixture);
        }''')
        page.wait_for_selector('#synthetic-result-sort-fixture [data-sort-column="0"]')
        page.locator('#synthetic-result-sort-fixture [data-sort-column="0"]').click()
        assert page.locator('#synthetic-result-sort-fixture tbody tr td:first-child').all_inner_texts()==['Alpha','Echo','Zulu']
        page.locator('#synthetic-result-sort-fixture [data-sort-column="1"]').click()
        assert page.locator('#synthetic-result-sort-fixture tbody tr td:last-child').all_inner_texts()==['3','8','12']
        page.locator('#synthetic-result-sort-fixture [data-sort-column="1"]').click()
        assert page.locator('#synthetic-result-sort-fixture tbody tr td:last-child').all_inner_texts()==['12','8','3']
        assert page.locator('#synthetic-result-sort-fixture th[aria-sort="descending"]').count()==1
        page.evaluate("document.querySelector('#synthetic-result-sort-fixture').remove()")

        # MusicBrainz quick targets use saved tags/playlist membership only.
        # Changing target criteria invalidates the prior preview; it must
        # never silently authorize a different enrichment selection.
        page.locator('.nav[data-view="musicbrainz"]').click()
        page.wait_for_selector('#musicbrainz-snapshot option[value="'+sid+'"]',state='attached')
        page.select_option('#musicbrainz-snapshot',sid)
        page.select_option('#lab-pilot-target','random')
        assert page.locator('#musicbrainz-target-value-label').is_hidden()
        assert 'seed' in page.locator('.musicbrainz-parameters').inner_text().lower()
        page.select_option('#lab-pilot-target','missing_genre')
        assert page.locator('#lab-pilot-preview').is_enabled()
        assert page.locator('#lab-pilot-start').is_disabled()
        page.select_option('#lab-pilot-target','genre')
        page.wait_for_selector('#lab-pilot-target-value option',state='attached')
        page.wait_for_function('document.querySelector("#lab-pilot-target-value").options.length>1')
        assert page.locator('#musicbrainz-target-value-label').is_visible()
        assert page.locator('#lab-pilot-start').is_disabled()

        assert not errors,errors
        return {'scanned_rows':rows,'global_filter':True,'global_sort':True,
                'visible_rows_sort':True,'aria_sort':True,'quick_targets':True,'no_page_errors':True}
    finally:
        context.close()
