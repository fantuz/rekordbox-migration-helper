"""Exercise collection pickers through the visible, collapsed navigation controls."""


def open_collection_picker(page, selector):
    node = page.locator(selector)
    page.wait_for_selector(selector, state='attached')
    group = node.locator('xpath=ancestor::details[1]')
    if group.count() and not node.is_visible():
        group.locator('summary').first.click()
    return node


def select_collection(page, selector, value):
    node = open_collection_picker(page, selector)
    node.select_option(value)
    group = node.locator('xpath=ancestor::details[1]')
    if group.count() and group.get_attribute('open') is not None:
        node.press('Escape')
