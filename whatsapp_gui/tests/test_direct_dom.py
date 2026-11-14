import importlib.util
import shutil
import unittest
from unittest.mock import Mock
from app import App


@unittest.skipUnless(importlib.util.find_spec('playwright'),'Teste DOM opcional requer Playwright no desenvolvimento')
class MessageDOMTests(unittest.TestCase):
    def test_confirmation_reads_message_id_and_multiline_text(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=shutil.which('chromium'),headless=True)
            try:
                page=browser.new_page()
                page.set_content('<div id="main"><div data-id="unique-id" class="message-out"><span class="selectable-text">Olá, Ana!<br>Segunda linha</span></div></div>')
                app=App.__new__(App)
                app.driver=Mock()
                app.driver.execute_script.side_effect=lambda script:page.evaluate('(function(){'+script+'})()')
                self.assertEqual(app.mensagens_saida(),{'unique-id':'Olá, Ana!\nSegunda linha'})
            finally:
                browser.close()
