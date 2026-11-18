"""Actual provider-config discovery through HTTP; no account or provider requests."""
from hashlib import sha256
import json
from pathlib import Path

from localization import LANGUAGES,catalogues


def cloud_fixture(root):
    root=Path(root)
    appdata=root/'cloud appdata'
    provider=root/'Example DJ team Dropbox'
    library=provider/'Example Customer 日本'/'rekordbox'
    library.mkdir(parents=True)
    (library/'master.db').write_bytes(b'OPAQUE SYNTHETIC DATABASE: name discovery must not read SQL')
    config=appdata/'Dropbox/info.json';config.parent.mkdir(parents=True)
    config.write_text(json.dumps({'business':{'path':str(provider),'email':'never-return@example.invalid',
                                            'secret':'synthetic-provider-private-value'}}))
    return {'appdata':appdata,'root':provider,'library':library,'config':config}


def check_cloud_locations_ui(browser,base,output,fixture):
    context=browser.new_context(locale='en-US',viewport={'width':1440,'height':1000})
    context.add_init_script("localStorage.setItem('library-workbench.language.v1','en')")
    context.tracing.start(screenshots=True,snapshots=True,sources=True)
    page=context.new_page();errors=[];mutations=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('request',lambda request:mutations.append(request.url) if request.method in ('POST','PUT','DELETE','PATCH') else None)
    before={str(path):sha256(path.read_bytes()).hexdigest() for path in (fixture['config'],fixture['library']/'master.db')}
    try:
        page.goto(base,wait_until='networkidle')
        page.locator('.nav[data-view="analyzer"]').click()
        page.locator('#cloud-locations summary').click()
        page.locator('#cloud-locations-refresh').click()
        page.wait_for_selector('[data-cloud-library]')
        assert str(fixture['root']) in page.locator('#cloud-location-results').inner_text()
        assert str(fixture['library']) in page.locator('#cloud-location-results').inner_text()
        assert 'Provider configuration' in page.locator('#cloud-location-results').inner_text()
        assert 'No previous location was recorded' in page.locator('#cloud-location-results').inner_text()
        page.locator('[data-cloud-library]').click()
        assert page.locator('#analyzer-path').input_value()==str(fixture['library'])
        assert mutations==[],mutations
        assert page.locator('#progress').is_hidden()
        page.locator('[data-cloud-root]').click()
        assert page.locator('#source-discovery-roots').input_value()==str(fixture['root'])
        assert mutations==[]
        response=context.request.get(base+'/api/cloud-locations/report')
        assert response.ok
        report=response.json()
        assert report['source_writes'] is False and report['database_queries'] is False and report['cloud_login'] is False
        assert report['relocations']==[]
        assert 'never-return@example.invalid' not in response.text()
        assert 'synthetic-provider-private-value' not in response.text()
        assert 'attachment;' in response.headers['content-disposition']
        messages=catalogues(Path(__file__).resolve().parents[1]/'static')
        for code in LANGUAGES:
            page.select_option('#language',code)
            page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
            assert page.locator('#cloud-locations summary').inner_text()==messages[code]['Cloud library locations']
            assert page.locator('#analyzer-path').input_value()==str(fixture['library'])
        page.select_option('#language','en')
        page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
        page.locator('#cloud-locations').scroll_into_view_if_needed()
        page.screenshot(path=str(output/'cloud-library-locations.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':900})
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.screenshot(path=str(output/'cloud-library-locations-narrow.png'),full_page=True)
        assert before=={str(path):sha256(path.read_bytes()).hexdigest() for path in (fixture['config'],fixture['library']/'master.db')}
        assert not errors,errors
        return {'real_http':True,'mocked_api_responses':False,'team_customer_layout':True,
                'no_automatic_analysis':True,'no_unproved_relocation':True,'config_privacy':True,
                'report_download':True,'languages':len(LANGUAGES),'narrow_layout':True,'source_preserved':True}
    except Exception:
        page.screenshot(path=str(output/'cloud-locations-failure.png'),full_page=True)
        raise
    finally:
        context.tracing.stop(path=str(output/'cloud-locations-trace.zip'))
        context.close()
