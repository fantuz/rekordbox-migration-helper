"""CI browser regressions for region preferences, RTL and mixed-script metadata."""
import json


def check_regional_languages_ui(browser, base, output):
    cases=[('pt-BR',None,'pt-BR'),('pt-PT',None,'pt-PT'),
           ('pt-AO',None,'pt-PT'),('pt',None,'pt-PT'),('ja-JP',None,'ja'),
           ('ar-EG',None,'ar'),('en-US','PT_br','pt-BR'),
           ('pt-BR','pt-PT','pt-PT'),('ja-JP','unsupported','ja')]
    errors=[]
    for locale,stored,expected in cases:
        context=browser.new_context(locale=locale,viewport={'width':1440,'height':1000})
        try:
            if stored is not None:
                context.add_init_script("if(!sessionStorage.getItem('seeded')){localStorage.setItem('library-workbench.language.v1',"+json.dumps(stored)+");sessionStorage.setItem('seeded','1')}")
            page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base,wait_until='networkidle')
            page.wait_for_function('(code)=>document.documentElement.lang===code',arg=expected)
            assert page.locator('#language').input_value()==expected,(locale,stored,expected)
            assert page.locator('html').get_attribute('dir')==('rtl' if expected=='ar' else 'ltr')
            page.select_option('#language','ar')
            page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
            sidebar=page.locator('.sidebar').bounding_box();main=page.locator('main').bounding_box()
            assert sidebar['x']>=main['x']+main['width']-1,(sidebar,main)
            assert abs(sidebar['x']+sidebar['width']-1440)<2,sidebar
            page.locator('.nav[data-view="analyzer"]').click()
            page.locator('#analyzer-path').fill('C:\\Music\\日本語\\موسيقى\\faixa.mp3')
            assert page.locator('#analyzer-path').evaluate('(node)=>getComputedStyle(node).direction')=='ltr'
            page.select_option('#language','ja')
            page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
            assert page.locator('#analyzer-path').input_value()=='C:\\Music\\日本語\\موسيقى\\faixa.mp3'
            assert page.locator('html').get_attribute('dir')=='ltr'
            page.reload(wait_until='networkidle')
            assert page.locator('#language').input_value()=='ja'
            # Rich translations isolate data, keep literal markup inert and retain controls.
            assert page.evaluate('''() => {
                const node=document.createElement('p');
                const value='Mixed <img src=x> العربية 日本語';
                I18n.text(node,'Technical detail: {detail}',{detail:value});
                const isolated=node.querySelector('bdi[dir=auto]');
                if(!isolated || isolated.textContent!==value || node.querySelector('img'))return false;
                const label=document.createElement('label'),input=document.createElement('input');
                input.value='Draft موسيقى';label.append(input);
                label.dataset.i18n='{slot0} Saved on this device {slot1}';
                I18n.apply(label);I18n.apply(label);
                return label.firstElementChild===input && input.value==='Draft موسيقى';
            }''')
            if locale=='ar-EG':
                page.set_viewport_size({'width':390,'height':844})
                for code in ('ar','ja','pt-PT','pt-BR'):
                    page.select_option('#language',code)
                    page.wait_for_function('document.documentElement.dataset.languageBusy!=="true"')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),code
                    page.screenshot(path=str(output/(code+'-narrow.png')),full_page=True)
        finally:
            context.close()
    assert not errors,errors
    return {'region_preferences':len(cases),'rtl_sidebar':True,'direction_switching':True,
            'path_preserved':True,'rich_parameters_isolated':True,'mobile_languages':4}
