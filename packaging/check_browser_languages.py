"""CI-only real browser checks; never load a user's library or query providers."""
import argparse
import csv
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from localization import LANGUAGES,catalogues
from metadata_export import export_metadata,track
from workbench_store import Store


def main():
    from playwright.sync_api import sync_playwright
    parser=argparse.ArgumentParser();parser.add_argument('--browser',choices=['chromium','firefox','webkit'],default='chromium');parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    errors=[];requests=[];api_issues=[];report={'browser':args.browser,'synthetic':True,'languages':[],'status':'running'}
    messages=catalogues(ROOT/'static')
    with tempfile.TemporaryDirectory(prefix='workbench-language-') as tmp:
        root=Path(tmp);data=root/'data';data.mkdir();store=Store(data/'workbench-sidecar.sqlite3')
        titles=['Unknown','Artist','Tracks','Ready','Most played','Copy','Grüße · Français · Città · Español','Ελληνικά · Łódź · Český · Русский','日本語 · 🎧 · cafe\u0301','</script><img src=x onerror="window.metadataExecuted=1">',' =1+1','\ufeff@SUM(1,1)']
        tracks=[{**track({'id':'t'+str(i),'title':title,'artist':'Автор & Łódź 🎧','album':'Album {slot0} <mix>','genre':'House' if i%2 else 'Unknown','bpm':120+i,'duration':240,'play_count':i+1,'rating':4,'manual_cues':1,'auto_cues':0,'analysed':True,'comment':'Local comment Ελληνικά 🎧','color_status':'assigned','color_key':'blue' if i%2 else 'green','color_name':'Closing' if i%2 else 'Opening','color_hex':'#2478bc' if i%2 else '#27815b'}),'cues':[]} for i,title in enumerate(titles)]
        snapshot={'schema':1,'scope_key':'synthetic:browser','source_kind':'Synthetic Unicode fixture','tracks':tracks,'playlists':[],'asset_references':[],'capabilities':{'cue_positions':True,'playlist_order':False}}
        saved=store.save_snapshot(snapshot,'Synthetic Unicode fixture');sid=saved['id'];before=deepcopy(store.snapshot(sid))
        offline=export_metadata(snapshot,root/'offline','a'*32,ROOT/'static',lambda *_:None,title='Synthetic Unicode fixture')
        env={**os.environ,'LIBRARY_WORKBENCH_DATA_DIR':str(data),'LIBRARY_WORKBENCH_NO_BROWSER':'1','LIBRARY_WORKBENCH_DISABLE_MUSICBRAINZ':'1'}
        log=(args.output/'application.log').open('w',encoding='utf-8')
        process=subprocess.Popen([sys.executable,str(ROOT/'desktop_launcher.py'),'--port','0','--no-browser'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+45
            while not (data/'instance.json').exists():
                if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Synthetic app startup failed; inspect application.log')
                time.sleep(.15)
            base=json.loads((data/'instance.json').read_text())['url']
            with sync_playwright() as p:
                browser=getattr(p,args.browser).launch()
                context=browser.new_context(locale='en-US',viewport={'width':1440,'height':1000})
                page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('request',lambda request:requests.append({'url':request.url,'method':request.method}))
                def check_api_response(response):
                    if response.url.startswith(base+'/api/') and (response.status>=400 or ('application/json' not in response.headers.get('content-type','') and '/api/i18n.js' not in response.url)):
                        api_issues.append({'url':response.url,'status':response.status,'content_type':response.headers.get('content-type')})
                page.on('response',check_api_response)
                page.goto(base,wait_until='networkidle');page.wait_for_function('typeof loadDJInsights === "function"')
                for code in LANGUAGES:
                    page.select_option('#language',code)
                    page.wait_for_function('(code)=>document.documentElement.lang===code && document.documentElement.dataset.languageBusy!=="true"',arg=code)
                    page.locator('.nav[data-view="insights"]').click();page.wait_for_selector('#dj-snapshot option[value="'+sid+'"]',state='attached')
                    page.select_option('#dj-snapshot',sid);page.select_option('#dj-perspective','all');page.locator('#dj-filter-form button[type="submit"]').click();page.wait_for_selector('[data-insight-open="t0"]')
                    assert page.locator('[data-insight-open="t0"]').inner_text()=='Unknown'
                    assert page.locator('[data-insight-open="t9"]').inner_text()==titles[9]
                    assert page.locator('img[src="x"]').count()==0
                    assert page.locator('.nav[data-view="review"]').inner_text().strip().endswith(messages[code]['Duplicate review'])
                    assert page.evaluate('window.metadataExecuted') is None
                    assert page.locator('#language').input_value()==code
                    assert page.locator('#dj-perspective option[value="most"]').inner_text()==messages[code]['Most played']
                    assert page.locator('#dj-search').get_attribute('placeholder')==messages[code]['Search captured tags']
                    assert page.locator('#dj-filter-reset').inner_text()==messages[code]['Reset']
                    assert page.locator('#dj-result-title').inner_text()==messages[code]['All matching tracks']
                    assert page.locator('#search').get_attribute('placeholder')==messages[code]['Find a track or artist']
                    assert page.locator('#search').get_attribute('aria-label')==messages[code]['Search candidate pairs']
                    report['languages'].append({'code':code,'app':'passed','metadata_unchanged':True})
                    if code in ('en','de','el','ru'):page.screenshot(path=str(args.output/(code+'-insights.png')),full_page=False)
                page.locator('[data-insight-open="t0"]').click();page.wait_for_selector('#track-detail-dialog[open]')
                page.locator('#track-comments-panel summary').click();note='Unsaved comment Σ Ł Č Русский 🎧 {slot0}'
                page.fill('#track-comment-text',note);page.select_option('#language','fr');page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
                assert page.locator('#track-comment-text').input_value()==note
                assert page.locator('#track-detail-unlock').is_checked() is False
                assert page.locator('#track-detail-save').is_disabled()
                page.locator('#track-detail-dialog .close-dialog').click()
                page.select_option('#language','de');page.locator('.nav[data-view="docs"]').click()
                page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"');page.wait_for_selector('#docs-content h1')
                assert page.locator('#docs-content').inner_text()
                assert page.locator('#page-title').inner_text()==messages['de']['Documentation']
                assert not any(r['method']!='GET' for r in requests), 'Language changes submitted a mutation'
                assert all(r['url'].startswith(base) or r['url'].startswith('blob:') for r in requests), 'Unexpected external request'
                assert store.snapshot(sid)==before
                assert not api_issues,api_issues
                assert page.locator('#toast').is_hidden() or not page.locator('#toast').inner_text(), 'Unexpected caught UI error: '+page.locator('#toast').inner_text()
                from check_workspace_ui import check_workspace_ui
                report['workspace_ui']=check_workspace_ui(browser,page,base,sid,args.output,offline)
                page.goto(Path(offline['directory']).joinpath('library.html').as_uri(),wait_until='load')
                for code in LANGUAGES:
                    page.select_option('#language',code);page.wait_for_function('(code)=>document.documentElement.lang===code',arg=code)
                    page.locator('#navigation a[data-view="tracks"]').click();page.wait_for_selector('#metadata-table tbody tr')
                    assert page.locator('#metadata-table').inner_text().find(titles[9])>=0
                    assert page.locator('img[src="x"]').count()==0
                    assert messages[code]['tracks'] in page.locator('#snapshot-info').inner_text()
                    assert messages[code]['Merge and relocation decisions are not applied.'] in page.locator('#scope-note').inner_text()
                    report['languages'][list(LANGUAGES).index(code)]['offline']='passed'
                with page.expect_download() as download:
                    page.locator('#download-csv').click()
                download_path=root/'browser-export.csv';download.value.save_as(download_path)
                with download_path.open(encoding='utf-8-sig',newline='') as stream:csv_rows=list(csv.reader(stream))
                assert any(row[0]=="' =1+1" for row in csv_rows[1:])
                assert any(row[0]=="'\ufeff@SUM(1,1)" for row in csv_rows[1:])
                assert not errors,errors
                browser.close()
            report.update(status='passed',errors=errors,language_changes_submit_no_mutations=True,unexpected_network_requests=0,unsaved_comment_preserved=True,locked_fields_preserved=True)
        except Exception as error:
            report.update(status='failed',error=str(error),errors=errors,api_issues=api_issues);raise
        finally:
            process.terminate()
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            log.close()
            if (data/'application.log').exists():(args.output/'server.log').write_text((data/'application.log').read_text(encoding='utf-8'),encoding='utf-8')
            (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
