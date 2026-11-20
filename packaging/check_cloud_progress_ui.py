"""Observe real job checkpoints in the existing central dialog using synthetic files."""
from threading import Event
from unittest.mock import patch


def check_cloud_progress(page, application, button, provider, *, download=False, screenshot=None):
    from playwright.sync_api import expect
    phases = ('Downloading audio',) if download else ('Reading folder metadata','Matching library paths','Saving file evidence')
    gates = {phase:(Event(),Event()) for phase in phases}
    observed = {}
    original = application.task_progress

    def report(job, amount, message):
        original(job,amount,message)
        detail=getattr(message,'detail',{})
        phase=detail.get('phase')
        if detail.get('provider')!=provider or phase not in gates or phase in observed:return
        if phase=='Reading folder metadata' and not detail['pages']:return
        if download and not 0<detail['completed']<detail['total']:return
        observed[phase]=detail
        entered,resume=gates[phase];entered.set()
        if not resume.wait(20):raise AssertionError('Browser did not observe '+phase)

    with patch.object(application,'task_progress',report),patch('dropbox_download.CHUNK_BYTES',8):
        try:
            button.click()
            for phase in phases:
                entered,resume=gates[phase]
                assert entered.wait(15),phase
                detail=observed[phase]
                expect(page.locator('#progress')).to_be_visible()
                expect(page.locator('#progress-label')).to_have_text(provider+' · '+phase)
                bar=page.locator('#progress-bar');counts=page.locator('#progress-counts')
                if phase=='Reading folder metadata':
                    expect(counts).to_contain_text('Entries '+str(detail['completed']))
                    expect(counts).to_contain_text('Metadata pages '+str(detail['pages']))
                    assert not bar.evaluate("bar=>bar.hasAttribute('value')")
                    expect(page.locator('#progress-percent')).to_have_text('—')
                else:
                    unit='Bytes' if download else 'Tracks'
                    expect(counts).to_contain_text(f"{unit} {detail['completed']} / {detail['total']}")
                    percent=100*detail['completed']/detail['total']
                    assert abs(float(bar.get_attribute('value'))-percent)<0.00001
                    expect(page.locator('#progress-percent')).to_have_text(f'{int(percent)}%')
                if detail['item']:
                    expect(page.locator('#progress-item')).to_have_text(detail['item'])
                    assert '/' not in detail['item'] and '\\' not in detail['item']
                expect(bar).to_have_attribute('aria-valuetext',counts.inner_text())
                if screenshot and (download or phase=='Reading folder metadata'):
                    page.locator('#progress').screenshot(path=str(screenshot))
                resume.set()
            expect(page.locator('#progress')).to_be_hidden(timeout=15000)
        finally:
            for _,resume in gates.values():resume.set()
