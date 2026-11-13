import json
import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from browser import Stopped, WhatsApp
from core import read_contacts, wait_seconds

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
