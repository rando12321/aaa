# WhatsApp — um script Python, sem instalar pacotes nem calibrar

A **V17** usa somente a biblioteca padrão do Python e APIs presentes no Windows. O aplicativo inteiro está em **`app.py`**. Não requer `pip`, OpenCV, NumPy, Pillow, Selenium, OCR, extensão, serviço de IA ou arquivos de calibração.

## Abrir

Requer **Windows 10/11**, Python 3.12+ com Tkinter (instalador padrão do Python para Windows) e Chrome normal.

1. Baixe `app.py` e execute `python app.py` ou `py app.py`.
2. Abra manualmente `https://web.whatsapp.com/` no Chrome normal e faça login pelo QR.
3. Deixe a aba WhatsApp ativa em uma única janela. Clique **Chrome / QR** no aplicativo para conectar essa janela.
4. Carregue o CSV, informe a mensagem e o intervalo e clique **Iniciar**.

Não há etapa de instalação de bibliotecas nem de seleção de imagens. Nenhum perfil novo de navegador é criado; o login é o do Chrome normal. Mantenha a janela do Chrome visível e não use mouse/teclado durante o lote. Se outra janela ganhar foco, as próximas teclas e cliques são bloqueados.

## Como funciona

O script chama **UI Automation do Windows por `ctypes`**, obtendo nomes, estados, valores e retângulos dos controles que o Chrome expõe. Os cliques e a digitação usam **Windows SendInput**, com confirmação de foco e conferência do valor digitado. Não injeta JavaScript na página, não usa WebDriver e não se conecta a API de IA externa.

As assinaturas COM seguem `uiautomationclient.h`: IUIAutomation, IUIAutomationElement, ValuePattern, TextPattern e LegacyIAccessiblePattern. O COM é inicializado e encerrado no thread que o utiliza; não são instalados `comtypes`, `pywin32` ou wrappers de automação.

**Limitação necessária:** o Chrome precisa expor o documento e os controles à acessibilidade do Windows. Nem todas as versões/interfaces fazem isso da mesma forma. Se um controle não tiver identificação acessível ou o valor do campo não puder ser lido, o script interrompe com diagnóstico. Não promete funcionamento universal nem automação indetectável. A mudança de tecnologia não comprova que os erros anteriores fossem causados por detecção do Selenium.

## Recursos mantidos

- GUI Tkinter, CSV `phone,name`, vírgula/ponto e vírgula, UTF-8, telefones como texto, deduplicação, exclusão de `11999999999` e sua versão internacional, normalização brasileira +55.
- Nomes automáticos curtos e únicos, personalização `{name}`, mensagem com várias linhas, Parar e logs por etapa.
- Abre o número diretamente por URL digitada com teclado nativo. Uma recusa exige texto real da interface; timeout é inconclusivo.
- Contato salvo precisa de Adicionar/Editar no menu/dados do contato, sem depender do nome do perfil. Existente é pulado sem mensagem e sem espera.
- Nome é digitado com teclas nativas e conferido. Telefone/país precisam corresponder ao CSV; não considera números com/sem nono dígito iguais por suposição. Um número visível em outra parte do histórico não comprova o telefone do formulário.
- Salvar é procurado por até 5 segundos. Sem o controle, ou com validação inválida antes de salvar, fecha pelo X, confirma Descartar e reabre pela interface uma única vez, sem F5 nessa recuperação. Não repete um clique em Salvar com resultado incerto.
- Cadastro exige nova notificação de sucesso ou confirmação de Editar contato antes de liberar o envio ao mesmo número. A verificação posterior não aplica SKIP ao contato cadastrado naquele lote.
- Rascunho existente é preservado e bloqueia o envio. A mensagem é conferida antes do clique em Enviar. A confirmação exige nova ocorrência do texto num elemento identificado como mensagem de saída; se o Chrome não expuser esse marcador, o resultado será **envio incerto**, sem nova tentativa automática. Campo vazio sozinho não confirma envio e não se afirma entrega.
- Espera base + inteiro aleatório de 60 a 180 segundos somente após envio, nunca após existente/recusado nem após o último contato.
- Chrome normal permanece aberto ao fechar o aplicativo. Não foi adicionada retomada automática entre execuções nem sincronização da agenda do celular.

## Diagnósticos

Falhas geram JSON dos controles acessíveis e captura **BMP**, ambos em `diagnosticos/`, ignorada pelo Git. A captura usa GDI nativo e o gravador BMP é implementado com `ctypes` e `struct`. Esses arquivos podem conter dados pessoais; não publique sessão ou diagnósticos.

## Validação

Os testes são executáveis com Python sem instalar pacotes:

```sh
python -m unittest discover -s tests -v
```

Foram verificados imports exclusivamente da biblioteca padrão em ambiente Python limpo, CSV e esperas, layout binário das estruturas Windows, sequências de teclas/mouse com API simulada, gravação BMP e fluxo com provedor de acessibilidade simulado: cadastrar→enviar, existente, rascunho, envio incerto, recusa, ambiguidade, controle coberto, telefone divergente e X→Descartar→reabrir.

**Não houve teste real de COM/UI Automation, SendInput, captura GDI, GUI ou conta autenticada no Windows nesta sessão Linux.** O script foi implementado e testado em simulação; o fluxo real ainda precisa ser validado no computador de uso. Não considere o processo de ponta a ponta confirmado por esses testes.
