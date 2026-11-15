"""Maintenance confirmations and long path layout using invented evidence only."""


def check_workspace_maintenance_ui(browser,base,output):
    context=browser.new_context(locale='en-US',viewport={'width':1366,'height':900})
    context.add_init_script("localStorage.setItem('library-workbench.language.v1','en')")
    page=context.new_page();errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    synthetic=r'C:\Users\Example\AppData\Local\LibraryWorkbench\.temporary\0123456789abcdef0123456789abcdef'
    try:
        page.goto(base,wait_until='networkidle')
        page.locator('.nav[data-view=investigations]').click()
        page.wait_for_selector('#workspace-maintenance')
        page.locator('#maintenance-cache').click()
        page.wait_for_selector('#maintenance-fresh')
        page.locator('#maintenance-fresh').click()
        page.wait_for_selector('#maintenance-ack')
        assert page.locator('#maintenance-confirm').is_disabled()
        page.locator('#maintenance-ack').check()
        assert page.locator('#maintenance-confirm').is_enabled()
        # Preview only: this browser check must not erase other synthetic test evidence.
        page.screenshot(path=str(output/'workspace-maintenance-preview.png'))
        for theme in ('light','dark'):
            page.select_option('#theme',theme)
            for width in (1366,768,390):
                page.set_viewport_size({'width':width,'height':900})
                page.evaluate('(value)=>{document.querySelector("#cleanup-path").textContent=value;document.querySelector("#cleanup-dialog").showModal();}',synthetic)
                page.wait_for_selector('#cleanup-path wbr',state='attached')
                result=page.locator('#cleanup-path').evaluate('''e=>({text:e.textContent,font:parseFloat(getComputedStyle(e).fontSize),width:e.clientWidth,scroll:e.scrollWidth,padding:parseFloat(getComputedStyle(e).paddingLeft)})''')
                assert result['text']==synthetic, result
                assert result['font']<=12 and result['padding']>=10, result
                assert result['scroll']<=result['width']+1, result
                assert page.locator('#cleanup-confirm').is_disabled()
                page.screenshot(path=str(output/f'cleanup-path-{theme}-{width}.png'))
                page.locator('#cleanup-cancel').click()
        assert not errors,errors
        return {'cache_clear':True,'fresh_preview_acknowledgment':True,'path_wrap':True,'copy_text_unchanged':True,'themes':['light','dark'],'widths':[1366,768,390],'synthetic':True}
    finally:
        context.close()
