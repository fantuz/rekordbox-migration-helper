"""Real-browser star edits share one SQLite sidecar across collection views."""
from copy import deepcopy

from ui_navigation import select_collection


def check_inline_ratings_ui(browser, base, store, output):
    from playwright.sync_api import expect
    from metadata_export import track

    scope = 'synthetic:inline-stars'
    original = {'schema': 1, 'scope_key': scope, 'source_kind': 'Synthetic personal stars',
                'tracks': [track({'id': identity, 'title': 'Synthetic shared title', 'artist': 'Invented artist',
                                  'rating': value, 'duration': 240, 'bpm': 120, 'genre': 'House',
                                  'play_count': 0, 'current_path': '/invented/music/shared.mp3'})
                           for identity, value in [('stars-one', 2), ('stars-unknown', None), ('stars-zero', 0)]],
                'playlists': [{'id': 'stars-list', 'name': 'Invented star playlist', 'folder': False,
                               'smart': False, 'tracks': ['stars-one', 'stars-unknown', 'stars-zero']}],
                'histories': [], 'capabilities': {'playlist_order': True, 'playlist_membership': True}}
    sid = store.save_snapshot(original, 'Invented inline stars')['id']
    before = deepcopy(store.snapshot(sid))
    context = browser.new_context(locale='en-US', viewport={'width': 1440, 'height': 1000})
    context.add_init_script("localStorage.setItem('library-workbench.language.v1','en')")
    page = context.new_page(); errors = []; writes = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: writes.append(request.post_data_json)
            if request.method == 'POST' and request.url.split('?')[0].endswith('/api/ratings') else None)

    def widget(container, identity='stars-one'):
        return page.locator(container+' [data-inline-rating="'+identity+'"]')

    def choose(node, stars):
        button = node.locator('[data-inline-stars="'+str(stars)+'"]')
        expect(button).to_be_enabled(); button.click()
        expect(button).to_have_attribute('aria-pressed', 'true')
        expect(button).to_be_enabled()

    try:
        page.goto(base, wait_until='networkidle')
        select_collection(page, '#journey-context-source', 'snapshot:'+sid)
        page.locator('.nav[data-view="insights"]').click()
        select_collection(page, '#dj-snapshot', sid)
        page.select_option('#dj-perspective', 'all')
        page.locator('#dj-filter-form [type="submit"]').click()
        node = widget('#dj-tracks'); expect(node).to_be_visible()
        choose(node, 4)
        expect(node).to_have_class('inline-rating inline-rating-staged')
        assert store.overrides(scope)['stars-one']['rating']['value'] == 4
        assert 'Captured: 2 / 5' in node.get_attribute('title')
        assert page.locator('#track-detail-dialog').is_visible() is False

        # New views show the saved working stars while immutable analysis stays captured.
        page.locator('.nav[data-view="bubbles"]').click()
        select_collection(page, '#bubble-snapshot', sid)
        bubble = widget('#bubble-tracks')
        expect(bubble.locator('[data-inline-stars="4"]')).to_have_attribute('aria-pressed', 'true')
        # A failed metadata read gives a visible explanation and a bounded retry,
        # instead of silently leaving the stars disabled until navigation.
        read = {'fail': True}
        def fail_read_once(route):
            if read['fail']:
                read['fail'] = False
                route.fulfill(status=503, json={'error': 'Synthetic rating refresh unavailable'})
            else:
                route.continue_()
        page.route('**/api/ratings?*', fail_read_once)
        page.locator('.nav[data-view="insights"]').click()
        refreshed = widget('#dj-tracks')
        expect(refreshed.locator('.inline-rating-state')).to_have_text('Unavailable')
        assert 'Synthetic rating refresh unavailable' in refreshed.get_attribute('title')
        expect(refreshed.locator('[data-inline-stars="4"]')).to_be_disabled()
        refreshed.locator('[data-inline-rating-retry]').click()
        expect(refreshed.locator('[data-inline-stars="4"]')).to_have_attribute('aria-pressed', 'true')
        expect(refreshed.locator('[data-inline-stars="4"]')).to_be_enabled()
        page.unroute('**/api/ratings?*', fail_read_once)
        page.locator('.nav[data-view="lab"]').click()
        page.locator('[data-lab-tab="editor"]').click()
        select_collection(page, '#lab-snapshot', sid)
        lab = widget('#lab-tracks')
        expect(lab.locator('[data-inline-stars="4"]')).to_have_attribute('aria-pressed', 'true')
        # The saved stars are visible while the editor is still loading their revision.
        lab.locator('[data-inline-stars="3"]:enabled').press('Enter')
        expect(lab.locator('[data-inline-stars="3"]')).to_have_attribute('aria-pressed', 'true')
        expect(lab.locator('[data-inline-stars="3"]')).to_be_focused()
        assert store.overrides(scope)['stars-one']['rating']['value'] == 3

        # A rejected value remains absent from SQLite and from the visible rating.
        reject = {'next': True}
        def reject_one(route):
            if route.request.method == 'POST' and reject['next']:
                reject['next'] = False
                route.fulfill(status=400, json={'error': 'Synthetic star rejection'})
            else:
                route.continue_()
        page.route('**/api/ratings', reject_one)
        lab.locator('[data-inline-stars="5"]').click()
        expect(page.locator('#toast')).to_contain_text('Synthetic star rejection')
        expect(lab.locator('[data-inline-stars="3"]')).to_have_attribute('aria-pressed', 'true')
        assert store.overrides(scope)['stars-one']['rating']['value'] == 3
        page.unroute('**/api/ratings', reject_one)

        # A second tab's edit wins; this stale click is rejected and refreshed,
        # rather than silently replayed over the concurrent change.
        store.save_override(scope, 'stars-one', 'rating', 1, 2)
        lab.locator('[data-inline-stars="5"]').click()
        expect(page.locator('#toast')).to_contain_text('Staged metadata changed')
        expect(lab.locator('[data-inline-stars="1"]')).to_have_attribute('aria-pressed', 'true')
        assert store.overrides(scope)['stars-one']['rating']['value'] == 1
        choose(lab, 4)
        lab.locator('[data-inline-rating-reset]').click()
        expect(lab.locator('[data-inline-stars="2"]')).to_have_attribute('aria-pressed', 'true')
        expect(lab.locator('[data-inline-rating-reset]')).to_be_hidden()

        unknown = widget('#lab-tracks', 'stars-unknown')
        expect(unknown.locator('.inline-rating-state')).to_have_text('Unknown')
        choose(unknown, 0)
        assert store.overrides(scope)['stars-unknown']['rating']['value'] == 0
        unknown.locator('[data-inline-rating-reset]').click()
        expect(unknown.locator('.inline-rating-state')).to_have_text('Unknown')
        zero = widget('#lab-tracks', 'stars-zero')
        expect(zero.locator('.inline-rating-state')).to_have_text('Unrated')

        page.locator('.nav[data-view="review"]').click()
        page.locator('[data-native-group]').first.click()
        duplicate = widget('.native-compare-records')
        expect(duplicate).to_be_visible(); choose(duplicate, 3)
        assert store.overrides(scope)['stars-one']['rating']['value'] == 3
        def assert_rating_fits_field():
            assert duplicate.locator('.inline-rating-choices').evaluate('''e=>{
                const choices=e.getBoundingClientRect(),field=e.closest('dd').getBoundingClientRect();
                return choices.left>=field.left-1&&choices.right<=field.right+1;
            }''')
        assert_rating_fits_field()
        expect(page.locator('#toast')).to_be_hidden(timeout=12000)
        for theme in ('dark', 'light'):
            page.select_option('#theme', theme)
            page.screenshot(path=str(output/('inline-stars-review-'+theme+'.png')))
        page.set_viewport_size({'width': 390, 'height': 900})
        # Narrow review uses its existing modal drawer; resizing deliberately
        # returns to the list until the candidate is opened again.
        page.locator('[data-native-group]').first.click()
        duplicate.scroll_into_view_if_needed()
        assert_rating_fits_field()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path=str(output/'inline-stars-review-narrow.png'))
        drawer=page.locator('.review-drawer[open]')
        controls='''[...e.querySelectorAll('button,a[href],input,select,textarea,[tabindex]')].filter(n=>n.tabIndex>=0&&!n.disabled&&n.getClientRects().length&&!n.closest('[hidden],[inert]'))'''
        drawer.evaluate('e=>{const controls='+controls+';controls.at(-1).focus();}')
        page.keyboard.press('Tab')
        assert drawer.evaluate('e=>document.activeElement===('+controls+')[0]')
        duplicate.locator('[data-inline-stars="3"]').focus()
        page.keyboard.press('Escape')
        expect(drawer).to_have_count(0)

        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.locator('.nav[data-view="intelligence"]').click()
        page.select_option('#intelligence-source', sid)
        page.wait_for_selector('#intelligence-playlist option[value="stars-list"]', state='attached')
        page.select_option('#intelligence-playlist', 'stars-list')
        page.locator('#intelligence-contents').click()
        playlist = widget('#intelligence-results')
        expect(playlist.locator('[data-inline-stars="3"]')).to_have_attribute('aria-pressed', 'true')
        choose(playlist, 5)
        page.reload(wait_until='networkidle')
        assert store.overrides(scope)['stars-one']['rating']['value'] == 5
        assert store.snapshot(sid) == before
        assert errors == [], errors
        return {'real_sidecar_save_reset': True, 'captured_snapshot_unchanged': True,
                'unknown_distinct_from_zero': True, 'view_scopes_consistent': True,
                'keyboard_and_focus': True, 'read_failure_and_retry': True, 'rejected_save_not_shown': True,
                'stale_write_rejected_not_replayed': True, 'reload_persists': True,
                'dark_light_narrow': True, 'modal_focus_and_escape':True, 'requests': len(writes)}
    except Exception:
        page.screenshot(path=str(output/'inline-stars-failure.png'), full_page=True)
        raise
    finally:
        context.close()
