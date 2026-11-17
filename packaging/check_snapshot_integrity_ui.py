"""Real-server comparison, filters and saved evidence for preparation workflows."""
from copy import deepcopy
import json
import re


def check_snapshot_integrity_ui(browser,base,store,output):
    from playwright.sync_api import expect
    from metadata_export import track
    tracks=[{**track({'id':key,'title':'Workflow '+key+' 日本','artist':'Synthetic artist',
                      'bpm':87,'tonality':'Am','play_count':0,'analysed':False}),
             'uuid':'uuid-'+key,'cues':[]} for key in ('one','two')]
    tracks[0]['cues']=[{'kind':4,'in_ms':1000,'out_ms':2000,'active_loop':0,'label':'Loop','color':3}]
    lists=[{'id':key,'uuid':'folder-'+key,'name':key,'parent':'root','folder':True,
            'smart':False,'tracks':[]} for key in ('a','b')]
    lists += [{'id':'p','uuid':'playlist-p','name':'Set <mix> 日本','parent':'a','folder':False,
               'smart':False,'tracks':['one','two','one']},
              {'id':'s','uuid':'playlist-s','name':'Rule conversion','parent':'root','folder':False,
               'smart':False,'tracks':['one']}]
    source={'schema':1,'scope_key':'synthetic:workflow-comparison','source_kind':'Synthetic workflow fixture',
            'tracks':tracks,'playlists':lists,'capabilities':{'cue_positions':True,'playlist_order':True}}
    changed=deepcopy(source)
    changed['tracks'][0].update(bpm=174,tonality='C',play_count=2,analysed=True)
    changed['tracks'][0]['cues'][0]['active_loop']=1
    changed['playlists'][0]['id']='new-a';changed['playlists'][1]['id']='new-b'
    changed['playlists'][2].update(parent='new-b',tracks=['two','one','one'])
    changed['playlists'][3]['smart']=True
    before=store.save_snapshot(source,'Workflow before 日本')['id']
    after=store.save_snapshot(changed,'Workflow after 日本')['id']
    originals={identity:store.snapshot(identity) for identity in (before,after)}
    context=browser.new_context(locale='en-US',viewport={'width':1440,'height':1050})
    context.add_init_script("if(location.protocol==='http:')localStorage.setItem('library-workbench.language.v1','en')")
    context.tracing.start(screenshots=True,snapshots=True,sources=True)
    page=context.new_page();errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        page.goto(base,wait_until='networkidle');page.locator('.nav[data-view="lab"]').click()
        page.locator('[data-lab-tab="compare"]').click()
        page.select_option('#lab-before',before);page.select_option('#lab-after',after)
        page.fill('#lab-tolerance','2')
        previous=page.locator('#lab-report-select').input_value()
        page.locator('#lab-compare-form button[type="submit"]').click()
        page.wait_for_function('(old)=>document.querySelector("#lab-report-select").value && document.querySelector("#lab-report-select").value!==old',arg=previous)
        saved=page.locator('#lab-report-select').input_value()
        expect(page.locator('#lab-report-download')).to_have_attribute('href',re.compile('/'+saved+'/download'))
        response=context.request.get(base+page.locator('#lab-report-download').get_attribute('href'))
        assert response.ok,response.status
        result=response.json();summary=result['summary']
        assert summary['matched_tracks']==2 and summary['metadata_changed']==4,summary
        assert summary['cue_active_loop']==1 and summary['playlists_changed']==2,summary
        assert summary['cue_tolerance_ms']==2
        loop=next(r for r in result['rows'] if r['section']=='cue_active_loop')
        assert loop['before']['active_loop']==0 and loop['after']['active_loop']==1
        moves=next(r for r in result['rows'] if r.get('playlist')=='Set <mix> 日本')['changes']
        assert moves=={'parent':['a','new-b'],'removed':[],'added':[],'order_changed':True},moves
        converted=next(r for r in result['rows'] if r.get('playlist')=='Rule conversion')['changes']
        assert converted=={'smart':[False,True]},converted
        page.select_option('#lab-report-section','cue_active_loop')
        expect(page.locator('#lab-report-rows tbody tr')).to_have_count(1)
        expect(page.locator('#lab-report-download')).to_have_attribute('href',re.compile('section=cue_active_loop'))
        with page.expect_download() as download:page.locator('#lab-report-download').click()
        path=output/'workflow-comparison-filtered.json';download.value.save_as(path)
        filtered=json.loads(path.read_text(encoding='utf-8'))
        assert len(filtered['rows'])==1 and filtered['rows'][0]==loop
        page.select_option('#lab-report-section','playlist')
        expect(page.locator('#lab-report-rows tbody tr')).to_have_count(2)
        expect(page.locator('#lab-report-rows')).to_contain_text('Set <mix> 日本')
        assert page.locator('#lab-report-rows mix').count()==0
        page.screenshot(path=str(output/'workflow-comparison.png'),full_page=True)
        page.reload(wait_until='networkidle');page.locator('.nav[data-view="lab"]').click()
        page.select_option('#lab-report-select',saved)
        expect(page.locator('#lab-report-download')).to_have_attribute('href',re.compile('/'+saved+'/download'))
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        assert not errors,errors
        for identity,original in originals.items():assert store.snapshot(identity)==original
        return {'status':'passed','saved_report_id':saved,'active_loop_changes':1,'metadata_changes':4,
                'playlist_moves':1,'playlist_type_changes':1,'duplicate_members_preserved':True,
                'renumbered_parents_resolved':True,'filtered_download':True,'snapshots_unchanged':True,
                'real_http':True,'mocked_api_responses':False}
    except Exception:
        page.screenshot(path=str(output/'workflow-comparison-failure.png'),full_page=True)
        raise
    finally:
        context.tracing.stop(path=str(output/'workflow-comparison-trace.zip'));context.close()
