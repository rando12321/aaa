"""Envio direto: sem consultar/cadastrar contatos; histórico local enviados.txt.
Baseado no último script anexado pelo usuário. Requer Selenium já instalado.
"""
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
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait


VERSAO = 'V24-reutilizar-rascunho-correto'
ARQUIVO_ENVIADOS = Path(__file__).resolve().parent / 'enviados.txt'

IGNORADOS = {"11999999999", "5511999999999"}

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

    return contatos, ignorados


SCRIPT_TEXTO_MENSAGEM = r"""
function textoMensagem(node) {
    if (node.nodeType===Node.TEXT_NODE) return node.nodeValue||'';
    if (node.nodeType!==Node.ELEMENT_NODE) return '';
    if (node.tagName==='IMG') return node.getAttribute('alt')||'';
    if (node.tagName==='BR') return '\n';
    let result='';
    const children=[...node.childNodes];
    for(let i=0;i<children.length;i++){
        const child=children[i];
        const block=child.nodeType===Node.ELEMENT_NODE && /^(P|DIV)$/.test(child.tagName);
        if(block && result && !result.endsWith('\n')) result+='\n';
        result+=textoMensagem(child);
        if(block && i<children.length-1 && !result.endsWith('\n')) result+='\n';
    }
    return result;
}
"""


def normalizar_mensagem(texto):
    texto=unicodedata.normalize('NFC',texto.replace('\r\n','\n').replace('\r','\n'))
    # Editor representation only. Keep ZWJ/variation selectors and internal lines.
    return texto.replace('\u00a0',' ').replace('\u202f',' ').replace('\u200b','').replace('\ufeff','').rstrip('\n')


class HistoricoTXT:
    def __init__(self,caminho=None):
        self.caminho=Path(caminho) if caminho is not None else ARQUIVO_ENVIADOS

    def ler(self):
        if not self.caminho.exists():
            return set()
        numeros=set()
        for indice,linha in enumerate(self.caminho.read_text(encoding='utf-8-sig').splitlines(),1):
            if not linha.strip():continue
            try:
                numeros.add(numero_brasileiro(linha))
            except ValueError as erro:
                raise ValueError(f'enviados.txt: telefone inválido na linha {indice}; corrija antes de enviar.') from erro
        return numeros

    def preparar(self):
        self.ler()
        # Check that the folder/file is writable before the first message.
        with self.caminho.open('a',encoding='utf-8') as arquivo:
            arquivo.flush()

    def registrar(self,numero):
        numero=numero_brasileiro(numero)
        if numero in self.ler():return
        with self.caminho.open('a+b') as arquivo:
            arquivo.seek(0,os.SEEK_END)
            tamanho=arquivo.tell()
            if tamanho:
                arquivo.seek(-1,os.SEEK_END)
                if arquivo.read(1)!=b'\n':arquivo.write(b'\n')
            arquivo.write((numero+'\n').encode('ascii'))
            arquivo.flush()
            os.fsync(arquivo.fileno())


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
        self.envio_incerto = False
        self.historico = HistoricoTXT()

        root.title(f"WhatsApp — envio direto — {VERSAO}")
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
                "Brasil +55. Sem consulta ou cadastro de contatos. "
                "Números no enviados.txt são pulados sem espera."
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
        self.log(f"Histórico de enviados: {self.historico.caminho}")
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
                self.driver = webdriver.Chrome(
                    options=opcoes
                )

            self.driver.get("https://web.whatsapp.com/")
            self.log(
                "Escaneie o QR e espere as conversas carregarem."
            )

        self.executar(abrir)

    def campo_mensagem(self, driver):
        campos=self.visiveis('#main footer [contenteditable="true"][role="textbox"], #main footer [contenteditable="true"][data-lexical-editor="true"]')
        campos=[c for c in campos if c.is_enabled()]
        return campos[0] if len(campos)==1 else False



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

            if any(aviso in texto for aviso in avisos) or re.search(r'numero.*invalido|phone number.*invalid',texto):
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
                    """
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


    def abrir_e_detectar(self, numero):
        self.numero_atual = None
        self.definir_etapa(f"Abrindo conversa diretamente com +{numero}...")
        self.driver.get("https://web.whatsapp.com/send?" + urlencode({"phone":numero}))
        def resposta(driver):
            painel=self.encontrar_aviso_numero()
            if painel is not None:
                raise NumeroRecusado(painel.text)
            return self.campo_mensagem(driver)
        self.esperar(resposta,90)
        self.numero_atual=numero
        self.log("Conversa aberta. Sem verificar ou cadastrar contato; seguindo ao envio.")




    def enviar(self, contato, texto):
        if self.numero_atual!=contato['phone']:
            raise RuntimeError('A conversa atual não foi aberta para este número.')
        self.definir_etapa('Preparando a mensagem na conversa aberta...')
        campo=self.esperar(self.campo_mensagem)
        texto=texto.replace('\r\n','\n').replace('\r','\n')
        esperado=normalizar_mensagem(texto)
        rascunho=self.ler_mensagem(campo)
        if rascunho.strip() and rascunho!=esperado:
            raise RuntimeError('Existe um rascunho diferente da mensagem configurada. Não será apagado ou misturado.')
        campo.click()
        if rascunho==esperado:
            self.log('O rascunho já contém a mensagem correta. Enviando sem redigitar.')
        else:
            self.conferir_parada()
            self.driver.execute_cdp_cmd('Input.insertText',{'text':texto})
            lido=['']
            self.definir_etapa('Conferindo a mensagem inserida, incluindo linhas e emojis...')
            def conferir(driver):
                lido[0]=self.ler_mensagem(campo)
                return lido[0]==esperado
            try:
                self.esperar(conferir,5)
            except Exception as erro:
                raise RuntimeError(f'O texto inserido não foi confirmado. Esperado: {len(esperado)} caracteres; lido: {len(lido[0])}. Rascunho preservado, sem envio e sem registro no TXT.') from erro
        anteriores=self.mensagens_saida()
        self.conferir_parada()
        self.definir_etapa('Enviando uma vez e confirmando nova mensagem de saída...')
        self.envio_incerto=True
        campo.send_keys(Keys.ENTER)
        def confirmado(driver):
            return any(chave not in anteriores and valor==esperado for chave,valor in self.mensagens_saida().items())
        try:
            self.esperar(confirmado,30)
        except Exception as erro:
            raise RuntimeError('ENVIO INCERTO: não foi confirmado e não será registrado no TXT. Confira a conversa antes de tentar novamente.') from erro
        self.log('Nova mensagem de saída confirmada; entrega não confirmada.')

    def ler_mensagem(self,campo):
        return normalizar_mensagem(self.driver.execute_script(SCRIPT_TEXTO_MENSAGEM+'return textoMensagem(arguments[0]);',campo))

    def mensagens_saida(self):
        linhas=self.driver.execute_script(SCRIPT_TEXTO_MENSAGEM+r"""
            return [...document.querySelectorAll('#main .message-out')].map(e=>{
                const row=e.closest('[data-id]')||e.querySelector('[data-id]');
                const text=[...e.querySelectorAll('.selectable-text')].map(textoMensagem).join('\n');
                return [row&&row.getAttribute('data-id'),text];
            }).filter(([id])=>id);
        """)
        return {chave:normalizar_mensagem(texto) for chave,texto in linhas}

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
        if self.envio_incerto:
            messagebox.showerror('Revisão necessária','O envio anterior ficou incerto ou não foi registrado. Confira a conversa e o TXT antes de reiniciar o programa.')
            return
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
            "Números no enviados.txt serão pulados sem envio e sem espera.\n"
            "Não haverá consulta nem cadastro de contatos.\n\n"
            "Use somente pessoas que aceitaram receber mensagens.",
        ):
            return

        contatos = list(self.contatos)

        def lote():
            self.historico.preparar()
            enviados=0
            pulados=0
            recusados=0
            total=len(contatos)
            for indice,contato in enumerate(contatos,1):
                self.conferir_parada()
                numero=contato['phone']
                self.log(f"\nCONTATO {indice}/{total}: +{numero} — {contato['name']}")
                if numero in self.historico.ler():
                    pulados+=1
                    self.log('SKIP: número já está em enviados.txt. Próximo sem espera.')
                    continue
                try:
                    self.abrir_e_detectar(numero)
                except NumeroRecusado as erro:
                    recusados+=1
                    self.log(f'SKIP: número recusado — {erro}')
                    self.fechar_aviso_numero()
                    continue
                self.enviar(contato,texto.replace('{name}',contato['name']))
                try:
                    self.historico.registrar(numero)
                except Exception as erro:
                    self.envio_incerto=True
                    raise RuntimeError('Mensagem confirmada, mas falhou a gravação no enviados.txt. Não repetir; confira a conversa e registre esse número manualmente.') from erro
                self.envio_incerto=False
                enviados+=1
                self.log('Registrado em enviados.txt: '+numero)
                ja_enviados=self.historico.ler()
                if any(c['phone'] not in ja_enviados for c in contatos[indice:]):
                    self.aguardar_proximo(base)
            self.log(f'\nCONCLUÍDO: {enviados} envios registrados; {pulados} números do TXT pulados; {recusados} recusados.')
            self.log('A próxima execução consultará enviados.txt novamente.')

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
