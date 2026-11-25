"""Measured SVG text and interaction checks on invented categories in GitHub CI."""
from ui_navigation import select_collection, open_collection_picker
from copy import deepcopy
from contextlib import nullcontext, suppress
import json
import re
from urllib.parse import parse_qs, urlsplit


def check_bubble_labels_ui(page,base,sid,output,store):
    """Retain the interaction trace and actual view state when navigation fails."""
    responses=[]
    def response_seen(response):
        if '/api/insights/bubbles?' in response.url or '/api/insights/tracks?' in response.url:
            responses.append({'url':response.url,'status':response.status})
            del responses[:-60]
    page.on('response',response_seen)
    page.context.tracing.start(screenshots=True,snapshots=True,sources=True)
    page.evaluate('''()=>{
        const events=[],types=['pointerdown','mousedown','pointerup','mouseup','click','keydown','keyup','focusin','focusout','input','change'];
        const describe=node=>node?{tag:node.tagName,id:node.id,index:node.dataset?.bubbleIndex,back:node.dataset?.bubbleBack,value:node.value,text:node.textContent?.slice(0,100)}:null;
        const rect=node=>{const r=node?.getBoundingClientRect();return r?{x:r.x,y:r.y,width:r.width,height:r.height}:null;};
        const state=(geometry=false)=>{const s=insightState.bubble;return {dimension:s.dimension,path:s.path.map(item=>({...item})),revision:s.revision,
            view:document.querySelector('.view:not([hidden])')?.id,metric:document.querySelector('#bubble-metric')?.value,
            snapshot:document.querySelector('#bubble-snapshot')?.value,optionsSnapshot:s.options?.snapshot?.id,
            languageBusy:document.documentElement.dataset.languageBusy,
            toast:document.querySelector('#toast')?.textContent?.slice(0,300),
            result:s.result?{dimension:s.result.dimension,metric:s.result.metric,entries:s.result.summary?.entries,groups:s.result.groups.length,snapshot:s.result.snapshot?.id}:null,
            busy:document.querySelector('#library-bubbles')?.getAttribute('aria-busy'),active:describe(document.activeElement),
            breadcrumbFocused:document.activeElement===document.querySelector('#bubble-breadcrumbs button:last-child'),
            breadcrumb:describe(document.querySelector('#bubble-breadcrumbs button:last-child')),
            scroll:{x:scrollX,y:scrollY,legend:document.querySelector('#bubble-groups')?.scrollTop},
            inspector:geometry?rect(document.querySelector('#bubble-selected')):undefined,legend:geometry?rect(document.querySelector('#bubble-groups')):undefined};};
        const record=(type,event)=>{events.push({type,time:performance.now(),key:event?.key,x:event?.clientX,y:event?.clientY,target:describe(event?.target),state:state()});if(events.length>150)events.shift();};
        const listener=event=>{if(!document.querySelector('#view-bubbles').hidden)record(event.type,event);};
        types.forEach(type=>document.addEventListener(type,listener,true));
        const observer=new MutationObserver(()=>record('inspector-or-breadcrumb-render'));
        for(const id of ['bubble-selected','bubble-breadcrumbs'])observer.observe(document.getElementById(id),{childList:true});
        window.bubbleNavigationDiagnostics={events,state,cleanup(){observer.disconnect();types.forEach(type=>document.removeEventListener(type,listener,true));}};
    }''')
    status='failed'
    try:
        result=_check_bubble_labels_ui(page,base,sid,output,store)
        status='passed'
        return result
    finally:
        # Diagnostic failures must not replace the original UI assertion.
        with suppress(Exception) if status=='failed' else nullcontext():
            captured=page.evaluate('()=>({state:window.bubbleNavigationDiagnostics.state(true),events:window.bubbleNavigationDiagnostics.events})')
            captured.update(status=status,responses=responses[-60:])
            (output/'bubble-navigation-diagnostics.json').write_text(json.dumps(captured,ensure_ascii=False,indent=2)+'\n')
            if status=='failed':page.screenshot(path=str(output/'bubble-navigation-failure.png'))
        with suppress(Exception) if status=='failed' else nullcontext():
            page.context.tracing.stop(path=str(output/'bubble-navigation-trace.zip'))
        page.remove_listener('response',response_seen)
        with suppress(Exception) if status=='failed' else nullcontext():
            page.evaluate('()=>{window.bubbleNavigationDiagnostics.cleanup();delete window.bubbleNavigationDiagnostics;}')


def _check_bubble_labels_ui(page,base,sid,output,store):
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
    select_collection(page,'#bubble-snapshot',record)
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
    scrollbar_styles={}
    for selected_theme in ('light','dark'):
        page.select_option('#theme',selected_theme);verify()
        style=page.locator('#bubble-groups').evaluate('''node=>{
            const style=getComputedStyle(node);
            return {width:style.scrollbarWidth,colours:style.scrollbarColor,gutter:node.offsetWidth-node.clientWidth};
        }''')
        assert style['width'] in ('auto','thin'),style
        colours=re.findall(r'rgba?\(([^)]+)\)',style['colours'])
        assert len(colours)==2,style
        def luminance(colour):
            channels=[float(value)/255 for value in re.findall(r'[\d.]+',colour)[:3]]
            assert len(channels)==3,style
            linear=[value/12.92 if value<=.04045 else ((value+.055)/1.055)**2.4 for value in channels]
            return sum(value*weight for value,weight in zip(linear,(.2126,.7152,.0722)))
        thumb,track=sorted(luminance(colour) for colour in colours)
        style['contrast']=(track+.05)/(thumb+.05)
        assert style['contrast']>=3,style
        scrollbar_styles[selected_theme]=style
        page.mouse.move(5,5)
        row=page.locator('#bubble-groups [data-bubble-index="1"]');row.focus()
        if selected_theme=='light':
            # Firefox can re-hit-test a stationary pointer as focus scrolls the legend.
            other=page.locator('#library-bubbles [data-bubble-index="8"]')
            other.dispatch_event('mouseenter',{'clientX':5,'clientY':5})
            other.dispatch_event('mousemove',{'clientX':5,'clientY':5})
        assert row.evaluate('(el)=>el.classList.contains("is-selected")')
        assert page.locator('#library-bubbles [data-bubble-index="1"]').evaluate('(el)=>el.classList.contains("is-selected")')
        assert page.locator('#bubble-selected h4').inner_text()==labels[1]
        if selected_theme=='light':
            other.hover()
            assert other.evaluate('(el)=>el.classList.contains("is-selected")')
            assert row.evaluate('(el)=>el===document.activeElement')
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
    # Native overlay scrollbars reserve no gutter, even with scrollbar-gutter:
    # stable. Check actual styles/contrast above and scrolling behavior here.
    assert geometry['scrollbar']!='none',geometry
    legend.hover();page.mouse.wheel(0,320)
    page.wait_for_function('document.querySelector("#bubble-groups").scrollTop>0')
    legend.evaluate('node=>node.scrollTop=0')
    (output/'bubble-scrollbars.json').write_text(json.dumps(scrollbar_styles,indent=2)+'\n')
    for code in ('de','ar','en'):
        page.select_option('#language',code)
        page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
        page.wait_for_function('document.querySelector(".bubble-scroll-hint")?.textContent===I18n.t("Scroll for more categories")')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),code
        assert page.locator('#bubble-groups [data-bubble-index="1"] span').inner_text()==labels[1]
        verify()
    assert page.locator('#bubble-groups img').count()==0
    assert page.evaluate('window.legendExecuted') is None
    last=page.evaluate('()=>({index:insightState.bubble.result.groups.length-1,...insightState.bubble.result.groups.at(-1)})')
    page.locator(f'#bubble-groups [data-bubble-index="{last["index"]}"]').click()
    page.wait_for_function('(key)=>insightState.bubble.result?.dimension==="tracks"&&insightState.bubble.path.length===1&&insightState.bubble.path[0].key===key&&document.activeElement===document.querySelector("#bubble-breadcrumbs button:last-child")',arg=last['key'])
    assert page.locator('#bubble-breadcrumbs button:last-child').inner_text()==last['label']
    assert page.locator('#bubble-summary strong').first.inner_text()==str(last['entries'])
    assert page.locator('#bubble-breadcrumbs button:last-child').evaluate('node=>node===document.activeElement')
    root_crumb=page.locator('#bubble-breadcrumbs [data-bubble-back="0"]')
    def back_to_artists(*,keyboard=False):
        if keyboard:root_crumb.press('Enter')
        else:root_crumb.click()
        page.wait_for_function('insightState.bubble.result?.dimension==="artist"&&insightState.bubble.path.length===0&&insightState.bubble.result.groups.length===21')
    back_to_artists()
    for key in ('Enter','Space'):
        page.locator('#bubble-groups [data-bubble-index="1"]').focus()
        page.keyboard.press(key)
        page.wait_for_function('insightState.bubble.result?.dimension==="tracks"&&insightState.bubble.path.length===1&&document.activeElement===document.querySelector("#bubble-breadcrumbs button:last-child")')
        assert page.locator('#bubble-breadcrumbs button:last-child').inner_text()==labels[1]
        assert page.locator('#bubble-summary strong').first.inner_text()=='30'
        if key=='Space':
            # Pressing a breadcrumb and releasing outside it cancels navigation.
            root_crumb.hover();page.mouse.down()
            assert root_crumb.evaluate('button=>button===document.activeElement')
            box=root_crumb.bounding_box()
            page.mouse.move(box['x']+box['width']/2,box['y']-5);page.mouse.up()
            assert page.evaluate('insightState.bubble.path.length===1')
            # Model the 21px native focus scroll seen between mouse-down and
            # mouse-up in WebKit. Playwright still delivers a real pointer click.
            page.locator('#bubble-breadcrumbs button:last-child').focus()
            root_crumb.evaluate('''button=>{
                button.addEventListener('mousedown',event=>{
                    if(!event.defaultPrevented)window.scrollBy(0,-21);
                },{once:true});
            }''')
        back_to_artists(keyboard=key=='Enter')
    # Keep one drill-down pending so a repeated key and a newer breadcrumb
    # selection cannot have their focus stolen by ignored or obsolete work.
    held=[]
    pattern='**/api/insights/*'
    page.evaluate('window.bubbleHeldRequests=0')
    def hold_branch(route):
        url=urlsplit(route.request.url);query=parse_qs(url.query)
        if (url.path in ('/api/insights/bubbles','/api/insights/tracks')
                and query.get('snapshot')==[record] and query.get('path')!=['[]']):
            held.append(route)
            page.evaluate('(count)=>window.bubbleHeldRequests=count',len(held))
        else:route.continue_()
    page.route(pattern,hold_branch)
    try:
        page.locator('#bubble-groups [data-bubble-index="1"]').focus()
        page.evaluate('()=>{window.bubbleHeldActivation=activateBubbleGroup(insightState.bubble.result.groups[1]);}')
        page.wait_for_function('window.bubbleHeldRequests===2&&document.querySelector("#library-bubbles").getAttribute("aria-busy")==="true"')
        page.keyboard.press('Enter')
        assert page.locator('#bubble-groups [data-bubble-index="1"]').evaluate('node=>node===document.activeElement'), 'Ignored activation moved keyboard focus'
        back_to_artists()
        page.locator('#bubble-metric').focus()
        while held:held.pop(0).continue_()
        page.evaluate('()=>window.bubbleHeldActivation')
        assert page.locator('#bubble-metric').evaluate('node=>node===document.activeElement'), 'Superseded navigation moved keyboard focus'
        assert page.evaluate('insightState.bubble.path.length===0&&insightState.bubble.result.dimension==="artist"')
    finally:
        while held:held.pop(0).continue_()
        page.unroute(pattern,hold_branch)
        page.evaluate('()=>{delete window.bubbleHeldRequests;delete window.bubbleHeldActivation;}')
    # A zero-usage category has no area, but remains reachable through its legend.
    page.select_option('#bubble-metric','plays')
    page.wait_for_function('insightState.bubble.result?.metric==="plays"')
    zero=page.evaluate('()=>({index:insightState.bubble.result.groups.findIndex(g=>g.label==="Zero recorded usage"),...insightState.bubble.result.groups.find(g=>g.label==="Zero recorded usage")})')
    assert zero['value']==0
    assert page.locator(f'#library-bubbles [data-bubble-index="{zero["index"]}"]').count()==0
    page.locator(f'#bubble-groups [data-bubble-index="{zero["index"]}"]').click()
    page.wait_for_function('insightState.bubble.path.length===1&&insightState.bubble.result?.summary.entries===1&&document.activeElement===document.querySelector("#bubble-breadcrumbs button:last-child")')
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
            'controls_after_counters':True,'fifteen_visible_legend_rows':True,'scrollbar_contrast_and_wheel':True,
            'legend_mouse_and_keyboard_drilldown':True,'breadcrumb_navigation':True,
            'zero_weight_categories_accessible':True,'ignored_activation_preserves_focus':True,
            'superseded_navigation_preserves_focus':True,'source_snapshot_preserved':True}
