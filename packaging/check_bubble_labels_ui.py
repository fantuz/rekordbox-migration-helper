"""Measured SVG text and interaction checks on invented categories in GitHub CI."""
from copy import deepcopy
import json


def check_bubble_labels_ui(page,base,sid,output,store):
    viewport=page.viewport_size;theme=page.locator('#theme').input_value();colour=page.locator('#bubble-color').input_value()
    source=deepcopy(store.snapshot(sid));source['tracks']=[]
    labels=['Wide WWW collection with a deliberately long category name',
            'Narrow iii collection with a deliberately long category name',
            '日本語の架空カテゴリー 🎧 café cafe\u0301',
            '👩‍💻👩‍💻👩‍💻👩‍💻👩‍💻', 'A single uninterrupted category name'.replace(' ',''),
            'Ελληνικά · Łódź · Český · Русский','Short','Tiny A','Tiny B','Tiny C','Tiny D','Tiny E']
    labels.extend([f'Synthetic legend category {index}' for index in range(13,20)])
    labels.extend(['\"><img src=x onerror="window.legendExecuted=1">','Zero recorded usage'])
    seed=store.snapshot(sid)['tracks'][0]
    for index,(label,count) in enumerate(zip(labels,[40,30,15,10,6,5,4,3,2,1,1,1]+[1]*9)):
        for entry in range(count):
            source['tracks'].append({**deepcopy(seed),'id':f'label-{index}-{entry}','artist':label,
                'title':f'Synthetic {index} {entry}','play_count':0 if label=='Zero recorded usage' else 1})
    source['playlists']=[];source['histories']=[]
    record=store.save_snapshot(source,'Synthetic bubble labels')['id']
    frozen=deepcopy(store.snapshot(record))
    page.evaluate('()=>Journeys.load()')
    page.evaluate('(id)=>Journeys.selectContext("snapshot:"+id,true)',record)
    page.locator('.nav[data-view="bubbles"]').click()
    page.wait_for_selector('#bubble-snapshot option[value="'+record+'"]',state='attached')
    page.select_option('#bubble-snapshot',record)
    page.wait_for_function('(id)=>insightState.bubble.result?.snapshot.id===id',arg=record)
    page.select_option('#bubble-dimension','artist');page.select_option('#bubble-metric','tracks')
    page.wait_for_function('insightState.bubble.result?.dimension==="artist" && document.querySelectorAll(".bubble-node").length===21')
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
        assert page.locator('.bubble-node').evaluate_all('(nodes)=>nodes.every(n=>n.getAttribute("aria-label").startsWith(insightState.bubble.result.groups[Number(n.dataset.bubbleIndex)].label+", "))')
        assert page.locator('.bubble-node circle').evaluate_all('(els)=>els.map(el=>[el.getAttribute("r"),el.parentNode.getAttribute("transform")])')==circles
    for width in (1920,1366,820,430):
        page.set_viewport_size({'width':width,'height':1050});verify()
        layout=page.evaluate('''()=>{
            const legend=document.querySelector('#bubble-groups').getBoundingClientRect(),panel=document.querySelector('.bubble-category-panel').getBoundingClientRect();
            return {viewport:innerWidth,page:document.documentElement.scrollWidth,legend:legend.width,panel:panel.width,
                outside:[...document.querySelectorAll('body *')].map(node=>{const r=node.getBoundingClientRect();return {tag:node.tagName,id:node.id,classes:node.className?.baseVal??node.className,left:r.left,right:r.right,width:r.width,height:r.height}})
                    .filter(node=>node.width>0&&node.height>0&&(node.right>innerWidth+1||node.left<-1)).slice(0,40)};
        }''')
        (output/f'bubble-layout-{width}.json').write_text(json.dumps(layout,indent=2)+'\n')
        if layout['page']>width or (width==820 and layout['legend']<layout['panel']-2):
            page.screenshot(path=str(output/f'bubble-layout-failure-{width}.png'),full_page=True)
        assert layout['page']<=width,layout
        if width==820:assert layout['legend']>=layout['panel']-2,layout
        if width==1920:
            assert page.locator('.bubble-label').count()>0
            # Bubble layout order is independent of the category insertion
            # order. Match every visible name to its own stable group index.
            visible=page.locator('.bubble-node').evaluate_all('''nodes=>nodes.map(node=>{
                const expected=insightState.bubble.result.groups[Number(node.dataset.bubbleIndex)].label;
                const shown=[...node.querySelectorAll('.bubble-label')].map(t=>t.textContent.trim());
                return {expected,shown};
            })''')
            for row in visible:
                if not row['shown']:
                    continue
                rendered=''.join(''.join(t.split()).rstrip('…') for t in row['shown'])
                expected=''.join(row['expected'].split())
                assert expected.startswith(rendered),(row,rendered)
            wide=next(row for row in visible if row['expected']==labels[0])
            assert len(''.join(wide['shown']))>=12,wide
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

    # The summary precedes both filter areas and the clickable navigation in DOM
    # order, so keyboard users follow the same order as the visible page.
    order=page.evaluate('''()=>{
        const summary=document.querySelector('#bubble-summary'),bounds=summary.getBoundingClientRect();
        return ['.bubble-toolbar','#bubble-filters','#bubble-breadcrumbs'].every(selector=>{
            const node=document.querySelector(selector),box=(selector==='#bubble-filters'?node.closest('details'):node).getBoundingClientRect();
            return Boolean(summary.compareDocumentPosition(node)&Node.DOCUMENT_POSITION_FOLLOWING) && box.top>=bounds.bottom-1;
        });
    }''')
    assert order
    legend=page.locator('#bubble-groups');legend.evaluate('node=>node.scrollTop=0')
    geometry=legend.evaluate('''node=>{
        const box=node.getBoundingClientRect(),top=box.top+node.clientTop,bottom=top+node.clientHeight;
        return {visible:[...node.children].filter(row=>{const r=row.getBoundingClientRect();return r.top>=top-.5&&r.bottom<=bottom+.5}).length,
            overflow:node.scrollHeight>node.clientHeight,gutter:node.offsetWidth-node.clientWidth,
            scrollbar:getComputedStyle(node).scrollbarWidth};
    }''')
    assert geometry['visible']==15 and geometry['overflow'],geometry
    assert geometry['gutter']>=8 and geometry['scrollbar']!='none',geometry
    for code in ('de','ar','en'):
        page.select_option('#language',code)
        page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
        page.wait_for_function('document.querySelector(".bubble-scroll-hint")?.textContent===I18n.t("Scroll for more categories")')
        assert page.locator('#bubble-groups [data-bubble-index="1"] span').inner_text()==labels[1]
        verify()
    assert page.locator('#bubble-groups img').count()==0
    assert page.evaluate('window.legendExecuted') is None
    last=page.evaluate('()=>({index:insightState.bubble.result.groups.length-1,...insightState.bubble.result.groups.at(-1)})')
    page.locator(f'#bubble-groups [data-bubble-index="{last["index"]}"]').click()
    page.wait_for_function('(key)=>insightState.bubble.result?.dimension==="tracks"&&insightState.bubble.path.length===1&&insightState.bubble.path[0].key===key',arg=last['key'])
    assert page.locator('#bubble-breadcrumbs button:last-child').inner_text()==last['label']
    assert page.locator('#bubble-summary strong').first.inner_text()==str(last['entries'])
    assert page.locator('#bubble-breadcrumbs button:last-child').evaluate('node=>node===document.activeElement')
    def back_to_artists():
        page.locator('#bubble-breadcrumbs [data-bubble-back="0"]').click()
        page.wait_for_function('insightState.bubble.result?.dimension==="artist"&&insightState.bubble.path.length===0&&insightState.bubble.result.groups.length===21')
    back_to_artists()
    for key in ('Enter','Space'):
        page.locator('#bubble-groups [data-bubble-index="1"]').focus()
        page.keyboard.press(key)
        page.wait_for_function('insightState.bubble.result?.dimension==="tracks"&&insightState.bubble.path.length===1')
        assert page.locator('#bubble-breadcrumbs button:last-child').inner_text()==labels[1]
        assert page.locator('#bubble-summary strong').first.inner_text()=='30'
        back_to_artists()
    # A zero-usage category has no area, but remains reachable through its legend.
    page.select_option('#bubble-metric','plays')
    page.wait_for_function('insightState.bubble.result?.metric==="plays"')
    zero=page.evaluate('()=>({index:insightState.bubble.result.groups.findIndex(g=>g.label==="Zero recorded usage"),...insightState.bubble.result.groups.find(g=>g.label==="Zero recorded usage")})')
    assert zero['value']==0
    assert page.locator(f'#library-bubbles [data-bubble-index="{zero["index"]}"]').count()==0
    page.locator(f'#bubble-groups [data-bubble-index="{zero["index"]}"]').click()
    page.wait_for_function('insightState.bubble.path.length===1&&insightState.bubble.result?.summary.entries===1')
    back_to_artists()
    page.select_option('#bubble-metric','tracks')
    page.wait_for_function('insightState.bubble.result?.metric==="tracks"')
    verify()
    page.select_option('#bubble-color','group')
    short=page.evaluate('insightState.bubble.result.groups.findIndex(group=>group.label==="Short")')
    page.locator(f'#bubble-groups [data-bubble-index="{short}"]').hover()
    page.mouse.move(0,0)
    page.locator('#bubble-summary').scroll_into_view_if_needed()
    page.locator('.bubble-workspace').screenshot(path=str(output/'bubble-navigation.png'))
    page.locator('#bubble-expand').click();page.wait_for_selector('#bubble-expanded[open]');verify()
    page.screenshot(path=str(output/'bubble-labels-expanded.png'))
    with page.expect_download() as downloaded:page.locator('#bubble-svg').click()
    target=output/'bubble-labels.svg';downloaded.value.save_as(target)
    assert 'bubble-label' in target.read_text(encoding='utf-8')
    page.keyboard.press('Escape');page.wait_for_selector('#bubble-expanded',state='hidden');verify()
    page.select_option('#theme',theme);page.select_option('#bubble-color',colour);page.set_viewport_size(viewport)
    assert store.snapshot(record)==frozen
    page.evaluate('(id)=>Journeys.selectContext("snapshot:"+id,true)',sid)
    return {'category_names_without_counters':True,'measured_text':True,'responsive_fonts':True,
            'circle_areas_preserved':True,'linked_focus':True,'standalone_svg':True,
            'controls_after_counters':True,'fifteen_visible_legend_rows':True,'visible_scrollbar':True,
            'legend_mouse_and_keyboard_drilldown':True,'breadcrumb_navigation':True,
            'zero_weight_categories_accessible':True,'source_snapshot_preserved':True}
