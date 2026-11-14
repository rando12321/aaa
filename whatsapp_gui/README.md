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

Na V25, o número é acrescentado ao TXT **imediatamente após o comando Enter retornar sem erro**. Não procura bolha de saída, não aguarda o campo esvaziar e não verifica envio ou entrega. Portanto, o TXT registra comandos de envio executados, não mensagens comprovadamente enviadas/entregues. O arquivo é descarregado e sincronizado em disco após cada registro.

Recusa do WhatsApp ou falha antes do comando Enter não entra no TXT. Uma exceção no próprio comando Enter ou na gravação interrompe o lote para evitar repetição imediata. Use uma única instância por pasta/histórico. Não apague o TXT entre execuções.
A espera continua sendo base + 60–180 segundos, apenas após enviar, quando ainda houver outro número não registrado para processar. Recusados e números do TXT passam imediatamente. Parar interrompe esperas/próximas etapas.

Capturas de falhas permanecem em `diagnosticos/`. O TXT e diagnósticos contêm dados pessoais e estão ignorados pelo Git.

## Verificação

Testes cobrem persistência/normalização do TXT, arquivo sem quebra de linha final, rejeição de histórico inválido, pular antes da navegação, retomada em nova execução, registro após Enter sem mensagem de saída, falha no próprio Enter, mensagem multilinha, erro de gravação e recusa. Há teste opcional do script de confirmação em Chromium usando Playwright apenas no desenvolvimento.

```sh
python -m unittest discover -s tests -v
```

O fluxo autenticado no WhatsApp/ChromeDriver real não foi executado nesta sessão. Os testes de lote usam navegador simulado; o teste opcional de DOM exercita a leitura real de uma página de teste. O código do aplicativo requer apenas Selenium, além dos módulos padrão do Python.
