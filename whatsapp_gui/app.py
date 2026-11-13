"""WhatsApp — script único com biblioteca padrão do Python.
Windows 10/11, Python 3.12+, Chrome normal com UI Automation disponível.
Não requer pip, OpenCV, Selenium, OCR externo ou calibração. Execute python app.py.
A integração real no Windows/WhatsApp precisa de validação; não há garantia de indetectabilidade.
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
import weakref
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlencode

VERSAO = '2026.11.13-v17-python-puro-acessibilidade-windows'
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


    def clicar(self, x, y):
        self.proteger()
        if self.rect() != self.rect_anterior:
            raise RuntimeError('A janela foi movida após a captura. Execute novamente para obter posições atualizadas.')
        left, top, right, bottom = self.rect_anterior
        if not (0 <= x < right-left and 0 <= y < bottom-top):
            raise RuntimeError('Ponto de clique fora da janela do Chrome.')
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


    def escrever(self, texto, parar, limpar=True, tab=False, conferir_foco=None):
        if conferir_foco and not conferir_foco():
            raise RuntimeError('Campo perdeu o foco antes da digitação.')
        if limpar:
            self.atalho(0x11, 0x41)
            self.atalho(0x08)
        for caractere in texto:
            if parar.is_set():
                raise InterruptedError()
            if conferir_foco and not conferir_foco():
                raise RuntimeError('Campo perdeu o foco durante a digitação.')
            if caractere == '\n':
                self.atalho(0x10, 0x0D)
            else:
                raw = caractere.encode('utf-16-le')
                eventos = []
                for i in range(0, len(raw), 2):
                    unidade = int.from_bytes(raw[i:i+2], 'little')
                    eventos.extend([(0, unidade, 4), (0, unidade, 6)])
                self.enviar(eventos, conferir_foco or self.em_primeiro_plano)
            if parar.wait(0.09):
                raise InterruptedError()
        if tab:
            self.atalho(0x09)


# UI Automation COM bindings: signatures follow uiautomationclient.h.
class GUID(ctypes.Structure):
    _fields_ = [('d1', ctypes.c_uint32), ('d2', ctypes.c_uint16), ('d3', ctypes.c_uint16), ('d4', ctypes.c_ubyte * 8)]

    @classmethod
    def from_string(cls, value):
        import uuid
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


class RECT(ctypes.Structure):
    _fields_ = [('left', ctypes.c_int32), ('top', ctypes.c_int32), ('right', ctypes.c_int32), ('bottom', ctypes.c_int32)]


class POINT(ctypes.Structure):
    _fields_ = [('x', ctypes.c_int32), ('y', ctypes.c_int32)]


class VARIANT_RECORD(ctypes.Structure):
    _fields_ = [('record', ctypes.c_void_p), ('info', ctypes.c_void_p)]


class VARIANT_VALUE(ctypes.Union):
    _fields_ = [('integer', ctypes.c_int32), ('boolean', ctypes.c_int16), ('real', ctypes.c_double),
                ('pointer', ctypes.c_void_p), ('record', VARIANT_RECORD)]


class VARIANT(ctypes.Structure):
    _anonymous_ = ('value',)
    _fields_ = [('vt', ctypes.c_uint16), ('r1', ctypes.c_uint16), ('r2', ctypes.c_uint16), ('r3', ctypes.c_uint16), ('value', VARIANT_VALUE)]


class NativeUIError(RuntimeError):
    pass


class COMPointer:
    def __init__(self, client, pointer):
        self.client, self.pointer = client, pointer
        if hasattr(client, 'pointers'):
            client.pointers.add(self)

    def close(self):
        if self.pointer and self.pointer.value:
            self.client.method(self.pointer, 2, ctypes.c_uint32)()
            self.pointer = ctypes.c_void_p()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


@dataclass
class Elemento:
    nome: str
    tipo: int
    rect: tuple
    habilitado: bool = True
    fora_tela: bool = False
    valor: object = None
    automation_id: str = ''
    ajuda: str = ''
    aria: str = ''
    nativo: object = None

    @property
    def visivel(self):
        return not self.fora_tela and self.rect[2] > self.rect[0] and self.rect[3] > self.rect[1]


class UIAWindows:
    def __init__(self):
        if not sistema_windows():
            raise NativeUIError('Acessibilidade UI Automation requer Windows.')
        self.pointers = weakref.WeakSet()
        self.ole = ctypes.WinDLL('ole32', use_last_error=True)
        self.aut = ctypes.WinDLL('oleaut32', use_last_error=True)
        self.ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.ole.CoInitializeEx.restype = ctypes.c_int32
        self.ole.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
        self.ole.CoCreateInstance.restype = ctypes.c_int32
        self.aut.SysFreeString.argtypes = [ctypes.c_void_p]
        resultado = self.ole.CoInitializeEx(None, 2)
        if resultado < 0:
            raise NativeUIError(f'Não foi possível inicializar COM: {resultado & 0xffffffff:08X}')
        self.inicializado = True
        pointer = ctypes.c_void_p()
        clsid = GUID.from_string('ff48dba4-60ef-4201-aa87-54103eef594e')
        iid = GUID.from_string('30cbe57d-d9d0-452a-ab13-7ac5ac4825ee')
        try:
            self.check(self.ole.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(pointer)))
            self.obj = COMPointer(self, pointer)
        except Exception:
            self.ole.CoUninitialize()
            self.inicializado = False
            raise

    @staticmethod
    def check(result):
        if result < 0:
            raise NativeUIError(f'Falha na acessibilidade do Windows: HRESULT {result & 0xffffffff:08X}')

    def method(self, pointer, index, result=ctypes.c_int32, args=()):
        if isinstance(pointer, COMPointer):
            pointer = pointer.pointer
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        fn = ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *args)(table[index])
        return lambda *values: fn(pointer, *values)

    def string(self, pointer, method):
        value = ctypes.c_void_p()
        self.check(self.method(pointer, method, args=(ctypes.POINTER(ctypes.c_void_p),))(ctypes.byref(value)))
        try:
            return ctypes.wstring_at(value) if value.value else ''
        finally:
            if value.value:
                self.aut.SysFreeString(value)

    def integer(self, pointer, method):
        value = ctypes.c_int32()
        self.check(self.method(pointer, method, args=(ctypes.POINTER(ctypes.c_int32),))(ctypes.byref(value)))
        return value.value

    def rectangle(self, pointer):
        value = RECT()
        self.check(self.method(pointer, 43, args=(ctypes.POINTER(RECT),))(ctypes.byref(value)))
        return value.left, value.top, value.right, value.bottom

    def root(self, hwnd):
        pointer = ctypes.c_void_p()
        self.check(self.method(self.obj, 6, args=(ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)))(hwnd, ctypes.byref(pointer)))
        return COMPointer(self, pointer)

    def condition(self, control_type):
        value = VARIANT()
        value.vt, value.integer = 3, control_type
        pointer = ctypes.c_void_p()
        self.check(self.method(self.obj, 23, args=(ctypes.c_int32, VARIANT, ctypes.POINTER(ctypes.c_void_p)))(30003, value, ctypes.byref(pointer)))
        return COMPointer(self, pointer)

    def findall(self, root, control_type):
        condition = self.condition(control_type)
        pointer = ctypes.c_void_p()
        self.check(self.method(root, 6, args=(ctypes.c_int32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)))(4, condition.pointer, ctypes.byref(pointer)))
        array = COMPointer(self, pointer)
        count = self.integer(array, 3)
        if count > 4000:
            raise NativeUIError('A árvore de acessibilidade está grande demais; reduza o histórico visível antes de iniciar.')
        result = []
        for index in range(count):
            element = ctypes.c_void_p()
            self.check(self.method(array, 4, args=(ctypes.c_int32, ctypes.POINTER(ctypes.c_void_p)))(index, ctypes.byref(element)))
            result.append(COMPointer(self, element))
        return result

    def pattern(self, element, pattern_id):
        iids = {10002:'a94cd8b1-0844-4cd6-9d2d-640537ab39e9',
                10018:'828055ad-355b-4435-86d5-3b51c14a9b1b',
                10014:'32eba289-3583-42c9-9c59-3b6d9a1e9b6a'}
        iid = GUID.from_string(iids[pattern_id])
        value = ctypes.c_void_p()
        result = self.method(element, 14, args=(ctypes.c_int32, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)))(pattern_id, ctypes.byref(iid), ctypes.byref(value))
        return COMPointer(self, value) if result >= 0 and value.value else None

    def read_value(self, element):
        # Value, Text and Legacy accessibility are standard native Windows patterns.
        valor_vazio = None
        for pattern_id, method in ((10002, 4), (10018, 8)):
            pattern = self.pattern(element, pattern_id)
            if pattern:
                try:
                    valor = self.string(pattern, method)
                    if valor:
                        return valor
                    valor_vazio = valor
                except NativeUIError:
                    pass
        text = self.pattern(element, 10014)
        if text:
            range_pointer = ctypes.c_void_p()
            self.check(self.method(text, 7, args=(ctypes.POINTER(ctypes.c_void_p),))(ctypes.byref(range_pointer)))
            text_range = COMPointer(self, range_pointer)
            value = ctypes.c_void_p()
            self.check(self.method(text_range, 12, args=(ctypes.c_int32, ctypes.POINTER(ctypes.c_void_p)))(-1, ctypes.byref(value)))
            try:
                return ctypes.wstring_at(value) if value.value else ''
            finally:
                if value.value:
                    self.aut.SysFreeString(value)
        return valor_vazio

    def optional_string(self, pointer, method):
        try:
            return self.string(pointer, method)
        except NativeUIError:
            return ''

    def info(self, pointer, control_type=None):
        kind = control_type or self.integer(pointer, 21)
        rect = self.rectangle(pointer)
        try:
            value = self.read_value(pointer) if kind == 50004 else None
        except NativeUIError:
            value = None
        return Elemento(self.string(pointer, 23), kind, rect, bool(self.integer(pointer, 28)),
                        bool(self.integer(pointer, 38)), value,
                        self.optional_string(pointer, 29), self.optional_string(pointer, 31), self.optional_string(pointer, 46), pointer)

    def nodes(self, hwnd):
        root = self.root(hwnd)
        documents = self.findall(root, 50030)
        candidates = []
        for doc in documents:
            try:
                name, rect = self.string(doc, 23), self.rectangle(doc)
                if 'whatsapp' in normalizar(name) and rect[2]-rect[0] > 200 and rect[3]-rect[1] > 200:
                    candidates.append(doc)
            except NativeUIError:
                continue
        if len(candidates) != 1:
            raise NativeUIError('O Chrome não expôs um único documento WhatsApp à acessibilidade. Ative a aba WhatsApp; esta versão não usará posições presumidas.')
        result = []
        for kind in (50000, 50003, 50004, 50007, 50009, 50011, 50020, 50025, 50026, 50032):
            for ptr in self.findall(candidates[0], kind):
                try:
                    info = self.info(ptr, kind)
                    if info.visivel:
                        result.append(info)
                except NativeUIError:
                    continue
        return result

    def refresh(self, element):
        return self.info(element.nativo, element.tipo)

    def focused(self, element):
        return bool(self.integer(element.nativo, 26))

    def hit_test(self, element):
        left, top, right, bottom = element.rect
        pointer = ctypes.c_void_p()
        point = POINT((left+right)//2, (top+bottom)//2)
        self.check(self.method(self.obj, 7, args=(POINT, ctypes.POINTER(ctypes.c_void_p)))(point, ctypes.byref(pointer)))
        hit = COMPointer(self, pointer)
        equal = ctypes.c_int32()
        self.check(self.method(self.obj, 3, args=(ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int32)))(hit.pointer, element.nativo.pointer, ctypes.byref(equal)))
        if equal.value:
            return True
        return bool(element.nome) and normalizar(self.string(hit, 23)) == normalizar(element.nome)

    def close(self):
        if self.inicializado:
            for pointer in list(self.pointers):
                pointer.close()
            self.obj.close()
            self.ole.CoUninitialize()
            self.inicializado = False


def gravar_bmp(destino, largura, altura, pixels):
    import struct
    if largura <= 0 or altura <= 0 or len(pixels) != largura * altura * 4:
        raise ValueError('Dimensões ou pixels BMP inválidos.')
    cabecalho = struct.pack('<2sIHHI', b'BM', 54+len(pixels), 0, 0, 54)
    info = struct.pack('<IiiHHIIiiII', 40, largura, altura, 1, 32, 0, len(pixels), 0, 0, 0, 0)
    Path(destino).write_bytes(cabecalho + info + pixels)


def capturar_bmp(desktop, destino):
    desktop.proteger()
    left, top, right, bottom = desktop.rect()
    w, h = right-left, bottom-top
    if not (0 < w <= 8192 and 0 < h <= 8192):
        raise RuntimeError('Janela com dimensões inválidas para captura.')
    c = ctypes
    user, gdi = desktop.api, c.WinDLL('gdi32', use_last_error=True)
    user.GetDC.argtypes, user.GetDC.restype = [c.c_void_p], c.c_void_p
    user.ReleaseDC.argtypes = [c.c_void_p, c.c_void_p]
    for name, args, result in (
        ('CreateCompatibleDC', [c.c_void_p], c.c_void_p),
        ('CreateCompatibleBitmap', [c.c_void_p,c.c_int32,c.c_int32], c.c_void_p),
        ('SelectObject', [c.c_void_p,c.c_void_p], c.c_void_p),
        ('DeleteObject', [c.c_void_p], c.c_int32), ('DeleteDC', [c.c_void_p], c.c_int32),
        ('BitBlt', [c.c_void_p,c.c_int32,c.c_int32,c.c_int32,c.c_int32,c.c_void_p,c.c_int32,c.c_int32,c.c_uint32], c.c_int32),
        ('GetDIBits', [c.c_void_p,c.c_void_p,c.c_uint32,c.c_uint32,c.c_void_p,c.c_void_p,c.c_uint32], c.c_int32),
    ):
        function = getattr(gdi, name)
        function.argtypes, function.restype = args, result
    screen = user.GetDC(None)
    memory = bitmap = previous = None
    try:
        memory = gdi.CreateCompatibleDC(screen)
        bitmap = gdi.CreateCompatibleBitmap(screen, w, h)
        if not screen or not memory or not bitmap:
            raise RuntimeError('Não foi possível criar a captura nativa.')
        previous = gdi.SelectObject(memory, bitmap)
        if not gdi.BitBlt(memory,0,0,w,h,screen,left,top,0x00CC0020|0x40000000):
            raise RuntimeError('Windows recusou a captura da janela.')
        gdi.SelectObject(memory, previous)
        previous = None
        import struct
        info = c.create_string_buffer(struct.pack('<IiiHHIIiiII',40,w,h,1,32,0,w*h*4,0,0,0,0))
        pixels = c.create_string_buffer(w*h*4)
        if gdi.GetDIBits(memory,bitmap,0,h,pixels,info,0) != h:
            raise RuntimeError('Não foi possível ler todos os pixels da captura.')
        gravar_bmp(destino,w,h,pixels.raw)
        return True
    finally:
        if previous and memory:
            gdi.SelectObject(memory, previous)
        if bitmap:
            gdi.DeleteObject(bitmap)
        if memory:
            gdi.DeleteDC(memory)
        if screen:
            user.ReleaseDC(None, screen)


ADICIONAR = ('Adicionar aos contatos', 'Adicionar a contatos', 'Adicionar aos contactos', 'Adicionar contato', 'Add to contacts', 'Add contact')
EDITAR = ('Editar contato', 'Editar contacto', 'Edit contact')
CRIAR = ('Criar contato', 'Criar novo contato', 'Novo contato', 'Create contact', 'Create new contact', 'New contact')


def texto_comparavel(texto):
    return ' '.join(unicodedata.normalize('NFC', texto or '').split())


def correspondencia_nomes(elementos, nomes, tipos=None):
    aceitos = {normalizar(n) for n in nomes}
    return [e for e in elementos if e.visivel and e.habilitado
            and (tipos is None or e.tipo in tipos) and re.sub(r'[\s:*]+$', '', normalizar(e.nome)) in aceitos]


class TelaNativa:
    def __init__(self, parar, log, desktop=None, client=None):
        self.parar, self.log = parar, log
        self.desktop = desktop if desktop is not None else DesktopWindows()
        self.client_injetado = client
        self.local = threading.local()
        self.ultimos = []
        self.numero_atual = None

    @property
    def client(self):
        if self.client_injetado is not None:
            return self.client_injetado
        if not hasattr(self.local, 'client'):
            self.local.client = UIAWindows()
        return self.local.client

    def encerrar_thread(self):
        if hasattr(self.local, 'client'):
            self.local.client.close()
            del self.local.client

    def conectar(self):
        if not self.desktop.ativar('WhatsApp'):
            raise RuntimeError('Abra uma única janela do Chrome com a aba WhatsApp ativa e tente conectar novamente.')
        self.desktop.proteger()

    def snapshot(self):
        self.conferir_parada()
        self.desktop.proteger()
        elementos = self.client.nodes(self.desktop.janela)
        self.ultimos = [{'nome': e.nome, 'tipo': e.tipo, 'rect': list(e.rect), 'habilitado': e.habilitado,
                         'ajuda': e.ajuda, 'aria': e.aria} for e in elementos]
        return elementos

    def conferir_parada(self):
        if self.parar.is_set():
            raise InterruptedError()

    def aguardar(self, funcao, segundos, etapa):
        fim = time.monotonic() + segundos
        ultimo = ''
        while time.monotonic() < fim:
            self.conferir_parada()
            try:
                resultado = funcao()
                if resultado:
                    return resultado
            except NativeUIError as erro:
                ultimo = str(erro)
            if self.parar.wait(0.2):
                raise InterruptedError()
        raise TimeoutError('Tempo esgotado: ' + etapa + ('. ' + ultimo if ultimo else ''))

    def buscar(self, nomes, tipos=(50000, 50011), elementos=None):
        encontrados = correspondencia_nomes(self.snapshot() if elementos is None else elementos, nomes, tipos)
        if len(encontrados) > 1:
            raise RuntimeError('Controle ambíguo na acessibilidade: ' + '/'.join(nomes))
        return encontrados[0] if encontrados else None

    def clicar_elemento(self, elemento):
        self.conferir_parada()
        atual = self.client.refresh(elemento)
        if not atual.visivel or not atual.habilitado:
            raise NativeUIError('Controle deixou de estar visível/habilitado: ' + elemento.nome)
        if not self.client.hit_test(atual):
            raise RuntimeError('O centro do controle está coberto por outro elemento. Clique bloqueado: ' + elemento.nome)
        self.desktop.rect_anterior = self.desktop.rect()
        left, top, _, _ = self.desktop.rect_anterior
        x1,y1,x2,y2 = atual.rect
        self.desktop.clicar((x1+x2)//2-left, (y1+y2)//2-top)
        self.log('Clique nativo no controle: ' + (atual.nome or 'sem nome'))

    def clicar(self, nomes, segundos=10, tipos=(50000,50011)):
        elemento = self.aguardar(lambda: self.buscar(nomes, tipos), segundos, 'localizar ' + '/'.join(nomes))
        self.clicar_elemento(elemento)
        return elemento

    def campo_nome(self, elementos=None):
        return self.buscar(('Nome', 'Primeiro nome', 'Nome completo', 'Name', 'First name', 'Full name'), (50004,), elementos)

    def campo_telefone(self, elementos=None):
        return self.buscar(('Número de telefone', 'Telefone', 'Número do telefone', 'Phone number', 'Phone'), (50004,), elementos)

    def campo_mensagem(self, elementos=None):
        encontrados = correspondencia_nomes(self.snapshot() if elementos is None else elementos,
            ('Digite uma mensagem', 'Mensagem', 'Type a message', 'Message'), (50004,))
        if len(encontrados) > 1:
            raise RuntimeError('Mais de um campo de mensagem exposto; envio bloqueado.')
        return encontrados[0] if encontrados else None

    def ler(self, elemento):
        atual = self.client.refresh(elemento)
        if atual.valor is None:
            raise NativeUIError('O Chrome não expôs o valor deste campo à acessibilidade: ' + elemento.nome)
        return str(atual.valor)

    def digitar(self, elemento, texto, tab=True):
        self.clicar_elemento(elemento)
        self.aguardar(lambda: self.client.focused(elemento), 3, 'confirmar foco no campo ' + elemento.nome)
        # Native SendInput only; the accessibility API is used to read/locate.
        self.desktop.escrever(texto, self.parar, tab=False, conferir_foco=lambda: self.client.focused(elemento))
        if tab:
            self.desktop.atalho(0x09)
        self.aguardar(lambda: texto_comparavel(self.ler(elemento)) == texto_comparavel(texto), 5, 'conferir valor digitado em ' + elemento.nome)

    def menu(self):
        elementos = self.snapshot()
        left,top,right,bottom = self.desktop.rect()
        candidatos = correspondencia_nomes(elementos, ('Menu','Mais opções','More options'), (50000,))
        candidatos = [e for e in candidatos if e.rect[0] > left+(right-left)*.4 and e.rect[1] < top+(bottom-top)*.3]
        if len(candidatos) != 1:
            raise NativeUIError('Não identifiquei um único menu no cabeçalho da conversa pela acessibilidade.')
        self.clicar_elemento(candidatos[0])

    def estado_contato(self):
        self.menu()
        def estado():
            elementos = self.snapshot()
            editar = self.buscar(EDITAR, elementos=elementos)
            adicionar = self.buscar(ADICIONAR, elementos=elementos)
            if editar and adicionar:
                raise RuntimeError('Adicionar e Editar presentes ao mesmo tempo. Estado inconclusivo.')
            return 'existente' if editar else ('novo' if adicionar else False)
        try:
            return self.aguardar(estado, 5, 'Adicionar/Editar contato')
        except TimeoutError:
            dados = self.buscar(('Dados do contato','Dados do contacto','Informações do contato','Contact info'))
            if not dados:
                raise
            self.clicar_elemento(dados)
            def nos_dados():
                e = estado()
                if e:
                    return e
                elementos = self.snapshot()
                editar = self.buscar(('Editar','Edit'), elementos=elementos)
                if editar and self.telefone_confirmado(self.numero_atual, elementos):
                    return 'existente'
                return False
            return self.aguardar(nos_dados, 10, 'contato salvo nos dados do contato')

    def aviso_recusa(self, elementos=None):
        elementos = self.snapshot() if elementos is None else elementos
        for e in elementos:
            if e.tipo not in (50020,50025,50026,50032):
                continue
            texto = normalizar(e.nome)
            if re.search(r'(numero.*(?:invalido|nao (?:esta |e )?(?:registrado )?no whatsapp)|phone number.*(?:invalid|not (?:registered )?on whatsapp))', texto):
                return e
        return None

    def abrir_numero(self, numero):
        self.numero_atual = numero
        self.desktop.atalho(0x11, 0x4C)
        self.desktop.escrever('https://web.whatsapp.com/send?' + urlencode({'phone':numero}), self.parar)
        self.desktop.atalho(0x0D)
        def saiu():
            try:
                return self.campo_mensagem() is None
            except NativeUIError:
                return True
        self.aguardar(saiu, 15, 'a conversa anterior sair da tela')
        def resposta():
            elementos = self.snapshot()
            if self.aviso_recusa(elementos):
                return 'recusado'
            return 'conversa' if self.campo_mensagem(elementos) else False
        return self.aguardar(resposta, 90, 'abrir destinatário na acessibilidade')

    def telefone_confirmado(self, numero, elementos=None):
        elementos = self.snapshot() if elementos is None else elementos
        campos = correspondencia_nomes(elementos,('Número de telefone','Telefone','Número do telefone','Phone number','Phone'),(50004,))
        if campos:
            if len(campos) != 1 or campos[0].valor is None:
                return False
            campo = campos[0]
            try:
                if numero_brasileiro(str(campo.valor)) != numero:
                    return False
            except ValueError:
                return False
            bruto = digitos(str(campo.valor))
            if bruto.startswith('55') and len(bruto) in (12,13):
                return True
            # Read country next to this field, not unrelated numbers in chat history.
            return any(re.search(r'\+\s*55(?:\D|$)|\bBR\b|\bBrasil\b',e.nome,re.I)
                       and e.rect[3]>=campo.rect[1]-120 and e.rect[1]<=campo.rect[3]+100
                       for e in elementos if e.tipo in (50003,50000,50020))
        # Contact-info drawers can show the complete phone as non-editable text.
        left,top,right,bottom = self.desktop.rect()
        for e in elementos:
            if e.tipo != 50020 or e.rect[0] < left+(right-left)*.35:
                continue
            for candidato in re.findall(r'\+?\d[\d\s().-]{8,}\d',e.nome):
                bruto = digitos(candidato)
                if bruto.startswith('55') and len(bruto) in (12,13) and bruto == numero:
                    return True
        return False

    def validar_formulario(self, numero):
        elementos = self.snapshot()
        if not self.telefone_confirmado(numero, elementos):
            raise NativeUIError('O telefone/país do formulário não corresponde exatamente ao CSV, ou o Chrome não expôs o valor. Cadastro bloqueado.')
        for e in elementos:
            if e.tipo == 50004 and ('invalid=true' in normalizar(e.aria) or 'invalid:true' in normalizar(e.aria)):
                raise NativeUIError('A interface sinaliza campo inválido: ' + e.nome)

    def tem_formulario(self, elementos=None):
        elementos = self.snapshot() if elementos is None else elementos
        return any(normalizar(e.nome) in ('novo contato','novo contacto','new contact','criar contato','create contact') for e in elementos if e.tipo in (50020,50025,50026,50032)) or self.campo_nome(elementos) is not None

    def fechar_formulario(self):
        elementos = self.snapshot()
        nome = self.campo_nome(elementos)
        if nome is None:
            raise NativeUIError('Não identifiquei o formulário do contato para fechar pelo X.')
        fechar = correspondencia_nomes(elementos, ('Fechar','Close','Fechar painel','Close panel'), (50000,))
        fechar = [e for e in fechar if e.rect[3] <= nome.rect[1] and e.rect[0] >= nome.rect[0]-150]
        if len(fechar) != 1:
            raise NativeUIError('O X do painel Novo contato não tem identificação acessível única. Página não será recarregada.')
        self.clicar_elemento(fechar[0])
        descartou = False
        def fechado():
            nonlocal descartou
            elementos = self.snapshot()
            aviso = any(any(p in normalizar(e.nome) for p in ('deseja descartar as mudancas','descartar alteracoes','discard changes','discard your changes')) for e in elementos)
            if aviso:
                if not descartou:
                    self.clicar(('Descartar','Discard'),5)
                    descartou = True
                return False
            return not self.tem_formulario(elementos)
        self.aguardar(fechado, 10, 'confirmar X/Descartar')
        self.log('Formulário fechado pelo X/Descartar, sem F5.')

    def avisos_salvo(self):
        return {(e.nome,e.rect) for e in self.snapshot() if e.tipo in (50020,50025,50026) and re.search(
            r'\b(?:contato|contacto) (?:foi )?(?:salvo|adicionado|guardado)\b|\bcontact (?:was )?(?:saved|added)\b', normalizar(e.nome))}

    def mensagens_saida(self):
        mensagens = []
        for e in self.snapshot():
            if e.tipo not in (50007,50025,50026):
                continue
            identificacao = normalizar(e.automation_id + ' ' + e.aria)
            if 'message-out' in identificacao or 'outgoing' in identificacao or re.match(r'^(voce|you)\s*:',normalizar(e.nome)):
                mensagens.append(texto_comparavel(e.nome))
        return mensagens

    def save_screenshot(self, destino):
        return capturar_bmp(self.desktop, Path(destino).with_suffix('.bmp'))

    def quit(self):
        self.encerrar_thread()


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
                if self.driver is not None:
                    try:
                        self.driver.encerrar_thread()
                    except Exception:
                        pass
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
            messagebox.showerror('Windows necessário', 'Este script usa apenas a biblioteca padrão do Python e as APIs nativas do Windows. Execute no Windows com o Chrome visível.')
            return
        if self.ocupado:
            return
        try:
            if self.driver is None:
                self.driver = TelaNativa(self.parar, self.log)
            self.driver.conectar()
            self.log('Chrome normal conectado. Sem instalação de pacotes, sem calibração e sem WebDriver.')
        except Exception as erro:
            messagebox.showerror('Chrome / QR', str(erro) + '\nAbra manualmente web.whatsapp.com no Chrome, faça login e deixe a aba ativa.')

    def abrir_e_detectar(self, numero):
        self.numero_atual = numero
        self.cadastro_confirmado = None
        self.definir_etapa(f'1/5: abrindo +{numero} com teclas do Windows...')
        if self.driver.abrir_numero(numero) == 'recusado':
            raise NumeroRecusado('WhatsApp exibiu aviso de número inválido ou não registrado.')
        self.definir_etapa('2/5: identificando Adicionar/Editar pela acessibilidade do Windows...')
        estado = self.driver.estado_contato()
        if estado == 'existente':
            self.driver.desktop.atalho(0x1B)
            self.log(f'SKIP: +{numero} já estava salvo. Sem mensagem e sem espera.')
            return False
        self.driver.clicar(ADICIONAR)
        return True

    def fechar_aviso_numero(self):
        self.driver.clicar(('OK','Ok'),5)
        self.driver.aguardar(lambda: self.driver.aviso_recusa() is None,5,'fechar aviso de número recusado')

    def cadastrar(self, contato):
        tela, nome, numero = self.driver, contato['name'], contato['phone']
        for tentativa in range(2):
            self.definir_etapa('3/5: localizando o campo Nome pela acessibilidade...')
            def formulario():
                campo = tela.campo_nome()
                if campo:
                    return 'nome',campo
                criar = tela.buscar(CRIAR)
                return ('criar',criar) if criar else False
            tipo,campo = tela.aguardar(formulario,20,'abrir formulário Novo contato')
            if tipo == 'criar':
                tela.clicar_elemento(campo)
                campo = tela.aguardar(tela.campo_nome,10,'campo Nome')
            tela.digitar(campo,nome)
            self.log('Nome digitado pelo Windows e confirmado no campo: '+nome)
            self.definir_etapa('4/5: conferindo o formulário e aguardando Salvar por até 5s...')
            antes = tela.avisos_salvo()
            try:
                tela.validar_formulario(numero)
                tela.clicar(('Salvar','Guardar','Save','Salvar contato','Save contact','Concluir','Done'),5)
            except (TimeoutError,NativeUIError) as erro:
                if tentativa:
                    raise RuntimeError('O formulário já foi reaberto pelo X uma vez: '+str(erro)) from erro
                self.log(str(erro))
                tela.fechar_formulario()
                if tela.campo_mensagem():
                    estado = tela.estado_contato()
                    if estado == 'existente':
                        tela.desktop.atalho(0x1B)
                        self.cadastro_confirmado = numero
                        self.log('Cadastro confirmado durante recuperação. Seguindo para o envio.')
                        return
                tela.clicar(ADICIONAR+CRIAR)
                continue
            # No retry after a Save click, even if confirmation is inconclusive.
            def concluido():
                avisos = tela.avisos_salvo()
                if avisos-antes:
                    return 'sucesso'
                return 'fechado' if not tela.tem_formulario() else False
            resultado = tela.aguardar(concluido,20,'confirmar cadastro salvo')
            if resultado != 'sucesso':
                if tela.abrir_numero(numero) != 'conversa' or tela.estado_contato() != 'existente':
                    raise RuntimeError('Cadastro não confirmado. Mensagem bloqueada.')
                tela.desktop.atalho(0x1B)
            self.cadastro_confirmado = numero
            self.log('Cadastro confirmado neste lote. Próxima etapa: ENVIAR, sem aplicar SKIP.')
            return

    def enviar(self, contato, texto):
        numero,tela = contato['phone'],self.driver
        if self.cadastro_confirmado != numero:
            raise RuntimeError('Cadastro deste destinatário não confirmado.')
        if self.envio_pendente:
            raise RuntimeError('Há envio incerto. Confira a conversa antes de reiniciar.')
        self.definir_etapa('5/5: abrindo o número exato e conferindo o rascunho...')
        if tela.abrir_numero(numero) != 'conversa':
            raise RuntimeError('Destinatário não abriu antes do envio.')
        campo = tela.aguardar(tela.campo_mensagem,15,'campo de mensagem')
        if tela.ler(campo).strip():
            raise RuntimeError('Existe rascunho. Não será apagado ou misturado.')
        mensagem = texto.replace('\r\n','\n').replace('\r','\n')
        esperado = texto_comparavel(mensagem)
        antes = sum(e.count(esperado) for e in tela.mensagens_saida())
        tela.digitar(campo,mensagem,tab=False)
        self.conferir_parada()
        self.envio_pendente = numero
        try:
            tela.clicar(('Enviar','Send'),5)
            tela.aguardar(lambda: sum(e.count(esperado) for e in tela.mensagens_saida()) > antes,30,
                          'confirmar nova mensagem com marcador de saída')
        except Exception as erro:
            raise RuntimeError('ENVIO INCERTO. Não repetir automaticamente; confira manualmente a conversa.') from erro
        self.envio_pendente = None
        self.log('Nova mensagem de saída observada. Entrega não confirmada.')

    def diagnostico(self):
        if self.driver is None:
            return
        pasta = Path(__file__).resolve().parent / 'diagnosticos'
        pasta.mkdir(exist_ok=True)
        nome = 'nativo_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        try:
            destino = pasta/(nome+'.json')
            destino.write_text(json.dumps({'etapa':self.etapa,'controles':self.driver.ultimos},ensure_ascii=False,indent=2),encoding='utf-8')
            self.log('Diagnóstico LOCAL de controles: '+str(destino))
            imagem = pasta/(nome+'.bmp')
            if self.driver.save_screenshot(imagem):
                self.log('Captura LOCAL: '+str(imagem))
        except Exception as erro:
            self.log('Não foi possível concluir a captura: '+str(erro))


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
