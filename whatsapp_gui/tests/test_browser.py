import os
import queue
import shutil
import threading
import unittest
from unittest.mock import Mock, patch
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
<section><button type="button" aria-label="Fechar" onclick="document.getElementById('form').hidden=true;document.getElementById('form').innerHTML=window.originalForm;window.closes=(window.closes||0)+1"><span data-icon="x"></span></button>
<form id="form" role="dialog" hidden onsubmit="return false"><h2>Novo contato</h2>
<label>Nome <input aria-label="Nome"></label><label>Telefone <input type="tel" value="+55 93 98410-8321"></label>
<button type="button" aria-label="Salvar" onclick="localStorage.saved='yes';form.hidden=true;document.getElementById('action').textContent='Editar contato'">Salvar</button></form></section>
<script>
window.originalForm=document.getElementById('form').innerHTML;
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

    def test_split_country_and_generic_phone_without_save_button(self):
        self.open()
        self.page.set_content('''<div id="main"><h2>Novo contato</h2>
        <label>Nome<input aria-label="Nome"></label><label>Sobrenome<input aria-label="Sobrenome"></label>
        <div><span>País</span><button>BR +55</button></div>
        <div><span>Número de telefone</span><input value="79 98165-6650"></div></div>''')
        campo = self.app.campo_nome(self.app.driver)
        painel = self.app.painel_formulario(campo)
        self.assertTrue(painel)
        self.app.conferir_telefone_formulario(painel, '5579981656650')
        self.assertTrue(self.app.telefone_no_painel(painel, '5579981656650'))

    def test_displayed_missing_nine_is_replaced_with_exact_csv_number(self):
        self.open()
        self.page.set_content('''<form><h2>Novo contato</h2>
        <label>Nome<input aria-label="Nome"></label><div>País<br><button type="button">BR +55</button></div>
        <div><span>Número de telefone</span><input value="79 8165-6650"></div></form>''')
        campo = self.app.campo_nome(self.app.driver)
        painel = self.app.painel_formulario(campo)
        self.assertFalse(self.app.telefone_no_painel(painel, '5579981656650'))
        self.app.conferir_telefone_formulario(painel, '5579981656650')
        self.assertEqual(self.page.locator('input').nth(1).input_value(), '79981656650')
        self.assertTrue(self.app.telefone_no_painel(painel, '5579981656650'))

    def test_non_brazilian_country_blocks_national_phone(self):
        self.open()
        self.page.set_content('''<form><h2>Novo contato</h2>
        <label>Nome<input aria-label="Nome"></label><div>País<br><button>PT +351</button></div>
        <label>Número de telefone<input type="tel" value="79981656650"></label></form>''')
        painel = self.app.painel_formulario(self.app.campo_nome(self.app.driver))
        with self.assertRaisesRegex(RuntimeError, 'Cadastro bloqueado'):
            self.app.conferir_telefone_formulario(painel, '5579981656650')
        self.assertEqual(self.page.locator('input[type=tel]').input_value(), '79981656650')

    def test_save_success_notice_sends_without_checking_edit_again(self):
        html = HTML.replace("localStorage.saved='yes';form.hidden=true;document.getElementById('action').textContent='Editar contato'",
            "localStorage.saved='yes';form.hidden=true;const notice=document.createElement('div');notice.setAttribute('role','status');notice.innerText='Contato salvo com sucesso';document.body.append(notice);document.getElementById('main').remove()")
        self.serve(html)
        self.app.abrir_e_detectar(self.contact['phone'])
        with patch.object(self.app, 'detectar_estado_contato', side_effect=AssertionError('não deve verificar Editar após aviso de sucesso')):
            self.app.cadastrar(self.contact)
        self.app.enviar(self.contact, 'Mensagem imediatamente após cadastro')
        self.assertEqual(self.page.evaluate('window.sent'), 1)

    def test_stale_save_notice_does_not_confirm_new_contact(self):
        html = HTML.replace("localStorage.saved='yes';form.hidden=true;document.getElementById('action').textContent='Editar contato'", "form.hidden=true")
        html += '<div role="status">Contato salvo com sucesso</div>'
        self.serve(html)
        self.app.abrir_e_detectar(self.contact['phone'])
        with self.assertRaisesRegex(RuntimeError, 'cadastro não foi confirmado'):
            self.app.cadastrar(self.contact)
        self.assertIsNone(self.app.cadastro_confirmado)
        self.assertIsNone(self.page.evaluate('window.sent'))

    def test_batch_adds_then_sends_same_contact_without_skip(self):
        self.app.contatos = [self.contact]
        self.app.mensagem = Mock()
        self.app.mensagem.get.return_value = 'Olá, {name}!'
        self.app.intervalo = Mock()
        self.app.intervalo.get.return_value = '0'
        self.app.executar = lambda tarefa: tarefa()
        with patch('app.messagebox.askyesno', return_value=True), patch.object(self.app, 'aguardar_proximo') as wait:
            self.app.iniciar()
        self.assertEqual(self.page.evaluate('window.sent'), 1)
        self.assertIn('Olá, Nome CSV!', self.app.mensagens_saida().values())
        wait.assert_not_called()
        logs = []
        while not self.app.eventos.empty():
            logs.append(self.app.eventos.get()[1])
        self.assertFalse(any('SKIP:' in log for log in logs))

    def test_missing_save_reopens_once_preserving_name_and_phone_then_sends(self):
        html = HTML.replace("menu.hidden=true;document.getElementById('form').hidden=false",
            "menu.hidden=true;document.getElementById('form').hidden=false;localStorage.opens=Number(localStorage.opens||0)+1;if(Number(localStorage.opens)===1)document.querySelector('#form button').remove()")
        html = html.replace("localStorage.saved='yes';", "localStorage.savedName=document.querySelector('input[aria-label=Nome]').value;localStorage.saved='yes';")
        self.serve(html)
        self.app.abrir_e_detectar(self.contact['phone'])
        original = self.app.esperar
        prazos_salvar = []
        def esperar(fn, segundos=30):
            if fn.__name__ == 'encontrar':
                prazos_salvar.append(segundos)
            return original(fn, min(segundos, 1))
        self.app.esperar = esperar
        self.app.cadastrar(self.contact)
        self.assertEqual(prazos_salvar, [5, 5])
        self.assertEqual(self.page.evaluate('localStorage.opens'), '2')
        self.assertEqual(self.page.evaluate('localStorage.savedName'), self.contact['name'])
        self.app.enviar(self.contact, 'Mensagem após recuperar formulário')
        self.assertEqual(self.page.evaluate('window.sent'), 1)
        self.assertEqual(self.page.evaluate('localStorage.opens'), '2')

    def test_missing_save_twice_stops_without_loop_or_send(self):
        html = HTML.replace("menu.hidden=true;document.getElementById('form').hidden=false",
            "menu.hidden=true;document.getElementById('form').hidden=false;localStorage.opens=Number(localStorage.opens||0)+1;document.querySelector('#form button').remove()")
        self.serve(html)
        self.app.abrir_e_detectar(self.contact['phone'])
        original = self.app.esperar
        self.app.esperar = lambda fn, segundos=30: original(fn, min(segundos, 1))
        with self.assertRaisesRegex(RuntimeError, 'botão de salvar'):
            self.app.cadastrar(self.contact)
        self.assertEqual(self.page.evaluate('localStorage.opens'), '2')
        self.assertIsNone(self.app.cadastro_confirmado)
        self.assertIsNone(self.page.evaluate('window.sent'))

    def test_uncertain_save_click_does_not_reopen_or_retry(self):
        from selenium.common.exceptions import TimeoutException
        self.app.abrir_e_detectar(self.contact['phone'])
        with patch.object(self.app, 'confirmar_cadastro', side_effect=TimeoutException('clique com resultado incerto')) as save, patch.object(self.app.driver, 'get') as navigate:
            with self.assertRaises(TimeoutException):
                self.app.cadastrar(self.contact)
            save.assert_called_once()
            navigate.assert_not_called()
        self.assertIsNone(self.page.evaluate('window.sent'))

    def test_name_typed_with_input_events_and_blur_enables_save(self):
        self.open()
        self.page.set_content('''<form><label>Nome<input aria-label="Nome" oninput="window.inputs=(window.inputs||0)+1" onblur="document.querySelector('button').disabled=!this.value.trim()"></label><button disabled>Salvar</button></form>''')
        self.app.digitar_nome('Ana 1234')
        self.assertEqual(self.page.locator('input').input_value(), 'Ana 1234')
        self.assertGreaterEqual(self.page.evaluate('window.inputs'), 8)
        self.assertTrue(self.page.get_by_role('button', name='Salvar').is_enabled())

    def test_name_disappearing_on_blur_blocks_save(self):
        self.open()
        self.page.set_content('''<form><label>Nome<input aria-label="Nome" onblur="this.value=''"></label><button>Salvar</button></form>''')
        original = self.app.esperar
        self.app.esperar = lambda fn, segundos=30: original(fn, min(segundos, 1))
        with self.assertRaisesRegex(RuntimeError, 'Digitando Nome'):
            self.app.digitar_nome('Ana 1234')

    def test_save_review_repairs_missing_name_without_reopening(self):
        self.app.abrir_e_detectar(self.contact['phone'])
        self.page.locator('input[aria-label=Nome]').fill('')
        self.page.evaluate("document.querySelector('input[aria-label=Nome]').onblur=()=>document.querySelector('#form button').disabled=false;document.querySelector('#form button').disabled=true")
        campo = self.app.verificar_formulario_sem_salvar(self.contact)
        self.assertEqual(self.page.locator('input[aria-label=Nome]').input_value(), self.contact['name'])
        self.app.confirmar_cadastro(campo)
        self.assertEqual(self.page.evaluate('localStorage.saved'), 'yes')

    def test_save_review_blocks_native_validation_error(self):
        self.app.abrir_e_detectar(self.contact['phone'])
        self.page.locator('input[aria-label=Nome]').fill(self.contact['name'])
        self.page.locator('input[type=tel]').evaluate("e=>e.setAttribute('pattern','[0-9]{99}')")
        with self.assertRaisesRegex(RuntimeError, 'campo inválido'):
            self.app.verificar_formulario_sem_salvar(self.contact)
        self.assertIsNone(self.page.evaluate('localStorage.saved'))

    def test_save_review_scrolls_panel_then_saves_without_reopening(self):
        html = HTML.replace('<form id="form"', '<form style="height:180px;overflow:auto" onscroll="if(this.scrollTop>100)this.querySelector(\'button\').hidden=false" id="form"')
        html = html.replace('<button type="button" aria-label="Salvar"', '<div style="height:600px"></div><button hidden type="button" aria-label="Salvar"')
        html = html.replace("menu.hidden=true;document.getElementById('form').hidden=false", "menu.hidden=true;document.getElementById('form').hidden=false;localStorage.opens=Number(localStorage.opens||0)+1")
        self.serve(html)
        self.app.abrir_e_detectar(self.contact['phone'])
        original = self.app.esperar
        self.app.esperar = lambda fn, segundos=30: original(fn, min(segundos, 1))
        self.app.cadastrar(self.contact)
        self.assertEqual(self.page.evaluate('localStorage.opens'), '1')
        self.assertEqual(self.app.cadastro_confirmado, self.contact['phone'])

    def test_invalid_phone_validation_reopens_before_save_then_sends(self):
        html = HTML.replace("menu.hidden=true;document.getElementById('form').hidden=false",
            "menu.hidden=true;document.getElementById('form').hidden=false;localStorage.opens=Number(localStorage.opens||0)+1;if(Number(localStorage.opens)===1)document.querySelector('input[type=tel]').setAttribute('aria-invalid','true')")
        self.serve(html)
        self.app.abrir_e_detectar(self.contact['phone'])
        self.app.cadastrar(self.contact)
        self.assertEqual(self.page.evaluate('localStorage.opens'), '2')
        self.assertEqual(self.app.cadastro_confirmado, self.contact['phone'])
        self.app.enviar(self.contact, 'Mensagem após recuperar validação')
        self.assertEqual(self.page.evaluate('window.sent'), 1)

    def test_persistent_invalid_phone_reopens_once_and_never_saves(self):
        html = HTML.replace("menu.hidden=true;document.getElementById('form').hidden=false",
            "menu.hidden=true;document.getElementById('form').hidden=false;localStorage.opens=Number(localStorage.opens||0)+1;document.querySelector('input[type=tel]').setAttribute('aria-invalid','true')")
        self.serve(html)
        self.app.abrir_e_detectar(self.contact['phone'])
        with self.assertRaisesRegex(RuntimeError, 'já foi reaberto uma vez'):
            self.app.cadastrar(self.contact)
        self.assertEqual(self.page.evaluate('localStorage.opens'), '2')
        self.assertIsNone(self.page.evaluate('localStorage.saved'))
        self.assertIsNone(self.page.evaluate('window.sent'))

    def test_recovery_clicks_x_without_navigation(self):
        html = HTML.replace("menu.hidden=true;document.getElementById('form').hidden=false",
            "menu.hidden=true;document.getElementById('form').hidden=false;localStorage.opens=Number(localStorage.opens||0)+1;if(Number(localStorage.opens)===1)document.querySelector('#form button').remove()")
        self.serve(html)
        self.app.abrir_e_detectar(self.contact['phone'])
        original = self.app.esperar
        self.app.esperar = lambda fn, segundos=30: original(fn, min(segundos, 1))
        with patch.object(self.app.driver, 'get', side_effect=AssertionError('não deve recarregar durante recuperação')), patch.object(self.app, 'confirmar_aviso_cadastro', return_value=True):
            self.app.cadastrar(self.contact)
        self.assertEqual(self.page.evaluate('window.closes'), 1)
        self.assertEqual(self.page.evaluate('localStorage.opens'), '2')
        self.assertEqual(self.app.cadastro_confirmado, self.contact['phone'])

    def test_no_identifiable_x_does_not_reload(self):
        self.app.abrir_e_detectar(self.contact['phone'])
        self.page.locator('button[aria-label=Fechar]').evaluate('e=>e.remove()')
        campo = self.app.campo_nome(self.app.driver)
        original = self.app.esperar
        self.app.esperar = lambda fn, segundos=30: original(fn, min(segundos, 1))
        with patch.object(self.app.driver, 'get') as navigate:
            with self.assertRaisesRegex(RuntimeError, 'Tempo esgotado'):
                self.app.fechar_cadastro_pelo_x(campo)
            navigate.assert_not_called()

    def add_discard_confirmation(self, prompt='Deseja descartar as mudanças?'):
        self.page.evaluate('''prompt => {
            const close=document.querySelector('button[aria-label=Fechar]');
            const original=close.onclick;
            close.onclick=()=>{
                const modal=document.createElement('div');modal.setAttribute('role','dialog');
                modal.style='position:fixed;inset:0;background:white;z-index:1000';
                const question=document.createElement('p');question.textContent=prompt;modal.append(question);
                const cancel=document.createElement('button');cancel.textContent='Cancelar';
                cancel.onclick=()=>{window.cancelled=(window.cancelled||0)+1;modal.remove()};
                const discard=document.createElement('button');discard.textContent='Descartar';
                discard.onclick=()=>{window.discarded=(window.discarded||0)+1;original.call(close);modal.remove()};
                modal.append(cancel,discard);document.body.append(modal);
            };
        }''', prompt)

    def test_x_confirms_discard_once_then_closes_form(self):
        self.app.abrir_e_detectar(self.contact['phone'])
        self.add_discard_confirmation()
        campo = self.app.campo_nome(self.app.driver)
        with patch.object(self.app.driver, 'get') as navigate:
            self.app.fechar_cadastro_pelo_x(campo)
            navigate.assert_not_called()
        self.assertEqual(self.page.evaluate('window.discarded'), 1)
        self.assertIsNone(self.page.evaluate('window.cancelled'))
        self.assertFalse(self.page.locator('#form').is_visible())

    def test_x_does_not_discard_unrelated_confirmation(self):
        self.app.abrir_e_detectar(self.contact['phone'])
        self.add_discard_confirmation('Deseja excluir esta conversa?')
        campo = self.app.campo_nome(self.app.driver)
        original = self.app.esperar
        self.app.esperar = lambda fn, segundos=30: original(fn, min(segundos, 1))
        with self.assertRaisesRegex(RuntimeError, 'Tempo esgotado'):
            self.app.fechar_cadastro_pelo_x(campo)
        self.assertIsNone(self.page.evaluate('window.discarded'))
        self.assertTrue(self.page.locator('#form').is_visible())

    def test_recovery_discards_then_reopens_without_refresh(self):
        html = HTML.replace("menu.hidden=true;document.getElementById('form').hidden=false",
            "menu.hidden=true;document.getElementById('form').hidden=false;localStorage.opens=Number(localStorage.opens||0)+1;if(Number(localStorage.opens)===1)document.querySelector('#form button').remove()")
        self.serve(html)
        self.app.abrir_e_detectar(self.contact['phone'])
        self.add_discard_confirmation()
        original = self.app.esperar
        self.app.esperar = lambda fn, segundos=30: original(fn, min(segundos, 1))
        with patch.object(self.app.driver, 'get', side_effect=AssertionError('não deve recarregar')), patch.object(self.app, 'confirmar_aviso_cadastro', return_value=True):
            self.app.cadastrar(self.contact)
        self.assertEqual(self.page.evaluate('window.discarded'), 1)
        self.assertEqual(self.page.evaluate('localStorage.opens'), '2')
        self.assertEqual(self.app.cadastro_confirmado, self.contact['phone'])

    def test_name_keyboard_events_focus_correct_field(self):
        self.open()
        self.page.set_content('''<form><label>Nome<input aria-label="Nome" onkeydown="(window.keys||=[]).push({key:event.key,trusted:event.isTrusted})" onkeyup="window.ups=(window.ups||0)+1"></label>
        <label>Sobrenome<input aria-label="Sobrenome" value="Preservado"></label></form>''')
        self.app.digitar_nome('Ana 1234')
        self.assertEqual(self.page.locator('input[aria-label=Nome]').input_value(), 'Ana 1234')
        self.assertEqual(self.page.locator('input[aria-label=Sobrenome]').input_value(), 'Preservado')
        self.assertTrue(all(e['trusted'] for e in self.page.evaluate('window.keys')))
        self.assertGreaterEqual(self.page.evaluate('window.ups'), len('Ana 1234'))
