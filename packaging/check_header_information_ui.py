"""Real-browser checks for the shared, compact contextual notice.

Use synthetic CI data only. The message must be visible without consuming a
standalone page row, while full guidance and its link remain available.
"""
def check_header_information_ui(page,output):
    page.select_option('#language','en')
    page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
    notice=page.locator('#header-information')
    assert notice.is_visible()
    assert page.locator('#session-cleanup-note').count()==1
    assert page.locator('main > .session-cleanup-note').count()==0
    assert page.locator('.workspace-toolbar #collection-navigation').count()==1
    assert page.locator('.workspace-toolbar #header-information').count()==1
    assert page.locator('.workspace-toolbar .header-actions').count()==1
    for view,fragment in (
        ('history','Session history requires'),
        ('statistics','STEMS readiness is unknown'),
        ('lab','Keep an untouched rekordbox Backup Library backup'),
    ):
        page.locator('.nav[data-view="'+view+'"]').click()
        page.wait_for_function('(name)=>document.querySelector(".nav.active")?.dataset.view===name',arg=view)
        assert page.locator('#header-information-context').is_visible()
        assert fragment in page.locator('#header-information-context').inner_text()
        assert page.locator('#view-'+view+' > aside.callout').count()==0
        expanded=page.locator('#header-information-details')
        expanded.locator('summary').click()
        assert expanded.get_attribute('open') is not None
        assert page.locator('#header-information-expanded .callout').count()==1
        assert fragment in page.locator('#header-information-expanded').inner_text()
        if view=='history':
            assert page.locator('#header-information-expanded [data-help-doc="discovery-assets-history"]').is_visible()
            for theme in ('light','dark'):
                page.select_option('#theme',theme)
                for width in (1920,1715,1366,1280,1024,768,390):
                    page.set_viewport_size({'width':width,'height':980})
                    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1'),(width,theme)
                    assert page.locator('#header-information').evaluate('''e=>{
                        const title=document.querySelector('.header-title').getBoundingClientRect(),
                              note=e.getBoundingClientRect(),
                              actions=document.querySelector('.header-actions').getBoundingClientRect();
                        const overlaps=(a,b)=>a.left<b.right-1&&a.right>b.left+1&&a.top<b.bottom-1&&a.bottom>b.top+1;
                        return !overlaps(title,note)&&!overlaps(note,actions);
                    }'''),(width,theme)
                    assert page.locator('.workspace-toolbar').evaluate('''e=>{
                        const row=e.getBoundingClientRect(),title=document.querySelector('.topbar').getBoundingClientRect();
                        return row.bottom<=title.top+1 && [...e.querySelectorAll(':scope>.header-actions>button,:scope>.header-actions>label,:scope>.collection-navigation>details>summary')].every(n=>{
                            const r=n.getBoundingClientRect();return r.width>0&&r.left>=-1&&r.right<=innerWidth+1;
                        });
                    }'''),(width,theme)
                    if width==1920:
                        assert page.locator('.workspace-toolbar').evaluate('''e=>{
                            const nodes=[...e.children].map(n=>n.getBoundingClientRect());
                            return Math.max(...nodes.map(r=>r.top))<Math.min(...nodes.map(r=>r.bottom));
                        }'''),theme
                page.set_viewport_size({'width':1920,'height':980})
                page.screenshot(path=str(output/('header-notice-'+theme+'.png')))
        expanded.locator('summary').click()
    page.locator('.nav[data-view="files"]').click()
    assert page.locator('#header-information-context').is_hidden()
    assert page.locator('#header-information-details').is_hidden()
    assert page.locator('#view-history > aside.callout').count()==1
    assert page.locator('#view-statistics > aside.callout').count()==1
    assert page.locator('#view-lab > aside.callout').count()==1
    page.locator('.nav[data-view="history"]').click()
    page.select_option('#language','de')
    page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
    assert page.locator('#header-information-context').is_visible()
    assert 'Session history requires' not in page.locator('#header-information-context').inner_text()
    for language in ('de','ar'):
        page.select_option('#language',language)
        page.wait_for_function('(language)=>document.documentElement.lang===language&&document.documentElement.dataset.languageBusy!=="true"',arg=language)
        for width in (1440,390):
            page.set_viewport_size({'width':width,'height':980})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(language,width)
            assert page.locator('#open-import').is_visible()
    page.select_option('#language','en')
    page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
    page.set_viewport_size({'width':1440,'height':1000})
    page.select_option('#theme','light')
    page.locator('.nav[data-view="files"]').click()
    return {'notice_singleton':True,'page_context':True,'details_and_help':True,
            'responsive':True,'dark_light':True,'translation':True,
            'original_guidance_retained':True,'shared_top_toolbar':True,
            'global_controls_wrap_without_overflow':True,'rtl_layout':True}
