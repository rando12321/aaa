import os
import shutil
import tempfile
import threading
import unittest
from playwright.sync_api import sync_playwright
from browser import WhatsApp
from core import Contact


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver = sync_playwright().start()
        cls.browser = cls.driver.chromium.launch(executable_path=os.environ.get('WHATSAPP_CHROME') or shutil.which('chromium'), headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.page.set_default_timeout(300)
        self.tmp = tempfile.TemporaryDirectory()
        self.adapter = WhatsApp(self.tmp.name, threading.Event(), lambda text: None)
        self.adapter.page = self.page
        self.contact = Contact('5593984108321', 'Teste')

    def tearDown(self):
        self.page.close()
        self.tmp.cleanup()

    def serve(self, html):
        self.page.route('https://web.whatsapp.com/**', lambda route: route.fulfill(body=html, content_type='text/html; charset=utf-8'))

    def test_refusal_dismissed_once(self):
        self.serve('<div role="dialog">O número de telefone é inválido<button onclick="this.parentElement.remove()">OK</button></div>')
        self.assertEqual(self.adapter.process(self.contact, 'Olá'), 'refused')
        self.assertEqual(self.page.get_by_role('dialog').count(), 0)

    def test_existing_with_different_name_never_sends(self):
        self.serve('''<div id="main"><header>Outro nome<button aria-label="Menu" onclick="document.querySelector('#edit').hidden=false">Menu</button></header>
        <footer><div role="textbox" contenteditable="true"></div></footer></div><button id="edit" hidden>Editar contato</button>''')
        self.assertEqual(self.adapter.process(self.contact, 'Olá'), 'existing')
        self.assertEqual(self.page.locator('[contenteditable]').inner_text(), '')

    def test_mismatched_form_phone_blocks_before_save(self):
        self.serve('''<div id="main"><header><button aria-label="Menu" onclick="document.querySelector('#add').hidden=false">Menu</button></header>
        <footer><div role="textbox" contenteditable="true"></div></footer></div>
        <button id="add" hidden onclick="document.querySelector('#form').hidden=false">Adicionar aos contatos</button>
        <div id="form" hidden><input aria-label="Nome"><input aria-label="Telefone" value="551123456789"><button onclick="window.saved=true">Salvar</button></div>''')
        with self.assertRaisesRegex(RuntimeError, 'diverge'):
            self.adapter.process(self.contact, 'Olá')
        self.assertIsNone(self.page.evaluate('window.saved'))
        self.assertEqual(self.page.locator('[contenteditable]').inner_text(), '')


if __name__ == '__main__':
    unittest.main()
