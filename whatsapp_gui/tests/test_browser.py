import os
import queue
import shutil
import threading
import unittest
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from app import App, NumeroRecusado
from dom_driver import DomDriver

HTML = '''<!doctype html><meta charset="utf-8"><style>[hidden]{display:none!important}</style>
<div id="side"><button aria-label="Menu" onclick="window.wrong=true">Menu lateral</button></div>
<div id="main"><header><span title="Nome de perfil diferente">Nome de perfil diferente</span>
<button aria-label="Menu" onclick="menu.hidden=false">Menu</button></header>
<div id="messages"></div><footer><div role="textbox" contenteditable="true"></div>
<button aria-label="Enviar" onclick="send()"><span data-icon="send"></span></button></footer></div>
<div id="menu" role="menu" hidden><button id="action" onclick="menu.hidden=true;document.getElementById('form').hidden=false">Adicionar aos contatos</button></div>
<form id="form" role="dialog" hidden onsubmit="return false"><h2>Novo contato</h2>
<label>Nome <input aria-label="Nome"></label><label>Telefone <input type="tel" value="+55 93 98410-8321"></label>
<button type="button" aria-label="Salvar" onclick="localStorage.saved='yes';form.hidden=true;document.getElementById('action').textContent='Editar contato'">Salvar</button></form>
<script>
if(localStorage.saved) action.textContent='Editar contato';
document.addEventListener('keydown',e=>{if(e.key==='Escape') menu.hidden=true});
function send(){const f=document.querySelector('footer [contenteditable]');
 const row=document.createElement('div');row.dataset.id='out-'+Date.now();row.className='message-out';
 const text=document.createElement('span');text.className='selectable-text';text.innerText=f.innerText;
 row.append(text);messages.append(row);f.innerText='';window.sent=(window.sent||0)+1;}
</script>'''


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
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.page.set_default_timeout(2000)
        self.app = App.__new__(App)
        self.app.driver = DomDriver(self.page)
        self.app.parar = threading.Event()
        self.app.eventos = queue.Queue()
        self.app.etapa = ''
        self.app.cadastro_confirmado = None
        self.app.envio_pendente = None
        self.contact = {'phone': '5593984108321', 'name': 'Nome CSV'}
        self.serve(HTML)

    def tearDown(self):
        self.context.close()

    def serve(self, html):
        self.page.unroute('https://web.whatsapp.com/**')
        self.page.route('https://web.whatsapp.com/**', lambda route: route.fulfill(body=html, content_type='text/html; charset=utf-8'))

    def open(self):
        self.page.goto('https://web.whatsapp.com/send?phone=5593984108321')

    def test_full_registration_and_multiline_emoji_send(self):
        self.assertTrue(self.app.abrir_e_detectar(self.contact['phone']))
        self.app.cadastrar(self.contact)
        self.assertEqual(self.app.cadastro_confirmado, self.contact['phone'])
        message = 'Olá, Nome CSV! 😊\nSegunda linha'
        self.app.enviar(self.contact, message)
        self.assertEqual(self.page.evaluate('window.sent'), 1)
        self.assertIn(message, self.app.mensagens_saida().values())
        self.assertIsNone(self.page.evaluate('window.wrong'))

    def test_existing_different_profile_name_skips(self):
        self.open()
        self.page.evaluate("localStorage.saved='yes'")
        self.assertFalse(self.app.abrir_e_detectar(self.contact['phone']))
        self.assertIsNone(self.page.evaluate('window.sent'))

    def test_phone_mismatch_blocks_save(self):
        self.serve(HTML.replace('+55 93 98410-8321', '+55 11 2345-6789'))
        self.assertTrue(self.app.abrir_e_detectar(self.contact['phone']))
        with self.assertRaisesRegex(RuntimeError, 'telefone do formulário'):
            self.app.cadastrar(self.contact)
        self.assertIsNone(self.page.evaluate('localStorage.saved'))

    def test_no_phone_evidence_blocks_save(self):
        self.serve(HTML.replace('+55 93 98410-8321', ''))
        self.app.abrir_e_detectar(self.contact['phone'])
        with self.assertRaisesRegex(RuntimeError, 'telefone do formulário'):
            self.app.cadastrar(self.contact)

    def test_refusal_dismissed(self):
        self.serve('<div role="dialog">O número de telefone é inválido<button onclick="this.parentElement.remove()">OK</button></div>')
        with self.assertRaises(NumeroRecusado):
            self.app.abrir_e_detectar(self.contact['phone'])
        self.app.fechar_aviso_numero()
        self.assertEqual(self.page.get_by_role('dialog').count(), 0)

    def test_draft_blocks_send(self):
        self.serve(HTML.replace('role="textbox" contenteditable="true"></div>', 'role="textbox" contenteditable="true">Rascunho</div>'))
        self.app.cadastro_confirmado = self.contact['phone']
        with self.assertRaisesRegex(RuntimeError, 'rascunho'):
            self.app.enviar(self.contact, 'Olá')
        self.assertIsNone(self.page.evaluate('window.sent'))

    def test_unconfirmed_contact_cannot_send(self):
        with self.assertRaisesRegex(RuntimeError, 'não confirmado'):
            self.app.enviar(self.contact, 'Olá')

    def test_empty_composer_does_not_confirm_send_or_retry(self):
        self.serve(HTML.replace('onclick="send()"', 'onclick="document.querySelector(\'footer [contenteditable]\').innerText=\'\';window.attempts=(window.attempts||0)+1"'))
        self.app.cadastro_confirmado = self.contact['phone']
        original = self.app.esperar
        self.app.esperar = lambda fn, segundos=30: original(fn, min(segundos, 1))
        with self.assertRaisesRegex(RuntimeError, 'ENVIO INCERTO'):
            self.app.enviar(self.contact, 'Mensagem incerta')
        self.assertEqual(self.page.evaluate('window.attempts'), 1)
        with self.assertRaisesRegex(RuntimeError, 'envio incerto'):
            self.app.enviar(self.contact, 'Mensagem incerta')
        self.assertEqual(self.page.evaluate('window.attempts'), 1)

    def test_menu_icon_scoped_to_chat(self):
        self.serve(HTML.replace('aria-label="Menu" onclick="menu.hidden=false">Menu', 'onclick="menu.hidden=false"><span data-icon="menu"></span>'))
        self.assertTrue(self.app.abrir_e_detectar(self.contact['phone']))
        self.assertIsNone(self.page.evaluate('window.wrong'))

    def test_contact_info_fallback_detects_edit_pencil(self):
        html = HTML.replace('id="action" onclick="menu.hidden=true;document.getElementById(\'form\').hidden=false">Adicionar aos contatos',
            'id="action" onclick="menu.hidden=true;document.getElementById(\'info\').hidden=false">Dados do contato')
        html += '''<aside id="info" data-testid="contact-info-drawer" hidden><h2>Dados do contato</h2>
        <p>+55 93 98410-8321</p><button aria-label="Editar"><span data-icon="edit"></span></button>
        <button aria-label="Fechar" onclick="this.parentElement.hidden=true">Fechar</button></aside>'''
        self.serve(html)
        self.assertFalse(self.app.abrir_e_detectar(self.contact['phone']))
        self.assertFalse(self.page.locator('#info').is_visible())
        self.assertIsNone(self.page.evaluate('window.sent'))

    def test_bottom_check_save_does_not_click_phone_check(self):
        html = HTML.replace('<form id="form"', '<form style="display:flex;flex-direction:column" id="form"')
        html = html.replace('<button type="button" aria-label="Salvar"', '<button style="margin-top:180px" type="button"')
        html = html.replace('>Salvar</button></form>', '><span data-icon="checkmark"></span></button></form>')
        html = html.replace('</label>\n<button style=', '<button type="button" onclick="window.phoneCheck=true"><span data-icon="checkmark"></span></button></label>\n<button style=')
        self.serve(html)
        self.app.abrir_e_detectar(self.contact['phone'])
        self.app.cadastrar(self.contact)
        self.assertEqual(self.app.cadastro_confirmado, self.contact['phone'])
        self.assertIsNone(self.page.evaluate('window.phoneCheck'))

    def test_same_header_name_without_edit_does_not_confirm_save(self):
        html = HTML.replace("localStorage.saved='yes';form.hidden=true;document.getElementById('action').textContent='Editar contato'", "form.hidden=true")
        html = html.replace('Nome de perfil diferente', self.contact['name'])
        self.serve(html)
        self.app.abrir_e_detectar(self.contact['phone'])
        with self.assertRaisesRegex(RuntimeError, 'cadastro não foi confirmado'):
            self.app.cadastrar(self.contact)
        self.assertIsNone(self.app.cadastro_confirmado)
        self.assertIsNone(self.page.evaluate('window.sent'))

    def test_save_returns_home_then_reopens_and_sends_once(self):
        html = HTML.replace("localStorage.saved='yes';form.hidden=true;document.getElementById('action').textContent='Editar contato'",
            "localStorage.saved='yes';localStorage.saves=Number(localStorage.saves||0)+1;form.hidden=true;document.getElementById('main').remove()")
        self.serve(html)
        self.app.abrir_e_detectar(self.contact['phone'])
        self.app.cadastrar(self.contact)
        self.assertEqual(self.app.cadastro_confirmado, self.contact['phone'])
        self.assertEqual(self.page.evaluate('localStorage.saves'), '1')
        self.app.enviar(self.contact, 'Mensagem após retornar da tela inicial')
        self.assertEqual(self.page.evaluate('window.sent'), 1)
        self.assertEqual(self.page.evaluate('localStorage.saves'), '1')

    def test_home_return_without_saved_contact_blocks_send(self):
        html = HTML.replace("localStorage.saved='yes';form.hidden=true;document.getElementById('action').textContent='Editar contato'",
            "form.hidden=true;document.getElementById('main').remove()")
        self.serve(html)
        self.app.abrir_e_detectar(self.contact['phone'])
        with self.assertRaisesRegex(RuntimeError, 'cadastro não foi confirmado'):
            self.app.cadastrar(self.contact)
        self.assertIsNone(self.app.cadastro_confirmado)
        self.assertIsNone(self.page.evaluate('window.sent'))

    def test_escape_without_overlay_would_close_chat(self):
        html = HTML.replace("if(e.key==='Escape') menu.hidden=true", "if(e.key==='Escape'){if(menu.hidden) document.getElementById('main')?.remove();else menu.hidden=true;}")
        self.serve(html)
        self.app.abrir_e_detectar(self.contact['phone'])
        self.app.cadastrar(self.contact)
        self.assertEqual(self.app.cadastro_confirmado, self.contact['phone'])
        self.app.enviar(self.contact, 'Sem fechar conversa com Escape')
        self.assertEqual(self.page.evaluate('window.sent'), 1)
