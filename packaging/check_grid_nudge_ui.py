"""Exercise the copy-only grid editor with a real XML import and encrypted backup."""
from hashlib import sha256
import os
import zipfile

from playwright.sync_api import expect

from test_grid_nudge_fixture import create_grid_fixture, grid_files


def check_grid_nudge_ui(browser, base, root, output):
    fixture = create_grid_fixture(root / 'grid inputs')
    sources = [fixture[name] for name in ('xml', 'backup', 'master')]
    before = {path: sha256(path.read_bytes()).digest() for path in sources}
    context = browser.new_context(locale='en-US', viewport={'width': 1280, 'height': 900})
    context.add_init_script("localStorage.setItem('library-workbench.language.v1','en')")
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))

    def open_editor():
        page.locator('.nav[data-view="lab"]').click()
        page.locator('[data-lab-tab="formats"]').click()

    def preview(offset):
        with page.expect_response(lambda r: r.url.endswith('/api/lab/grid-nudge/preview')) as request:
            page.locator('#grid-preview').click()
        response = request.value
        assert response.ok, response.text()
        assert response.request.post_data_json['offset_ms'] == offset
        result = page.locator('#grid-result')
        for label, original in [('First beat (ms)', 125), ('Last beat (ms)', 625)]:
            cells = result.get_by_role('row', name=label).get_by_role('cell')
            expect(cells).to_have_text([str(original), str(original + offset)])
        expect(result).to_contain_text('/Music/Night Signal.wav')
        expect(result).to_contain_text('ANLZ0000.DAT')
        expect(result).to_contain_text('ANLZ0000.EXT')
        expect(page.locator('#grid-download')).to_be_enabled()

    try:
        page.goto(base, wait_until='networkidle')
        open_editor()
        page.locator('#grid-import').click()
        page.locator('[data-import-mode="local"]').click()
        page.locator('#local-zip').fill(str(fixture['backup']))
        page.locator('#local-xml').fill(str(fixture['xml']))
        page.locator('#local-import-form button[type="submit"]').click()
        page.locator('#preparation-later').click()
        open_editor()
        page.locator('#grid-query').fill('Night Signal')
        page.locator('#grid-search').click()
        track = page.locator('#grid-track')
        track.select_option(fixture['track_id'])
        expect(track.locator('option:checked')).to_contain_text('Night Signal')
        expect(page.locator('#grid-download')).to_be_disabled()

        page.locator('#grid-direction').select_option('earlier')
        preview(-1)
        page.locator('#grid-direction').select_option('later')
        expect(page.locator('#grid-result')).to_be_empty()
        expect(page.locator('#grid-download')).to_be_disabled()
        preview(1)
        page.locator('#lab-grid-nudge').screenshot(path=str(output / 'beat-grid-nudge.png'))
        with page.expect_download() as download:
            page.locator('#grid-download').click()
        assert download.value.suggested_filename == 'analysis-grid-nudge.zip'
        target = output / download.value.suggested_filename
        download.value.save_as(target)
        expected = grid_files(1, clear_mirror=True)
        with zipfile.ZipFile(target) as archive:
            assert archive.testzip() is None
            assert sorted(archive.namelist()) == sorted(expected)
            for name, raw in expected.items():
                assert archive.read(name) == raw, name
        page.locator('#grid-query').fill('Other track')
        expect(page.locator('#grid-download')).to_be_disabled()
        expect(page.locator('#grid-track')).to_be_disabled()
        expect(page.locator('#grid-result')).to_be_empty()
        # Change the linked input after a second preview. The real download route must refuse it.
        page.locator('#grid-query').fill('Night Signal')
        page.locator('#grid-search').click()
        track.select_option(fixture['track_id'])
        preview(1)
        modified = fixture['backup']
        stat = modified.stat()
        os.utime(modified, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))
        try:
            with page.expect_response(lambda r: r.url.endswith('/api/lab/grid-nudge/download')) as refused:
                page.locator('#grid-download').click()
            assert refused.value.status == 400, refused.value.status
            expect(page.locator('#grid-status')).to_contain_text('changed')
            expect(page.locator('#grid-download')).to_be_disabled()
        finally:
            os.utime(modified, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        assert all(sha256(path.read_bytes()).digest() == original for path, original in before.items())
        assert not errors, errors
        return {'status': 'passed', 'directions_checked': ['earlier', 'later'],
                'stale_source_refused': True, 'source_preserved': True, 'download_verified_byte_for_byte': True}
    except Exception:
        page.screenshot(path=str(output / 'grid-nudge-failure.png'), full_page=True)
        raise
    finally:
        context.close()
