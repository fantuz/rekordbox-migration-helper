"""Real HTTP connection-gate and Google Drive workflows with invented providers.

Application responses are not intercepted. Only the remote provider transport
and local OS discovery fixture are synthetic; Flask, SQLite, jobs, JavaScript
and the actual filesystem attachment/download paths remain real.
"""
import argparse
from copy import deepcopy
import json
import logging
from pathlib import Path
import re
import sys
from threading import Thread
import time
from urllib.parse import parse_qs,urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--browser',choices=('chromium','firefox','webkit'),default='chromium')
    parser.add_argument('--headed',action='store_true')
    args=parser.parse_args();output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    report={'status':'running','browser':args.browser,'synthetic':True,'real_http':True,
            'mocked_api_responses':False,'synthetic_provider_transport':True,
            'live_accounts_validated':False}
    from playwright.sync_api import sync_playwright,expect
    from werkzeug.serving import make_server
    from test_cloud_connection_workflows import CloudConnectionWorkflowTests
    fixture=CloudConnectionWorkflowTests('test_both_selected_cache_attachments_preserve_sources_and_detach_independently')
    fixture.setUp();application=fixture.application
    server=make_server('127.0.0.1',0,application.app,threaded=True)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_port)
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    try:
        with sync_playwright() as playwright:
            browser=getattr(playwright,args.browser).launch(headless=not args.headed)
            context=browser.new_context(locale='en-US',viewport={'width':1440,'height':1050})
            context.add_init_script("if(location.protocol==='http:')localStorage.setItem('library-workbench.language.v1','en')")
            context.tracing.start(screenshots=True,snapshots=True,sources=True)
            page=context.new_page();errors=[];external=[];transfers=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            context.on('request',lambda request:external.append(request.url) if urlsplit(request.url).scheme not in
                ('data','blob','file') and urlsplit(request.url).netloc!=urlsplit(base).netloc else None)
            page.on('request',lambda request:transfers.append(request.url) if
                urlsplit(request.url).path in ('/api/dropbox/download','/api/google-drive/download') else None)

            def get(path):
                response=context.request.get(base+'/api/'+path)
                assert response.ok,response.text()
                return response.json()

            def post(path,value):
                return context.request.post(base+'/api/'+path,data=value,headers=fixture.headers)

            def setup_stage(provider):
                page.locator('#cloud-setup-'+('google' if provider=='google_drive' else 'dropbox')).check()
                if provider=='dropbox':page.select_option('#cloud-setup-arrangement','cloud_option')
                expect(page.locator('#cloud-setup-sync-mode')).to_have_value('selected')
                page.select_option('#cloud-setup-desktop-mode','unknown')
                page.select_option('#cloud-setup-default-upload','dropbox')
                page.locator('#cloud-setup-next').click()
                expect(page.locator('#cloud-setup-account-state')).to_contain_text(
                    'Invented Google account' if provider=='google_drive' else 'Invented Dropbox account')
                callback=base+('/api/google-drive/callback' if provider=='google_drive' else '/api/dropbox/callback')
                expect(page.locator('#cloud-setup-redirect')).to_have_value(callback)
                page.locator('#cloud-setup-copy-redirect').click()
                response=post(('google-drive' if provider=='google_drive' else 'dropbox')+'/connect',{})
                assert response.ok,response.text()
                authorization=response.json()
                assert parse_qs(urlsplit(authorization.get('authorize_url',authorization.get('authorization_url'))).query)['redirect_uri']==[callback]
                assert not external
                page.locator('#cloud-setup-next').click()
                page.select_option('#cloud-setup-source',fixture.source)
                expect(page.locator('#cloud-setup-source')).to_have_value(fixture.source)
                cache=fixture.google_cache if provider=='google_drive' else fixture.dropbox_cache
                page.fill('#cloud-setup-local-root',str(cache))
                page.fill('#cloud-setup-recorded-root','E:/Old Drive' if provider=='google_drive' else 'D:/Old Dropbox')
                page.fill('#cloud-setup-remote-root','drive-music' if provider=='google_drive' else '/Music')
                if provider=='dropbox':page.fill('#cloud-setup-namespace','101')

            def preview(matched):
                page.locator('#cloud-setup-next').click()
                expect(page.locator('#cloud-setup-review-state')).to_contain_text(f'{matched} / 64')

            try:
                connected_state=deepcopy(fixture.providers['dropbox'].state)
                fixture.providers['dropbox'].state.update(configured=False,connected=False,app_key='',account=None)
                page.goto(base,wait_until='networkidle');page.locator('.nav[data-view="cloud-connect"]').click()
                expect(page.locator('#view-cloud-connect')).to_be_visible()
                expect(page.locator('#cloud-setup-attach')).to_be_disabled()
                initial=get('cloud-setup/status?source='+fixture.source)
                assert any(row['root']==str(fixture.dropbox) and row['provider_verified'] for row in initial['roots'])
                assert any(row['root']==str(fixture.google_hint) and not row['provider_verified'] for row in initial['roots'])
                assert all(not item.downloads and not item.calls for item in fixture.providers.values())
                page.locator('#cloud-setup-next').click()
                expect(page.locator('#cloud-setup-next')).to_be_disabled()
                expect(page.locator('#cloud-setup-connect')).to_be_disabled()
                expect(page.locator('#cloud-setup-redirect')).to_have_value(base+'/api/dropbox/callback')
                expect(page.locator('#cloud-setup-copy-redirect')).to_be_enabled()
                expect(page.locator('#cloud-setup-developer-console')).to_have_attribute('href','https://www.dropbox.com/developers/apps')
                page.locator('#cloud-setup-copy-redirect').click()
                page.screenshot(path=str(output/'cloud-connection-setup.png'),full_page=True)
                assert all(not item.downloads and not item.calls for item in fixture.providers.values())
                fixture.providers['dropbox'].state=connected_state
                page.locator('#cloud-setup-refresh').click()
                expect(page.locator('#cloud-setup-account-state')).to_contain_text('Invented Dropbox account')
                page.locator('#cloud-setup-previous').click()
                setup_stage('dropbox')
                expect(page.locator('#cloud-setup-suggestions')).to_contain_text(str(fixture.dropbox))
                preview(2)
                expect(page.locator('#cloud-setup-attach')).to_be_enabled()
                expect(page.locator('#cloud-setup-review-summary')).to_contain_text(str(fixture.dropbox_cache))
                expect(page.locator('#cloud-setup-review-examples')).to_contain_text('Dropbox 000.mp3')
                assert all(not item.downloads for item in fixture.providers.values())
                page.screenshot(path=str(output/'cloud-attachment-preview.png'),full_page=True)
                page.locator('#cloud-setup-attach').click()
                expect(page.locator('#cloud-setup-attached')).to_contain_text('Dropbox')
                attached=get('cloud-setup/status?source='+fixture.source)
                assert attached['attachments']['dropbox']['local_root']==str(fixture.dropbox_cache)

                setup_stage('google_drive')
                expect(page.locator('#cloud-setup-sync-mode option[value="all"]')).to_have_count(0)
                refused=post('cloud-setup/preview',fixture.values('google_drive',sync_mode='all'))
                assert refused.status==400,refused.text()
                page.fill('#cloud-setup-remote-root','drive-empty');preview(0)
                expect(page.locator('#cloud-setup-attach')).to_be_disabled()
                assert not get('cloud-setup/status?source='+fixture.source)['attachments']['google_drive']
                page.locator('#cloud-setup-previous').click()
                fixture.providers['google_drive'].ambiguous=True
                page.fill('#cloud-setup-remote-root','drive-music')
                page.locator('#cloud-setup-next').click()
                expect(page.locator('#cloud-setup-review-counts')).to_contain_text('Ambiguous paths')
                expect(page.locator('#cloud-setup-attach')).to_be_disabled()
                assert not get('cloud-setup/status?source='+fixture.source)['attachments']['google_drive']
                fixture.providers['google_drive'].ambiguous=False
                page.locator('#cloud-setup-previous').click();preview(61)
                expect(page.locator('#cloud-setup-attach')).to_be_enabled()

                # A folder replaced after preview must not inherit its consent.
                old_cache=fixture.root/'Previous Google cache'
                fixture.google_cache.rename(old_cache)
                (fixture.google_cache/'Album').mkdir(parents=True)
                page.locator('#cloud-setup-attach').click()
                expect(page.locator('#toast')).to_contain_text(re.compile('changed|again|expired',re.I))
                assert not get('cloud-setup/status?source='+fixture.source)['attachments']['google_drive']
                (fixture.google_cache/'Album').rmdir();fixture.google_cache.rmdir();old_cache.rename(fixture.google_cache)
                page.locator('#cloud-setup-previous').click();preview(61)
                page.locator('#cloud-setup-attach').click()
                expect(page.locator('#cloud-setup-attached .cloud-attached-card')).to_have_count(2)
                both=get('cloud-setup/status?source='+fixture.source)
                assert all(both['attachments'][name] for name in fixture.providers)
                assert all(not item.downloads for item in fixture.providers.values())
                assert fixture.store.snapshot(fixture.sid)==fixture.before
                page.screenshot(path=str(output/'cloud-connections-attached.png'),full_page=True)

                page.locator('.nav[data-view="google-drive"]').click()
                expect(page.locator('#google-drive-connection-state')).to_contain_text('Invented Google account')
                expect(page.locator('#google-drive-redirect')).to_have_value(base+'/api/google-drive/callback')
                page.select_option('#google-drive-source',fixture.source)
                page.locator('#google-drive-check').click()
                expect(page.locator('#google-drive-count')).to_contain_text('64')
                expect(page.locator('#google-drive-results tbody tr')).to_have_count(50)
                assert all(not item.downloads for item in fixture.providers.values())
                page.select_option('#google-drive-status','present')
                expect(page.locator('#google-drive-count')).to_contain_text('61')
                page.locator('#google-drive-next').click()
                expect(page.locator('#google-drive-results tbody tr')).to_have_count(11)
                page.fill('#google-drive-search','Invented Google 060');page.locator('#google-drive-find').click()
                expect(page.locator('#google-drive-results tbody tr')).to_have_count(1)
                expect(page.locator('#google-drive-results')).to_contain_text('Invented Google 060 <mix>')
                assert page.locator('#google-drive-results img').count()==0
                page.locator('[data-google-drive-download="gd-60"]').click()
                dialog=page.locator('#google-drive-download-dialog')
                expect(dialog).to_be_visible();expect(page.locator('#google-drive-download-cancel')).to_be_focused()
                expect(page.locator('#google-drive-download-path')).to_have_text(str(fixture.google_cache/'Album'/'Drive 060.mp3'))
                page.screenshot(path=str(output/'google-drive-confirmation.png'),full_page=True)
                page.locator('#google-drive-download-cancel').click();expect(dialog).to_be_hidden()
                assert not fixture.providers['google_drive'].downloads
                page.locator('[data-google-drive-download="gd-60"]').click();expect(dialog).to_be_visible()
                page.keyboard.press('Escape');expect(dialog).to_be_hidden()
                assert not fixture.providers['google_drive'].downloads
                page.locator('[data-google-drive-download="gd-60"]').click();expect(dialog).to_be_visible()
                page.locator('#google-drive-download-confirm').click()
                expect(page.locator('#toast')).to_contain_text('One track downloaded',timeout=20000)
                assert fixture.providers['google_drive'].downloads==['drive-60']
                assert (fixture.google_cache/'Album'/'Drive 060.mp3').read_bytes()==fixture.providers['google_drive'].body
                expect(page.locator('[data-google-drive-download="gd-60"]')).to_have_count(0)

                # A second, explicitly approved corrupt transfer publishes nothing.
                fixture.providers['google_drive'].corrupt=True
                page.fill('#google-drive-search','Invented Google 059');page.locator('#google-drive-find').click()
                page.locator('[data-google-drive-download="gd-59"]').click();expect(dialog).to_be_visible()
                page.locator('#google-drive-download-confirm').click()
                expect(page.locator('#toast')).to_contain_text(re.compile('checksum|does not match|content',re.I),timeout=20000)
                assert not (fixture.google_cache/'Album'/'Drive 059.mp3').exists()
                assert len(list((fixture.google_cache/'Album').iterdir()))==1
                fixture.providers['google_drive'].corrupt=False

                page.locator('.nav[data-view="cloud-connect"]').click()
                dropbox_card=page.locator('#cloud-setup-attached .cloud-attached-card').filter(has_text='Dropbox')
                dropbox_card.get_by_role('button',name='Detach location',exact=True).click()
                expect(page.locator('#cloud-setup-attached .cloud-attached-card')).to_have_count(1)
                remaining=get('cloud-setup/status?source='+fixture.source)
                assert not remaining['attachments']['dropbox'] and remaining['attachments']['google_drive']
                assert all(row['connected'] for row in remaining['providers'].values())
                assert (fixture.google_cache/'Album'/'Drive 060.mp3').read_bytes()==fixture.providers['google_drive'].body
                assert fixture.store.snapshot(fixture.sid)==fixture.before
                for width in (820,390):
                    page.set_viewport_size({'width':width,'height':900})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
                assert not errors,errors
                assert not external,external
                assert len(transfers)==2,transfers
                report.update(status='passed',initial_setup_before_credentials=True,detected_provenance_retained=True,selected_cache_outside_provider_root=True,
                    precise_callback_before_authorization=True,google_all_mode_rejected=True,zero_match_held=True,
                    ambiguous_path_held=True,changed_local_folder_invalidates_consent=True,both_providers_coexist=True,
                    metadata_only_check=True,full_scope_pagination=True,cancel_and_escape_preserve_files=True,
                    explicit_single_download=True,rejected_corrupt_transfer=True,detach_preserves_other_provider_and_files=True,
                    snapshot_unchanged=True,mobile_layout=True,downloaded_files=1,external_requests=external)
            except Exception:
                page.screenshot(path=str(output/'cloud-connections-failure.png'),full_page=True);raise
            finally:
                context.tracing.stop(path=str(output/'cloud-connections-trace.zip'));context.close();browser.close()
    except Exception as error:
        report.update(status='failed',error=str(error));raise
    finally:
        server.shutdown();thread.join(timeout=5);server.server_close();fixture.doCleanups()
        (output/'cloud-connections-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
