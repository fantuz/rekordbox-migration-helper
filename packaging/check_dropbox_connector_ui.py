"""Real HTTP Dropbox workflows with a synthetic server-side provider transport.

No application API responses are intercepted and no live account is contacted.
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
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


class SyntheticProvider:
    def __init__(self,folder):
        self.folder=folder;self.body=b'Invented Dropbox download fixture; not real music.'
        self.calls=[];self.downloads=[];self.fail_scan=False
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
                               'email':'synthetic@example.invalid','root_namespace_id':'101','home_namespace_id':'102'}}

    def status(self):return deepcopy(self.state)

    def rpc(self,route,payload,**_kwargs):
        from dropbox_http import DropboxError
        self.calls.append(route)
        if route=='files/list_folder':
            if self.fail_scan:raise DropboxError('Synthetic metadata interruption',tag='network')
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
                page=context.new_page();errors=[];external=[];requests=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                context.on('request',lambda request:external.append(request.url) if urlsplit(request.url).scheme not in
                    ('data','blob','file') and urlsplit(request.url).netloc!=urlsplit(base).netloc else None)
                page.on('request',lambda request:requests.append(request.url) if '/api/dropbox/download' in request.url else None)
                try:
                    page.goto(base,wait_until='networkidle');page.locator('.nav[data-view="dropbox"]').click()
                    expect(page.locator('#dropbox-connection-state')).to_contain_text('Invented browser account')
                    expect(page.locator('#dropbox-remember')).to_be_disabled()
                    expect(page.locator('#dropbox-check')).to_be_disabled()
                    page.fill('#dropbox-local-root',str(folder));page.fill('#dropbox-remote-root','/Music')
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
                    page.screenshot(path=str(output/'dropbox-checked.png'),full_page=True)
                    assert not provider.downloads and not list(album.iterdir())
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
                    page.fill('#dropbox-search','Invented 060');page.locator('#dropbox-find').click()
                    expect(page.locator('#dropbox-results tbody tr')).to_have_count(1)
                    expect(page.locator('#dropbox-results')).to_contain_text('Invented 060 <mix>')
                    assert not page.locator('#dropbox-results img').count()
                    page.locator('[data-dropbox-download="60"]').click()
                    dialog=page.locator('#dropbox-download-dialog')
                    expect(dialog).to_be_visible();expect(page.locator('#dropbox-download-cancel')).to_be_focused()
                    expect(page.locator('#dropbox-download-path')).to_have_text(str(album/'Synthetic 060.mp3'))
                    page.screenshot(path=str(output/'dropbox-confirmation.png'),full_page=True)
                    page.locator('#dropbox-download-cancel').click();expect(dialog).to_be_hidden()
                    assert not provider.downloads and not list(album.iterdir())
                    page.locator('[data-dropbox-download="60"]').click();expect(dialog).to_be_visible()
                    page.keyboard.press('Escape');expect(dialog).to_be_hidden()
                    assert not provider.downloads and not list(album.iterdir())
                    page.locator('[data-dropbox-download="60"]').click();expect(dialog).to_be_visible()
                    page.locator('#dropbox-download-confirm').click()
                    expect(page.locator('#toast')).to_contain_text('One track downloaded',timeout=20000)
                    expect(page.locator('[data-dropbox-download="60"]')).to_have_count(0)
                    assert provider.downloads==['id:invented-60']
                    assert (album/'Synthetic 060.mp3').read_bytes()==provider.body
                    assert len(list(album.iterdir()))==1
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
                    provider.state.update(connected=False,credential_cleanup_pending=True)
                    page.locator('#dropbox-refresh').click()
                    expect(page.locator('#dropbox-cleanup-state')).to_contain_text('Credential removal is pending')
                    expect(page.locator('#dropbox-disconnect')).to_be_enabled()
                    expect(page.locator('#dropbox-check')).to_be_disabled()
                    assert store.snapshot(sid)==before
                    assert not errors,errors
                    assert not external,external
                    assert sum(url.endswith('/api/dropbox/download') for url in requests)==1,requests
                    report.update(status='passed',metadata_only_check=True,full_scope_pagination=True,
                        explicit_single_download=True,cancel_and_escape_preserve_files=True,snapshot_unchanged=True,
                        remote_files=61,downloaded_files=1,mobile_layout=True,
                        failed_recheck_preserves_evidence=True,credential_cleanup_remains_actionable=True,
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
