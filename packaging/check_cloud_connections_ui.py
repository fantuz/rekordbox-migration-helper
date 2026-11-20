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
    from ui_navigation import select_collection,open_collection_picker
    from check_cloud_progress_ui import check_cloud_progress
    from werkzeug.serving import make_server
    from test_cloud_connection_workflows import CloudConnectionWorkflowTests
    fixture=CloudConnectionWorkflowTests('test_both_selected_cache_attachments_preserve_sources_and_detach_independently')
    fixture.setUp();application=fixture.application
    other=deepcopy(fixture.before);other['scope_key']='synthetic:other-cloud-collection'
    other_sid=fixture.store.save_snapshot(other,'Other invented cloud collection')['id']
    other_source='snapshot:'+other_sid
    statistics_tracks=[{'id':'year-'+str(i),'title':'Invented year '+str(i),'artist':'Invented artist',
                       'year':year,'duration':240,'genre':'Invented genre'}
                      for i,year in enumerate((2020,2020,2022,1999,None,None,None))]
    statistics_sid=fixture.store.save_snapshot({'scope_key':'synthetic:cloud-year-order',
        'tracks':statistics_tracks,'playlists':[]},'Invented release-year ordering')['id']
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
            page=context.new_page();errors=[];external=[];transfers=[];statistics_reads=[];dropbox_checks=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            context.on('request',lambda request:external.append(request.url) if urlsplit(request.url).scheme not in
                ('data','blob','file') and urlsplit(request.url).netloc!=urlsplit(base).netloc else None)
            page.on('request',lambda request:transfers.append(request.url) if
                urlsplit(request.url).path in ('/api/dropbox/download','/api/google-drive/download') else None)
            page.on('request',lambda request:statistics_reads.append(request.url) if
                urlsplit(request.url).path in ('/api/statistics','/api/collection/statistics') else None)
            page.on('request',lambda request:dropbox_checks.append(request.url) if
                urlsplit(request.url).path=='/api/dropbox/check' and request.method=='POST' else None)

            def get(path):
                response=context.request.get(base+'/api/'+path)
                assert response.ok,response.text()
                return response.json()

            def post(path,value):
                return context.request.post(base+'/api/'+path,data=value,headers=fixture.headers)

            def provider_calls():return sum(len(provider.calls) for provider in fixture.providers.values())

            def capture(locator,name):
                expect(page.locator('#toast')).to_be_hidden(timeout=12000)
                locator.screenshot(path=str(output/name))

            def run_ui_job(button,path):
                with page.expect_response(lambda response:
                        urlsplit(response.url).path==path and response.request.method=='POST') as response:
                    button.click()
                assert response.value.ok,response.value.text()
                started=response.value.json();deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    job=get('tasks/'+started['job'])
                    if job['status']=='complete':break
                    assert job['status'] not in ('error','cancelled'),job
                    time.sleep(0.02)
                else:raise AssertionError('Requested scan did not complete: '+path)
                return job['result']

            def scan_local():
                run_ui_job(page.locator('#file-health-scan'),'/api/file-health/scan')
                expect(page.locator('#file-health-state')).to_contain_text('complete',timeout=20000)

            def check_release_order():
                select_collection(page,'#journey-context-source','snapshot:'+statistics_sid)
                page.wait_for_function('(source)=>Journeys.context()?.source===source',arg='snapshot:'+statistics_sid)
                page.locator('.nav[data-view="statistics"]').click()
                page.wait_for_selector('#release-histogram .hist-row')
                selector=page.locator('#statistics-release-order')
                expect(selector).to_have_value('year_desc')
                known=page.locator('#release-histogram .hist-row[data-chart-unknown=false]>span')
                assert known.all_text_contents()==['2022','2020','1999']
                note=page.locator('#release-histogram .chart-exclusion-note').inner_text()
                reads_before_sort=len(statistics_reads)
                selector.select_option('count_desc')
                assert known.all_text_contents()==['2020','2022','1999']
                assert len(statistics_reads)==reads_before_sort
                assert page.locator('#release-histogram .chart-exclusion-note').inner_text()==note
                assert page.locator('#release-histogram .hist-row').last.get_attribute('data-chart-unknown')=='true'
                page.locator('#view-statistics [data-hide-unknown]').check()
                expect(selector).to_have_value('count_desc')
                expect(page.locator('#release-histogram [data-chart-unknown=true]')).to_have_count(0)
                expect(page.locator('#release-histogram .chart-exclusion-note')).to_contain_text('4 / 7')
                selector.select_option('year_desc')
                assert known.all_text_contents()==['2022','2020','1999']
                capture(page.locator('#release-histogram').locator('..'),'release-year-order.png')
                for width in (820,390):
                    page.set_viewport_size({'width':width,'height':900})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
                    expect(selector).to_be_visible()
                page.set_viewport_size({'width':1440,'height':1050})
                page.locator('#view-statistics [data-hide-unknown]').uncheck()

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
                capture(page.locator('#view-cloud-connect .cloud-wizard'),'cloud-connection-setup.png')
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
                capture(page.locator('#view-cloud-connect .cloud-wizard'),'cloud-attachment-preview.png')
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

                # Gate preview only checks paths. Persist an explicit Dropbox
                # metadata scan as independent evidence before local scanning.
                page.locator('.nav[data-view="dropbox"]').click()
                select_collection(page,'#dropbox-source',fixture.source)
                dropbox_check=page.locator('#dropbox-check')
                check_cloud_progress(page,application,dropbox_check,'Dropbox',screenshot=output/'dropbox-metadata-progress.png')
                expect(page.locator('#dropbox-count')).to_contain_text('64')
                expect(dropbox_check).to_be_enabled()

                # Editing a verified mapping is a draft, never a hidden change
                # to the scope used for a remote check. Restoring the exact
                # verified fields reuses the existing metadata cache.
                verified_remote=page.locator('#dropbox-remote-root').input_value()
                verified_local=page.locator('#dropbox-local-root').input_value()
                verified_namespace=page.locator('#dropbox-namespace').input_value()
                checks_before_draft=len(dropbox_checks);calls_before_draft=provider_calls()
                page.fill('#dropbox-remote-root','/Different unverified folder')
                expect(dropbox_check).to_be_disabled()
                expect(page.locator('#dropbox-results tbody tr')).to_have_count(0)
                page.fill('#dropbox-remote-root',verified_remote)
                expect(dropbox_check).to_be_enabled()
                expect(page.locator('#dropbox-count')).to_contain_text('64')
                page.fill('#dropbox-local-root',str(fixture.google_cache))
                expect(dropbox_check).to_be_disabled()
                page.fill('#dropbox-local-root',verified_local)
                expect(dropbox_check).to_be_enabled()

                account_root=fixture.providers['dropbox'].state['account']['root_namespace_id']
                open_collection_picker(page,'#dropbox-namespace')
                page.fill('#dropbox-namespace','')
                expect(dropbox_check).to_be_enabled()
                page.fill('#dropbox-namespace',account_root)
                expect(dropbox_check).to_be_enabled()
                page.fill('#dropbox-namespace',verified_namespace)
                expect(dropbox_check).to_be_enabled()
                select_collection(page,'#dropbox-source',other_source)
                expect(dropbox_check).to_be_enabled()
                select_collection(page,'#dropbox-source',fixture.source)
                page.fill('#dropbox-search','Invented Dropbox 000');page.locator('#dropbox-find').click()
                expect(page.locator('#dropbox-results tbody tr')).to_have_count(1)
                expect(dropbox_check).to_be_enabled()
                page.fill('#dropbox-search','');page.locator('#dropbox-find').click()
                expect(page.locator('#dropbox-count')).to_contain_text('64')
                assert len(dropbox_checks)==checks_before_draft
                assert provider_calls()==calls_before_draft

                # Named team namespaces remain an explicit selection. A
                # personal account exposes one namespace, not duplicate scopes.
                namespace_choice=page.locator('#dropbox-namespace-choice')
                expect(namespace_choice.locator('option')).to_have_count(3)
                expect(namespace_choice).to_contain_text('Member home folder')
                expect(namespace_choice).to_contain_text('Team root folder')
                namespace_choice.select_option('102')
                expect(page.locator('#dropbox-remote-root')).to_have_value('')
                expect(dropbox_check).to_be_disabled()
                namespace_choice.select_option(account_root)
                page.fill('#dropbox-remote-root',verified_remote)
                expect(dropbox_check).to_be_enabled()
                fixture.providers['dropbox'].state['account']['home_namespace_id']=account_root
                page.locator('#dropbox-refresh').click()
                expect(namespace_choice.locator('option')).to_have_count(2)
                expect(namespace_choice).not_to_contain_text('Team root folder')
                fixture.providers['dropbox'].state['account']['home_namespace_id']='102'
                page.locator('#dropbox-refresh').click()
                expect(namespace_choice.locator('option')).to_have_count(3)
                expect(dropbox_check).to_be_enabled()
                assert len(dropbox_checks)==checks_before_draft
                assert provider_calls()==calls_before_draft

                # An unsupported provider filename makes the listing partial;
                # positive matches survive and the plain uncertainty note is
                # visible instead of treating unseen paths as missing.
                original_entries=deepcopy(fixture.providers['dropbox'].entries)
                unsupported=deepcopy(original_entries[0])
                unsupported.update(id='id:unsupported-name',name='Legacy\\Archive.mp3',
                    path_display='/Music/Album/Legacy\\Archive.mp3',path_lower='/music/album/legacy\\archive.mp3')
                fixture.providers['dropbox'].entries.append(unsupported)
                partial=run_ui_job(dropbox_check,'/api/dropbox/check')
                assert partial['complete'] is False and partial['scan_note']
                expect(page.locator('#dropbox-checked')).to_contain_text('Unverified')
                expect(page.locator('#dropbox-checked')).to_contain_text(partial['scan_note'])
                assert page.locator('#dropbox-checked').locator('*').count()==0
                fixture.providers['dropbox'].entries=original_entries
                complete=run_ui_job(dropbox_check,'/api/dropbox/check')
                assert complete['complete'] is True
                expect(page.locator('#dropbox-checked')).not_to_contain_text('Unverified')

                page.locator('.nav[data-view="google-drive"]').click()
                expect(page.locator('#google-drive-connection-state')).to_contain_text('Invented Google account')
                expect(page.locator('#google-drive-redirect')).to_have_value(base+'/api/google-drive/callback')
                select_collection(page,'#google-drive-source',fixture.source)
                check_cloud_progress(page,application,page.locator('#google-drive-check'),'Google Drive')
                expect(page.locator('#google-drive-count')).to_contain_text('64')
                expect(page.locator('#google-drive-results tbody tr')).to_have_count(50)
                assert all(not item.downloads for item in fixture.providers.values())

                # A local scan and a cloud scan are different evidence. Opening
                # File health only reads indexed results and must not query a
                # provider or mistake remote presence for local residency.
                calls=provider_calls()
                page.locator('.nav[data-view="file-health"]').click()
                select_collection(page,'#file-health-source',fixture.source)
                scan_local()
                expect(page.locator('#file-health-results tbody tr')).to_have_count(50)
                assert provider_calls()==calls
                health=get('file-health?source='+fixture.source+'&q=Invented+Dropbox+000')
                assert len(health['rows'])==1
                assert health['rows'][0]['status']=='unverified'
                assert any(row['provider']=='dropbox' and row['status']=='present'
                           for row in health['rows'][0]['cloud_evidence'])
                page.fill('#file-health-search','Invented Dropbox')
                page.locator('#file-health-find').click()
                expect(page.locator('#file-health-results tbody tr')).to_have_count(2)
                expect(page.locator('#file-health-results')).to_contain_text('Local access')
                expect(page.locator('#file-health-results')).to_contain_text('Cloud presence')
                expect(page.locator('#file-health-results')).to_contain_text('Reachable')
                assert provider_calls()==calls
                capture(page.locator('#view-file-health'),'cloud-file-evidence.png')
                for width in (820,390):
                    page.set_viewport_size({'width':width,'height':900})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
                page.set_viewport_size({'width':1440,'height':1050})

                # Identical track IDs in another snapshot must not inherit the
                # first collection's cloud proof.
                select_collection(page,'#file-health-source',other_source)
                page.fill('#file-health-search','');page.locator('#file-health-find').click()
                scan_local()
                other_health=get('file-health?source='+other_source)
                assert all(not row['cloud_evidence'] for row in other_health['rows'])
                assert provider_calls()==calls
                select_collection(page,'#file-health-source',fixture.source)
                page.wait_for_selector('#file-health-results tbody tr')
                page.evaluate('(source)=>BrowseState.set("cloud-setup-source",source)',other_source)
                page.locator('#view-file-health [data-view="cloud-connect"]').first.click()
                expect(page.locator('#cloud-setup-source')).to_have_value(fixture.source)
                assert provider_calls()==calls

                page.locator('.nav[data-view="google-drive"]').click()
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
                check_cloud_progress(page,application,page.locator('#google-drive-download-confirm'),'Google Drive',
                                     download=True,screenshot=output/'google-drive-byte-progress.png')
                expect(page.locator('#toast')).to_contain_text('One track downloaded',timeout=20000)
                assert fixture.providers['google_drive'].downloads==['drive-60']
                assert (fixture.google_cache/'Album'/'Drive 060.mp3').read_bytes()==fixture.providers['google_drive'].body
                expect(page.locator('[data-google-drive-download="gd-60"]')).to_have_count(0)

                page.locator('.nav[data-view="file-health"]').click()
                select_collection(page,'#file-health-source',fixture.source)
                page.fill('#file-health-search','Invented Google 060');page.locator('#file-health-find').click()
                scan_local()
                resident=get('file-health?source='+fixture.source+'&q=Invented+Google+060')
                assert len(resident['rows'])==1 and resident['rows'][0]['status']=='playable'
                assert any(row['provider']=='google_drive' and row['status']=='present'
                           for row in resident['rows'][0]['cloud_evidence'])
                expect(page.locator('#file-health-results tbody tr')).to_have_count(1)
                expect(page.locator('#file-health-results tbody tr')).to_contain_text('Yes')
                page.locator('.nav[data-view="google-drive"]').click()

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
                check_release_order()
                assert fixture.store.snapshot(statistics_sid)['tracks']==statistics_tracks
                page.locator('.nav[data-view="cloud-connect"]').click()
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
                    local_and_cloud_evidence_distinct=True,file_health_open_no_provider_requests=True,
                    cloud_evidence_source_isolation=True,file_health_source_handoff=True,
                    downloaded_file_local_recheck=True,release_year_order=True,release_year_count_order=True,
                    verified_mapping_drafts_held=True,restored_mapping_reuses_cache=True,
                    equivalent_default_namespace=True,source_search_preserve_verified_mapping=True,
                    explicit_team_namespace_choices=True,personal_namespace_not_duplicated=True,
                    partial_dropbox_check_note=True,
                    snapshot_unchanged=True,mobile_layout=True,downloaded_files=1,external_requests=external,
                    measured_cloud_metadata_and_track_progress=True,confirmed_download_byte_progress=True)
                from check_cloud_root_suggestions_ui import check_cloud_root_suggestions_ui
                report['cloud_root_suggestions_ui']=check_cloud_root_suggestions_ui(browser,base,fixture,output)
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
