import ast
import ctypes
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from app import (App, Elemento, RECT, POINT, NativeUIError,
                 TelaNativa, correspondencia_nomes, gravar_bmp)


class BindingTests(unittest.TestCase):
    def test_no_extra_graphics_or_input_packages(self):
        source = Path(__file__).resolve().parents[1] / 'app.py'
        tree = ast.parse(source.read_text())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add(node.module.split('.')[0])
        self.assertTrue(names <= sys.stdlib_module_names | {'selenium'}, names - sys.stdlib_module_names - {'selenium'})

    def test_windows_abi_layout(self):
        self.assertEqual(ctypes.sizeof(RECT), 16)
        self.assertEqual(ctypes.sizeof(POINT), 8)

    def test_bmp_writer_without_pillow(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'test.bmp'
            pixels = b'\x00\x00\xff\x00' * 4
            gravar_bmp(path,2,2,pixels)
            data = path.read_bytes()
            self.assertEqual(data[:2], b'BM')
            self.assertEqual(int.from_bytes(data[2:6],'little'),len(data))
            self.assertEqual(data[54:],pixels)
            with self.assertRaises(ValueError):
                gravar_bmp(path,2,2,b'')

    def test_disabled_or_offscreen_controls_excluded(self):
        candidates = [Elemento('Salvar',50000,(0,0,20,20),False),
                      Elemento('Salvar',50000,(0,0,20,20),True,True),
                      Elemento('Salvar',50020,(0,0,20,20)),
                      Elemento('Salvar',50000,(0,0,20,20))]
        self.assertEqual(correspondencia_nomes(candidates,['Salvar'],(50000,)),[candidates[-1]])

    def test_required_field_label_is_recognized(self):
        field=Elemento('Nome *',50004,(400,100,800,130),valor='')
        self.assertEqual(correspondencia_nomes([field],['Nome'],(50004,)),[field])


class FakeDesktop:
    janela = 123
    def __init__(self):
        self.state = 'chat'
        self.saved = False
        self.name = ''
        self.phone = '5593984108321'
        self.country = 'BR +55'
        self.draft = ''
        self.messages = []
        self.focus = None
        self.opens = self.closes = self.discards = self.saves = self.sends = self.navigation = 0
        self.hide_save_first = False
        self.invalid = False
        self.loading = False
        self.toast = False
        self.refuse = False
        self.render_sent = True
        self.ui = None
        self.rect_anterior = (0,0,1000,700)

    def ativar(self, marker): return True
    def proteger(self): pass
    def rect(self): return (0,0,1000,700)

    def clicar(self,x,y):
        candidates = [e for e in self.ui.nodes(self.janela) if e.tipo in (50000,50004,50011)
                      and e.rect[0]<=x<e.rect[2] and e.rect[1]<=y<e.rect[3]]
        if len(candidates)!=1:
            raise AssertionError(f'clique não identificado: {x},{y}')
        name = candidates[0].nome
        if name=='Menu': self.state='menu'
        elif name=='Adicionar aos contatos': self.state='form';self.opens+=1;self.name='';self.toast=False
        elif name=='Nome': self.focus='name'
        elif name=='Mensagem': self.focus='draft'
        elif name=='Salvar': self.saved=True;self.saves+=1;self.state='chat';self.toast=True
        elif name=='Fechar': self.closes+=1;self.state='discard'
        elif name=='Descartar': self.discards+=1;self.state='chat'
        elif name=='Enviar':
            self.sends+=1
            if self.render_sent:self.messages.append(self.draft)
            self.draft=''
        elif name=='OK':self.state='chat';self.refuse=False

    def abrir_url(self,url,parar,conferir_barra=None):
        self.atalho(0x11,0x4C)
        self.escrever(url,parar)
        self.atalho(0x0D)

    def atalho(self,*keys):
        if keys==(0x11,0x4C):self.focus='url'
        elif keys==(0x0D,):self.loading=True;self.state='refused' if self.refuse else 'chat';self.toast=False
        elif keys==(0x1B,):self.state='chat'
        elif keys==(0x09,):self.focus=None

    def escrever(self,text,parar,limpar=True,tab=False,conferir_foco=None):
        if conferir_foco and not conferir_foco():raise RuntimeError('sem foco')
        if self.focus=='url':self.navigation+=1
        elif self.focus:setattr(self,self.focus,text)
        if tab:self.focus=None


class FakeUIA:
    def __init__(self, desktop):
        self.desktop=desktop;desktop.ui=self
        self.block_hit=False

    def nodes(self,hwnd):
        d=self.desktop
        if d.loading:
            d.loading=False
            return []
        result=[]
        def add(name,kind,rect,value=None,aid='',aria=''):
            result.append(Elemento(name,kind,rect,valor=value,automation_id=aid,aria=aria))
        if d.state in ('chat','menu'):
            add('Menu',50000,(900,30,950,65))
            add('Mensagem',50004,(450,600,850,640),d.draft)
            add('Enviar',50000,(900,600,950,640))
            if d.state=='menu':add('Editar contato' if d.saved else 'Adicionar aos contatos',50011,(750,100,970,140))
            if d.toast:add('Contato salvo com sucesso',50020,(500,450,800,480))
            for i,msg in enumerate(d.messages):add('Você: '+msg,50026,(450,400+i*30,800,425+i*30),aid='message-out-'+str(i))
        if d.state in ('form','discard'):
            add('Novo contato',50020,(450,25,650,60))
            add('Fechar',50000,(400,25,435,60))
            add('Nome',50004,(450,100,850,135),d.name)
            add(d.country,50003,(450,150,560,180))
            add('Número de telefone',50004,(450,220,850,255),d.phone,aria='invalid:true' if d.invalid else '')
            if not d.hide_save_first or d.opens>1:add('Salvar',50000,(800,600,860,650))
        if d.state=='discard':
            add('Deseja descartar as mudanças?',50032,(400,300,900,550))
            add('Descartar',50000,(750,480,860,520))
        if d.state=='refused':
            add('O número de telefone é inválido',50020,(450,200,850,240))
            add('OK',50000,(750,300,800,340))
        return result

    def refresh(self,e):
        for atual in self.nodes(123):
            if atual.nome==e.nome and atual.tipo==e.tipo:return atual
        raise NativeUIError('controle saiu da tela')

    def hit_test(self,e):return not self.block_hit
    def focused(self,e):return self.desktop.focus=={'Nome':'name','Mensagem':'draft'}.get(e.nome)


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.desktop=FakeDesktop()
        self.client=FakeUIA(self.desktop)
        self.tela=TelaNativa(threading.Event(),lambda t:None,desktop=self.desktop,client=self.client)
        original=self.tela.aguardar
        self.tela.aguardar=lambda fn,segundos,etapa:original(fn,min(segundos,.5),etapa)
        self.app=App.__new__(App)
        self.app.driver=self.tela
        self.app.parar=self.tela.parar
        self.app.log=Mock()
        self.app.cadastro_confirmado=None
        self.app.envio_pendente=None
        self.contact={'phone':self.desktop.phone,'name':'Ana 1234'}

    def test_new_contact_saves_then_sends_once(self):
        self.assertTrue(self.app.abrir_e_detectar(self.contact['phone']))
        self.app.cadastrar(self.contact)
        self.app.enviar(self.contact,'Olá, Ana 1234!\nSegunda linha')
        self.assertEqual((self.desktop.saves,self.desktop.sends),(1,1))
        self.assertEqual(self.desktop.name,self.contact['name'])
        self.assertIsNone(self.app.envio_pendente)

    def test_existing_contact_skips_without_send(self):
        self.desktop.saved=True
        self.assertFalse(self.app.abrir_e_detectar(self.contact['phone']))
        self.assertEqual((self.desktop.saves,self.desktop.sends),(0,0))

    def test_missing_save_uses_x_discard_without_page_navigation(self):
        self.desktop.hide_save_first=True
        self.app.abrir_e_detectar(self.contact['phone'])
        before=self.desktop.navigation
        self.app.cadastrar(self.contact)
        self.assertEqual((self.desktop.opens,self.desktop.closes,self.desktop.discards),(2,1,1))
        self.assertEqual(self.desktop.navigation,before)
        self.assertEqual(self.desktop.saves,1)

    def test_invalid_field_reopens_once_without_saving(self):
        self.desktop.invalid=True
        self.app.abrir_e_detectar(self.contact['phone'])
        with self.assertRaisesRegex(RuntimeError,'já foi reaberto'):
            self.app.cadastrar(self.contact)
        self.assertEqual(self.desktop.opens,2)
        self.assertEqual(self.desktop.saves,0)

    def test_wrong_phone_cannot_be_saved(self):
        self.app.abrir_e_detectar(self.contact['phone'])
        self.desktop.phone='551123456789'
        with self.assertRaisesRegex(RuntimeError,'telefone'):
            self.app.cadastrar(self.contact)
        self.assertEqual(self.desktop.saves,0)

    def test_existing_draft_is_preserved(self):
        self.app.cadastro_confirmado=self.contact['phone']
        self.desktop.draft='Não apagar'
        with self.assertRaisesRegex(RuntimeError,'rascunho'):
            self.app.enviar(self.contact,'Outra mensagem')
        self.assertEqual(self.desktop.draft,'Não apagar')
        self.assertEqual(self.desktop.sends,0)

    def test_uncertain_send_not_repeated(self):
        self.app.cadastro_confirmado=self.contact['phone']
        self.desktop.render_sent=False
        with self.assertRaisesRegex(RuntimeError,'ENVIO INCERTO'):
            self.app.enviar(self.contact,'Mensagem')
        with self.assertRaisesRegex(RuntimeError,'envio incerto'):
            self.app.enviar(self.contact,'Mensagem')
        self.assertEqual(self.desktop.sends,1)

    def test_refused_number_closes_ok(self):
        from app import NumeroRecusado
        self.desktop.refuse=True
        with self.assertRaises(NumeroRecusado):self.app.abrir_e_detectar(self.contact['phone'])
        self.app.fechar_aviso_numero()
        self.assertEqual(self.desktop.state,'chat')
        self.assertEqual((self.desktop.saves,self.desktop.sends),(0,0))

    def test_ambiguous_menu_action_is_not_clicked(self):
        nodes=[Elemento('Salvar',50000,(400,500,450,530)),Elemento('Salvar',50000,(500,500,550,530))]
        with self.assertRaisesRegex(RuntimeError,'ambíguo'):
            self.tela.buscar(('Salvar',),elementos=nodes)

    def test_covered_button_does_not_receive_click(self):
        self.client.block_hit=True
        with self.assertRaisesRegex(RuntimeError,'coberto'):
            self.tela.clicar(('Menu',))
        self.assertEqual(self.desktop.state,'chat')

    def test_unrelated_visible_number_cannot_validate_wrong_form_phone(self):
        self.app.abrir_e_detectar(self.contact['phone'])
        self.desktop.phone='551123456789'
        original=self.client.nodes
        def decoy(hwnd):
            return original(hwnd)+[Elemento('BR +55 '+self.contact['phone'],50020,(450,400,800,430))]
        self.client.nodes=decoy
        self.assertFalse(self.tela.telefone_confirmado(self.contact['phone']))
