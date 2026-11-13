import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

import cv2
import numpy as np

from app import (App, AREAS, OBRIGATORIOS, TelaVisual, localizar_imagem, texto_comparavel)


class MatchTests(unittest.TestCase):
    def test_unique_image_found_in_correct_region(self):
        model = np.random.default_rng(1).integers(0, 255, (16, 22, 3), dtype=np.uint8)
        frame = np.full((100, 180, 3), 230, dtype=np.uint8)
        frame[40:56, 60:82] = model
        found = localizar_imagem(frame, model)
        self.assertEqual((found['x'], found['y']), (60, 40))
        self.assertIsNone(localizar_imagem(frame, model, busca=(90, 0, 180, 100)))

    def test_duplicate_is_not_clicked(self):
        model = np.random.default_rng(2).integers(0, 255, (16, 22, 3), dtype=np.uint8)
        frame = np.full((100, 180, 3), 230, dtype=np.uint8)
        frame[10:26, 20:42] = model
        frame[60:76, 100:122] = model
        with self.assertRaisesRegex(RuntimeError, 'Mais de uma'):
            localizar_imagem(frame, model)

    def test_blank_template_rejected(self):
        with self.assertRaises(ValueError):
            localizar_imagem(np.zeros((40, 40, 3), np.uint8), np.zeros((10, 10, 3), np.uint8))


class FakeDesktop:
    def __init__(self, controls, models):
        self.controls, self.models = controls, models
        self.state = 'chat'
        self.focus = None
        self.saved = False
        self.name = ''
        self.phone = '5593984108321'
        self.country = 'BR +55'
        self.draft, self.outgoing = '', ''
        self.opens = self.closes = self.discards = self.navigation = self.saves = self.sends = 0
        self.missing_save = False
        self.loading = False
        self.refuse = False
        self.rect_anterior = (0, 0, 900, 640)

    def ativar(self, marker):
        return True

    def proteger(self):
        pass

    def capturar(self):
        frame = np.full((640, 900, 3), 240, dtype=np.uint8)
        for marker, (x1,y1,x2,y2) in enumerate(((500,100,850,130),(500,180,850,220),(400,550,850,590),(400,280,850,450)), 1):
            frame[y1:y2,x1:x2] = marker * 40
        if self.loading:
            self.loading = False
            return frame
        visible = []
        if self.state in ('chat', 'menu'):
            visible += ['menu', 'conversa', 'mensagem', 'enviar']
            if self.saved:
                visible += ['salvo']
        if self.state == 'menu':
            visible += ['editar' if self.saved else 'adicionar']
        if self.state == 'form':
            visible += ['nome', 'telefone', 'telefone_ok', 'fechar']
            if not self.missing_save or self.opens > 1:
                visible += ['salvar']
        if self.state == 'discard':
            visible += ['aviso_descartar', 'descartar']
        if self.state == 'refused':
            visible += ['recusado', 'ok']
        for name in visible:
            x,y = self.controls[name]
            model = self.models[name]
            frame[y:y+model.shape[0],x:x+model.shape[1]] = model
        return frame

    def clicar(self, x, y):
        matched = [name for name, (cx,cy) in self.controls.items() if cx <= x < cx+24 and cy <= y < cy+18]
        if len(matched) != 1:
            raise AssertionError('clique inesperado')
        name = matched[0]
        if name == 'menu': self.state = 'menu'
        elif name == 'adicionar': self.state = 'form'; self.opens += 1; self.name = ''
        elif name == 'nome': self.focus = 'name'
        elif name == 'mensagem': self.focus = 'draft'
        elif name == 'salvar': self.saved = True; self.saves += 1; self.state = 'chat'
        elif name == 'enviar': self.sends += 1; self.outgoing += '\n' + self.draft; self.draft = ''
        elif name == 'fechar': self.closes += 1; self.state = 'discard'
        elif name == 'descartar': self.discards += 1; self.state = 'chat'
        elif name == 'ok': self.state = 'chat'

    def escrever(self, text, parar, limpar=True, tab=False):
        if self.focus == 'url':
            self.navigation += 1
        elif self.focus:
            setattr(self, self.focus, text)

    def atalho(self, *keys):
        if keys == (0x11, 0x4C): self.focus = 'url'
        elif keys == (0x0D,): self.state = 'refused' if self.refuse else 'chat'; self.loading = True
        elif keys == (0x1B,): self.state = 'chat'

    def ocr(self, crop):
        marker = int(crop[0,0,0])
        text = {40:self.name, 80:self.country+'\nNúmero de telefone\n'+self.phone[2:], 120:self.draft, 160:self.outgoing}.get(marker, '')
        return ([[[], text, .99]] if text else []), 0


class VisualFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.models, positions = {}, {}
        names = sorted(OBRIGATORIOS | {'salvo'})
        for i, name in enumerate(names):
            positions[name] = (20+(i%6)*55, 30+(i//6)*65)
            self.models[name] = np.random.default_rng(i+10).integers(0, 255, (18,24,3), dtype=np.uint8)
        self.desktop = FakeDesktop(positions, self.models)
        self.tela = TelaVisual(threading.Event(), lambda t: None, desktop=self.desktop, pasta=self.tmp.name, ocr=self.desktop.ocr)
        self.tela.config['tamanho'] = [900,640]
        for name, (x,y) in positions.items():
            cv2.imwrite(str(Path(self.tmp.name)/(name+'.png')), self.models[name])
            self.tela.config['controles'][name] = {'clique':[12,9], 'limite':.9, 'busca':[x-2,y-2,x+26,y+20]}
        self.tela.config['areas'] = dict(zip(AREAS, ((500,180,850,220),(500,100,850,130),(400,550,850,590),(400,280,850,450))))
        original = self.tela.aguardar
        self.tela.aguardar = lambda fn, segundos, etapa: original(fn, min(segundos, .5), etapa)
        self.app = App.__new__(App)
        self.app.driver = self.tela
        self.app.parar = self.tela.parar
        self.app.log = Mock()
        self.app.cadastro_confirmado = None
        self.app.envio_pendente = None
        self.contact = {'phone': self.desktop.phone, 'name': 'Ana 1234'}

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_contact_saves_then_sends_once(self):
        self.assertTrue(self.app.abrir_e_detectar(self.contact['phone']))
        self.app.cadastrar(self.contact)
        self.app.enviar(self.contact, 'Olá, Ana 1234!\nSegunda linha')
        self.assertEqual((self.desktop.saves, self.desktop.sends), (1,1))
        self.assertEqual(self.desktop.name, 'Ana 1234')
        self.assertIsNone(self.app.envio_pendente)

    def test_existing_skips_without_message(self):
        self.desktop.saved = True
        self.assertFalse(self.app.abrir_e_detectar(self.contact['phone']))
        self.assertEqual((self.desktop.saves, self.desktop.sends), (0,0))

    def test_missing_save_closes_x_discards_and_reopens_without_navigation(self):
        self.desktop.missing_save = True
        self.app.abrir_e_detectar(self.contact['phone'])
        navigation = self.desktop.navigation
        self.app.cadastrar(self.contact)
        self.assertEqual((self.desktop.opens, self.desktop.closes, self.desktop.discards), (2,1,1))
        self.assertEqual(self.desktop.navigation, navigation)
        self.assertEqual(self.desktop.saves, 1)

    def test_wrong_phone_blocks_save(self):
        self.app.abrir_e_detectar(self.contact['phone'])
        self.desktop.phone = '551123456789'
        with self.assertRaisesRegex(RuntimeError, 'destinatário'):
            self.app.cadastrar(self.contact)
        self.assertEqual(self.desktop.saves, 0)

    def test_draft_is_preserved_and_blocks_send(self):
        self.app.cadastro_confirmado = self.contact['phone']
        self.desktop.draft = 'Não apagar'
        with self.assertRaisesRegex(RuntimeError, 'Rascunho'):
            self.app.enviar(self.contact, 'Nova mensagem')
        self.assertEqual(self.desktop.draft, 'Não apagar')
        self.assertEqual(self.desktop.sends, 0)

    def test_old_message_is_not_confirmation_of_new_send(self):
        self.app.cadastro_confirmado = self.contact['phone']
        self.desktop.outgoing = 'Mensagem repetida'
        original = self.desktop.clicar
        def no_new_bubble(x, y):
            position = self.desktop.controls['enviar']
            if position[0] <= x < position[0]+24 and position[1] <= y < position[1]+18:
                self.desktop.sends += 1
                self.desktop.draft = ''
            else:
                original(x,y)
        self.desktop.clicar = no_new_bubble
        with self.assertRaisesRegex(RuntimeError, 'ENVIO INCERTO'):
            self.app.enviar(self.contact, 'Mensagem repetida')
        self.assertEqual(self.desktop.sends, 1)
        self.assertEqual(self.app.envio_pendente, self.contact['phone'])

    def test_missing_calibration_stops_before_clicking(self):
        self.tela.config['controles'].pop('salvar')
        with self.assertRaisesRegex(RuntimeError, 'Calibração necessária'):
            self.app.abrir_e_detectar(self.contact['phone'])
        self.assertEqual(self.desktop.navigation, 0)

    def test_window_size_change_rejected(self):
        self.tela.config['tamanho'] = [800,600]
        with self.assertRaisesRegex(RuntimeError, 'Tamanho da janela'):
            self.tela.frame()

    def test_refused_number_closes_ok_once_without_saving(self):
        from app import NumeroRecusado
        self.desktop.refuse = True
        with self.assertRaises(NumeroRecusado):
            self.app.abrir_e_detectar(self.contact['phone'])
        self.app.fechar_aviso_numero()
        self.assertEqual(self.desktop.state, 'chat')
        self.assertEqual((self.desktop.saves, self.desktop.sends), (0,0))

    def test_non_brazilian_country_blocks_even_matching_national_digits(self):
        self.app.abrir_e_detectar(self.contact['phone'])
        self.desktop.country = 'PT +351'
        with self.assertRaisesRegex(RuntimeError, 'destinatário'):
            self.app.cadastrar(self.contact)
        self.assertEqual(self.desktop.saves, 0)


class OCRTests(unittest.TestCase):
    def test_real_local_ocr_reads_phone(self):
        from PIL import Image, ImageDraw, ImageFont
        from rapidocr_onnxruntime import RapidOCR
        image = Image.new('RGB', (740,120), 'white')
        font = ImageFont.load_default(size=36)
        ImageDraw.Draw(image).text((20,30), '+55 93 98410-8321', fill='black', font=font)
        engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
        result, _ = engine(cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR))
        digits = ''.join(c for row in (result or []) for c in row[1] if c.isdigit())
        self.assertEqual(digits, '5593984108321')
