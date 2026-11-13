"""Local browser integration of bounded intelligence views; synthetic data only."""
from copy import deepcopy


def check_intelligence_ui(page,base,sid,output,store):
    first=store.snapshot(sid)
    sample=deepcopy(first);sample['scope_key']='synthetic:intelligence'
    sample['capabilities'].update(playlist_order=True,history_details=True,history_order=True)
    sample['playlists']=[{'id':'a','name':'Set A','tracks':['t0','t1']},{'id':'b','name':'Set B','tracks':['t1','t0']}]
    sample['histories']=[{'id':'gig','name':'Synthetic gig','date':'2026-01-01','entries':[{'track_id':'t0','position':1},{'track_id':'t1','position':2}]}]
    before=store.save_snapshot(sample,'Intelligence before')['id']
    later=deepcopy(sample);later['tracks'][0]['genre']='Techno'
    after=store.save_snapshot(later,'Intelligence after')['id']
    page.evaluate('()=>Journeys.load()')
    page.evaluate('(id)=>Journeys.selectContext("snapshot:"+id,true)',before)
    page.locator('.nav[data-view="intelligence"]').click()
    page.wait_for_selector('#intelligence-source option[value="'+before+'"]',state='attached')
    page.select_option('#intelligence-source',before)
    page.wait_for_selector('#intelligence-playlist option[value="a"]',state='attached')
    page.select_option('#intelligence-playlist','a');page.locator('#intelligence-playlists').click()
    page.wait_for_function('document.querySelector("#intelligence-results").textContent.includes("Set B")')
    assert '100%' in page.locator('#intelligence-results').inner_text()
    page.select_option('#intelligence-history','gig');page.locator('#intelligence-session').click()
    page.wait_for_function('document.querySelectorAll("#intelligence-results tbody tr").length===2')
    assert 'Unknown' in page.locator('#intelligence-results').inner_text()
    page.select_option('#intelligence-before',before);page.select_option('#intelligence-after',after)
    page.locator('#intelligence-evolution').click()
    page.wait_for_function('document.querySelector("#intelligence-results").textContent.includes("Techno")')
    page.locator('#intelligence-save').click();page.wait_for_selector('#intelligence-download',state='visible')
    href=page.locator('#intelligence-download').get_attribute('href')
    assert page.context.request.get(base+href).ok
    page.screenshot(path=str(output/'library-intelligence.png'))
    assert store.snapshot(sid)==first
    page.evaluate('(id)=>Journeys.selectContext("snapshot:"+id,true)',sid)
    return {'playlist_overlap':True,'saved_order_progression':True,'snapshot_evolution':True,'immutable_capture':True,'saved_report':True}
