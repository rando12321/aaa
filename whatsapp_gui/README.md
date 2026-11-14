# Envio direto com histórico enviados.txt

Versão baseada no último script anexado pelo usuário. Todo o aplicativo está em **`app.py`**, usando Selenium e a interface Tkinter do arquivo original.

**Foram removidos a consulta de contato salvo e o cadastro de contatos.** O programa abre o telefone diretamente e envia, independentemente de estar salvo na agenda. Não abre três pontos, não procura Editar e não usa formulário/Salvar contato.

## Usar

1. Execute `python app.py` com o Selenium já disponível, como no script original.
2. Use **Chrome / QR**, faça login e aguarde as conversas.
3. Carregue CSV UTF-8 com `phone,name` (vírgula ou ponto e vírgula), personalize a mensagem e clique **Iniciar**.

O perfil separado do Chrome permanece em `~/.whatsapp_csv_sender/chrome`. As regras brasileiras +55, exclusões e deduplicação de telefone foram preservadas. Nomes são usados só em `{name}`; não são cadastrados. Diferentes números podem ter o mesmo nome no CSV.

## enviados.txt

O arquivo é criado automaticamente **na mesma pasta do `app.py`**, mesmo que o programa seja iniciado por atalho ou a partir de outra pasta. Formato: um número por linha, sem nome ou data:

```text
5593984108321
5511987654321
```

Antes de abrir cada conversa, o aplicativo lê o TXT e pula números já registrados **sem envio e sem espera**. O histórico persiste após fechar/reabrir o programa. Números formatados ou nacionais colocados manualmente no TXT são normalizados na leitura; linha inválida interrompe antes de enviar para evitar ignorar um histórico corrompido.

Se o campo já contiver um rascunho igual à mensagem configurada, ele é reutilizado: o programa clica no campo e pressiona Enter uma única vez, sem inserir o texto novamente. Um rascunho diferente continua preservado e bloqueia o envio.

Quando o campo está vazio, a mensagem é inserida inteira pelo evento de texto do Chrome (`Input.insertText`), suportando Unicode e várias linhas sem pressionar Enter entre as linhas. A leitura do editor considera emojis em imagens, espaços não separáveis e quebras finais do DOM; preserva palavras, caracteres de composição de emojis e linhas internas. Diferença real ou texto faltando continua bloqueando o envio.

O número só é acrescentado ao arquivo depois de observar uma **nova mensagem de saída com identificador e texto correspondentes**. Campo vazio sozinho não comprova envio. O arquivo é descarregado e sincronizado em disco após cada registro; não é preciso esperar acabar o lote. Não significa confirmação de entrega ao destinatário.

Recusa do WhatsApp, falha ou resultado incerto não entram no TXT. Se o envio ficar incerto ou se falhar a gravação depois de enviar, o lote interrompe e novas tentativas ficam bloqueadas nessa sessão. **Antes de reiniciar, confira a conversa:** se foi enviado, coloque o número em `enviados.txt` manualmente. Não apague o histórico para retomar; isso permite reenviar aos números removidos. Use uma única instância do programa por pasta/histórico.

A espera continua sendo base + 60–180 segundos, apenas após enviar, quando ainda houver outro número não registrado para processar. Recusados e números do TXT passam imediatamente. Parar interrompe esperas/próximas etapas.

Capturas de falhas permanecem em `diagnosticos/`. O TXT e diagnósticos contêm dados pessoais e estão ignorados pelo Git.

## Verificação

Testes cobrem persistência/normalização do TXT, arquivo sem quebra de linha final, rejeição de histórico inválido, pular antes da navegação, retomada em nova execução, falta de confirmação, mensagem multilinha, erro de gravação e recusa. Há teste opcional do script de confirmação em Chromium usando Playwright apenas no desenvolvimento.

```sh
python -m unittest discover -s tests -v
```

O fluxo autenticado no WhatsApp/ChromeDriver real não foi executado nesta sessão. Os testes de lote usam navegador simulado; o teste opcional de DOM exercita a leitura real de uma página de teste. O código do aplicativo requer apenas Selenium, além dos módulos padrão do Python.
