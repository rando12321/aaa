"""Conservative UI adapter. Unknown UI states stop the current contact, never send."""
import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright


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
