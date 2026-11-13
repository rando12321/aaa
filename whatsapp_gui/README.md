# WhatsApp visual — OpenCV + teclado/mouse do Windows

A V16 removeu Selenium e WebDriver do aplicativo. **Todo o programa continua em `app.py`**. O Chrome é o navegador normal do usuário; o aplicativo reconhece imagens na tela, lê regiões por OCR local e usa `SendInput` para clicar e digitar.

## Instalar e abrir

Use **Windows 10/11 com Python 3.12 de 64 bits**, desktop desbloqueado e Chrome visível. No terminal:

```powershell
py -3.12 -m pip install numpy==2.2.6 opencv-python==4.11.0.86 Pillow==11.3.0 rapidocr_onnxruntime==1.4.4 onnxruntime==1.20.1
py -3.12 app.py
```

Ou, com o repositório completo, instale `python -m pip install -r requirements.txt`. OpenCV não substitui os pacotes de OCR. Os modelos OCR vêm no pacote RapidOCR e são executados localmente; não é necessário Tesseract nem serviço de IA externo.

Abra manualmente `https://web.whatsapp.com/` no Chrome normal, faça login por QR e deixe essa aba ativa em uma única janela. Clique **Chrome / QR** no aplicativo para conectar a janela. O aplicativo não inicia outro perfil, não instala extensão e não encerra o Chrome ao fechar.

## Calibração obrigatória antes do primeiro lote

A versão não contém imagens presumidas de botões. **Sem calibrar, ela bloqueia o lote antes de navegar, salvar ou enviar.** As capturas anteriores desta conversa não fornecem todos os controles necessários com a escala e resolução do computador atual.

1. Mantenha fixos o tamanho da janela do Chrome, zoom, tema e escala do Windows.
2. Clique **Calibrar OpenCV**. Abra manualmente no Chrome a tela/menu que contém o controle escolhido.
3. Selecione um item na lista e clique **Capturar controle/área**. O aplicativo ativa a janela do WhatsApp e apresenta uma captura estática para seleção.
4. Para um controle, arraste um retângulo ao redor de uma imagem estável (rótulo/ícone). Depois clique, na captura, no ponto exato onde a ação deve ocorrer. O campo pode ficar ao lado do rótulo: o ponto do clique é registrado separadamente.
5. Para uma região OCR, arraste apenas a região solicitada. A área `telefone_lido` inclui país e valor; `nome_lido` e `rascunho_lido` incluem só os valores, sem rótulos. `saida_lida` deve incluir as últimas mensagens enviadas e não mensagens recebidas.
6. Repita os itens obrigatórios. `criar`, `salvo`, `dados` e `menu_dados` são opcionais, conforme sua interface. A lista de itens ainda ausentes aparece ao tentar iniciar.

Distinga **`telefone_ok` (✓ verde junto ao telefone)** de **`salvar` (círculo ✓ inferior)**. Capture os controles habilitados. No campo Nome, use ícone ou rótulo que continue visível após preencher; não capture apenas o placeholder que desaparece. A imagem `conversa` deve ser um ícone estável no rodapé, que desapareça durante o carregamento de outro destinatário. Não use a área inteira com mensagens variáveis como modelo.

A busca usa uma região ao redor da posição calibrada, correspondência de imagem e cor. Se encontrar dois candidatos ou se a janela mudar de tamanho, interrompe. Não clica por coordenadas presumidas. As coordenadas de ação são sempre derivadas da imagem encontrada e da calibração.

## Fluxo mantido

- CSV UTF-8, `phone,name`, vírgula/ponto e vírgula, deduplicação, exclusões e +55. Nomes gerados curtos e únicos; `{name}` e várias linhas de mensagem.
- Abre diretamente o número por URL digitada na barra de endereço com teclas nativas. Espera a conversa anterior sair antes de aceitar nova conversa/aviso de recusa.
- Contato existente exige imagem de Editar no menu, não o nome de perfil. É pulado sem mensagem e sem espera.
- Após adicionar, digita o nome e compara a leitura OCR com o valor desejado. O telefone lido precisa corresponder exatamente ao CSV; não adiciona/remove nono dígito por suposição. Exige a imagem de telefone validado antes de salvar.
- Se Salvar/validação não aparecer em 5 segundos, fecha pelo X, confirma Descartar e reabre pela interface uma única vez, sem navegar ou dar F5 nessa recuperação. Depois preenche novamente o mesmo nome. Clique em Salvar com resultado incerto não é repetido.
- Cadastro precisa de nova tela de sucesso ou de confirmação posterior de Editar contato antes do envio. Um formulário fechado sozinho não basta.
- Reabre o número exato antes de enviar, bloqueia rascunhos e confere o texto por OCR. Clica Enviar uma vez; exige aumento das ocorrências do texto na região de mensagens de saída. Esvaziar o campo não comprova envio. OCR inconclusivo gera envio incerto, sem repetição automática.
- Espera base + inteiro de 60 a 180 segundos apenas após envio, nunca após existente/recusado nem após último contato. Parar interrompe a espera e as próximas ações.
- Logs por etapa e capturas em `diagnosticos/`. Calibração em `.local/opencv/`. Ambas são locais e ignoradas pelo Git. Proteja-as: podem conter dados pessoais. Não foi adicionada retomada automática entre execuções.

Mantenha o Chrome em primeiro plano e não use mouse/teclado durante o lote. Se outra janela ganhar foco, as próximas entradas são bloqueadas. Não há garantia de automação indetectável. O programa pode parar quando OCR, cor, escala ou interface diferirem da calibração; não diminua os limites para forçar um clique sem conferir a imagem.

## O que foi e não foi validado

Nesta sessão Linux foram executados os testes de CSV/espera, estruturas e sequências de entrada nativa com API simulada, reconhecimento OpenCV com imagens e fluxo visual simulado, incluindo cadastro→envio, existente, rascunho, envio incerto e X→Descartar→reabrir. O OCR local real foi exercitado com uma imagem de telefone renderizada.

**A captura/cliques/teclas no Windows real, a janela Tkinter de calibração e o fluxo autenticado da conta WhatsApp não foram validados nesta sessão.** A migração está implementada; o uso requer calibração e teste manual inicial no seu Windows. Não é uma versão validada de ponta a ponta na sua conta.

Para desenvolvimento:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

No Windows, use `.venv\Scripts\python.exe` no lugar de `.venv/bin/python`.
