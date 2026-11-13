# WhatsApp — cadastrar e enviar (arquivo único)

A versão atual foi refeita a partir do último script Selenium enviado pelo usuário. Todo o aplicativo está em **`app.py`**; não importa outros arquivos locais.

## Executar

Requer Python 3.12+, Tkinter, Google Chrome/Chromium e desktop gráfico:

```sh
python -m pip install selenium==4.38.0
python app.py
```

O Selenium Manager localiza/obtém o ChromeDriver compatível. Em máquinas com caminhos personalizados, informe `WHATSAPP_CHROME` (navegador) e, se necessário, `WHATSAPP_CHROMEDRIVER` (driver). Não é necessário Playwright para usar o programa.

1. Carregue CSV UTF-8 com colunas `phone,name`, separado por vírgula ou ponto e vírgula.
2. Clique **Chrome / QR** e faça login. O perfil separado original permanece em `~/.whatsapp_csv_sender/chrome`.
3. Informe a mensagem com `{name}`, o tempo base e clique **Iniciar**. **Parar** interrompe a espera e as próximas etapas.

## Recursos preservados

A tela, os botões, a confirmação antes do lote, os logs por etapa, as capturas locais, a geração de nomes, as regras do CSV e de exclusão, a deduplicação, a normalização +55, a personalização e as esperas permanecem. A espera continua sendo base + inteiro aleatório de 60 a 180 segundos, somente após envio; contato existente e número recusado seguem sem espera e o último contato não gera espera. As restrições originais do CSV, inclusive nomes distintos por contato, foram mantidas. Não foi adicionada retomada automática entre execuções nem sincronização com a agenda do celular.

## Correções

- O menu é localizado por rótulo/ícone **dentro do cabeçalho da conversa**, em vez de escolher o botão mais à direita da tela.
- A detecção procura Adicionar/Editar no menu e nos dados do contato. Reconhece também o botão de edição com lápis nos dados do contato quando o telefone corresponde. O nome do perfil/cabeçalho não comprova contato salvo.
- Nomes gerados agora são curtos, como `Ana 1234`, e permanecem únicos no lote. Nomes fornecidos no CSV são preservados. No Windows, o preenchimento do Nome usa **SendInput nativo do Windows** (sem dependência extra), identifica a janela correta do Chrome por título temporário, verifica primeiro plano e foco antes de cada grupo de teclas, digita Unicode com pausa e sai com Tab. Em outros sistemas mantém ActionChains. O valor é conferido após a digitação; o log informa o valor mantido e seu tamanho.
- Antes de procurar Salvar, confere nome, telefone/país e validação dos campos, redigita o mesmo nome se estiver vazio ou divergente, tira o foco e rola o painel. Registra candidatos Salvar/✓ visíveis, ocultos ou desabilitados e procura novamente. Antes de clicar, exige que o botão esteja habilitado e sem outro elemento cobrindo seu centro. A busca espera no máximo **5 segundos**; se o botão não aparecer, fecha pelo X ao lado de Novo contato, confirma **Descartar** se surgir “Deseja descartar as mudanças?” e reabre a opção pela interface, sem recarregar a página, uma única vez, sem outra rodada de espera ou conferência antes de reabrir e preenche o mesmo nome e telefone novamente. A recuperação ocorre no timeout de 5 segundos ou se a validação dos campos impedir Salvar, antes de qualquer clique; não repete um clique de resultado incerto. Se continuar sem o botão, interrompe com diagnóstico.
- O formulário é reconhecido mesmo antes de aparecer Salvar, com país e telefone em campos separados. O telefone deve corresponder exatamente ao CSV. Se houver um único campo de telefone editável e país explicitamente +55, preenche o número nacional exato do CSV e confere novamente; não considera versões com/sem nono dígito automaticamente equivalentes. O botão Salvar/✓ é procurado dentro do formulário, distinguindo a ação inferior do verificador ao lado do telefone.
- Depois de salvar, uma nova notificação explícita de contato salvo/adicionado confirma o cadastro e libera diretamente o envio. Avisos que já existiam antes de clicar Salvar são ignorados. Sem nova notificação, reabre o número exato para confirmar Editar contato; essa confirmação pós-cadastro não aplica SKIP. Fechar o formulário ou exibir o nome desejado não basta. O contato cadastrado no lote segue ao envio da mensagem, enquanto a regra de pular existentes vale somente antes do cadastro.
- Antes de enviar, reabre o número exato, bloqueia rascunhos, insere a mensagem completa pelo Chrome DevTools (incluindo emoji) e confere o texto. Aciona Enviar uma vez e exige nova mensagem de saída com identificador e texto correspondentes. Campo vazio sozinho não confirma envio; entrega não é afirmada.
- Resultado de envio incerto interrompe o lote e bloqueia novo envio na sessão até revisão manual e reconexão. Não existe repetição automática. Reiniciar o programa não substitui essa revisão.
- Falhas geram captura e um JSON de diagnóstico com etapa e metadados dos controles em `diagnosticos/`, ignorada pelo Git. Não publique capturas ou perfil autenticado.

## Validação e limites

Os testes exercitam as regras de dados e os scripts DOM em Chromium com páginas simuladas: cadastro e envio, mensagem com emoji/várias linhas, contato salvo com nome diferente, dados do contato com lápis de edição, botão inferior de salvar, telefone divergente/ausente, recusa, rascunho e envio incerto.

O transporte dos testes é uma ponte de WebElements para Playwright, usada apenas nos testes. **Não houve validação de ponta a ponta com ChromeDriver, GUI visível e sua conta autenticada do WhatsApp.** Mudanças reais na interface podem exigir ajuste adicional de seletor. Nesses casos, o programa interrompe com a etapa e diagnóstico; timeout não é classificado como contato existente ou número inválido.

Para desenvolvimento:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m unittest discover -s tests -v
```

No Windows use `.venv\Scripts\python.exe`. No ambiente de nuvem atual, os testes usam `/usr/bin/chromium`; a GUI ainda precisa de display gráfico.

A entrada nativa do Windows não foi executada em Windows nesta sessão Linux: foram testados a estrutura binária, sequências Unicode, bloqueios de foco e o encaminhamento para o backend com API simulada. O Selenium continua na navegação e leitura do DOM. Não há garantia de automação indetectável. Mantenha o Chrome em primeiro plano durante a digitação nativa; se mudar de janela, o programa interrompe as próximas teclas.
