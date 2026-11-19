"""Real HTTP Dropbox workflows with a synthetic server-side provider transport.

No application API response data is fabricated and no live account is contacted.
One real availability response is delayed unchanged to test a download race.
The synthetic provider models an already authorized account; OAuth/PKCE and
credential storage are tested separately in test_dropbox_auth.py.
"""
import argparse
from contextlib import ExitStack
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import sys
import time
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


class SyntheticProvider:
    def __init__(self,folder):
        self.folder=folder;self.body=b'Invented Dropbox download fixture; not real music.'
        self.calls=[];self.downloads=[];self.fail_scan=False;self.partial_scan=False
        digest=sha256(sha256(self.body).digest()).hexdigest()
        self.entries=[{'.tag':'file','id':'id:invented-'+str(i),'rev':'rev-'+str(i),
                       'name':f'Synthetic {i:03}.mp3','path_display':f'/Music/Album/Synthetic {i:03}.mp3',
                       'path_lower':f'/music/album/synthetic {i:03}.mp3','size':len(self.body),
                       'content_hash':digest,'server_modified':'2026-01-01T10:00:00Z'} for i in range(61)]
        self.state={'configured':True,'app_key':'syntheticpublickey','remember':False,'connected':True,
                    'state':'session','connection_id':'invented-browser-connection','vault_available':False,
                    'vault_backend':'','credential_cleanup_pending':False,
                    'scopes':['account_info.read','files.metadata.read','files.content.read'],
                    'account':{'account_id':'dbid:invented-browser','display_name':'Invented browser account',
                               'email':'synthetic@example.invalid','root_namespace_id':'101','home_namespace_id':'102',
                               'home_path':'/Invented customer'}}

    def status(self):return deepcopy(self.state)

    def rpc(self,route,payload,**_kwargs):
        from dropbox_http import DropboxError
        self.calls.append(route)
        if route=='files/list_folder':
            if self.fail_scan:raise DropboxError('Synthetic metadata interruption',tag='network')
            if self.partial_scan:return {'entries':deepcopy(self.entries[:1]),'has_more':True,'cursor':'invented-partial'}
            return {'entries':deepcopy(self.entries),'has_more':False,'cursor':'invented'}
        if route=='files/get_metadata':
            if payload['path']=='/Music':return {'.tag':'folder','id':'id:folder','name':'Music'}
            for entry in self.entries:
                if payload['path'] in (entry['id'],entry['path_display'],entry['path_lower']):return deepcopy(entry)
            raise DropboxError('Synthetic path not found',status=409,tag='not_found')
        raise AssertionError('Unexpected provider route: '+route)

    def download(self,path,rev=None,**_kwargs):
        entry=next(entry for entry in self.entries if entry['id']==path)
        assert entry['rev']==rev
        self.downloads.append(path)
        response=BytesIO(self.body);response.metadata=deepcopy(entry);response.length=len(self.body)
        return response


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--browser',choices=('chromium','firefox','webkit'),default='chromium')
    parser.add_argument('--headed',action='store_true')
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    report={'status':'running','browser':args.browser,'synthetic':True,'real_http':True,'mocked_api_responses':False,
            'synthetic_provider_transport':True,'live_dropbox_validated':False}
    from playwright.sync_api import sync_playwright,expect
    from ui_navigation import select_collection
    from werkzeug.serving import make_server
    from workbench_store import Store
    with TemporaryDirectory(prefix='dropbox-browser-') as temporary,ExitStack() as patches:
        root=Path(temporary).resolve();data=root/'work';dropbox=root/'Dropbox (Invented team)'
        folder=dropbox/'Invented customer';album=folder/'Album';album.mkdir(parents=True)
        patches.enter_context(patch.dict(os.environ,{'LIBRARY_WORKBENCH_DATA_DIR':str(data),
            'LIBRARY_WORKBENCH_NO_BROWSER':'1','LIBRARY_WORKBENCH_DISABLE_MUSICBRAINZ':'1'}))
        import app as application
        import dropbox_connector
        for name,value in [('DATA',data),('sessions',{}),('active',None),('tasks',{}),('task_controls',{})]:
            patches.enter_context(patch.object(application,name,value))
        provider=SyntheticProvider(folder);connection=dropbox_connector.connection(application)
        for name in ('status','rpc','download'):patches.enter_context(patch.object(connection,name,getattr(provider,name)))
        patches.enter_context(patch('dropbox_files.detected_roots',return_value=[
            {'root':str(dropbox),'kind':'dropbox','provider_verified':True,'availability':'local'}]))
        store=Store(data/'workbench-sidecar.sqlite3')
        tracks=[{'id':str(i),'title':f'Invented {i:03} <mix>','artist':'Synthetic artist',
                 'current_path':str(album/f'Synthetic {i:03}.mp3')} for i in range(61)]
        tracks[60]['size']=len(provider.body)
        tracks[59]['size']=len(provider.body)+1
        tracks.extend([{'id':'missing','title':'Absent mapped path','current_path':str(album/'Absent.mp3')},
                       {'id':'outside','title':'Unmapped path','current_path':str(root/'Elsewhere'/'Other.mp3')}])
        sid=store.save_snapshot({'scope_key':'synthetic:dropbox-browser','tracks':tracks,'playlists':[]},
                                'Invented Dropbox browser collection')['id']
        before=deepcopy(store.snapshot(sid))
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        server=make_server('127.0.0.1',0,application.app,threaded=True)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            with sync_playwright() as playwright:
                browser=getattr(playwright,args.browser).launch(headless=not args.headed)
                context=browser.new_context(locale='en-US',viewport={'width':1440,'height':1050})
                context.add_init_script("if(location.protocol==='http:')localStorage.setItem('library-workbench.language.v1','en')")
                context.tracing.start(screenshots=True,snapshots=True,sources=True)
                page=context.new_page();errors=[];external=[];requests=[];availability=[];playback_opens=[];opened_paths=[]
                def open_default(path):
                    # Replace only OS dispatch; Flask/jobs and file validation
                    # stay real, including bytes already published before open.
                    assert path.is_file() and path.read_bytes()==provider.body
                    opened_paths.append(str(path))
                patches.enter_context(patch('track_playback.open_audio',side_effect=open_default))
                page.on('pageerror',lambda error:errors.append(str(error)))
                context.on('request',lambda request:external.append(request.url) if urlsplit(request.url).scheme not in
                    ('data','blob','file') and urlsplit(request.url).netloc!=urlsplit(base).netloc else None)
                page.on('request',lambda request:requests.append(request.url) if '/api/dropbox/download' in request.url else None)
                page.on('request',lambda request:availability.append(request.post_data_json) if
                    urlsplit(request.url).path=='/api/playback/availability' else None)
                page.on('request',lambda request:playback_opens.append(request.url) if
                    urlsplit(request.url).path=='/api/playback/open' else None)
                try:
                    page.goto(base,wait_until='networkidle');page.locator('.nav[data-view="dropbox"]').click()
                    expect(page.locator('#dropbox-connection-state')).to_contain_text('Invented browser account')
                    expect(page.locator('#dropbox-remember')).to_be_disabled()
                    expect(page.locator('#dropbox-check')).to_be_disabled()
                    page.fill('#dropbox-local-root',str(folder))
                    page.select_option('#dropbox-namespace-choice','101')
                    hint=page.locator('#dropbox-namespace-context-mapping-hint')
                    expect(hint).to_be_visible()
                    expect(hint).to_contain_text('This local folder matches the member home folder')
                    calls_before_hint=len(provider.calls)
                    hint.locator('button').focus();page.keyboard.press('Enter')
                    expect(page.locator('#dropbox-namespace')).to_have_value('102')
                    expect(page.locator('#dropbox-remote-root')).to_have_value('')
                    expect(hint).to_be_hidden()
                    assert len(provider.calls)==calls_before_hint and not provider.downloads
                    page.select_option('#dropbox-namespace-choice','101')
                    page.fill('#dropbox-remote-root','/Music')
                    with page.expect_response(lambda response:response.url.endswith('/api/dropbox/mapping')) as saved:
                        page.locator('#dropbox-mapping-save').click()
                    assert saved.value.ok,saved.value.text()
                    page.locator('#view-dropbox .dropbox-layout').screenshot(path=str(output/'dropbox-setup.png'))
                    page.select_option('#dropbox-source','snapshot:'+sid)
                    expect(page.locator('#dropbox-check')).to_be_enabled()
                    assert not provider.downloads
                    page.locator('#dropbox-check').click()
                    expect(page.locator('#dropbox-count')).to_contain_text('63')
                    expect(page.locator('#dropbox-results tbody tr')).to_have_count(50)
                    expect(page.locator('#dropbox-results .dropbox-evidence-present').first).to_have_text('Reachable')
                    page.screenshot(path=str(output/'dropbox-checked.png'),full_page=True)
                    assert not provider.downloads and not list(album.iterdir())
                    page.fill('#dropbox-search','Unmapped path');page.locator('#dropbox-find').click()
                    expect(page.locator('#dropbox-results .dropbox-evidence-unmapped')).to_have_text('Unmapped')
                    details=page.locator('#dropbox-results .dropbox-mapping-details')
                    expect(details).to_be_visible();calls_before_details=len(provider.calls)
                    details.locator('summary').click()
                    expect(details).to_contain_text(str(root/'Elsewhere'/'Other.mp3'))
                    expect(details).to_contain_text(str(folder))
                    expect(details).to_contain_text('/Music')
                    assert len(provider.calls)==calls_before_details and not provider.downloads
                    page.fill('#dropbox-search','');page.locator('#dropbox-find').click()
                    # A bounded listing must explain why unseen rows have no
                    # cloud size, without relabelling them as missing files.
                    import dropbox_files
                    provider.partial_scan=True
                    with patch.object(dropbox_files,'MAX_PAGES',1):
                        page.fill('#dropbox-search','Invented 060');page.locator('#dropbox-find').click()
                        page.locator('#dropbox-check').click()
                        expect(page.locator('#dropbox-checked')).to_contain_text('Dropbox metadata listing is incomplete.')
                        expect(page.locator('#dropbox-checked')).to_contain_text('Listed 1 files in 1 metadata pages.')
                        expect(page.locator('#dropbox-results .dropbox-evidence-unverified')).to_have_text('Unverified')
                        expect(page.locator('#dropbox-results')).to_contain_text('This file was not covered by the incomplete Dropbox listing.')
                        expect(page.locator('#dropbox-results')).to_contain_text('Remote metadata is not confirmed yet; download is unavailable.')
                        expect(page.locator('#dropbox-results [data-dropbox-download]')).to_have_count(0)
                        assert not provider.downloads and not list(album.iterdir())
                    provider.partial_scan=False
                    page.fill('#dropbox-search','');page.locator('#dropbox-find').click()
                    page.locator('#dropbox-check').click()
                    expect(page.locator('#dropbox-checked')).not_to_contain_text('Dropbox metadata listing is incomplete.')
                    expect(page.locator('#dropbox-results .dropbox-evidence-present').first).to_have_text('Reachable')
                    # Reachable is remote path evidence while the same row's
                    # local access remains unverified. Metadata never hydrates.
                    calls_before_health=len(provider.calls)
                    page.locator('.nav[data-view="file-health"]').click()
                    select_collection(page,'#file-health-source','snapshot:'+sid)
                    page.fill('#file-health-search','Invented 060');page.locator('#file-health-find').click()
                    page.locator('#file-health-scan').click()
                    expect(page.locator('#file-health-state')).to_contain_text('complete',timeout=20000)
                    expect(page.locator('#file-health-results tbody tr')).to_have_count(1)
                    expect(page.locator('#file-health-results [data-local-access="unverified"]')).to_have_text('Unknown')
                    expect(page.locator('#file-health-results [data-cloud-presence]')).to_contain_text('Reachable')
                    expect(page.locator('#file-health-results [data-cloud-presence]')).to_contain_text('Size matches')
                    expect(page.locator('#file-health-results [data-play-track="60"]')).to_be_enabled()
                    expect(page.locator('#file-health-results [data-play-track="60"]')).to_have_attribute('data-available','false')
                    expect(page.locator('#file-health-results [data-play-track="60"]')).to_have_attribute('title','Download and play this track')
                    assert len(provider.calls)==calls_before_health and not provider.downloads
                    page.locator('.nav[data-view="dropbox"]').click()
                    evidence_url=base+'/api/dropbox/files?source=snapshot:'+sid
                    checked_at=context.request.get(evidence_url).json()['checked_at']
                    provider.fail_scan=True;page.locator('#dropbox-check').click()
                    expect(page.locator('#toast')).to_contain_text('Synthetic metadata interruption')
                    assert context.request.get(evidence_url).json()['checked_at']==checked_at
                    provider.fail_scan=False
                    page.select_option('#dropbox-status','present')
                    expect(page.locator('#dropbox-count')).to_contain_text('61')
                    page.locator('#dropbox-next').click()
                    expect(page.locator('#dropbox-count')).to_contain_text('51–61')
                    expect(page.locator('#dropbox-results tbody tr')).to_have_count(11)
                    for identity,comparison,label in [('58','unknown','Size unknown'),('59','mismatch','Size differs'),('60','match','Size matches')]:
                        page.fill('#dropbox-search','Invented 0'+identity);page.locator('#dropbox-find').click()
                        expect(page.locator('#dropbox-results tbody tr')).to_have_count(1)
                        expect(page.locator('#dropbox-results [data-size-comparison]')).to_have_attribute('data-size-comparison',comparison)
                        expect(page.locator('#dropbox-results')).to_contain_text(label)
                        expect(page.locator('#dropbox-results')).to_contain_text('Library size')
                        expect(page.locator('#dropbox-results')).to_contain_text('Cloud size')
                        if comparison=='mismatch':
                            page.locator('[data-dropbox-download="59"]').click()
                            expect(page.locator('#dropbox-download-dialog')).to_be_visible()
                            expect(page.locator('#dropbox-download-comparison')).to_contain_text('Size differs')
                            page.locator('#dropbox-download-cancel').click()
                            assert not provider.downloads and not list(album.iterdir())
                    page.fill('#dropbox-search','Invented 060');page.locator('#dropbox-find').click()
                    expect(page.locator('#dropbox-results tbody tr')).to_have_count(1)
                    expect(page.locator('#dropbox-results')).to_contain_text('Invented 060 <mix>')
                    play=page.locator('#dropbox-results [data-play-track="60"]')
                    expect(play).to_have_attribute('data-available','false')
                    expect(play).to_be_enabled()
                    expect(play).to_have_attribute('title','Download and play this track')
                    assert not page.locator('#dropbox-results img').count()
                    page.locator('[data-dropbox-download="60"]').click()
                    dialog=page.locator('#dropbox-download-dialog')
                    expect(dialog).to_be_visible();expect(page.locator('#dropbox-download-cancel')).to_be_focused()
                    expect(page.locator('#dropbox-download-path')).to_have_text(str(album/'Synthetic 060.mp3'))
                    expect(page.locator('#dropbox-download-comparison')).to_contain_text('Size matches')
                    page.screenshot(path=str(output/'dropbox-confirmation.png'),full_page=True)
                    page.locator('#dropbox-download-cancel').click();expect(dialog).to_be_hidden()
                    assert not provider.downloads and not list(album.iterdir())
                    page.locator('[data-dropbox-download="60"]').click();expect(dialog).to_be_visible()
                    page.keyboard.press('Escape');expect(dialog).to_be_hidden()
                    assert not provider.downloads and not list(album.iterdir())
                    page.locator('[data-dropbox-download="60"]').click();expect(dialog).to_be_visible()
                    # A completed transfer refreshes this track even when a
                    # focus refresh and its cached negative result are recent.
                    # Hold a real negative response until after download. An
                    # existing button in another live renderer can survive the
                    # Dropbox table rerender, so retain a duplicate here.
                    held=[]
                    def delay_availability(route):
                        if not held and route.request.post_data_json.get('track_ids')==['60']:
                            response=route.fetch()
                            assert response.json()['tracks']['60'] is False
                            held.append((route,response))
                        else:route.continue_()
                    page.route('**/api/playback/availability',delay_availability)
                    page.evaluate('''source=>{
                      const retained=document.createElement('div');retained.id='retained-playback-renderer';
                      retained.style.cssText='position:fixed;bottom:12px;right:12px;z-index:100';
                      retained.innerHTML=TrackPlayback.button(source.slice(9),'60');
                      document.querySelector('#view-dropbox').append(retained);
                      TrackPlayback.recheck({force:true,source,track_id:'60'});
                    }''','snapshot:'+sid)
                    deadline=time.monotonic()+10
                    while not held and time.monotonic()<deadline:page.wait_for_timeout(20)
                    assert held,'Negative availability request was not held'
                    availability_before=len(availability)
                    page.locator('#dropbox-download-confirm').click()
                    expect(page.locator('#toast')).to_contain_text('One track downloaded',timeout=20000)
                    held[0][0].fulfill(response=held[0][1])
                    expect(page.locator('#retained-playback-renderer [data-play-track="60"]')).to_be_enabled()
                    expect(page.locator('#retained-playback-renderer [data-play-track="60"]')).to_have_attribute('data-available','true')
                    expect(page.locator('[data-dropbox-download="60"]')).to_have_count(0)
                    expect(page.locator('#dropbox-results [data-play-track="60"]')).to_be_enabled()
                    expect(page.locator('#dropbox-results [data-play-track="60"]')).to_have_attribute('data-available','true')
                    assert any(value.get('refresh') is True and value.get('track_ids')==['60']
                               for value in availability[availability_before:]),availability
                    page.locator('#retained-playback-renderer').evaluate('element=>element.remove()')
                    page.unroute('**/api/playback/availability',delay_availability)
                    assert provider.downloads==['id:invented-60']
                    assert not opened_paths,'Download-only must not open a media player'
                    assert (album/'Synthetic 060.mp3').read_bytes()==provider.body
                    assert len(list(album.iterdir()))==1
                    # The existing local scan is refreshed by the completed
                    # one-file transfer; returning to File health needs no scan.
                    page.locator('.nav[data-view="file-health"]').click()
                    select_collection(page,'#file-health-source','snapshot:'+sid)
                    page.fill('#file-health-search','Invented 060');page.locator('#file-health-find').click()
                    expect(page.locator('#file-health-results tbody tr')).to_have_count(1)
                    expect(page.locator('#file-health-results [data-local-access="playable"]')).to_have_text('Yes')
                    expect(page.locator('#file-health-results [data-cloud-presence]')).to_contain_text('Reachable')
                    expect(page.locator('#file-health-results [data-cloud-presence]')).to_contain_text('Size matches')
                    expect(page.locator('#file-health-results [data-play-track="60"]')).to_be_enabled()
                    page.screenshot(path=str(output/'dropbox-file-health.png'),full_page=True)

                    # The visible scan still records local access after an
                    # external eviction. Refreshing attributes alone must retain
                    # reachable Play, without a scan, remote query or hydration.
                    resident_path=album/'Synthetic 060.mp3'
                    resident_path.unlink();calls_before_eviction=len(provider.calls)
                    page.evaluate('source=>TrackPlayback.recheck({force:true,source,track_id:"60"})','snapshot:'+sid)
                    resident_play=page.locator('#file-health-results [data-play-track="60"]')
                    expect(resident_play).to_have_attribute('data-available','false')
                    expect(resident_play).to_be_enabled()
                    expect(resident_play).to_have_attribute('title','Download and play this track')
                    stale_scan=context.request.get(base+'/api/file-health?source=snapshot:'+sid+'&q=Invented+060').json()
                    assert stale_scan['rows'][0]['status']=='playable'
                    assert not resident_path.exists() and not opened_paths
                    assert provider.downloads==['id:invented-60'] and len(provider.calls)==calls_before_eviction
                    # Restore only the invented fixture so later assertions
                    # retain their expected file count; the app did no transfer.
                    resident_path.write_bytes(provider.body)
                    page.evaluate('source=>TrackPlayback.recheck({force:true,source,track_id:"60"})','snapshot:'+sid)
                    expect(resident_play).to_have_attribute('data-available','true')

                    # Reachable Play keeps the user on File health and requests
                    # consent for exactly one download followed by OS dispatch.
                    page.fill('#file-health-search','Invented 059');page.locator('#file-health-find').click()
                    expect(page.locator('#file-health-results tbody tr')).to_have_count(1)
                    remote_play=page.locator('#file-health-results [data-play-track="59"]')
                    expect(remote_play).to_be_enabled()
                    expect(remote_play).to_have_attribute('data-available','false')
                    for close in ('cancel','escape'):
                        remote_play.click();expect(dialog).to_be_visible()
                        expect(page.locator('#dropbox-download-heading')).to_have_text('Download and play only this track?')
                        expect(page.locator('#dropbox-download-confirm')).to_have_text('Download and play this track')
                        expect(page.locator('#dropbox-download-play-note')).to_be_visible()
                        expect(page.locator('#dropbox-download-comparison')).to_contain_text('Size differs')
                        expect(page.locator('#dropbox-download-path')).to_have_text(str(album/'Synthetic 059.mp3'))
                        expect(page.locator('#dropbox-download-cancel')).to_be_focused()
                        assert page.locator('#view-file-health').is_visible()
                        if close=='cancel':page.locator('#dropbox-download-cancel').click()
                        else:page.keyboard.press('Escape')
                        expect(dialog).to_be_hidden()
                        assert provider.downloads==['id:invented-60'] and not opened_paths
                    remote_play.click();expect(dialog).to_be_visible()
                    page.screenshot(path=str(output/'dropbox-play-confirmation.png'),full_page=True)
                    page.locator('#dropbox-download-confirm').click()
                    expect(page.locator('#toast')).to_contain_text('Opened in your default media player',timeout=20000)
                    assert provider.downloads==['id:invented-60','id:invented-59']
                    assert opened_paths==[str(album/'Synthetic 059.mp3')]
                    assert len(list(album.iterdir()))==2
                    expect(page.locator('#file-health-results [data-local-access="playable"]')).to_have_text('Yes')
                    expect(page.locator('#file-health-results [data-play-track="59"]')).to_have_attribute('data-available','true')
                    assert page.locator('#view-file-health').is_visible()
                    page.locator('.nav[data-view="dropbox"]').click()
                    page.fill('#dropbox-search','');page.select_option('#dropbox-status','not_found')
                    page.locator('#dropbox-find').click()
                    expect(page.locator('#dropbox-results tbody tr')).to_have_count(1)
                    expect(page.locator('#dropbox-results')).to_contain_text('Absent mapped path')
                    expect(page.locator('#dropbox-results [data-dropbox-download]')).to_have_count(0)
                    page.select_option('#dropbox-status','all')
                    expect(page.locator('#dropbox-results tbody tr')).to_have_count(50)
                    expect(page.locator('#toast')).to_be_hidden(timeout=12000)
                    page.screenshot(path=str(output/'dropbox-connector.png'),full_page=True)
                    for width in (820,390):
                        page.set_viewport_size({'width':width,'height':900})
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
                        page.locator('#dropbox-check').scroll_into_view_if_needed()
                        expect(page.locator('#dropbox-check')).to_be_in_viewport()
                    # The shared display choice filters saved evidence only;
                    # it must not perform a fresh provider check or a transfer.
                    page.set_viewport_size({'width':1440,'height':1000})
                    sidecar=deepcopy(provider.entries[0]);sidecar.update(id='id:invented-sidecar',name='._Metadata.mp3',
                        path_lower='/music/album/._metadata.mp3',path_display='/Music/Album/._Metadata.mp3')
                    provider.entries.append(sidecar)
                    sidecar_tracks=[deepcopy(tracks[0]),{'id':'sidecar','title':'Invented metadata sidecar',
                        'current_path':str(album/'._Metadata.mp3')}]
                    sidecar_sid=store.save_snapshot({'scope_key':'synthetic:dropbox-sidecar-view',
                        'tracks':sidecar_tracks,'playlists':[]},'Invented Dropbox sidecar view')['id']
                    sidecar_before=deepcopy(store.snapshot(sidecar_sid))
                    page.reload(wait_until='networkidle')
                    page.select_option('#dropbox-source','snapshot:'+sidecar_sid)
                    page.locator('#dropbox-check').click()
                    expect(page.locator('#dropbox-results tbody tr')).to_have_count(2)
                    sidecar_toggle=page.locator('#dropbox-display-preferences [data-hide-metadata-sidecars]')
                    expect(sidecar_toggle).not_to_be_checked();calls_before_filter=len(provider.calls)
                    sidecar_toggle.check()
                    expect(page.locator('#dropbox-results tbody tr')).to_have_count(1)
                    expect(page.locator('#dropbox-checked')).to_contain_text('1 metadata sidecars hidden')
                    assert len(provider.calls)==calls_before_filter
                    assert provider.downloads==['id:invented-60','id:invented-59']
                    page.screenshot(path=str(output/'metadata-sidecar-dropbox.png'),full_page=True)
                    sidecar_toggle.uncheck();expect(page.locator('#dropbox-results tbody tr')).to_have_count(2)
                    assert store.snapshot(sidecar_sid)==sidecar_before
                    provider.state.update(connected=False,credential_cleanup_pending=True)
                    page.locator('#dropbox-refresh').click()
                    expect(page.locator('#dropbox-cleanup-state')).to_contain_text('Credential removal is pending')
                    expect(page.locator('#dropbox-disconnect')).to_be_enabled()
                    expect(page.locator('#dropbox-check')).to_be_disabled()
                    assert store.snapshot(sid)==before
                    assert not errors,errors
                    assert not external,external
                    assert not playback_opens,playback_opens
                    assert sum(url.endswith('/api/dropbox/download') for url in requests)==2,requests
                    report.update(status='passed',metadata_only_check=True,full_scope_pagination=True,
                        explicit_single_download=True,cancel_and_escape_preserve_files=True,snapshot_unchanged=True,
                        remote_files=len(provider.entries),downloaded_files=2,mobile_layout=True,metadata_sidecar_display_filter=True,
                        failed_recheck_preserves_evidence=True,credential_cleanup_remains_actionable=True,
                        reachable_separate_from_local_access=True,captured_size_match_mismatch_unknown=True,
                        size_warning_before_download=True,download_enables_play_without_autoplay=True,
                        member_home_namespace_hint=True,incomplete_listing_explained=True,unmapped_path_details=True,
                        delayed_availability_response_unchanged=True,stale_negative_cannot_override_download=True,
                        reachable_play_same_page=True,play_cancel_and_escape_no_transfer=True,
                        download_only_never_opens=True,approved_play_opens_only_published_target=True,
                        evicted_resident_keeps_reachable_play=True,eviction_check_no_provider_request=True,
                        synthetic_eviction_fixture_restored=True,
                        external_requests=external)
                except Exception:
                    page.screenshot(path=str(output/'dropbox-failure.png'),full_page=True);raise
                finally:
                    context.tracing.stop(path=str(output/'dropbox-trace.zip'));context.close();browser.close()
        except Exception as error:
            report.update(status='failed',error=str(error));raise
        finally:
            server.shutdown();thread.join(timeout=5);server.server_close()
            (output/'dropbox-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
