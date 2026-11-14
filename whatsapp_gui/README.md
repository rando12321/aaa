# WhatsApp híbrido — Selenium lê; Windows clica e digita

A versão atual mantém todo o aplicativo em **`app.py`** e usa a combinação solicitada:

- **Selenium** inicia o Chrome controlado e lê controles, textos, valores, posição e resultado das ações.
- **Windows SendInput** envia todos os cliques, rolagens, atalhos e caracteres. Não são usados `WebElement.click()`, `send_keys()`, `ActionChains`, atribuição de valores no DOM ou `dispatchEvent`.
- Não usa OpenCV, OCR externo, pyautogui, pywin32 ou comtypes. Não precisa calibrar imagens.

Isso não garante ser indetectável: o Chrome continua sendo iniciado pelo Selenium. Os erros anteriores não comprovam que o WhatsApp estivesse bloqueando a digitação por detectar automação.

## Requisitos existentes

Windows 10/11, Python com Tkinter, **Selenium já instalado** e **ChromeDriver compatível já disponível**, como nas primeiras versões do aplicativo.

**O script não instala bibliotecas e não baixa drivers automaticamente.** Reutiliza `WHATSAPP_CHROMEDRIVER`, um ChromeDriver encontrado no PATH ou no cache `~/.cache/selenium/chromedriver`. Se não houver Selenium/driver no Python usado, para com uma mensagem específica. A versão híbrida não pode executar sem esses componentes existentes.

## Executar

1. Execute `py app.py` ou `python app.py`.
2. Clique **Chrome / QR**. O Selenium abre uma janela com perfil separado em `~/.whatsapp_csv_sender/chrome_native_hybrid`.
3. Faça login por QR nessa janela, se necessário, e aguarde as conversas. O login é mantido nesse perfil.
4. Carregue CSV `phone,name`, informe mensagem/espera e clique **Iniciar**.

A janela é vinculada pelo identificador e processo da janela recém-criada, não pela exigência de haver apenas um título “WhatsApp”. Outras janelas do navegador podem permanecer abertas. Se o Windows recusar primeiro plano, o erro pede para clicar na janela vinculada; nenhuma tecla é enviada a outra janela.

Mantenha esse Chrome visível, com a aba WhatsApp ativa, sem DevTools ou painel lateral do navegador. Não use mouse/teclado durante o lote. As posições dos controles vêm da leitura atual e são convertidas para pixels nativos com DPI/zoom e dimensões da área cliente; não são coordenadas fixas ou calibradas manualmente. Painéis laterais incompatíveis bloqueiam cliques. O centro do controle precisa estar desobstruído na página e o campo precisa ter foco antes de receber caracteres.

## Comportamento

- CSV UTF-8 com vírgula/ponto e vírgula, leitura como texto, deduplicação, exclusão de `11999999999` e versão internacional, normalização brasileira +55 sem inventar nono dígito.
- Nomes automáticos curtos e únicos, `{name}`, várias linhas, Parar e logs por etapa.
- O número é aberto por Ctrl+L, espera de foco da barra, pausa após limpar, URL completa `https://` digitada e Enter **pelo Windows**. A pausa evita perder o primeiro caractere ao mudar o foco. O Selenium apenas observa a transição e o resultado.
- A verificação procura Adicionar/Editar no menu da conversa; sem evidência, abre Dados do contato pelo menu ou título do cabeçalho e verifica também o menu interno desse painel. Contato existente exige Adicionar/Editar na interface; nome de perfil não basta. Existente é pulado sem mensagem e sem espera.
- Nome digitado e valor conferido; país/telefone precisam corresponder ao CSV. Número de outra região do histórico não comprova o telefone do formulário.
- Se Salvar estiver fora da área rolável visível, a rolagem é feita pela roda nativa do mouse. Sem Salvar em 5 segundos ou com validação inválida antes de salvar, fecha no X, confirma Descartar e reabre uma vez pela interface, sem F5 nessa recuperação. Não repete clique em Salvar com resultado incerto.
- Cadastro exige nova notificação de sucesso ou confirmação posterior de Editar contato. O contato recém-cadastrado segue ao envio no mesmo lote, sem SKIP nessa etapa.
- Rascunho é preservado e bloqueia o envio. A mensagem digitada é lida e conferida antes de clicar Enviar uma única vez. Confirmação exige **novo identificador de mensagem de saída** com o texto esperado, não apenas mensagem antiga semelhante ou campo vazio. Entrega não é afirmada.
- Espera base + inteiro aleatório 60–180 segundos apenas após envio, nunca após existente/recusado nem após o último contato. Resultado de envio incerto interrompe e não é repetido automaticamente.
- Não foi adicionada retomada automática entre execuções nem sincronização da agenda.

Ao fechar o aplicativo, encerra apenas a sessão de Chrome criada pelo Selenium, preservando outras janelas do usuário. Falhas geram diagnóstico local JSON/BMP em `diagnosticos/`, ignorada pelo Git. Proteja esses arquivos: podem conter dados pessoais.

## Validação e limites

Foram testados CSV/esperas, comandos nativos e vinculação HWND/processo com APIs simuladas, conversão CSS/DPI para pixels, ausência de instalação automática e os fluxos com provedores simulados. Os testes opcionais de DOM executam os scripts de leitura no Chromium e simulam o transporte das ações nativas: leitura sem modificar a página, cadastro→envio, existente e rolagem para Salvar.

**Não houve validação de ponta a ponta com ChromeDriver, SendInput, geometria real da janela, GUI e conta autenticada no Windows nesta sessão Linux.** A versão implementa a combinação solicitada, mas o resultado real ainda precisa ser confirmado no computador de uso. Se o nome ou estado do controle não puder ser lido com segurança, o programa interrompe com diagnóstico.

Para desenvolvimento, `python -m unittest discover -s tests -v` executa os testes básicos sem pacotes extras; os testes DOM são marcados como pulados se Playwright não estiver disponível. `requirements-dev.txt` é apenas para o ambiente de desenvolvimento, não um instalador automático do aplicativo.
