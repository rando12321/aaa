import importlib.util
import shutil
import threading
import unittest
from unittest.mock import Mock
from app import App,normalizar_mensagem


@unittest.skipUnless(importlib.util.find_spec('playwright'),'Teste DOM opcional requer Playwright no desenvolvimento')
class MessageDOMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.pw=sync_playwright().start()
        cls.browser=cls.pw.chromium.launch(executable_path=shutil.which('chromium'),headless=True)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()
    def setUp(self):
        self.page=self.browser.new_page()
        self.app=App.__new__(App)
        self.app.driver=Mock();self.app.log=Mock();self.app.parar=threading.Event()
        self.field=Mock()
        def execute(script,*args):
            values=[self.page.locator('#editor').element_handle() if arg is self.field else arg for arg in args]
            return self.page.evaluate('(args)=>{return(function(){'+script+'}).apply(null,args)}',values)
        self.app.driver.execute_script.side_effect=execute
    def tearDown(self):self.page.close()

    def test_confirmation_reads_message_id_and_multiline_text(self):
        self.page.set_content('<div id="main"><div data-id="unique-id" class="message-out"><span class="selectable-text">Olá, Ana!<br>Segunda linha</span></div></div>')
        self.assertEqual(self.app.mensagens_saida(),{'unique-id':'Olá, Ana!\nSegunda linha'})

    def test_editor_images_nbsp_and_blank_paragraphs_preserve_message(self):
        self.page.set_content('<div id="editor" contenteditable="true"><p>Olá&nbsp;Ana<img alt=" 👩‍💻"><br></p><p><br></p><p>Segunda linha</p></div>')
        self.assertEqual(self.app.ler_mensagem(self.field),'Olá Ana 👩‍💻\n\nSegunda linha')

    def test_browser_insert_multiline_emoji_then_confirm_actual_outgoing(self):
        self.page.set_content(r'''<div id="main"><div id="messages"></div><footer><div id="editor" contenteditable="true" role="textbox"></div></footer></div>
        <script>const editor=document.querySelector('#editor');let model='';editor.addEventListener('input',e=>{if(e.inputType==='insertText')model+=e.data===null?'\n':e.data;});editor.addEventListener('keydown',e=>{
            if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();const row=document.createElement('div');row.className='message-out';row.dataset.id='new-id';
            const text=document.createElement('span');text.className='selectable-text';text.innerText=model;window.lastSentText=model;model='';row.append(text);document.querySelector('#messages').append(row);editor.replaceChildren();window.sent=(window.sent||0)+1;}
        });</script>''')
        self.field.click.side_effect=lambda:self.page.locator('#editor').click()
        self.field.send_keys.side_effect=lambda key:self.page.keyboard.press('Enter')
        self.app.campo_mensagem=Mock(return_value=self.field)
        def insert(command,args):
            self.assertEqual(command,'Input.insertText')
            self.page.keyboard.insert_text(args['text'])
        self.app.driver.execute_cdp_cmd.side_effect=insert
        self.app.numero_atual='5593984108321';self.app.envio_incerto=False
        text='Olá 👩‍💻!\n\nSegunda linha'
        self.app.enviar({'phone':self.app.numero_atual,'name':'Ana'},text)
        self.assertEqual(self.page.evaluate('window.sent'),1)
        self.assertEqual(self.page.evaluate('window.lastSentText'),text)
        self.assertEqual(self.app.mensagens_saida(),{'new-id':normalizar_mensagem(text)})
