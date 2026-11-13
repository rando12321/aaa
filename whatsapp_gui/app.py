"""Versão baseada integralmente no último arquivo fornecido pelo usuário.
Requer: pip install selenium==4.38.0
Execute: python app.py
"""
import json
import os
import csv
import queue
import random
import re
import secrets
import threading
import tkinter as tk
import unicodedata

from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlencode

from selenium import webdriver
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait


IGNORADOS = {"11999999999", "5511999999999"}

ADICIONAR = [
    "Adicionar aos contatos",
    "Adicionar a contatos",
    "Adicionar aos contactos",
    "Adicionar contato",
    "Add to contacts",
    "Add contact",
]

EDITAR = [
    "Editar contato",
    "Editar contacto",
    "Edit contact",
]

CRIAR = [
    "Criar contato",
    "Criar novo contato",
    "Novo contato",
    "Create contact",
    "Create new contact",
    "New contact",
]

PAINEIS = (
    '[role="dialog"], [role="alertdialog"], [role="alert"], '
    '[data-animate-modal-popup="true"], '
    '[data-testid="popup-contents"]'
)


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
    sobrenome = secrets.choice(
        ("Silva", "Costa", "Lima", "Rocha", "Souza")
    )
    return f"{primeiro} {sobrenome} {secrets.token_hex(3).upper()}"


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

    nomes = [contato["name"] for contato in contatos]

    if len(nomes) != len(set(nomes)):
        raise ValueError(
            "Use nomes diferentes para cada contato."
        )

    return contatos, ignorados


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

        root.title("WhatsApp — cadastrar e enviar")
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
                "Brasil +55. Contatos existentes são pulados. "
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

    def esperar(self, funcao, segundos=30):
        def verificar(driver):
            self.conferir_parada()

            try:
                return funcao(driver)
            except StaleElementReferenceException:
                return False

        try:
            return WebDriverWait(
                self.driver, segundos
            ).until(verificar)

        except TimeoutException as erro:
            raise RuntimeError(
                "Tempo esgotado na etapa: " + self.etapa
            ) from erro

    def visiveis(self, seletor, base=None):
        base = base if base is not None else self.driver

        return [
            elemento
            for elemento in base.find_elements(
                By.CSS_SELECTOR, seletor
            )
            if elemento.is_displayed()
        ]

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

    def chrome(self):
        if self.envio_pendente:
            if not messagebox.askyesno("Envio incerto", "Confira manualmente a conversa antes de continuar. Você já verificou o envio anterior?"):
                return
            self.envio_pendente = None
        def abrir():
            if self.driver is None:
                opcoes = webdriver.ChromeOptions()
                perfil = (
                    Path.home()
                    / ".whatsapp_csv_sender"
                    / "chrome"
                )

                opcoes.add_argument(
                    f"--user-data-dir={perfil}"
                )
                if os.environ.get("WHATSAPP_CHROME"):
                    opcoes.binary_location = os.environ["WHATSAPP_CHROME"]
                servico = Service(executable_path=os.environ["WHATSAPP_CHROMEDRIVER"]) if os.environ.get("WHATSAPP_CHROMEDRIVER") else Service()
                self.driver = webdriver.Chrome(service=servico, options=opcoes)

            self.driver.get("https://web.whatsapp.com/")
            self.log(
                "Escaneie o QR e espere as conversas carregarem."
            )

        self.executar(abrir)

    def campo_mensagem(self, driver):
        # Never accept a search field or a textbox belonging to another panel.
        campos = self.visiveis(
            '#main footer [contenteditable="true"][role="textbox"], '
            '#main footer [contenteditable="true"][data-lexical-editor="true"]'
        )
        campos = [c for c in campos if c.is_enabled()]
        return campos[0] if len(campos) == 1 else False

    def cabecalho(self):
        elementos = self.visiveis('#main header')
        return elementos[0] if len(elementos) == 1 else None

    def nome_confirmado(self, nome):
        cabecalho = self.cabecalho()

        if cabecalho is None:
            return False

        textos = cabecalho.text.splitlines()
        textos += [
            elemento.get_attribute("title") or ""
            for elemento in cabecalho.find_elements(
                By.CSS_SELECTOR, "[title]"
            )
        ]

        esperado = " ".join(nome.split())

        return esperado in [
            " ".join(texto.split())
            for texto in textos
        ]

    def buscar_texto(self, nomes, base=None):
        base = base if base is not None else self.driver

        for nome in nomes:
            condicao = (
                f"normalize-space(.)={literal(nome)}"
            )
            xpath = (
                f".//*[{condicao} "
                f"and not(.//*[{condicao}])]"
            )

            for elemento in base.find_elements(
                By.XPATH, xpath
            ):
                if (
                    elemento.is_displayed()
                    and elemento.is_enabled()
                ):
                    return elemento

        return False

    def encontrar_aviso_numero(self):
        avisos = (
            "numero de telefone invalido",
            "numero compartilhado por url e invalido",
            "phone number shared via url is invalid",
            "phone number is invalid",
            "nao esta no whatsapp",
            "nao esta registrado no whatsapp",
            "is not on whatsapp",
            "isn't on whatsapp",
            "not registered on whatsapp",
        )

        for painel in self.visiveis(PAINEIS):
            texto = normalizar(painel.text)

            if any(aviso in texto for aviso in avisos) or re.search(
                r"(?:numero.*(?:invalido|nao (?:esta |e )?(?:registrado )?no whatsapp)|phone number.*(?:invalid|not (?:registered )?on whatsapp))", texto
            ):
                return painel

        return None

    def fechar_aviso_numero(self):
        self.definir_etapa(
            "Fechando o aviso do WhatsApp..."
        )

        def localizar(driver):
            painel = self.encontrar_aviso_numero()

            if painel is None:
                return "fechado", None

            for botao in painel.find_elements(
                By.CSS_SELECTOR,
                'button, [role="button"]',
            ):
                if (
                    not botao.is_displayed()
                    or not botao.is_enabled()
                ):
                    continue

                rotulo = normalizar(
                    botao.text
                    or botao.get_attribute("aria-label")
                    or ""
                )

                if rotulo == "ok":
                    return "botao", botao

            elemento = self.buscar_texto(
                ["OK", "Ok"], painel
            )

            if elemento:
                botao = driver.execute_script(
                    r"""
                    return arguments[0].closest(
                        'button, [role="button"]'
                    ) || arguments[0];
                    """,
                    elemento,
                )
                return "botao", botao

            return False

        estado, botao = self.esperar(localizar, 15)

        if estado == "botao":
            self.conferir_parada()
            botao.click()

        self.esperar(
            lambda driver:
            self.encontrar_aviso_numero() is None,
            15,
        )

        self.log("Aviso fechado.")

    def localizar_menu(self, driver, base=None):
        base = base if base is not None else self.cabecalho()
        if base is None:
            return False
        return driver.execute_script(
            r"""
            const root = arguments[0];
            const visible = e => e.getClientRects().length
                && getComputedStyle(e).visibility !== 'hidden';
            const found = new Set();
            for (const e of root.querySelectorAll(
                'button, [role="button"], [data-icon], [aria-label], [title]'
            )) {
                if (!visible(e)) continue;
                const label = (e.getAttribute('aria-label') || e.getAttribute('title') || '').trim();
                const icon = e.getAttribute('data-icon') || '';
                if (!/^(menu|mais op[cç][oõ]es|more options)$/i.test(label)
                    && !/^(menu|more-vertical|more_vert|overflow-menu)$/.test(icon)) continue;
                const button = e.closest('button, [role="button"], [tabindex="0"]');
                if (button && root.contains(button) && visible(button)
                    && !button.disabled && button.getAttribute('aria-disabled') !== 'true') found.add(button);
            }
            return found.size === 1 ? [...found][0] : null;
            """, base,
        ) or False

    def abrir_e_detectar(self, numero):
        self.numero_atual = numero
        self.cadastro_confirmado = None
        self.definir_etapa(f"1/5: abrindo e verificando +{numero}...")
        self.driver.get("https://web.whatsapp.com/send?" + urlencode({"phone": numero}))
        self.esperar(self.conversa_ou_recusa, 90)
        self.definir_etapa("2/5: verificando se o contato está salvo...")
        estado, elemento = self.detectar_estado_contato()
        if estado == "existente":
            self.log(f"SKIP: +{numero} já está nos contatos. Cadastro e envio ignorados.")
            self.fechar_sobreposicoes()
            return False
        self.conferir_parada()
        elemento.click()
        return True

    def campo_nome(self, driver):
        aceitos = {
            "nome",
            "primeiro nome",
            "name",
            "first name",
            "given name",
            "given-name",
            "nome completo",
            "full name",
        }

        seletor = (
            'input:not([type="hidden"])'
            ':not([type="checkbox"])'
            ':not([type="radio"])'
            ':not([type="search"]), '
            '[contenteditable="true"][role="textbox"]'
        )

        for campo in self.visiveis(seletor):
            if not campo.is_enabled():
                continue

            if driver.execute_script(
                "return !!arguments[0].closest('footer, #side');",
                campo,
            ):
                continue

            rotulos = [
                campo.get_attribute(atributo) or ""
                for atributo in (
                    "aria-label",
                    "placeholder",
                    "name",
                    "autocomplete",
                )
            ]

            rotulos += driver.execute_script(
                r"""
                return Array.from(arguments[0].labels || [])
                    .map(label => label.innerText);
                """,
                campo,
            )

            for referencia in (
                campo.get_attribute("aria-labelledby") or ""
            ).split():
                rotulos += [
                    elemento.text
                    for elemento in driver.find_elements(
                        By.ID, referencia
                    )
                ]

            for rotulo in rotulos:
                texto = re.sub(
                    r"[\s:*]+$", "", normalizar(rotulo)
                )

                if texto in aceitos:
                    return campo

        xpath = (
            "//*[normalize-space(.)='Nome' "
            "and not(.//*[normalize-space(.)='Nome'])]"
        )

        for rotulo in driver.find_elements(By.XPATH, xpath):
            if not rotulo.is_displayed():
                continue

            campo = driver.execute_script(
                r"""
                let parent = arguments[0].parentElement;

                for (
                    let level = 0;
                    parent && level < 6;
                    level++, parent = parent.parentElement
                ) {
                    const fields = Array.from(
                        parent.querySelectorAll(
                            'input:not([type=hidden])'
                            + ':not([type=checkbox])'
                            + ':not([type=radio]), '
                            + '[contenteditable=true]'
                        )
                    ).filter(e =>
                        e.getClientRects().length
                        && !e.disabled
                        && !e.closest('footer, #side')
                    );

                    if (fields.length === 1) return fields[0];
                    if (fields.length > 1) return null;
                }

                return null;
                """,
                rotulo,
            )

            if campo:
                return campo

        return False

    def confirmar_cadastro(self, campo):
        self.definir_etapa("4/5: procurando o botão de salvar no formulário...")
        def encontrar(driver):
            painel = self.painel_formulario(campo)
            if not painel:
                return False
            return driver.execute_script(
                r"""
                const panel = arguments[0], field = arguments[1];
                const visible = e => e.getClientRects().length
                    && getComputedStyle(e).visibility !== 'hidden';
                const norm = s => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
                const buttons = [...panel.querySelectorAll('button, [role="button"]')]
                    .filter(e => visible(e) && !e.disabled && e.getAttribute('aria-disabled') !== 'true');
                const named = buttons.filter(b => [b.innerText, b.getAttribute('aria-label'), b.title]
                    .some(t => /^(salvar|guardar|save|salvar contato|save contact|concluir|done)$/.test(norm(t || ''))));
                if (named.length === 1) return named[0];
                if (named.length > 1) return null;
                // Icon-only save: require the unique bottom action in this form.
                // A phone validation check is inside its field row, never an action.
                const f = field.getBoundingClientRect();
                const checks = buttons.filter(b => {
                    const r = b.getBoundingClientRect();
                    const icon = [b, ...b.querySelectorAll('[data-icon], [aria-label]')]
                        .some(e => /^(check|checkmark|tick|done|save)$/.test(
                            (e.getAttribute('data-icon') || e.getAttribute('aria-label') || '').toLowerCase()));
                    const row = b.closest('label, [data-testid*="phone"], [data-testid*="input"]');
                    return icon && !row && r.top > f.bottom && r.top >= panel.getBoundingClientRect().top
                        && !buttons.some(other => other !== b && other.getBoundingClientRect().top > r.bottom);
                });
                return checks.length === 1 ? checks[0] : null;
                """, painel, campo,
            ) or False
        botao = self.esperar(encontrar)
        self.conferir_parada()
        botao.click()

    def cadastrar(self, contato):
        nome, numero = contato["name"], contato["phone"]
        self.definir_etapa("3/5: abrindo o formulário e preenchendo Nome...")
        def formulario(driver):
            campo = self.campo_nome(driver)
            if campo:
                return "campo", campo
            criar = self.acao_visivel(CRIAR)
            return ("criar", criar) if criar else False
        tipo, campo = self.esperar(formulario)
        if tipo == "criar":
            self.conferir_parada()
            campo.click()
            campo = self.esperar(self.campo_nome)
        self.definir_etapa("Conferindo telefone do formulário...")
        painel = self.painel_formulario(campo)
        if not painel or not self.telefone_no_painel(painel, numero):
            raise RuntimeError("Não foi possível confirmar o telefone do formulário. Cadastro bloqueado.")
        self.conferir_parada()
        campo.click()
        modificador = Keys.COMMAND if self.driver.capabilities.get('platformName', '').lower() == 'mac' else Keys.CONTROL
        campo.send_keys(modificador, "a")
        campo.send_keys(Keys.BACKSPACE)
        campo.send_keys(nome)
        atributo = "value" if campo.tag_name.lower() == "input" else "textContent"
        if (campo.get_attribute(atributo) or "").strip() != nome:
            raise RuntimeError("O campo Nome não recebeu o texto esperado.")
        self.confirmar_cadastro(campo)
        def fechado(driver):
            try:
                return not campo.is_displayed()
            except StaleElementReferenceException:
                return True
        self.esperar(fechado)
        self.definir_etapa("Confirmando cadastro salvo pela opção Editar contato...")
        self.fechar_sobreposicoes()
        estado, _ = self.detectar_estado_contato()
        self.fechar_sobreposicoes()
        if estado != "existente":
            raise RuntimeError("O formulário fechou, mas o cadastro não foi confirmado. Envio bloqueado.")
        self.cadastro_confirmado = numero
        self.log("Cadastro confirmado pela interface: Editar contato disponível.")

    def enviar(self, contato, texto):
        numero = contato["phone"]
        if getattr(self, "cadastro_confirmado", None) != numero:
            raise RuntimeError("Cadastro deste destinatário não confirmado. Envio bloqueado.")
        if getattr(self, "envio_pendente", None):
            raise RuntimeError("Há um envio incerto nesta sessão. Confira a conversa e reconecte antes de tentar novamente.")
        self.definir_etapa("5/5: reabrindo o número exato antes de enviar...")
        self.driver.get("https://web.whatsapp.com/send?" + urlencode({"phone": numero}))
        self.esperar(self.conversa_ou_recusa, 90)
        campo = self.esperar(self.campo_mensagem)
        if (campo.get_attribute("textContent") or "").strip():
            raise RuntimeError("Existe um rascunho na conversa. Limpe-o antes de continuar.")
        texto = texto.replace("\r\n", "\n").replace("\r", "\n")
        anteriores = self.mensagens_saida()
        self.definir_etapa("Preenchendo e conferindo a mensagem completa...")
        # insertText supports emoji/non-BMP text, unlike ChromeDriver send_keys.
        campo.click()
        self.driver.execute_cdp_cmd('Input.insertText', {'text': texto})
        def conferir_texto(driver):
            atual = self.campo_mensagem(driver)
            return atual and self.texto_editor(atual) == texto
        self.esperar(conferir_texto, 10)
        self.conferir_parada()
        self.definir_etapa("Enviando uma única vez e aguardando nova mensagem de saída...")
        self.envio_pendente = numero
        try:
            # Prefer the explicit send action; only use Enter when no action exists.
            botoes = self.driver.execute_script(
                r"""
                const footer = arguments[0].closest('footer');
                const found = new Set();
                for (const e of footer.querySelectorAll('button, [role="button"], [data-icon]')) {
                    if (!e.getClientRects().length) continue;
                    const label = e.getAttribute('aria-label') || '';
                    if (!/^(enviar|send)$/i.test(label) && e.getAttribute('data-icon') !== 'send') continue;
                    const b = e.closest('button, [role="button"]');
                    if (b && !b.disabled && b.getAttribute('aria-disabled') !== 'true') found.add(b);
                }
                return [...found];
                """, campo,
            )
            if len(botoes) > 1:
                self.envio_pendente = None
                raise RuntimeError("Mais de um botão de envio encontrado; envio bloqueado.")
            if botoes:
                botoes[0].click()
            else:
                campo.send_keys(Keys.ENTER)
            def nova_mensagem(driver):
                mensagens = self.mensagens_saida()
                return any(chave not in anteriores and valor == texto for chave, valor in mensagens.items())
            self.esperar(nova_mensagem, 30)
        except Exception as erro:
            raise RuntimeError("ENVIO INCERTO: não repetir automaticamente. Confira a conversa; o lote foi interrompido.") from erro
        self.envio_pendente = None
        self.log("Nova mensagem de saída confirmada na conversa. Entrega ao destinatário não confirmada.")


    def conversa_ou_recusa(self, driver):
        painel = self.encontrar_aviso_numero()
        if painel is not None:
            raise NumeroRecusado(painel.text)
        return self.cabecalho() and self.campo_mensagem(driver)

    def acao_visivel(self, nomes, bases=None):
        # Match actionable labels, including aria-label/title and nested span text.
        bases = bases if bases is not None else self.visiveis(
            '[role="menu"], [role="dialog"], [data-testid="drawer-right"], '
            '[data-testid="contact-info-drawer"], #app [role="complementary"], '
            '[data-animate-dropdown-menu="true"]'
        )
        if not bases:
            # Portaled WhatsApp menus may not declare role=menu. Only semantic
            # interactive actions with the exact expected label are accepted.
            bases = [self.driver]
        encontrados = {}
        aceitos = {normalizar(nome) for nome in nomes}
        for base in bases:
            for elemento in base.find_elements(By.CSS_SELECTOR, 'button, [role="button"], [role="menuitem"], [tabindex="0"]'):
                if not elemento.is_displayed() or not elemento.is_enabled():
                    continue
                if elemento.get_attribute('aria-disabled') == 'true':
                    continue
                rotulos = [elemento.text, elemento.get_attribute('aria-label') or '', elemento.get_attribute('title') or '']
                if any(normalizar(rotulo) in aceitos for rotulo in rotulos):
                    encontrados[elemento.id] = elemento
            # Keep support for older text-only menu items from the supplied file.
            texto = self.buscar_texto(nomes, base) if base is not self.driver else False
            if texto:
                botao = self.driver.execute_script(
                    "return arguments[0].closest('button, [role=button], [role=menuitem]') || arguments[0];", texto)
                if not self.driver.execute_script("return !!arguments[0].closest('#main .message-in, #main .message-out, #side');", botao):
                    encontrados[botao.id] = botao
        if len(encontrados) > 1:
            raise RuntimeError('Ação de contato ambígua; confira o diagnóstico.')
        return next(iter(encontrados.values()), False)

    def estado_visivel(self):
        editar = self.acao_visivel(EDITAR)
        adicionar = self.acao_visivel(ADICIONAR)
        if editar and adicionar:
            raise RuntimeError('Interface exibe adicionar e editar ao mesmo tempo; estado inconclusivo.')
        if editar:
            return 'existente', editar
        # In Contact info, some versions use a pencil instead of 'Edit contact'.
        for painel in self.paineis_contato():
            if not self.telefone_no_painel(painel, self.numero_atual):
                continue
            lapis = self.driver.execute_script(r"""
                const found = new Set();
                for (const e of arguments[0].querySelectorAll('[data-icon], button, [role=button]')) {
                    if (!e.getClientRects().length) continue;
                    const label = e.getAttribute('aria-label') || '';
                    if (!/^(editar|edit|editar contato|edit contact)$/i.test(label)
                        && !/^(edit|pencil|edit-contact)$/.test(e.getAttribute('data-icon') || '')) continue;
                    const b = e.closest('button, [role=button]');
                    if (b && !b.disabled && b.getAttribute('aria-disabled') !== 'true') found.add(b);
                }
                return found.size === 1 ? [...found][0] : null;
            """, painel)
            if lapis:
                if adicionar:
                    raise RuntimeError('Evidências de contato conflitantes nos dados do contato.')
                return 'existente', lapis
        if adicionar:
            return 'novo', adicionar
        return False

    def fechar_sobreposicoes(self):
        ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
        # The contact information drawer does not always close on Escape.
        for painel in self.paineis_contato():
            botao = self.acao_visivel(['Fechar', 'Close', 'Voltar', 'Back'], [painel])
            if botao:
                botao.click()
                def fechado(driver):
                    try:
                        return not painel.is_displayed()
                    except StaleElementReferenceException:
                        return True
                self.esperar(fechado)

    def detectar_estado_contato(self):
        # Some versions expose Add/Edit in the chat menu, others in Contact info.
        # Profile names and timeouts are never evidence of a saved contact.
        def no_menu(driver):
            return self.estado_visivel()
        menu = self.esperar(self.localizar_menu, 15)
        self.conferir_parada()
        menu.click()
        try:
            return self.esperar(no_menu, 5)
        except RuntimeError as erro:
            if not isinstance(erro.__cause__, TimeoutException):
                raise
        info = self.acao_visivel(['Dados do contato', 'Dados do contacto', 'Informações do contato', 'Contact info'])
        if info:
            info.click()
        else:
            ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            # Open only the title area inside the current conversation header.
            titulo = self.driver.execute_script(
                r"""
                const header = arguments[0];
                const candidates = [...header.querySelectorAll('[data-testid="conversation-info-header-chat-title"], [title], [role="button"]')]
                    .filter(e => e.getClientRects().length && e.innerText.trim()
                        && !e.closest('button') && !e.querySelector('[data-icon="menu"]')
                        && !/^(menu|mais opções|more options)$/i.test(e.getAttribute('aria-label') || ''));
                return candidates.find(e => e.hasAttribute('title')) || (candidates.length === 1 ? candidates[0] : null);
                """, self.cabecalho())
            if not titulo:
                raise RuntimeError('Não identifiquei a área de dados do contato nesta versão do WhatsApp.')
            titulo.click()
        self.definir_etapa('Verificando Adicionar/Editar nos dados do contato...')
        def dados(driver):
            estado = self.estado_visivel()
            if estado:
                return 'estado', estado
            paineis = self.paineis_contato()
            for painel in paineis:
                botao = self.localizar_menu(driver, painel)
                if botao:
                    return 'menu', botao
            return False
        tipo, valor = self.esperar(dados, 15)
        if tipo == 'estado':
            return valor
        valor.click()
        return self.esperar(no_menu, 10)

    def paineis_contato(self):
        return self.visiveis('[data-testid="drawer-right"], [data-testid="contact-info-drawer"], #app [role="complementary"]')

    def painel_formulario(self, campo):
        return self.driver.execute_script(
            r"""
            const ancestors = [];
            let p = arguments[0].parentElement;
            while (p && p !== document.body && !['app', 'main', 'side'].includes(p.id)) {
                ancestors.push(p);
                p = p.parentElement;
            }
            const semantic = ancestors.find(e => e.matches('form, [role="dialog"], [data-testid="drawer-right"]'));
            if (semantic) return semantic;
            for (const e of ancestors) {
                const text = (e.innerText || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
                const actions = [...e.querySelectorAll('button, [role="button"]')];
                const save = actions.some(b => /^(salvar|save|guardar|concluir|done|salvar contato|save contact)$/i.test(
                    (b.getAttribute('aria-label') || b.innerText || '').trim()));
                if (save && /contato|contact|telefone|phone/.test(text)) return e;
            }
            return null;
            """, campo) or False

    def telefone_no_painel(self, painel, numero):
        valores = self.driver.execute_script(
            r"""
            const p = arguments[0];
            const values = [...p.querySelectorAll('input')].filter(e => e.getClientRects().length)
                .map(e => e.value || '');
            return values.concat((p.innerText || '').split(/\n/));
            """, painel)
        for valor in valores:
            # Compare complete phone-like strings; do not accept arbitrary substrings.
            for candidato in re.findall(r'\+?\d[\d\s().-]{8,}\d', valor):
                try:
                    if numero_brasileiro(candidato) == numero:
                        return True
                except ValueError:
                    pass
        return False

    def texto_editor(self, campo):
        return self.driver.execute_script(
            "return arguments[0].innerText.replace(/\\r\\n?/g, '\\n');", campo)

    def mensagens_saida(self):
        linhas = self.driver.execute_script(
            r"""
            return [...document.querySelectorAll('#main .message-out')].map(e => {
                const row = e.closest('[data-id]') || e.querySelector('[data-id]');
                const text = [...e.querySelectorAll('.selectable-text')]
                    .map(t => t.innerText).join('\n').replace(/\r\n?/g, '\n');
                return [row && row.getAttribute('data-id'), text];
            }).filter(([id]) => id);
            """)
        return dict(linhas)

    def aguardar_proximo(self, base):
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
            f"Espera: {base:g}s + 60 a 180s aleatórios.\n"
            "Números recusados não terão espera.\n"
            "Contatos existentes serão pulados sem envio.\n\n"
            "Use somente pessoas que aceitaram receber mensagens.",
        ):
            return

        contatos = list(self.contatos)

        def lote():
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

                    if indice < total:
                        self.aguardar_proximo(base)

                    continue

                self.cadastrar(contato)

                self.enviar(
                    contato,
                    texto.replace(
                        "{name}", contato["name"]
                    ),
                )
                enviados += 1

                if indice < total:
                    self.aguardar_proximo(base)

            self.log(
                f"\nCONCLUÍDO: {enviados} envios processados; "
                f"{existentes} contatos existentes pulados; "
                f"{recusados} números recusados pulados."
            )
            self.log(
                "Uma nova execução começa do primeiro contato."
            )

        self.executar(lote)

    def diagnostico(self):
        if self.driver is None:
            return

        try:
            pasta = (
                Path(__file__).resolve().parent
                / "diagnosticos"
            )
            pasta.mkdir(exist_ok=True)

            data = datetime.now().strftime(
                "%Y%m%d_%H%M%S_%f"
            )
            imagem = pasta / f"falha_{data}.png"

            elementos = self.driver.execute_script(r"""
                return [...document.querySelectorAll('#main header button, #main header [role=button], [role=menuitem], [role=dialog] input, [data-testid=drawer-right] input')]
                    .filter(e => e.getClientRects().length).map(e => ({tag: e.tagName, role: e.getAttribute('role'),
                        label: e.getAttribute('aria-label'), testid: e.getAttribute('data-testid'), type: e.getAttribute('type')}));
            """)
            (pasta / f"falha_{data}.json").write_text(
                json.dumps({'etapa': self.etapa, 'elementos': elementos}, ensure_ascii=False, indent=2), encoding='utf-8')
            if self.driver.save_screenshot(str(imagem)):
                self.log(
                    "Captura LOCAL: " + str(imagem)
                )

        except Exception:
            pass

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


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
