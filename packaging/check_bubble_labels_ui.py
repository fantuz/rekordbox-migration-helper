"""Measured SVG text and interaction checks on invented categories in GitHub CI."""
from copy import deepcopy


def check_bubble_labels_ui(page,base,sid,output,store):
    viewport=page.viewport_size;theme=page.locator('#theme').input_value()
    source=deepcopy(store.snapshot(sid));source['tracks']=[]
    labels=['Wide WWW collection with a deliberately long category name',
            'Narrow iii collection with a deliberately long category name',
            '日本語の架空カテゴリー 🎧 café cafe\u0301',
            '👩‍💻👩‍💻👩‍💻👩‍💻👩‍💻', 'A single uninterrupted category name'.replace(' ',''),
            'Ελληνικά · Łódź · Český · Русский','Short','Tiny A','Tiny B','Tiny C','Tiny D','Tiny E']
    seed=store.snapshot(sid)['tracks'][0]
    for index,(label,count) in enumerate(zip(labels,[40,30,15,10,6,5,4,3,2,1,1,1])):
        for entry in range(count):
            source['tracks'].append({**deepcopy(seed),'id':f'label-{index}-{entry}','artist':label,'title':f'Synthetic {index} {entry}'})
    source['playlists']=[];source['histories']=[]
    record=store.save_snapshot(source,'Synthetic bubble labels')['id']
    page.evaluate('()=>Journeys.load()')
    page.evaluate('(id)=>Journeys.selectContext("snapshot:"+id,true)',record)
    page.locator('.nav[data-view="bubbles"]').click()
    page.wait_for_selector('#bubble-snapshot option[value="'+record+'"]',state='attached')
    page.select_option('#bubble-snapshot',record)
    page.wait_for_function('(id)=>insightState.bubble.result?.snapshot.id===id',arg=record)
    page.select_option('#bubble-dimension','artist');page.select_option('#bubble-metric','tracks')
    page.wait_for_function('insightState.bubble.result?.dimension==="artist" && document.querySelectorAll(".bubble-node").length===12')
    circles=page.locator('.bubble-node circle').evaluate_all('(els)=>els.map(el=>[el.getAttribute("r"),el.parentNode.getAttribute("transform")])')
    def verify():
        page.wait_for_function('''()=>{const svg=document.querySelector('#library-bubbles'),m=svg.getScreenCTM(),scale=Math.hypot(m.a,m.b);return [...svg.querySelectorAll('.bubble-label')].length>0 && [...svg.querySelectorAll('.bubble-label')].every(t=>Math.abs(Number(t.getAttribute('font-size'))*scale-12)<.1)}''')
        result=page.locator('#library-bubbles').evaluate('''svg=>{
            const m=svg.getScreenCTM(),scale=Math.hypot(m.a,m.b),nodes=[...svg.querySelectorAll('.bubble-node')];
            return {labels:svg.querySelectorAll('.bubble-label').length,valid:nodes.every(g=>{
                const r=Number(g.querySelector('circle').getAttribute('r'));
                return g.querySelectorAll('.bubble-label').length<=4 && [...g.querySelectorAll('tspan')].every(t=>{
                    const b=t.getBBox(),font=Number(t.getAttribute('font-size'))*scale;
                    return Math.abs(font-12)<.1 &&
                        Math.hypot(Math.max(Math.abs(b.x),Math.abs(b.x+b.width)),Math.max(Math.abs(b.y),Math.abs(b.y+b.height)))<r;
                });
            })};
        }''')
        assert result['valid'],result
        assert page.locator('.bubble-number').count()==0
        assert page.locator('.bubble-node').evaluate_all('(nodes)=>nodes.every(n=>n.getAttribute("aria-label") && n.querySelector("title"))')
        assert page.locator('.bubble-node circle').evaluate_all('(els)=>els.map(el=>[el.getAttribute("r"),el.parentNode.getAttribute("transform")])')==circles
    for width in (1920,1366,820,430):
        page.set_viewport_size({'width':width,'height':1050});verify()
        if width==1920:
            assert page.locator('.bubble-label').count()>0
            assert page.locator('.bubble-node').first.locator('.bubble-label').all_text_contents()==['Wide WWW collection with a deliberately long category name'] or len(' '.join(page.locator('.bubble-node').first.locator('.bubble-label').all_text_contents()))>=45
            page.locator('#library-bubbles').scroll_into_view_if_needed()
            page.screenshot(path=str(output/'bubble-labels-desktop.png'))
    page.set_viewport_size({'width':1366,'height':1050})
    for selected_theme in ('light','dark'):
        page.select_option('#theme',selected_theme);verify()
        row=page.locator('#bubble-groups [data-bubble-index="1"]');row.focus()
        assert row.evaluate('(el)=>el.classList.contains("is-selected")')
        assert page.locator('#library-bubbles [data-bubble-index="1"]').evaluate('(el)=>el.classList.contains("is-selected")')
        assert page.locator('#bubble-selected h4').inner_text()==labels[1]
        node=page.locator('#library-bubbles [data-bubble-index="0"]');node.focus()
        assert page.locator('#bubble-groups [data-bubble-index="0"]').evaluate('(el)=>el.classList.contains("is-selected")')
    page.locator('#bubble-expand').click();page.wait_for_selector('#bubble-expanded[open]');verify()
    page.screenshot(path=str(output/'bubble-labels-expanded.png'))
    with page.expect_download() as downloaded:page.locator('#bubble-svg').click()
    target=output/'bubble-labels.svg';downloaded.value.save_as(target)
    assert 'bubble-label' in target.read_text(encoding='utf-8')
    page.keyboard.press('Escape');page.wait_for_selector('#bubble-expanded',state='hidden');verify()
    page.select_option('#theme',theme);page.set_viewport_size(viewport)
    page.evaluate('(id)=>Journeys.selectContext("snapshot:"+id,true)',sid)
    return {'category_names_without_counters':True,'measured_text':True,'responsive_fonts':True,'circle_areas_preserved':True,'linked_focus':True,'standalone_svg':True}
