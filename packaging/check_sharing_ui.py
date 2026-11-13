"""CI-only sharing journeys with synthetic metadata; no providers or personal files."""
import json
from pathlib import Path
import re


def embedded_data(document):
    match=re.search(r'window\.METADATA_SNAPSHOT=(.*?);</script>',document,re.S)
    assert match,'Standalone HTML has no metadata payload'
    return json.loads(match.group(1))


def check_sharing_ui(page,base,sid,output):
    page.select_option('#language','en')
    page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
    page.locator('.nav[data-view="quick"]').click()
    page.wait_for_selector('#share-preset')
    page.select_option('#quick-source','lab:'+sid)
    assert page.locator('#share-preset').input_value()=='public'
    page.wait_for_function('!document.querySelector("#quick-generate").disabled')
    assert page.locator('#quick-paths').is_disabled()

    def generate():
        before=page.locator('#quick-history .export-record').count()
        page.locator('#quick-generate').click()
        page.wait_for_function('(before)=>document.querySelectorAll("#quick-history .export-record").length>before',arg=before)
        record=page.locator('#quick-history .export-record').first
        href=record.locator('a[href$="/report"]').get_attribute('href')
        details=page.context.request.get(base+href)
        assert details.ok,details.status
        info=details.json()
        html_file=next(f for f in info['files'] if f['kind']=='html')
        response=page.context.request.get(base+html_file['download'])
        assert response.ok,response.status
        return info,embedded_data(response.text()),response.text()

    public,aggregate,html=generate()
    assert aggregate['preset']=='public' and aggregate['rows']==[] and aggregate['columns']==[]
    assert aggregate['track_count']==12 and aggregate['aggregates']['tracks']==12
    assert aggregate['data_state']=='captured' and public['staged_changes_applied'] is False
    assert not aggregate['includes_paths']
    assert all(field not in aggregate['aggregates'] for field in ('playlists','play_count','date_added','last_played','id','title'))
    assert 'Local comment Ελληνικά' not in html and 'window.metadataExecuted=1' not in html
    public_path=Path(output)/'synthetic-public-summary.html';public_path.write_text(html,encoding='utf-8')
    offline=page.context.new_page();errors=[];offline.on('pageerror',lambda error:errors.append(str(error)))
    try:
        offline.goto(public_path.as_uri(),wait_until='load')
        assert offline.locator('#navigation [data-view="tracks"]').count()==0
        assert offline.locator('.filters').is_hidden()
        assert offline.locator('#metadata-table tbody tr').count()>=1
        assert offline.locator('#metrics').inner_text().find('12')>=0
        offline.screenshot(path=str(Path(output)/'public-summary.png'))
        assert not errors,errors
    finally:offline.close()

    page.select_option('#share-preset','selected')
    page.wait_for_function('document.querySelector("#quick-generate").disabled')
    page.fill('#share-track-ids','t0, t9')
    page.wait_for_function('document.querySelector("#share-disclosure strong")?.textContent.startsWith("2 tracks") && !document.querySelector("#quick-generate").disabled')
    _,selected,_=generate()
    assert selected['track_count']==2 and len(selected['rows'])==2
    assert 'id' not in selected['columns'] and 'playlists' not in selected['columns']
    assert 'play_count' not in selected['columns'] and 'last_played' not in selected['columns']
    assert selected['rows'][0][selected['columns'].index('title')]=='Unknown'

    page.select_option('#share-preset','private')
    page.locator('#share-field-options summary').click()
    for checkbox in page.locator('[data-share-field]').all():checkbox.set_checked(checkbox.get_attribute('data-share-field')=='genre')
    page.locator('#share-working').check()
    page.wait_for_function('document.querySelector("#share-disclosure").textContent.includes("Metadata state: Working metadata") && !document.querySelector("#quick-generate").disabled')
    _,private,_=generate()
    assert private['columns']==['genre'] and private['data_state']=='working'
    assert private['rows']==[['Unknown'] if i%2==0 else ['House'] for i in range(12)]
    assert not private['staged_changes_applied']
    page.screenshot(path=str(Path(output)/'sharing-disclosure.png'))

    xml=b'<DJ_PLAYLISTS><PRODUCT Version="7.0"/><COLLECTION Entries="1"><TRACK TrackID="44" Name="XML only private title" Artist="XML artist" Genre="House" AverageBpm="126" TotalTime="300" Location="file://localhost/C:/private-xml/track.mp3"/></COLLECTION><PLAYLISTS><NODE Name="ROOT" Type="0"/></PLAYLISTS></DJ_PLAYLISTS>'
    page.locator('#quick-xml-input').set_input_files({'name':'synthetic-collection.xml','mimeType':'application/xml','buffer':xml})
    page.locator('#quick-xml-form button[type="submit"]').click()
    page.wait_for_function('/^[a-f0-9]{32}$/.test(document.querySelector("#quick-source").value)')
    page.select_option('#share-preset','public');page.locator('#share-working').uncheck()
    page.wait_for_function('document.querySelector("#share-disclosure strong")?.textContent.startsWith("1 tracks") && !document.querySelector("#quick-generate").disabled')
    _,from_xml,xml_html=generate()
    assert from_xml['aggregates']['tracks']==1 and from_xml['rows']==[]
    assert from_xml['aggregates']['categories']['artists'][0]['label']=='XML artist'
    assert 'XML only private title' not in xml_html and 'private-xml' not in xml_html
    # Leave the original shared snapshot selected for the remaining CI journeys.
    page.evaluate('(sid)=>Journeys.selectContext("snapshot:"+sid,true)',sid)
    return {'public_aggregate_only':True,'selected_track_list':True,'private_field_omission':True,
            'working_context_preserved':True,'empty_selection_disabled':True,'xml_only_input':True,
            'public_offline_render':True,'data':'synthetic fixture only'}
