"""Test-only WebElement bridge to exercise the app's DOM scripts in real Chromium.
Not a substitute for validating ChromeDriver or the actual WhatsApp interface.
"""
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import StaleElementReferenceException


class Element:
    def __init__(self, driver, handle):
        self.driver, self.handle = driver, handle

    @property
    def id(self):
        return self.handle.evaluate('(e) => e.__testID ||= String(++window.__testCounter || (window.__testCounter=1))')

    @property
    def text(self):
        return self.handle.inner_text()

    @property
    def tag_name(self):
        return self.handle.evaluate('(e) => e.tagName.toLowerCase()')

    def is_displayed(self):
        if not self.handle.evaluate('(e) => e.isConnected'):
            raise StaleElementReferenceException()
        return self.handle.is_visible()

    def is_enabled(self):
        return self.handle.is_enabled()

    def get_attribute(self, name):
        return self.handle.evaluate('(e, n) => n in e ? e[n] : e.getAttribute(n)', name)

    def click(self):
        self.handle.click()

    def find_elements(self, by, selector):
        prefix = 'xpath=' if by == By.XPATH else ''
        if by == By.ID:
            selector = '[id="' + selector + '"]'
        return [Element(self.driver, e) for e in self.handle.query_selector_all(prefix + selector)]

    def send_keys(self, *keys):
        if keys and keys[0] in (Keys.CONTROL, Keys.COMMAND):
            self.handle.press('Control+' + keys[1])
        elif keys == (Keys.BACKSPACE,):
            self.handle.press('Backspace')
        elif keys == (Keys.TAB,):
            self.handle.press('Tab')
        elif keys == (Keys.ENTER,):
            self.handle.press('Enter')
        elif keys == (Keys.SHIFT, Keys.ENTER):
            self.handle.press('Shift+Enter')
        else:
            self.handle.type(''.join(keys))


class DomDriver:
    capabilities = {'platformName': 'linux'}

    def __init__(self, page):
        self.page = page

    def get(self, url):
        self.page.goto(url)

    def find_elements(self, by, selector):
        prefix = 'xpath=' if by == By.XPATH else ''
        if by == By.ID:
            selector = '[id="' + selector + '"]'
        return [Element(self, e) for e in self.page.query_selector_all(prefix + selector)]

    def execute_script(self, script, *args):
        values = [arg.handle if isinstance(arg, Element) else arg for arg in args]
        handle = self.page.evaluate_handle('(args) => { return (function() {' + script + '\n}).apply(null, args); }', values)
        return self.convert(handle)

    def convert(self, handle):
        element = handle.as_element()
        if element:
            return Element(self, element)
        if handle.evaluate('(v) => Array.isArray(v)'):
            return [self.convert(v) for k, v in handle.get_properties().items() if k.isdigit()]
        return handle.json_value()

    def execute_cdp_cmd(self, name, args):
        assert name == 'Input.insertText'
        self.page.keyboard.insert_text(args['text'])

    def execute(self, command, params):
        assert command == 'actions'
        special = {Keys.CONTROL: 'Control', Keys.COMMAND: 'Meta', Keys.SHIFT: 'Shift',
                   Keys.BACKSPACE: 'Backspace', Keys.TAB: 'Tab', Keys.ESCAPE: 'Escape', Keys.ENTER: 'Enter'}
        for device in params['actions']:
            if device['type'] != 'key':
                continue
            for action in device['actions']:
                if action['type'] == 'keyDown':
                    self.page.keyboard.down(special.get(action['value'], action['value']))
                elif action['type'] == 'keyUp':
                    self.page.keyboard.up(special.get(action['value'], action['value']))
        return {'value': None}
