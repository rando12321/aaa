"""WhatsApp visual: OpenCV + OCR local + Windows SendInput. Sem WebDriver.
Instale: python -m pip install -r requirements.txt
Abra o Chrome normal, conecte a janela e calibre os controles antes de iniciar.
"""
import csv
import ctypes
import json
import os
import queue
import random
import re
import secrets
import threading
import time
import tkinter as tk
import unicodedata
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlencode

import cv2
import numpy as np
from PIL import Image, ImageGrab

VERSAO = '2026.11.13-v16-opencv-windows-sem-webdriver'
IGNORADOS = {'11999999999', '5511999999999'}

class NumeroRecusado(Exception):
    pass


def normalizar(texto):
    texto = "".join(
        c for c in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(c)
    )
    return " ".join(texto.lower().split())


def digitos(texto):
    return re.sub(r"[^0-9]", "", texto)


def numero_brasileiro(valor):
    original = valor.strip()

    if not re.fullmatch(r"\+?[0-9\s().-]+", original):
        raise ValueError(
            f"Telefone inválido: {valor}. "
            "Use texto sem fórmulas ou notação científica."
        )

    numero = digitos(original)

    # DDD + telefone: acrescenta 55 completo.
    if len(numero) in (10, 11):
        return "55" + numero

    # Já contém o código brasileiro e está completo.
    if len(numero) in (12, 13) and numero.startswith("55"):
        return numero

    raise ValueError(
        f"Telefone brasileiro inválido: {valor}. "
        "Informe DDD + telefone ou 55 + DDD + telefone."
    )


def literal(texto):
    if "'" not in texto:
        return "'" + texto + "'"

    if '"' not in texto:
        return '"' + texto + '"'

    partes = ["'" + parte + "'" for parte in texto.split("'")]
    return "concat(" + ', "\'", '.join(partes) + ")"


def gerar_nome():
    primeiro = secrets.choice(
        ("Lucas", "Ana", "Marina", "Pedro", "Clara", "Rafael")
    )
    return f"{primeiro} {secrets.randbelow(10000):04d}"


def ler_csv(caminho):
    contatos = []
    vistos = set()
    ignorados = 0

    with open(caminho, encoding="utf-8-sig", newline="") as arquivo:
        amostra = arquivo.read(4096)
        arquivo.seek(0)

        try:
            formato = csv.Sniffer().sniff(
                amostra, delimiters=",;"
            )
        except csv.Error:
            formato = csv.excel

        leitor = csv.DictReader(arquivo, dialect=formato)
        leitor.fieldnames = [
            coluna.strip().lower()
            for coluna in (leitor.fieldnames or [])
        ]

        if not {"phone", "name"}.issubset(leitor.fieldnames):
            raise ValueError(
                "O CSV precisa das colunas phone e name."
            )

        for linha, registro in enumerate(leitor, 2):
            original = (registro.get("phone") or "").strip()
            nome = (registro.get("name") or "").strip()

            if not original and not nome:
                continue

            if digitos(original) in IGNORADOS:
                ignorados += 1
                continue

            try:
                numero = numero_brasileiro(original)
            except ValueError as erro:
                raise ValueError(
                    f"Linha {linha}: {erro}"
                ) from erro

            if numero in IGNORADOS:
                ignorados += 1
                continue

            if numero in vistos:
                continue

            vistos.add(numero)
            contatos.append({
                "original": original,
                "phone": numero,
                "name": nome or gerar_nome(),
                "nome_gerado": not nome,
            })

    if not contatos:
        raise ValueError(
            "Nenhum contato disponível após remover "
            "números ignorados e duplicados."
        )

    # Keep generated names short and unique, without modifying names from CSV.
    reservados = {c["name"] for c in contatos if not c["nome_gerado"]}
    for indice, contato in enumerate(contatos, 1):
        if contato["nome_gerado"]:
            candidato = contato["name"]
            contador = indice
            while candidato in reservados:
                candidato = f"{contato['name'].split()[0]} {contador:04d}"
                contador += 1
            contato["name"] = candidato
            reservados.add(candidato)
    nomes = [contato["name"] for contato in contatos]

    if len(nomes) != len(set(nomes)):
        raise ValueError(
            "Use nomes diferentes para cada contato."
        )

    return contatos, ignorados


def sistema_windows():
    return os.name == 'nt'


class TecladoWindows:
    """Windows SendInput. No stealth claims; injection remains observable by Windows."""
    @staticmethod
    def tipos_entrada():
        import ctypes
        WORD, DWORD, LONG = ctypes.c_uint16, ctypes.c_uint32, ctypes.c_int32
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [('wVk', WORD), ('wScan', WORD), ('dwFlags', DWORD), ('time', DWORD), ('dwExtraInfo', ctypes.c_size_t)]
        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [('dx', LONG), ('dy', LONG), ('mouseData', DWORD), ('dwFlags', DWORD), ('time', DWORD), ('dwExtraInfo', ctypes.c_size_t)]
        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [('uMsg', DWORD), ('wParamL', WORD), ('wParamH', WORD)]
        class PAYLOAD(ctypes.Union):
            _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT), ('hi', HARDWAREINPUT)]
        class INPUT(ctypes.Structure):
            _anonymous_ = ('payload',)
            _fields_ = [('type', DWORD), ('payload', PAYLOAD)]
        return INPUT

    def __init__(self):
        import ctypes
        if not sistema_windows():
            raise RuntimeError('SendInput requer Windows.')
        self.ctypes = ctypes
        self.INPUT = self.tipos_entrada()
        self.api = ctypes.WinDLL('user32', use_last_error=True)
        self.enum_callback = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_ssize_t)
        self.api.EnumWindows.argtypes = [self.enum_callback, ctypes.c_ssize_t]
        self.api.EnumWindows.restype = ctypes.c_int
        self.api.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        self.api.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        self.api.IsWindowVisible.argtypes = [ctypes.c_void_p]
        self.api.GetForegroundWindow.restype = ctypes.c_void_p
        self.api.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        self.api.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.api.SendInput.argtypes = [ctypes.c_uint32, ctypes.POINTER(self.INPUT), ctypes.c_int]
        self.api.SendInput.restype = ctypes.c_uint32
        self.janela = None

    def ativar(self, marcador):
        encontrados = []
        @self.enum_callback
        def janela(hwnd, extra):
            titulo = self.ctypes.create_unicode_buffer(1024)
            classe = self.ctypes.create_unicode_buffer(256)
            self.api.GetWindowTextW(hwnd, titulo, len(titulo))
            self.api.GetClassNameW(hwnd, classe, len(classe))
            if self.api.IsWindowVisible(hwnd) and classe.value.startswith('Chrome_WidgetWin') and marcador in titulo.value:
                encontrados.append(hwnd)
            return 1
        self.api.EnumWindows(janela, 0)
        if len(encontrados) != 1:
            return False
        self.janela = encontrados[0]
        if not self.em_primeiro_plano():
            self.api.ShowWindow(self.janela, 9)
            self.api.SetForegroundWindow(self.janela)
        return self.em_primeiro_plano()

    def em_primeiro_plano(self):
        return bool(self.janela) and self.api.GetForegroundWindow() == self.janela

    def enviar(self, eventos, conferir_foco):
        if not self.em_primeiro_plano() or not conferir_foco():
            raise RuntimeError('Chrome perdeu o primeiro plano ou o campo Nome perdeu o foco. Digitação nativa interrompida.')
        entradas = (self.INPUT * len(eventos))()
        for entrada, (vk, scan, flags) in zip(entradas, eventos):
            entrada.type = 1
            entrada.ki.wVk, entrada.ki.wScan, entrada.ki.dwFlags = vk, scan, flags
        total = self.api.SendInput(len(entradas), entradas, self.ctypes.sizeof(self.INPUT))
        if total != len(entradas):
            # Release Control if Windows accepted only part of the shortcut.
            soltar = self.INPUT()
            soltar.type, soltar.ki.wVk, soltar.ki.dwFlags = 1, 0x11, 2
            self.api.SendInput(1, self.ctypes.byref(soltar), self.ctypes.sizeof(self.INPUT))
            raise RuntimeError('Windows recusou parte das teclas nativas. Confira a janela e suas permissões.')

    def digitar(self, nome, parar, conferir_foco):
        if parar.is_set():
            raise InterruptedError()
        self.enviar([(0x11, 0, 0), (0x41, 0, 0), (0x41, 0, 2), (0x11, 0, 2), (0x08, 0, 0), (0x08, 0, 2)], conferir_foco)
        for caractere in nome:
            if parar.is_set():
                raise InterruptedError()
            utf16 = caractere.encode('utf-16-le')
            eventos = []
            for indice in range(0, len(utf16), 2):
                unidade = int.from_bytes(utf16[indice:indice + 2], 'little')
                eventos.extend([(0, unidade, 4), (0, unidade, 6)])
            self.enviar(eventos, conferir_foco)
            if parar.wait(0.12):
                raise InterruptedError()
        if parar.is_set():
            raise InterruptedError()
        self.enviar([(0x09, 0, 0), (0x09, 0, 2)], conferir_foco)


VISUAL_DIR = Path(__file__).resolve().parent / '.local' / 'opencv'
CONTROLES = {
    'menu': 'Três pontos da conversa', 'adicionar': 'Adicionar aos contatos',
    'editar': 'Editar contato', 'criar': 'Criar contato (se existir)',
    'nome': 'Campo Nome (capturar rótulo estável; clicar onde digitar)',
    'telefone': 'Campo telefone (capturar rótulo; clicar onde digitar)',
    'telefone_ok': '✓ verde de telefone válido (não é Salvar)',
    'salvar': 'Salvar / círculo ✓ inferior', 'fechar': 'X ao lado de Novo contato',
    'aviso_descartar': 'Pergunta Deseja descartar as mudanças?', 'descartar': 'Botão Descartar',
    'conversa': 'Conversa aberta (ícone estável no rodapé)',
    'mensagem': 'Campo de mensagem (rótulo/ícone estável)', 'enviar': 'Botão Enviar',
    'recusado': 'Aviso de número inválido/não está no WhatsApp', 'ok': 'OK do aviso de número',
    'salvo': 'Notificação Contato salvo (opcional)', 'dados': 'Dados do contato (opcional)',
    'menu_dados': 'Menu nos dados do contato (opcional)',
}
AREAS = {
    'telefone_lido': 'Região contendo país +55 e valor do telefone no formulário',
    'nome_lido': 'Região só do valor digitado no Nome (sem o rótulo)',
    'rascunho_lido': 'Região do texto do rascunho (sem rótulos/ícones)',
    'saida_lida': 'Região das últimas mensagens de saída',
}
OBRIGATORIOS = {'menu', 'adicionar', 'editar', 'nome', 'telefone', 'salvar', 'fechar',
                'aviso_descartar', 'descartar', 'telefone_ok', 'conversa', 'mensagem', 'enviar', 'recusado', 'ok'}


def texto_comparavel(texto):
    return ' '.join(unicodedata.normalize('NFC', texto).split())


def localizar_imagem(frame, modelo, limite=0.90, busca=None):
    """Unique match within a calibrated region; ambiguity is never clicked."""
    cinza, alvo = frame, modelo
    if frame.ndim != modelo.ndim:
        cinza = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        alvo = cv2.cvtColor(modelo, cv2.COLOR_BGR2GRAY) if modelo.ndim == 3 else modelo
    detalhe = float(alvo.std(axis=(0, 1)).mean()) if alvo.ndim == 3 else float(alvo.std())
    if alvo.size == 0 or detalhe < 3:
        raise ValueError('Modelo sem detalhe suficiente. Capture rótulo, borda ou ícone completo.')
    h, w = cinza.shape[:2]
    if busca:
        x1, y1, x2, y2 = [int(v) for v in busca]
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
    else:
        x1, y1, x2, y2 = 0, 0, w, h
    regiao = cinza[y1:y2, x1:x2]
    th, tw = alvo.shape[:2]
    if th > regiao.shape[0] or tw > regiao.shape[1]:
        return None
    scores = cv2.matchTemplate(regiao, alvo, cv2.TM_CCOEFF_NORMED)
    _, melhor, _, (x, y) = cv2.minMaxLoc(scores)
    if not np.isfinite(melhor) or melhor < limite:
        return None
    diferenca = float(cv2.absdiff(regiao[y:y+th, x:x+tw], alvo).mean())
    if diferenca > 22:
        return None
    outros = scores.copy()
    outros[max(0, y-th//2):y+th//2+1, max(0, x-tw//2):x+tw//2+1] = -1
    if outros.size and float(outros.max()) >= limite:
        raise RuntimeError('Mais de uma correspondência visual. Reduza a região de busca na calibração.')
    return {'x': x+x1, 'y': y+y1, 'score': float(melhor), 'w': tw, 'h': th}


class DesktopWindows(TecladoWindows):
    def __init__(self):
        super().__init__()
        self.api.GetWindowRect.argtypes = [self.ctypes.c_void_p, self.ctypes.c_void_p]
        self.api.GetSystemMetrics.argtypes = [self.ctypes.c_int]
        self.rect_anterior = None

    def rect(self):
        c = self.ctypes
        class RECT(c.Structure):
            _fields_ = [('left', c.c_int32), ('top', c.c_int32), ('right', c.c_int32), ('bottom', c.c_int32)]
        r = RECT()
        if not self.api.GetWindowRect(self.janela, c.byref(r)):
            raise RuntimeError('Não foi possível ler a janela do Chrome.')
        return r.left, r.top, r.right, r.bottom

    def proteger(self):
        if not self.em_primeiro_plano():
            raise RuntimeError('Chrome perdeu o primeiro plano. Interrompido para não clicar/digitar em outra janela.')

    def capturar(self):
        self.proteger()
        self.rect_anterior = self.rect()
        shot = ImageGrab.grab(bbox=self.rect_anterior, all_screens=True).convert('RGB')
        return cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2BGR)

    def clicar(self, x, y):
        self.proteger()
        if self.rect() != self.rect_anterior:
            raise RuntimeError('A janela foi movida após a captura. Execute novamente para obter posições atualizadas.')
        left, top, right, bottom = self.rect_anterior
        if not (0 <= x < right-left and 0 <= y < bottom-top):
            raise RuntimeError('Ponto de clique fora da janela calibrada.')
        vx, vy = self.api.GetSystemMetrics(76), self.api.GetSystemMetrics(77)
        vw, vh = self.api.GetSystemMetrics(78), self.api.GetSystemMetrics(79)
        if vw <= 1 or vh <= 1:
            raise RuntimeError('Dimensões inválidas da área de trabalho.')
        entradas = (self.INPUT * 3)()
        for e in entradas:
            e.type = 0
        entradas[0].mi.dx = round((left+x-vx) * 65535 / (vw-1))
        entradas[0].mi.dy = round((top+y-vy) * 65535 / (vh-1))
        entradas[0].mi.dwFlags = 0x8000 | 0x4000 | 0x0001
        entradas[1].mi.dwFlags, entradas[2].mi.dwFlags = 0x0002, 0x0004
        if self.api.SendInput(3, entradas, self.ctypes.sizeof(self.INPUT)) != 3:
            soltar = self.INPUT()
            soltar.type, soltar.mi.dwFlags = 0, 0x0004
            self.api.SendInput(1, self.ctypes.byref(soltar), self.ctypes.sizeof(self.INPUT))
            raise RuntimeError('Windows recusou parte do clique nativo. Não repetir sem conferir a tela.')

    def atalho(self, *teclas):
        eventos = [(t, 0, 0) for t in teclas] + [(t, 0, 2) for t in reversed(teclas)]
        self.enviar(eventos, self.em_primeiro_plano)

    def escrever(self, texto, parar, limpar=True, tab=False):
        if limpar:
            self.atalho(0x11, 0x41)
            self.atalho(0x08)
        for caractere in texto:
            if parar.is_set():
                raise InterruptedError()
            if caractere == '\n':
                self.atalho(0x10, 0x0D)
            else:
                raw = caractere.encode('utf-16-le')
                eventos = []
                for i in range(0, len(raw), 2):
                    unidade = int.from_bytes(raw[i:i+2], 'little')
                    eventos.extend([(0, unidade, 4), (0, unidade, 6)])
                self.enviar(eventos, self.em_primeiro_plano)
            if parar.wait(0.09):
                raise InterruptedError()
        if tab:
            self.atalho(0x09)


class TelaVisual:
    def __init__(self, parar, log, desktop=None, pasta=VISUAL_DIR, ocr=None):
        self.parar, self.log = parar, log
        self.desktop = desktop if desktop is not None else DesktopWindows()
        self.pasta = Path(pasta)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.arquivo = self.pasta / 'calibracao.json'
        self.config = json.loads(self.arquivo.read_text(encoding='utf-8')) if self.arquivo.exists() else {'controles': {}, 'areas': {}}
        self.ocr = ocr
        self.modelos = {}

    def conectar(self):
        if not self.desktop.ativar('WhatsApp'):
            raise RuntimeError('Deixe uma única janela do Chrome com a aba WhatsApp ativa e tente conectar novamente.')
        return self.desktop.capturar()

    def frame(self):
        if self.parar.is_set():
            raise InterruptedError()
        frame = self.desktop.capturar()
        esperado = self.config.get('tamanho')
        if esperado and [frame.shape[1], frame.shape[0]] != esperado:
            raise RuntimeError('Tamanho da janela mudou. Restaure o tamanho usado na calibração ou calibre novamente.')
        return frame

    def validar(self):
        faltam = sorted(OBRIGATORIOS - self.config['controles'].keys())
        faltam += sorted(AREAS.keys() - self.config['areas'].keys())
        if faltam:
            raise RuntimeError('Calibração necessária antes do lote: ' + ', '.join(faltam))

    def aguardar(self, funcao, segundos, etapa):
        fim = time.monotonic() + segundos
        while time.monotonic() < fim:
            if self.parar.is_set():
                raise InterruptedError()
            resultado = funcao()
            if resultado:
                return resultado
            if self.parar.wait(0.2):
                raise InterruptedError()
        raise TimeoutError('Tempo esgotado: ' + etapa)

    def localizar(self, nome, frame=None):
        cfg = self.config['controles'].get(nome)
        if not cfg:
            return None
        frame = self.frame() if frame is None else frame
        if nome not in self.modelos:
            imagem = cv2.imread(str(self.pasta / (nome + '.png')))
            if imagem is None:
                raise RuntimeError('Modelo ausente ou ilegível: ' + nome)
            self.modelos[nome] = imagem
        return localizar_imagem(frame, self.modelos[nome], cfg.get('limite', 0.90), cfg['busca'])

    def clicar(self, nome, segundos=10):
        def acao():
            frame = self.frame()
            match = self.localizar(nome, frame)
            if match:
                cfg = self.config['controles'][nome]
                self.desktop.clicar(match['x']+cfg['clique'][0], match['y']+cfg['clique'][1])
                self.log(f'OpenCV: {nome} identificado ({match["score"]:.3f}); clique nativo.')
                return True
            return False
        return self.aguardar(acao, segundos, 'localizar ' + nome)

    def ler(self, area, frame=None):
        if area not in self.config['areas']:
            raise RuntimeError('Região OCR não calibrada: ' + area)
        frame = self.frame() if frame is None else frame
        x1, y1, x2, y2 = self.config['areas'][area]
        crop = frame[y1:y2, x1:x2]
        if not crop.size:
            raise RuntimeError('Região OCR vazia: ' + area)
        if self.ocr is None:
            from rapidocr_onnxruntime import RapidOCR
            self.ocr = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
        result, _ = self.ocr(crop)
        textos = [str(row[1]) for row in (result or []) if float(row[2]) >= 0.85]
        return '\n'.join(textos)

    def escrever_campo(self, alvo, texto, area):
        self.clicar(alvo)
        self.desktop.escrever(texto, self.parar, tab=True)
        self.aguardar(lambda: texto_comparavel(self.ler(area)) == texto_comparavel(texto), 5, 'conferir texto em ' + alvo)

    def abrir_numero(self, numero):
        self.desktop.proteger()
        self.desktop.atalho(0x11, 0x4C)
        self.desktop.escrever('https://web.whatsapp.com/send?' + urlencode({'phone': numero}), self.parar)
        self.desktop.atalho(0x0D)
        # Do not mistake the old conversation still visible during navigation for readiness.
        self.aguardar(lambda: self.localizar('conversa') is None, 15, 'a conversa anterior sair da tela')
        def resposta():
            frame = self.frame()
            if self.localizar('recusado', frame):
                return 'recusado'
            return 'conversa' if self.localizar('conversa', frame) else False
        return self.aguardar(resposta, 90, 'abrir destinatário ou exibir recusa')

    def estado_contato(self):
        self.clicar('menu')
        def estado():
            frame = self.frame()
            editar, adicionar = self.localizar('editar', frame), self.localizar('adicionar', frame)
            if editar and adicionar:
                raise RuntimeError('Menu ambíguo: Adicionar e Editar foram encontrados ao mesmo tempo.')
            return 'existente' if editar else ('novo' if adicionar else False)
        try:
            return self.aguardar(estado, 5, 'Adicionar ou Editar contato')
        except TimeoutError:
            if 'dados' not in self.config['controles']:
                raise
            self.clicar('dados')
            if 'menu_dados' in self.config['controles']:
                self.clicar('menu_dados')
            return self.aguardar(estado, 10, 'Adicionar/Editar nos dados do contato')

    def fechar_formulario(self):
        self.clicar('fechar', 5)
        descartou = False
        def fechado():
            nonlocal descartou
            frame = self.frame()
            if self.localizar('aviso_descartar', frame):
                if not descartou:
                    self.clicar('descartar', 5)
                    descartou = True
                return False
            return self.localizar('nome', frame) is None
        self.aguardar(fechado, 10, 'fechar formulário pelo X/Descartar')
        self.log('Formulário fechado pelo X e Descartar, sem recarregar a página.')

    def save_screenshot(self, destino):
        return cv2.imwrite(str(destino), self.desktop.capturar())

    def quit(self):
        # The user's normal Chrome window is not owned by this application.
        pass


class Calibracao(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title('Calibração OpenCV — janela, escala e tema fixos')
        self.geometry('760x300')
        ttk.Label(self, text='Abra manualmente a tela/menu no Chrome. Escolha o controle ou área e clique Capturar.\nPara botões: selecione uma imagem estável e depois o ponto exato do clique.\nPara áreas OCR: selecione somente o texto/valor que será conferido.', wraplength=720).pack(pady=12)
        self.itens = list(CONTROLES) + list(AREAS)
        self.slot = tk.StringVar(value=self.itens[0])
        combo = ttk.Combobox(self, textvariable=self.slot, values=self.itens, state='readonly', width=35)
        combo.pack()
        self.descricao = tk.StringVar(value=CONTROLES[self.itens[0]])
        combo.bind('<<ComboboxSelected>>', lambda e: self.descricao.set({**CONTROLES, **AREAS}[self.slot.get()]))
        ttk.Label(self, textvariable=self.descricao, wraplength=720).pack(pady=8)
        ttk.Button(self, text='Capturar controle/área', command=self.capturar).pack(pady=6)
        ttk.Label(self, text='Calibre o ✓ inferior de Salvar, não o ✓ ao lado do telefone.\nA mensagem, os contatos, perfil e imagens ficam locais. Não compartilhe a pasta .local.', wraplength=720).pack(pady=6)

    def capturar(self):
        if self.app.ocupado:
            return
        self.withdraw()
        self.app.root.withdraw()
        self.after(300, self.obter)

    def obter(self):
        try:
            tela = self.app.driver
            frame = tela.conectar()
            self.selecionar(frame, self.slot.get())
        except Exception as erro:
            self.app.root.deiconify()
            self.deiconify()
            messagebox.showerror('Calibração', str(erro), parent=self)

    def selecionar(self, frame, slot):
        from PIL import ImageTk
        h, w = frame.shape[:2]
        escala = min(1200/w, 720/h, max(200,self.winfo_screenwidth()-80)/w, max(200,self.winfo_screenheight()-120)/h, 1)
        janela = tk.Toplevel(self)
        janela.title('Arraste a imagem/área; depois clique no ponto de ação. Esc cancela.')
        rgb = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        foto = ImageTk.PhotoImage(rgb.resize((int(w*escala), int(h*escala))))
        canvas = tk.Canvas(janela, width=foto.width(), height=foto.height(), cursor='crosshair')
        canvas.pack()
        canvas.create_image(0, 0, anchor='nw', image=foto)
        canvas.image = foto
        estado = {'inicio': None, 'rect': None, 'area': None}
        def terminar():
            janela.destroy()
            self.app.root.deiconify()
            self.deiconify()
        def salvar(area, clique=None):
            tela = self.app.driver
            tamanho = [w, h]
            if tela.config.get('tamanho') and tela.config['tamanho'] != tamanho:
                raise ValueError('Restaure o tamanho anterior da janela ou reinicie toda a calibração.')
            tela.config['tamanho'] = tamanho
            if slot in AREAS:
                tela.config['areas'][slot] = list(area)
            else:
                x1,y1,x2,y2 = area
                modelo = frame[y1:y2,x1:x2]
                if float(cv2.cvtColor(modelo, cv2.COLOR_BGR2GRAY).std()) < 3:
                    raise ValueError('Seleção sem detalhes. Capture um rótulo ou ícone completo.')
                margem_x, margem_y = int(w*.12), int(h*.12)
                tela.config['controles'][slot] = {'clique': [clique[0]-x1, clique[1]-y1], 'limite': .90,
                    'busca': [max(0,x1-margem_x), max(0,y1-margem_y), min(w,x2+margem_x), min(h,y2+margem_y)]}
                if not cv2.imwrite(str(tela.pasta / (slot+'.png')), modelo):
                    raise RuntimeError('Não foi possível salvar a imagem.')
                tela.modelos.pop(slot, None)
            temp = tela.arquivo.with_suffix('.tmp')
            temp.write_text(json.dumps(tela.config, ensure_ascii=False, indent=2), encoding='utf-8')
            temp.replace(tela.arquivo)
            self.app.log('Calibrado: ' + slot)
            terminar()
        def down(e):
            try:
                if estado['area']:
                    salvar(estado['area'], (int(e.x/escala), int(e.y/escala)))
                    return
                estado['inicio'] = (e.x,e.y)
                estado['rect'] = canvas.create_rectangle(e.x,e.y,e.x,e.y, outline='red', width=2)
            except Exception as erro:
                messagebox.showerror('Calibração', str(erro), parent=janela)
        def move(e):
            if estado['inicio'] and not estado['area']:
                canvas.coords(estado['rect'], *estado['inicio'], e.x,e.y)
        def up(e):
            if not estado['inicio'] or estado['area']:
                return
            x,y = estado['inicio']
            area = (max(0,int(min(x,e.x)/escala)),max(0,int(min(y,e.y)/escala)),min(w,int(max(x,e.x)/escala)),min(h,int(max(y,e.y)/escala)))
            if area[2]-area[0] < 8 or area[3]-area[1] < 8:
                return
            estado['area'] = area
            if slot in AREAS:
                salvar(area)
            else:
                janela.title('Agora clique no ponto onde a ação deve acontecer')
        canvas.bind('<ButtonPress-1>', down)
        canvas.bind('<B1-Motion>', move)
        canvas.bind('<ButtonRelease-1>', up)
        janela.bind('<Escape>', lambda e: terminar())
        janela.protocol('WM_DELETE_WINDOW', terminar)


class App:
    def __init__(self, root):
        self.root = root
        self.driver = None
        self.contatos = []
        self.eventos = queue.Queue()
        self.parar = threading.Event()
        self.ocupado = False
        self.etapa = ""
        self.numero_atual = None
        self.cadastro_confirmado = None
        self.envio_pendente = None

        root.title(f"WhatsApp — cadastrar e enviar — {VERSAO}")
        root.geometry("960x730")

        barra = ttk.Frame(root)
        barra.pack(fill="x", padx=12, pady=12)

        self.botoes = []

        for titulo, comando in (
            ("Carregar CSV", self.carregar),
            ("Chrome / QR", self.chrome),
            ("Calibrar OpenCV", self.calibrar),
            ("Iniciar", self.iniciar),
        ):
            botao = ttk.Button(
                barra, text=titulo, command=comando
            )
            botao.pack(side="left", padx=4)
            self.botoes.append(botao)

        ttk.Button(
            barra, text="Parar", command=self.parar.set
        ).pack(side="left", padx=4)

        self.status = tk.StringVar(
            value="Carregue o CSV e conecte o WhatsApp."
        )

        ttk.Label(
            root, textvariable=self.status
        ).pack(anchor="w", padx=12)

        ttk.Label(
            root,
            text=(
                "Brasil +55. Contatos existentes são pulados sem espera. "
                "Números recusados passam ao próximo sem espera."
            ),
        ).pack(anchor="w", padx=12, pady=(8, 0))

        ttk.Label(
            root,
            text="Mensagem — use {name} para inserir o nome:",
        ).pack(anchor="w", padx=12, pady=(12, 4))

        self.mensagem = tk.Text(
            root, height=7, wrap="word"
        )
        self.mensagem.pack(fill="x", padx=12)
        self.mensagem.insert(
            "1.0", "Olá, {name}! Tudo bem?"
        )

        linha = ttk.Frame(root)
        linha.pack(fill="x", padx=12, pady=10)

        ttk.Label(
            linha, text="Tempo base em segundos:"
        ).pack(side="left")

        self.intervalo = tk.StringVar(value="15")
        ttk.Entry(
            linha,
            textvariable=self.intervalo,
            width=8,
        ).pack(side="left", padx=8)

        ttk.Label(
            linha,
            text="+ 60 a 180 segundos aleatórios",
        ).pack(side="left")

        self.registro = tk.Text(
            root, state="disabled", wrap="word"
        )
        self.registro.pack(
            fill="both", expand=True, padx=12, pady=10
        )

        self.log(f"VERSÃO: {VERSAO}")
        self.log(f"ARQUIVO EM EXECUÇÃO: {Path(__file__).resolve()}")
        root.after(100, self.atualizar)
        root.protocol("WM_DELETE_WINDOW", self.fechar)


    def log(self, texto):
        self.eventos.put(("log", texto))


    def definir_etapa(self, texto):
        self.etapa = texto
        self.log(texto)


    def conferir_parada(self):
        if self.parar.is_set():
            raise InterruptedError()


    def executar(self, tarefa):
        if self.ocupado:
            return

        self.ocupado = True
        self.parar.clear()

        for botao in self.botoes:
            botao.configure(state="disabled")

        def trabalho():
            try:
                tarefa()

            except InterruptedError:
                self.log("Interrompido pelo usuário.")

            except Exception as erro:
                self.log(
                    f"ERRO: {type(erro).__name__}: {erro}"
                )
                self.diagnostico()
                self.log(
                    "Lote interrompido. "
                    "Não haverá repetição automática."
                )

            finally:
                self.eventos.put(("fim", None))

        threading.Thread(
            target=trabalho, daemon=True
        ).start()


    def carregar(self):
        caminho = filedialog.askopenfilename(
            filetypes=[("Arquivo CSV", "*.csv")]
        )

        if not caminho:
            return

        try:
            contatos, ignorados = ler_csv(caminho)
        except Exception as erro:
            messagebox.showerror("CSV", str(erro))
            return

        self.contatos = contatos
        self.status.set(
            f"{len(contatos)} contatos únicos carregados."
        )

        self.log(
            f"{ignorados} ocorrência(s) da lista "
            "de exclusão ignorada(s)."
        )

        for contato in contatos:
            self.log(
                f"CSV: {contato['original']} "
                f"→ +{contato['phone']} "
                f"— {contato['name']}"
            )


    def aguardar_proximo(self, base, resultado=None):
        if resultado != "enviado":
            self.log("SEM ESPERA: não houve envio confirmado neste contato.")
            return
        extra = random.randint(60, 180)
        total = base + extra
        minutos, segundos = divmod(int(total), 60)

        self.log(
            f"Base: {base:g}s + extra aleatório: {extra}s. "
            f"Aguardando {minutos}min {segundos:02d}s "
            "antes do próximo contato..."
        )

        if self.parar.wait(total):
            raise InterruptedError()


    def iniciar(self):
        if not self.contatos or self.driver is None:
            messagebox.showinfo(
                "Preparação",
                "Carregue o CSV e conecte o WhatsApp.",
            )
            return

        texto = self.mensagem.get("1.0", "end-1c")

        if not texto.strip():
            messagebox.showerror(
                "Mensagem", "Digite uma mensagem."
            )
            return

        try:
            base = float(
                self.intervalo.get().replace(",", ".")
            )

            if not 0 <= base <= 86400:
                raise ValueError()

        except ValueError:
            messagebox.showerror(
                "Tempo base",
                "Informe de 0 a 86400 segundos.",
            )
            return

        if not messagebox.askyesno(
            "Confirmar",
            f"Processar {len(self.contatos)} contatos?\n\n"
            "Números nacionais recebem 55 completo.\n"
            f"Espera após envio: {base:g}s + 60 a 180s aleatórios.\n"
            "Números recusados não terão espera.\n"
            "Contatos existentes serão pulados sem envio e sem espera.\n\n"
            "Use somente pessoas que aceitaram receber mensagens.",
        ):
            return

        self.log(f"LOTE — VERSÃO: {VERSAO}. Espera somente após envio confirmado.")
        contatos = list(self.contatos)

        def lote():
            self.driver.conectar()
            enviados = 0
            existentes = 0
            recusados = 0
            total = len(contatos)

            for indice, contato in enumerate(contatos, 1):
                self.conferir_parada()

                self.log(
                    f"\nCONTATO {indice}/{total}: "
                    f"+{contato['phone']} — {contato['name']}"
                )

                try:
                    precisa_cadastrar = self.abrir_e_detectar(
                        contato["phone"]
                    )

                except NumeroRecusado as erro:
                    recusados += 1
                    self.log(
                        f"SKIP: +{contato['phone']} — {erro}"
                    )
                    self.fechar_aviso_numero()

                    self.log(
                        "Número recusado. Próximo contato SEM ESPERA."
                    )
                    continue

                if not precisa_cadastrar:
                    existentes += 1
                    self.log("Contato existente. Próximo contato SEM ESPERA.")
                    continue

                self.cadastrar(contato)
                self.log("Cadastro concluído neste lote: enviando a mensagem agora, sem aplicar SKIP de contato existente.")
                self.enviar(
                    contato,
                    texto.replace(
                        "{name}", contato["name"]
                    ),
                )
                enviados += 1

                if indice < total:
                    self.aguardar_proximo(base, resultado="enviado")

            self.log(
                f"\nCONCLUÍDO: {enviados} envios processados; "
                f"{existentes} contatos existentes pulados; "
                f"{recusados} números recusados pulados."
            )
            self.log(
                "Uma nova execução começa do primeiro contato."
            )

        self.executar(lote)


    def atualizar(self):
        try:
            while True:
                tipo, valor = self.eventos.get_nowait()

                if tipo == "fim":
                    self.ocupado = False

                    for botao in self.botoes:
                        botao.configure(state="normal")

                else:
                    self.registro.configure(state="normal")
                    self.registro.insert("end", valor + "\n")
                    self.registro.see("end")
                    self.registro.configure(state="disabled")

        except queue.Empty:
            pass

        self.root.after(100, self.atualizar)


    def fechar(self):
        self.parar.set()

        if self.ocupado:
            messagebox.showinfo(
                "Aguarde",
                "Parada solicitada. Espere terminar "
                "e feche novamente.",
            )
            return

        driver = self.driver
        self.driver = None
        self.root.destroy()

        if driver:
            try:
                driver.quit()
            except Exception:
                pass


    def chrome(self):
        if not sistema_windows():
            messagebox.showerror('Windows necessário', 'Esta versão controla o Chrome pela tela e pelo Windows SendInput. Execute em Windows com desktop visível.')
            return
        if self.ocupado:
            return
        if self.envio_pendente:
            messagebox.showwarning('Envio incerto', 'Confira manualmente a conversa antes de qualquer nova tentativa. Reiniciar não comprova que a mensagem não foi enviada.')
            return
        try:
            if self.driver is None:
                self.driver = TelaVisual(self.parar, self.log)
            self.driver.conectar()
            self.log('Chrome normal conectado pela janela. Nenhum WebDriver foi iniciado. Faça login por QR no navegador, se necessário.')
        except Exception as erro:
            messagebox.showerror('Chrome / QR', str(erro) + '\nAbra manualmente https://web.whatsapp.com/ no Chrome normal e deixe essa aba ativa.')

    def calibrar(self):
        if self.ocupado:
            return
        if self.driver is None:
            self.chrome()
        if self.driver is not None:
            Calibracao(self)

    def abrir_e_detectar(self, numero):
        self.driver.validar()
        self.numero_atual = numero
        self.cadastro_confirmado = None
        self.definir_etapa(f'1/5: abrindo +{numero} com teclado nativo...')
        resposta = self.driver.abrir_numero(numero)
        if resposta == 'recusado':
            raise NumeroRecusado('Aviso de número recusado reconhecido visualmente.')
        self.definir_etapa('2/5: verificando Adicionar/Editar contato por OpenCV...')
        estado = self.driver.estado_contato()
        if estado == 'existente':
            self.driver.desktop.atalho(0x1B)
            self.log(f'SKIP: +{numero} já está salvo; sem cadastro, envio ou espera.')
            return False
        self.driver.clicar('adicionar')
        return True

    def fechar_aviso_numero(self):
        self.definir_etapa('Fechando aviso de número recusado...')
        self.driver.clicar('ok')
        self.driver.aguardar(lambda: self.driver.localizar('recusado') is None, 5, 'aviso desaparecer')

    def conferir_telefone_visual(self, numero):
        texto = self.driver.ler('telefone_lido')
        numeros = set()
        for candidato in re.findall(r'\+?\d[\d\s().-]{8,}\d', texto):
            try:
                numeros.add(numero_brasileiro(candidato))
            except ValueError:
                pass
        pais_brasil = bool(re.search(r'\+\s*55(?:\D|$)|\bBR\b|\bBrasil\b', texto, re.I))
        if numeros == {numero} and pais_brasil:
            self.log('OCR confirmou o telefone exato: +' + numero)
            return
        # No automatic equivalence between different digit strings, including 9th digit.
        raise RuntimeError(f'OCR não confirmou o destinatário: esperado +{numero}, lido {texto!r}. Nenhum contato será salvo/enviado com essa divergência.')

    def cadastrar(self, contato):
        tela, nome, numero = self.driver, contato['name'], contato['phone']
        for tentativa in range(2):
            self.definir_etapa('3/5: abrindo formulário e digitando Nome por SendInput...')
            def formulario():
                frame = tela.frame()
                if tela.localizar('nome', frame):
                    return 'nome'
                return 'criar' if tela.localizar('criar', frame) else False
            estado = tela.aguardar(formulario, 20, 'formulário de contato')
            if estado == 'criar':
                tela.clicar('criar')
            tela.escrever_campo('nome', nome, 'nome_lido')
            self.conferir_telefone_visual(numero)
            # Only click Save after name/phone OCR matches and WhatsApp shows valid phone.
            self.definir_etapa('4/5: aguardando confirmação visual do telefone e botão Salvar (até 5s)...')
            try:
                tela.aguardar(lambda: tela.localizar('telefone_ok'), 5, 'WhatsApp validar o telefone')
                tela.clicar('salvar', 5)
            except TimeoutError:
                if tentativa:
                    raise RuntimeError('Formulário já foi reaberto pelo X uma vez e continua sem validação/Salvar.')
                tela.fechar_formulario()
                # Reopen via UI only: no address navigation or reload in recovery.
                if tela.localizar('conversa'):
                    estado = tela.estado_contato()
                    if estado == 'existente':
                        tela.desktop.atalho(0x1B)
                        self.cadastro_confirmado = numero
                        return
                    tela.clicar('adicionar')
                else:
                    # Optional direct add action on WhatsApp home screen.
                    tela.clicar('adicionar')
                continue
            # A Save click is never repeated if its result becomes uncertain.
            def salvo_ou_fechado():
                frame = tela.frame()
                if tela.localizar('salvo', frame):
                    return 'salvo'
                return 'fechado' if tela.localizar('nome', frame) is None else False
            resultado = tela.aguardar(salvo_ou_fechado, 20, 'confirmar resultado do clique em Salvar')
            if resultado != 'salvo':
                resposta = tela.abrir_numero(numero)
                if resposta != 'conversa' or tela.estado_contato() != 'existente':
                    raise RuntimeError('Cadastro não confirmado pela interface. Mensagem bloqueada.')
                tela.desktop.atalho(0x1B)
            self.cadastro_confirmado = numero
            self.log('Cadastro confirmado. Próxima etapa: enviar a mensagem ao mesmo contato.')
            return

    def enviar(self, contato, texto):
        numero = contato['phone']
        if self.cadastro_confirmado != numero:
            raise RuntimeError('Este cadastro não foi confirmado. Envio bloqueado.')
        if self.envio_pendente:
            raise RuntimeError('Há um envio incerto. Confira a conversa antes de reiniciar.')
        tela = self.driver
        self.definir_etapa('5/5: abrindo o número exato e conferindo rascunho por OCR...')
        if tela.abrir_numero(numero) != 'conversa':
            raise RuntimeError('Destinatário não abriu antes do envio.')
        if tela.ler('rascunho_lido').strip():
            raise RuntimeError('Rascunho existente ou região OCR incorreta. Não será apagado nem misturado.')
        mensagem = texto.replace('\r\n', '\n').replace('\r', '\n')
        antes = texto_comparavel(tela.ler('saida_lida'))
        esperado = texto_comparavel(mensagem)
        tela.escrever_campo('mensagem', mensagem, 'rascunho_lido')
        # Count occurrences before/after, so an old copy is never proof of a new send.
        ocorrencias = antes.count(esperado)
        self.envio_pendente = numero
        try:
            tela.clicar('enviar', 5)
            tela.aguardar(lambda: texto_comparavel(tela.ler('saida_lida')).count(esperado) > ocorrencias,
                          30, 'nova mensagem de saída contendo o texto enviado')
        except Exception as erro:
            raise RuntimeError('ENVIO INCERTO. Não repetir automaticamente; confira a conversa.') from erro
        self.envio_pendente = None
        self.log('Nova mensagem de saída observada por OCR. Entrega não confirmada.')

    def diagnostico(self):
        if self.driver is None:
            return
        try:
            pasta = Path(__file__).resolve().parent / 'diagnosticos'
            pasta.mkdir(exist_ok=True)
            destino = pasta / ('visual_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.png')
            if self.driver.save_screenshot(destino):
                self.log('Captura LOCAL: ' + str(destino))
        except Exception as erro:
            self.log('Falha ao capturar diagnóstico: ' + str(erro))


if __name__ == '__main__':
    if sistema_windows():
        try:
            ctypes.WinDLL('user32').SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            try:
                ctypes.WinDLL('user32').SetProcessDPIAware()
            except Exception:
                pass
    root = tk.Tk()
    App(root)
    root.mainloop()
