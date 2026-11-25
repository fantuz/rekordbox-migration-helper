"""Real-server Chromium workflows: persistence, stale tabs and export integrity.

Uses disposable synthetic snapshots; no intercepted API responses or user data.
"""
from ui_navigation import select_collection, open_collection_picker
import argparse
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from metadata_export import track
from workbench_store import Store


def main():
    from playwright.sync_api import sync_playwright, expect
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {'status': 'running', 'synthetic': True, 'mocked_api_responses': False, 'checks': []}
    process = context = browser = playwright = None
    with tempfile.TemporaryDirectory(prefix='workbench-integrity-') as tmp:
        root = Path(tmp)
        data = root / 'data'
        store = Store(data / 'workbench-sidecar.sqlite3')
        source = {'schema': 1, 'scope_key': 'synthetic:integrity:a',
                  'source_kind': 'Synthetic integrity fixture', 'playlists': [],
                  'tracks': [track({'id': 'one', 'title': 'Integrity track 日本', 'artist': 'Synthetic artist',
                                    'genre': 'House', 'rating': 3, 'comment': 'Original private comment',
                                    'current_path': '/private/synthetic/one.wav'})], 'capabilities': {}}
        sid = store.save_snapshot(source, 'Integrity A')['id']
        other = deepcopy(source)
        other['scope_key'] = 'synthetic:integrity:b'
        other_sid = store.save_snapshot(other, 'Integrity B')['id']
        originals = {identity: store.snapshot(identity) for identity in (sid, other_sid)}
        env = {**os.environ, 'LIBRARY_WORKBENCH_DATA_DIR': str(data),
               'LIBRARY_WORKBENCH_NO_BROWSER': '1', 'LIBRARY_WORKBENCH_DISABLE_MUSICBRAINZ': '1'}
        errors, unexpected_network = [], []
        log = (output / 'application.log').open('w', encoding='utf-8')

        def start():
            nonlocal process
            process = subprocess.Popen([sys.executable, str(ROOT / 'desktop_launcher.py'),
                                        '--no-browser', '--port', '0'], cwd=ROOT, env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError('App exited during startup; inspect application.log')
                try:
                    base = json.loads((data / 'instance.json').read_text())['url']
                    with urllib.request.urlopen(base + '/api/status', timeout=1) as response:
                        assert json.load(response)['app_id'] == 'library-workbench'
                    return base
                except (OSError, ValueError, KeyError):
                    time.sleep(.1)
            raise RuntimeError('App readiness timed out')

        def stop():
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                    raise RuntimeError('App did not shut down gracefully')

        def open_track(page, base, identity=sid):
            page.goto(base, wait_until='networkidle')
            page.locator('.nav[data-view="lab"]').click()
            select_collection(page,'#lab-snapshot', identity)
            page.locator('[data-lab-tab="editor"]').click()
            page.locator('[data-lab-edit="0"]').click()
            expect(page.locator('#track-detail-dialog')).to_be_visible()

        def save_comment(page, value):
            page.fill('#track-comment-text', value)
            with page.expect_response(lambda r: r.url.endswith('/api/lab/overrides') and r.request.method == 'POST') as pending:
                page.locator('#track-comment-save').click()
            assert pending.value.status == 200, pending.value.text()
            expect(page.locator('#track-comment-save')).to_be_disabled()
            assert store.edit_state(source['scope_key'])['overrides']['one']['comment']['value'] == value

        try:
            base = start()
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch()
            context = browser.new_context(locale='en-US', viewport={'width':1440, 'height':1000})
            context.add_init_script("if (location.protocol === 'http:') localStorage.setItem('library-workbench.language.v1','en')")
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            context.on('page', lambda p: p.on('pageerror', lambda e: errors.append(str(e))))
            context.on('request', lambda r: unexpected_network.append(r.url)
                       if not r.url.startswith(('http://127.0.0.1:', 'data:', 'file:')) else None)
            page, stale = context.new_page(), context.new_page()
            open_track(page, base)
            open_track(stale, base)
            assert not page.locator('#track-detail-unlock').is_checked()
            assert page.locator('[data-track-edit-field]').evaluate_all('els=>els.length>0 && els.every(e=>e.disabled)')
            note = 'Saved private note · Ελληνικά 日本 🎧 <mix>'
            save_comment(page, note)
            assert set(store.edit_state(source['scope_key'])['overrides']['one']) == {'comment'}
            report['checks'].append('UI save commits only the requested field to SQLite')

            stale.fill('#track-comment-text', 'Stale tab draft')
            with stale.expect_response(lambda r: r.url.endswith('/api/lab/overrides') and r.request.method == 'POST') as pending:
                stale.locator('#track-comment-save').click()
            assert pending.value.status == 409, pending.value.text()
            expect(stale.locator('#toast')).to_contain_text('Staged metadata changed')
            assert stale.locator('#track-comment-text').input_value() == 'Stale tab draft'
            assert store.edit_state(source['scope_key'])['overrides']['one']['comment']['value'] == note
            report['checks'].append('Real stale-tab conflict returns 409, preserves draft and does not overwrite saved data')

            open_track(stale, base)
            assert stale.locator('#track-comment-text').input_value() == note
            save_comment(stale, note + ' reviewed')
            note += ' reviewed'
            open_track(page, base, other_sid)
            assert page.locator('#track-comment-text').input_value() == 'Original private comment'
            assert store.edit_state(other['scope_key'])['overrides'] == {}
            report['checks'].append('Same track ID in another scope does not inherit edits')

            stop()
            base = start()
            open_track(page, base)
            assert page.locator('#track-comment-text').input_value() == note
            assert not page.locator('#track-detail-unlock').is_checked()
            report['checks'].append('Saved edit survives actual server restart while advanced fields remain locked')
            page.locator('#track-detail-dialog .close-dialog').click()
            page.locator('.nav[data-view="quick"]').click()
            page.select_option('#quick-source', 'lab:' + sid)
            page.select_option('#share-preset', 'public')
            expect(page.locator('#quick-generate')).to_be_enabled()
            before = page.locator('#quick-history .export-record').count()
            page.locator('#quick-generate').click()
            page.wait_for_function('(n)=>document.querySelectorAll("#quick-history .export-record").length>n', arg=before)
            record = page.locator('#quick-history .export-record').first
            report_href = record.locator('a[href$="/report"]').get_attribute('href')
            response = context.request.get(base + report_href)
            assert response.ok
            exported = response.json()
            downloaded = {}
            for item in exported['files']:
                link = record.locator('a[href="' + item['download'] + '"]')
                with page.expect_download() as pending:
                    link.click()
                target = output / ('download-' + item['name'])
                pending.value.save_as(target)
                content = target.read_bytes()
                assert len(content) == item['bytes']
                assert sha256(content).hexdigest() == item['sha256']
                downloaded[item['kind']] = content
                if item['kind'] == 'zip':
                    with zipfile.ZipFile(target) as archive:
                        assert archive.testzip() is None
                assert note.encode() not in content
            html = downloaded['html'].decode('utf-8')
            assert 'Original private comment' not in html
            assert '/private/synthetic/' not in html
            assert exported['staged_changes_applied'] is False
            report['checks'].append('Browser downloads match manifest byte counts and SHA-256; ZIP CRCs pass; public HTML omits private data')
            stop()
            base = start()
            page.goto(base, wait_until='networkidle')
            response = context.request.get(base + report_href)
            assert response.ok and response.json() == exported
            for item in exported['files']:
                response = context.request.get(base + item['download'])
                assert response.ok and response.body() == downloaded[item['kind']]
            report['checks'].append('Published export records and exact downloadable bytes survive server restart')

            open_track(page, base)
            with page.expect_response(lambda r: r.url.endswith('/api/lab/overrides') and r.request.method == 'DELETE') as pending:
                page.locator('#track-comment-reset').click()
            assert pending.value.status == 200
            expect(page.locator('#track-comment-text')).to_have_value('Original private comment')
            assert store.edit_state(source['scope_key'])['overrides'] == {}
            stop()
            base = start()
            open_track(page, base)
            assert page.locator('#track-comment-text').input_value() == 'Original private comment'
            assert store.edit_state(source['scope_key'])['overrides'] == {}
            for identity, original in originals.items():
                assert store.snapshot(identity) == original
            report['checks'].append('Reset persists across restart; both immutable source snapshots remain identical')
            from check_migration_readiness_ui import check_migration_readiness_ui
            report['migration_readiness']=check_migration_readiness_ui(browser,base,store,root,output)
            from check_format_insights_ui import check_format_insights_ui
            report['format_insights']=check_format_insights_ui(browser,base,store,root,output)
            from check_snapshot_integrity_ui import check_snapshot_integrity_ui
            report['snapshot_integrity']=check_snapshot_integrity_ui(browser,base,store,output)
            from check_stems_workflows_ui import check_stems_workflows_ui
            report['stems_workflows']=check_stems_workflows_ui(browser,base,store,root,output)
            stop()
            base=start()
            saved_id=report['stems_workflows']['saved_report_id']
            response=context.request.get(base+'/api/lab/reports/'+saved_id+'/download')
            assert response.ok and response.json()['summary']['stems_eligibility']['tracks']==125
            report['stems_workflows']['survives_server_restart']=True
            saved_id=report['snapshot_integrity']['saved_report_id']
            response=context.request.get(base+'/api/lab/reports/'+saved_id+'/download')
            assert response.ok and response.json()['summary']['cue_active_loop']==1
            report['snapshot_integrity']['survives_server_restart']=True
            from check_onetagger_results_ui import check_onetagger_results_ui
            report['onetagger_results']=check_onetagger_results_ui(browser,base,store,root,output)
            stop()
            base=start()
            bridge=report['onetagger_results']
            response=context.request.get(base+'/api/onetagger/'+bridge['selection_id']+'/review')
            assert response.ok and response.json()['scan']['report']['digest']==bridge['report_digest']
            assert response.json()['scan']['review_revision']==bridge['review_revision']
            bridge['survives_server_restart']=True
            from check_grid_nudge_ui import check_grid_nudge_ui
            report['grid_nudge'] = check_grid_nudge_ui(browser, base, root, output)
            assert not errors, errors
            assert not unexpected_network, unexpected_network
            report.update(status='passed', page_errors=errors, unexpected_network_requests=unexpected_network)
        except Exception as error:
            report.update(status='failed', error=str(error), page_errors=errors,
                          unexpected_network_requests=unexpected_network)
            if context:
                for i, page in enumerate(context.pages):
                    try:
                        page.screenshot(path=str(output / f'failure-{i}.png'))
                    except Exception:
                        pass
            raise
        finally:
            try:
                if context:
                    context.tracing.stop(path=str(output / 'trace.zip'))
                    context.close()
                if browser:
                    browser.close()
                if playwright:
                    playwright.stop()
            finally:
                stop()
                log.close()
                (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
                print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
