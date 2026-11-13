# Contatos e mensagens pelo WhatsApp Web

Aplicativo Python/Tkinter independente dos outros arquivos deste repositório.
Requer Python 3.12+, Tkinter, ambiente gráfico e login pelo QR. Interface do WhatsApp em português ou inglês.

## Instalação

Execute nesta pasta:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python app.py
```

No Windows, use `.venv\Scripts\python.exe` no lugar de `.venv/bin/python`.
Se usar um Chrome/Chromium instalado, informe seu caminho na variável `WHATSAPP_CHROME`; nesse caso não precisa baixar o navegador do Playwright.
No Linux, Tkinter e as bibliotecas do Chromium devem estar instalados no sistema. Na nuvem atual, use `WHATSAPP_CHROME=/usr/bin/chromium`.

Escolha CSV UTF-8 com `phone,name`, separado por vírgula ou ponto e vírgula. Informe mensagem e espera base, clique Iniciar e leia o QR. Use Parar para cancelar a espera ou a próxima etapa. Operações pontuais do navegador podem levar alguns segundos para terminar.

## Comportamento e limites de validação

- Normaliza números brasileiros sem inventar nono dígito; deduplica e ignora o número de exclusão especificado. Nome aleatório é gerado uma vez por contato importado.
- Abre diretamente o número e distingue aviso de recusa, conversa e timeout. Só evidencia contato salvo quando o menu da conversa oferece Editar contato. Nome do cabeçalho não é usado como prova.
- Formulário precisa expor campos acessíveis Nome e Telefone e botão Salvar. Confere telefone completo, salva e exige evidência de Editar contato antes de preparar a mensagem.
- Seletores são conservadores e **ainda não foram validados na conta real**. O botão verde sem nome acessível não será clicado por coordenadas nem confundido com o verificador do telefone. Uma interface diferente pode bloquear o fluxo: veja o log e a captura para adaptar seletores em uma tarefa de código.
- Reabre o número antes do envio, bloqueia rascunhos existentes e observa uma nova bolha de saída com o texto esperado. Isso não comprova entrega. Resultado incerto interrompe a execução, sem repetição automática.
- Espera base + inteiro de 60 a 180 após envio ou contato existente, exceto no fim; recusa segue imediatamente.
- `.local/historico.jsonl` registra tentativas antes de qualquer alteração. Números registrados não são repetidos em execuções posteriores. Revise manualmente a conversa antes de remover registros para tentar novamente. Isto evita duplicação, mas não é retomada automática de etapas.
- Perfil autenticado, histórico e capturas ficam em `.local/`, ignorada pelo Git. Proteja essa pasta: contém dados pessoais e sessão autenticada. Não sincroniza a agenda do celular.

Os testes locais validam importação, normalização e espera. A abertura do navegador e a GUI podem ser verificadas sem login. A sequência completa cadastro → salvar → enviar exige teste manual com conta autenticada e destinatário autorizado; não foi confirmada nesta entrega.
