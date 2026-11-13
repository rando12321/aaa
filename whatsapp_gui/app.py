"""Aplicativo completo em um arquivo.

Instalação: python -m pip install playwright==1.56.0
Navegador: python -m playwright install chromium
Execução: python app.py
Requer Python 3.12+, Tkinter e desktop gráfico.
Cadastro/envio reais ainda exigem validação com a interface autenticada.
"""
import csv
import json
import os
import queue
import random
import re
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from playwright.sync_api import sync_playwright


@dataclass(frozen=True)
class Contact:
    phone: str
    name: str


def normalize_phone(value):
    # Only strip whitespace and ordinary telephone punctuation; never discard letters.
    number = re.sub(r'[\s()+.\-/]', '', value)
    if not number.isascii() or not number.isdigit():
        raise ValueError('telefone contém caracteres inválidos')
    if len(number) in (10, 11):
        number = '55' + number
    elif len(number) not in (12, 13) or not number.startswith('55'):
        raise ValueError('esperado número brasileiro nacional ou com 55 completo')
    if number == '5511999999999':
        return None
    return number


def read_contacts(path):
    contacts, errors, seen = [], [], set()
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        sample = stream.read(8192)
        stream.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=',;')
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(stream, dialect=dialect)
        if not {'phone', 'name'}.issubset(reader.fieldnames or []):
            raise ValueError('CSV precisa das colunas phone e name')
        for line, row in enumerate(reader, 2):
            raw = (row.get('phone') or '').strip()
            if not raw:
                continue
            try:
                phone = normalize_phone(raw)
            except ValueError as exc:
                errors.append(f'Linha {line}: {exc}')
                continue
            if phone is None or phone in seen:
                continue
            seen.add(phone)
            name = (row.get('name') or '').strip() or f'Contato {random.SystemRandom().randint(100000, 999999)}'
            contacts.append(Contact(phone, name))
    return contacts, errors


def wait_seconds(base, rng=random):
    if base < 0:
        raise ValueError('tempo base não pode ser negativo')
    return base + rng.randint(60, 180)


class Stopped(Exception):
    pass


class WhatsApp:
    def __init__(self, root, stop, log, executable=None):
        self.root, self.stop, self.log = Path(root), stop, log
        self.executable = executable
        self.stage = 'inicialização'

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.driver = sync_playwright().start()
        try:
            self.context = self.driver.chromium.launch_persistent_context(
                str(self.root / 'profile'), headless=False,
                executable_path=self.executable, viewport={'width': 1280, 'height': 900})
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            self.page.set_default_timeout(1200)
            self.page.goto('https://web.whatsapp.com/', wait_until='domcontentloaded')
            self.log('Faça login pelo QR no Chrome. Aguardando lista de conversas (até 180s).')
            self.until(lambda: self.page.locator('#pane-side').is_visible(), 180)
            return self
        except BaseException:
            if hasattr(self, 'context'):
                self.context.close()
            self.driver.stop()
            raise

    def __exit__(self, *args):
        self.context.close()
        self.driver.stop()

    def until(self, predicate, timeout=30):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.stop.is_set():
                raise Stopped()
            result = predicate()
            if result:
                return result
            self.stop.wait(.2)
        raise TimeoutError(f'timeout na etapa: {self.stage}')

    def step(self, name):
        self.stage = name
        self.log(name)

    def one(self, locator):
        if locator.count() != 1 or not locator.is_visible():
            raise RuntimeError(f'{self.stage}: elemento único visível não identificado')
        return locator

    def menu(self):
        header = self.one(self.page.locator('#main header'))
        self.one(header.get_by_role('button', name=re.compile(r'^(Menu|Mais opções|More options)$', re.I))).click()

    def menu_entry(self, pattern):
        return self.page.get_by_role('button', name=pattern).or_(self.page.get_by_role('menuitem', name=pattern))

    def contact_state(self):
        self.menu()
        edit = self.menu_entry(re.compile(r'^(Editar contato|Edit contact)$', re.I))
        add = self.menu_entry(re.compile(r'^(Adicionar aos contatos|Add to contacts)$', re.I))
        try:
            self.until(lambda: edit.is_visible() or add.is_visible(), 5)
            if edit.is_visible() and not add.is_visible():
                return 'existing', None
            if add.is_visible() and not edit.is_visible():
                return 'new', add
            raise RuntimeError('evidências de contato conflitantes')
        except BaseException:
            self.page.keyboard.press('Escape')
            raise

    def process(self, contact, message):
        self.step('abrir destinatário e verificar resposta')
        self.page.goto(f'https://web.whatsapp.com/send?phone={contact.phone}', wait_until='domcontentloaded')
        refused = self.page.get_by_role('dialog').filter(has_text=re.compile(
            r'(número.*(inválido|não.*WhatsApp)|phone number.*(invalid|not on WhatsApp))', re.I))
        composer = self.page.locator('#main footer [contenteditable="true"][role="textbox"]')
        self.until(lambda: refused.is_visible() or composer.is_visible(), 60)
        if refused.is_visible():
            self.log('Aviso: ' + refused.inner_text())
            self.one(refused.get_by_role('button', name=re.compile(r'^OK$', re.I))).click()
            self.until(lambda: not refused.is_visible(), 5)
            return 'refused'
        self.step('detectar contato salvo pelo menu da conversa')
        state, add = self.contact_state()
        if state == 'existing':
            self.page.keyboard.press('Escape')
            return 'existing'
        self.step('abrir formulário de novo contato')
        self.one(add).click()
        create = self.menu_entry(re.compile(r'^(Criar contato|Create new contact|Create contact)$', re.I))
        name = self.page.get_by_role('textbox', name=re.compile(r'^(Nome|First name|Name)$', re.I))
        self.until(lambda: name.is_visible() or create.is_visible(), 10)
        if create.is_visible():
            self.one(create).click()
        self.until(lambda: name.is_visible(), 10)
        self.step('conferir telefone do formulário e preencher nome')
        phone = self.one(self.page.get_by_role('textbox', name=re.compile(r'^(Telefone|Número de telefone|Phone|Phone number)$', re.I)))
        if re.sub(r'\D', '', phone.input_value()) != contact.phone:
            raise RuntimeError('telefone do formulário diverge do destinatário')
        self.one(name).fill(contact.name)
        self.step('salvar contato pelo botão identificado por nome acessível')
        # Never click a generic checkmark: it could be the phone verification icon.
        save = self.page.get_by_role('button', name=re.compile(r'^(Salvar|Save|Salvar contato|Save contact)$', re.I))
        self.one(save).click()
        self.until(lambda: not name.is_visible(), 15)
        self.step('confirmar cadastro salvo pelo menu Editar contato')
        state, _ = self.contact_state()
        self.page.keyboard.press('Escape')
        if state != 'existing':
            raise RuntimeError('cadastro não confirmado; mensagem bloqueada')
        self.step('confirmar destinatário novamente')
        # Re-open exactly the requested number after the contact form was closed.
        self.page.goto(f'https://web.whatsapp.com/send?phone={contact.phone}', wait_until='domcontentloaded')
        self.until(lambda: composer.is_visible(), 60)
        self.step('preparar mensagem sem misturar rascunho')
        field = self.one(composer)
        if field.inner_text().strip():
            raise RuntimeError('há rascunho existente; mensagem bloqueada')
        outgoing = self.page.locator('#main .message-out')
        previous_ids = set(outgoing.evaluate_all('(els) => els.map(e => e.closest("[data-id]")?.getAttribute("data-id")).filter(Boolean)'))
        rendered = message.replace('{name}', contact.name)
        field.fill(rendered)
        if field.inner_text().replace('\r\n', '\n') != rendered.replace('\r\n', '\n'):
            raise RuntimeError('rascunho não corresponde à mensagem; envio bloqueado')
        self.step('envio solicitado; não repetir se confirmação falhar')
        if self.stop.is_set():
            raise Stopped()
        field.press('Enter')
        def new_bubble():
            for bubble in outgoing.all():
                identifier = bubble.evaluate('(e) => e.closest("[data-id]")?.getAttribute("data-id")')
                if identifier and identifier not in previous_ids:
                    text = bubble.locator('.selectable-text')
                    if text.count() and text.first.inner_text().strip() == rendered.strip():
                        return True
            return False
        try:
            self.until(new_bubble, 20)
        except Exception as exc:
            raise RuntimeError('ENVIO INCERTO: não repetir automaticamente; confira a conversa') from exc
        return 'sent'

    def screenshot(self, phone):
        target = self.root / f'erro-{phone}-{time.time_ns()}.png'
        self.page.screenshot(path=str(target), full_page=True)
        return target


ROOT = Path(__file__).resolve().parent / '.local'


class App:
    def __init__(self, window):
        self.window = window
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.running = False
        window.title('Contatos • WhatsApp Web')
        window.geometry('850x680')
        frame = ttk.Frame(window, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Cadastro e mensagens', font=('', 20, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='CSV: phone,name • Login por QR • Interface em português ou inglês').pack(anchor='w', pady=8)
        self.csv = tk.StringVar()
        row = ttk.Frame(frame)
        row.pack(fill='x')
        ttk.Entry(row, textvariable=self.csv).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='Escolher CSV', command=self.choose).pack(side='right')
        ttk.Label(frame, text='Mensagem ({name} será substituído pelo nome cadastrado):').pack(anchor='w', pady=(15, 5))
        self.message = scrolledtext.ScrolledText(frame, height=6)
        self.message.pack(fill='x')
        self.message.insert('1.0', 'Olá, {name}!')
        row = ttk.Frame(frame)
        row.pack(fill='x', pady=12)
        ttk.Label(row, text='Espera base (segundos) + sorteio de 60 a 180:').pack(side='left')
        self.base = tk.StringVar(value='30')
        ttk.Entry(row, textvariable=self.base, width=8).pack(side='left', padx=8)
        self.start = ttk.Button(row, text='Iniciar', command=self.begin)
        self.start.pack(side='left', padx=8)
        ttk.Button(row, text='Parar', command=self.stop.set).pack(side='left')
        self.progress = tk.StringVar(value='Aguardando CSV')
        ttk.Label(frame, textvariable=self.progress).pack(anchor='w')
        self.logs = scrolledtext.ScrolledText(frame, height=16, state='disabled')
        self.logs.pack(fill='both', expand=True, pady=8)
        window.protocol('WM_DELETE_WINDOW', self.close)
        window.after(100, self.poll)

    def choose(self):
        path = filedialog.askopenfilename(filetypes=[('CSV', '*.csv')])
        if path:
            self.csv.set(path)

    def log(self, text):
        self.events.put(('log', text))

    def begin(self):
        if self.running:
            return
        try:
            contacts, errors = read_contacts(self.csv.get())
            base = int(self.base.get())
            if base < 0 or not contacts:
                raise ValueError('Informe tempo não negativo e CSV com contatos válidos')
            message = self.message.get('1.0', 'end-1c')
            if not message.strip():
                raise ValueError('Mensagem vazia')
        except Exception as exc:
            messagebox.showerror('Dados inválidos', str(exc))
            return
        for error in errors:
            self.log(error)
        self.running = True
        self.start.configure(state='disabled')
        self.stop.clear()
        threading.Thread(target=self.run, args=(contacts, base, message), daemon=True).start()

    def run(self, contacts, base, message):
        ROOT.mkdir(parents=True, exist_ok=True)
        journal = ROOT / 'historico.jsonl'
        try:
            # Started numbers require manual review on later runs: no accidental retry.
            seen = set()
            if journal.exists():
                for line in journal.read_text(encoding='utf-8').splitlines():
                    seen.add(json.loads(line)['phone'])
            with journal.open('a', encoding='utf-8') as output:
                def record(phone, status):
                    output.write(json.dumps({'phone': phone, 'status': status, 'time': time.time()}, ensure_ascii=False) + '\n')
                    output.flush()
                    os.fsync(output.fileno())
                with WhatsApp(ROOT, self.stop, self.log, os.environ.get('WHATSAPP_CHROME')) as browser:
                    for i, contact in enumerate(contacts):
                        if self.stop.is_set():
                            break
                        self.events.put(('progress', f'{i + 1}/{len(contacts)} — {contact.name} — {contact.phone}'))
                        if contact.phone in seen:
                            self.log('SKIP: já registrado; revise o histórico antes de nova tentativa')
                            continue
                        record(contact.phone, 'started')
                        try:
                            outcome = browser.process(contact, message)
                            record(contact.phone, outcome)
                            self.log({'sent': 'ENVIADO: nova mensagem observada na conversa; entrega não confirmada',
                                      'existing': 'SKIP: contato existente', 'refused': 'SKIP: número recusado'}[outcome])
                        except Stopped:
                            record(contact.phone, 'stopped_review_required')
                            break
                        except Exception as exc:
                            record(contact.phone, 'error_review_required')
                            self.log(f'ERRO [{browser.stage}]: {exc}')
                            try:
                                self.log(f'Captura: {browser.screenshot(contact.phone)}')
                            except Exception as capture_error:
                                self.log(f'Falha ao capturar: {capture_error}')
                            # Stop on unknown UI or uncertain send; do not compound errors.
                            break
                        remaining = any(c.phone not in seen for c in contacts[i + 1:])
                        if remaining and outcome in ('sent', 'existing'):
                            delay = wait_seconds(base)
                            self.log(f'Espera: {delay}s (Parar interrompe)')
                            if self.stop.wait(delay):
                                break
        except Stopped:
            self.log('Interrompido')
        except Exception as exc:
            self.log(f'ERRO: {exc}')
        finally:
            self.events.put(('done', 'Processamento encerrado. Consulte o registro.'))

    def poll(self):
        try:
            while True:
                kind, text = self.events.get_nowait()
                if kind == 'progress':
                    self.progress.set(text)
                else:
                    self.logs.configure(state='normal')
                    self.logs.insert('end', time.strftime('%H:%M:%S ') + text + '\n')
                    self.logs.see('end')
                    self.logs.configure(state='disabled')
                if kind == 'done':
                    self.running = False
                    self.start.configure(state='normal')
        except queue.Empty:
            pass
        self.window.after(100, self.poll)

    def close(self):
        if self.running:
            self.stop.set()
            self.log('Parando; aguarde o navegador encerrar antes de fechar a janela.')
        else:
            self.window.destroy()


if __name__ == '__main__':
    window = tk.Tk()
    App(window)
    window.mainloop()
