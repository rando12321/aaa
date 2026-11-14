import queue
import importlib.util
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

from app import (App,DOM_LEITURA,LeitorSelenium,TelaNativa,localizar_chromedriver)


class DriverTests(unittest.TestCase):
    def test_no_driver_is_downloaded_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('app.os.environ.get',return_value=None), patch('shutil.which',return_value=None),patch('app.Path.home',return_value=Path(tmp)):
                with self.assertRaisesRegex(RuntimeError,'não baixa nem instala'):
                    localizar_chromedriver()

    def test_viewport_maps_css_to_native_pixels(self):
        driver=Mock()
        driver.execute_script.return_value={'w':500,'h':300,'dpr':2}
        desktop=Mock()
        desktop.client_rect.return_value=(10,20,1000,700)
        desktop.dpi_scale.return_value=1
        leitor=LeitorSelenium(driver,desktop)
        viewport=leitor.viewport()
        node=leitor.elemento({'name':'Nome','kind':50004,'rect':[10,15,30,45],
            'enabled':True,'offscreen':False,'value':'','id':'','help':'','aria':'','ref':object()},viewport)
        self.assertEqual(node.rect,(30,150,70,210))

    def test_side_panel_is_rejected_before_clicking(self):
        driver=Mock()
        driver.execute_script.return_value={'w':500,'h':600,'dpr':1}
        desktop=Mock();desktop.client_rect.return_value=(0,0,1000,700)
        with self.assertRaisesRegex(RuntimeError,'painéis laterais'):
            LeitorSelenium(driver,desktop).viewport()
        desktop.clicar.assert_not_called()


HTML='''<!doctype html><meta charset="utf-8"><style>[hidden]{display:none!important}
#main header button{position:absolute;left:900px;top:30px;width:50px;height:35px}
#message{position:absolute;left:450px;top:600px;width:400px;height:35px}
#send{position:absolute;left:900px;top:600px;width:60px;height:35px}
#form{position:absolute;left:400px;top:20px;width:500px;height:600px;background:white}
#close{position:absolute;left:0;top:0;width:35px;height:35px}
#name{position:absolute;left:50px;top:80px;width:350px;height:35px}
#country{position:absolute;left:50px;top:130px}
#phone{position:absolute;left:50px;top:200px;width:350px;height:35px}
#save{position:absolute;left:400px;top:550px;width:60px;height:40px}
#action{position:absolute;left:750px;top:100px;width:220px;height:40px}
</style><div id="main"><header><button aria-label="Menu" onclick="document.querySelector('#menu').hidden=false">Menu</button></header>
<div id="messages"></div><footer><div id="message" contenteditable="true" role="textbox" aria-label="Mensagem"></div>
<button id="send" aria-label="Enviar" onclick="sendMessage()">Enviar</button></footer></div>
<div id="menu" role="menu" hidden><button id="action" role="menuitem" onclick="document.querySelector('#menu').hidden=true;document.querySelector('#form').hidden=false">Adicionar aos contatos</button></div>
<div id="form" role="dialog" hidden><span>Novo contato</span><button id="close" aria-label="Fechar" onclick="document.querySelector('#form').hidden=true">X</button>
<input id="name" aria-label="Nome" oninput="window.inputEvents=(window.inputEvents||0)+1">
<button id="country" role="combobox">BR +55</button><input id="phone" aria-label="Número de telefone" value="5593984108321">
<button id="save" aria-label="Salvar" onclick="localStorage.saved='yes';document.querySelector('#form').hidden=true;document.querySelector('#action').textContent='Editar contato';const toast=document.createElement('div');toast.setAttribute('role','status');toast.textContent='Contato salvo com sucesso';document.body.append(toast)">Salvar</button></div>
<script>
if(localStorage.saved) document.querySelector('#action').textContent='Editar contato';
document.addEventListener('keydown',e=>{if(e.key==='Escape') document.querySelector('#menu').hidden=true});
function sendMessage(){const editor=document.querySelector('#message');const row=document.createElement('div');row.className='message-out';row.dataset.id='out-'+Date.now();const text=document.createElement('span');text.className='selectable-text';text.innerText=editor.innerText;row.append(text);document.querySelector('#messages').append(row);editor.innerText='';window.sent=(window.sent||0)+1;}
</script>'''


class ReadOnlyDriver:
    def __init__(self,page):self.page=page;self.loading=False
    def convert(self,handle):
        element=handle.as_element()
        if element:return element
        if handle.evaluate('(v)=>Array.isArray(v)'):
            return [self.convert(v) for k,v in handle.get_properties().items() if k.isdigit()]
        if handle.evaluate('(v)=>v!==null && typeof v==="object"'):
            return {k:self.convert(v) for k,v in handle.get_properties().items()}
        return handle.json_value()
    def execute_script(self,script,*args):
        if script==DOM_LEITURA and self.loading:
            self.loading=False
            return []
        result=self.page.evaluate_handle('(args)=>{return(function(){'+script+'\n}).apply(null,args)}',list(args))
        return self.convert(result)
    def get(self,*args):raise AssertionError('Selenium não deve navegar')
    def click(self,*args):raise AssertionError('Selenium não deve clicar')
    def send_keys(self,*args):raise AssertionError('Selenium não deve digitar')


class NativeDesktopFixture:
    janela=123
    def __init__(self,page,driver):self.page,self.driver=page,driver;self.focus=None;self.native_clicks=self.native_keys=0;self.rect_anterior=(0,0,1000,700)
    def ativar(self,marker):return True
    def proteger(self):pass
    def rect(self):return(0,0,1000,700)
    def client_rect(self):return(0,0,1000,700)
    def dpi_scale(self):return 1
    def clicar(self,x,y):self.native_clicks+=1;self.page.mouse.click(x,y)
    def rolar(self,x,y,delta):
        self.page.mouse.move(x,y)
        self.page.mouse.wheel(0,-delta)
    def abrir_url(self,url,parar,conferir_barra=None):
        self.atalho(0x11,0x4C)
        self.escrever(url,parar)
        self.atalho(0x0D)

    def atalho(self,*keys):
        self.native_keys+=1
        if keys==(0x11,0x4C):self.focus='url'
        elif keys==(0x0D,) and self.focus=='url':
            self.page.goto(self.url);self.focus=None;self.driver.loading=True
        elif keys==(0x1B,):self.page.keyboard.press('Escape')
        elif keys==(0x09,):self.page.keyboard.press('Tab')
    def escrever(self,text,parar,limpar=True,tab=False,conferir_foco=None):
        self.native_keys+=1
        if conferir_foco and not conferir_foco():raise AssertionError('foco incorreto')
        if self.focus=='url':self.url=text;return
        if limpar:self.page.keyboard.press('Control+A');self.page.keyboard.press('Backspace')
        self.page.keyboard.insert_text(text)
        if tab:self.page.keyboard.press('Tab')


@unittest.skipUnless(importlib.util.find_spec('playwright'), 'Teste DOM opcional requer Playwright apenas no ambiente de desenvolvimento')
class DOMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import shutil
        from playwright.sync_api import sync_playwright
        cls.pw=sync_playwright().start()
        cls.browser=cls.pw.chromium.launch(executable_path=shutil.which('chromium'),headless=True)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()
    def setUp(self):
        self.context=self.browser.new_context(viewport={'width':1000,'height':700})
        self.page=self.context.new_page()
        self.page.route('https://web.whatsapp.com/**',lambda route:route.fulfill(body=HTML,content_type='text/html; charset=utf-8'))
        self.page.goto('https://web.whatsapp.com/')
        self.raw=ReadOnlyDriver(self.page)
        self.desktop=NativeDesktopFixture(self.page,self.raw)
        self.leitor=LeitorSelenium(self.raw,self.desktop)
        self.tela=TelaNativa(threading.Event(),lambda t:None,desktop=self.desktop,client=self.leitor)
        self.app=App.__new__(App);self.app.eventos=queue.Queue();self.app.driver=self.tela;self.app.parar=self.tela.parar;self.app.log=Mock();self.app.cadastro_confirmado=None;self.app.envio_pendente=None
        self.contact={'phone':'5593984108321','name':'Ana 1234'}
    def tearDown(self):self.context.close()
    def test_reader_does_not_trigger_input_or_change_page(self):
        before=self.page.content()
        self.leitor.nodes(123)
        self.assertEqual(self.page.content(),before)
        self.assertIsNone(self.page.evaluate('window.inputEvents'))
        self.assertEqual((self.desktop.native_clicks,self.desktop.native_keys),(0,0))
    def test_register_and_send_with_read_only_driver_and_native_actions(self):
        self.assertTrue(self.app.abrir_e_detectar(self.contact['phone']))
        self.app.cadastrar(self.contact)
        self.app.enviar(self.contact,'Olá, Ana 1234!\nSegunda linha')
        self.assertEqual(self.page.evaluate('window.sent'),1)
        self.assertGreater(self.desktop.native_clicks,0)
        self.assertGreater(self.desktop.native_keys,0)
    def test_saved_contact_is_skipped(self):
        self.page.evaluate("localStorage.saved='yes'")
        self.assertFalse(self.app.abrir_e_detectar(self.contact['phone']))
        self.assertIsNone(self.page.evaluate('window.sent'))

    def test_save_below_scroll_area_is_revealed_by_native_wheel(self):
        self.page.locator('#form').evaluate("e=>{e.hidden=false;e.style.height='320px';e.style.overflow='auto'}")
        self.tela.clicar(('Salvar',),5)
        self.assertEqual(self.page.evaluate('localStorage.saved'),'yes')

    def contact_info_html(self, header_fallback=False):
        html=HTML.replace("document.querySelector('#form').hidden=false", "document.querySelector('#info').hidden=false")
        html=html.replace("if(localStorage.saved) document.querySelector('#action').textContent='Editar contato';", "document.querySelector('#action').textContent='Dados do contato';")
        html+='''<aside data-testid="contact-info-drawer" id="info" hidden style="position:absolute;left:400px;top:0;width:600px;height:700px;background:white;z-index:20">
        <h2>Dados do contato</h2><p>Nome salvo diferente do CSV</p><span style="position:absolute;left:50px;top:180px">+55 93 98410-8321</span>
        <button aria-label="Menu" style="position:absolute;left:500px;top:30px;width:50px;height:35px" onclick="document.querySelector('#info-menu').hidden=false">Menu</button></aside>
        <div id="info-menu" role="menu" hidden style="position:absolute;left:750px;top:100px;z-index:30"><button role="menuitem">Editar contato</button></div>'''
        if header_fallback:
            html=html.replace("document.querySelector('#action').textContent='Dados do contato';", "document.querySelector('#action').textContent='Limpar conversa';")
            html=html.replace('<header>', '<header><span title="Nome salvo diferente do CSV" style="position:absolute;left:450px;top:30px" onclick="document.querySelector(\'#info\').hidden=false">Nome salvo diferente do CSV</span>')
        return html

    def test_existing_contact_found_in_contact_info_internal_menu(self):
        html=self.contact_info_html()
        self.page.unroute('https://web.whatsapp.com/**')
        self.page.route('https://web.whatsapp.com/**',lambda route:route.fulfill(body=html,content_type='text/html; charset=utf-8'))
        original=self.tela.aguardar
        self.tela.aguardar=lambda fn,seconds,stage:original(fn,min(seconds,5 if 'menu interno' in stage else 1),stage)
        self.assertFalse(self.app.abrir_e_detectar(self.contact['phone']))
        self.assertIsNone(self.page.evaluate('window.sent'))
        self.assertIsNone(self.page.evaluate('localStorage.saved'))

    def test_header_opens_contact_info_when_chat_menu_has_no_info_entry(self):
        html=self.contact_info_html(header_fallback=True)
        self.page.unroute('https://web.whatsapp.com/**')
        self.page.route('https://web.whatsapp.com/**',lambda route:route.fulfill(body=html,content_type='text/html; charset=utf-8'))
        original=self.tela.aguardar
        self.tela.aguardar=lambda fn,seconds,stage:original(fn,min(seconds,5 if 'menu interno' in stage else 1),stage)
        self.assertFalse(self.app.abrir_e_detectar(self.contact['phone']))
        self.assertIsNone(self.page.evaluate('window.sent'))
        self.assertIsNone(self.page.evaluate('localStorage.saved'))

    def test_profile_name_alone_does_not_prove_saved_contact(self):
        html=self.contact_info_html(header_fallback=True).replace('>Editar contato</button>','>Bloquear</button>')
        self.page.unroute('https://web.whatsapp.com/**')
        self.page.route('https://web.whatsapp.com/**',lambda route:route.fulfill(body=html,content_type='text/html; charset=utf-8'))
        self.contact['name']='Nome salvo diferente do CSV'
        original=self.tela.aguardar
        self.tela.aguardar=lambda fn,seconds,stage:original(fn,min(seconds,2),stage)
        with self.assertRaises(TimeoutError):
            self.app.abrir_e_detectar(self.contact['phone'])
        self.assertIsNone(self.page.evaluate('window.sent'))
        self.assertIsNone(self.page.evaluate('localStorage.saved'))

    def test_navigation_ready_even_if_empty_conversation_frame_was_missed(self):
        original=self.desktop.abrir_url
        def immediately_ready(*args,**kwargs):
            original(*args,**kwargs)
            self.raw.loading=False  # The conversation never appears empty to the reader.
        self.desktop.abrir_url=immediately_ready
        self.assertTrue(self.app.abrir_e_detectar(self.contact['phone']))

    def test_same_document_is_not_accepted_as_new_recipient(self):
        self.desktop.abrir_url=lambda *args,**kwargs:None  # Native navigation did not occur.
        original=self.tela.aguardar
        self.tela.aguardar=lambda fn,seconds,stage:original(fn,min(seconds,.5),stage)
        with self.assertRaisesRegex(TimeoutError,'nova página'):
            self.app.abrir_e_detectar(self.contact['phone'])
        self.assertIsNone(self.page.evaluate('window.sent'))

    def test_saved_contact_menu_div_without_button_role_is_detected(self):
        html=HTML.replace('<div id="menu" role="menu"', '<div id="menu" data-animate-dropdown-menu="true"')
        html=html.replace('<button id="action" role="menuitem"','<div id="action" tabindex="-1"')
        html=html.replace('Adicionar aos contatos</button></div>','Adicionar aos contatos</div></div>')
        self.page.unroute('https://web.whatsapp.com/**')
        self.page.route('https://web.whatsapp.com/**',lambda route:route.fulfill(body=html,content_type='text/html; charset=utf-8'))
        self.page.evaluate("localStorage.saved='yes'")
        self.assertFalse(self.app.abrir_e_detectar(self.contact['phone']))
        self.assertIsNone(self.page.evaluate('window.sent'))

    def test_saved_contact_plain_menu_text_without_tabindex_is_detected(self):
        html=HTML.replace('<div id="menu" role="menu"', '<div id="menu" data-animate-dropdown-menu="true"')
        html=html.replace('<button id="action" role="menuitem"','<div id="action" style="cursor:pointer"')
        html=html.replace('Adicionar aos contatos</button></div>','Adicionar aos contatos</div></div>')
        self.page.unroute('https://web.whatsapp.com/**')
        self.page.route('https://web.whatsapp.com/**',lambda route:route.fulfill(body=html,content_type='text/html; charset=utf-8'))
        self.page.evaluate("localStorage.saved='yes'")
        self.assertFalse(self.app.abrir_e_detectar(self.contact['phone']))
        self.assertIsNone(self.page.evaluate('window.sent'))
