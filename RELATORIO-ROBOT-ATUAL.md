# Relatorio do Robot atual

A implementacao usa exclusivamente o projeto do ZIP fornecido nesta solicitacao.
SHA-256 do ZIP de entrada: `5c4494e45a711f6fda35cb0518ec86a38200a767ce6a4392e3c6a7a0a1ff799f`.
O loader original desse ZIP esta em `fontes-robot-atual/entrada-atual.swf`, com
checksum exigido pelo build. Nao foi usado o pacote corrigido em turnos anteriores.

## Resultado implementado

O runtime inicia com Auto Play habilitado. Aguarda mapa, corpo, clipe, posicao,
dimensoes e liberacao da rodada; exige identidade estavel em pelo menos dois
quadros e 100 ms. Cada nova vida/rodada reinicia a rota correspondente uma vez.
Desligar por F2, checkbox ou pela opcao de parar ao mover mantem o Robot desligado
nas proximas rodadas, ate reativacao. REC suspende a reproducao sem apagar essa
preferencia. Morte, vitoria, troca de sala e remocao do documento liberam controles.

Gravacoes concluidas sao salvas automaticamente no servidor local por usuario e
mapa; SAVE publica separadamente no GitHub. Novas gravacoes locais tem prioridade.
LIST e DELETE usam esse armazenamento atual. DELETE cria uma desativacao local,
sem apagar o catalogo compartilhado do GitHub. As permissoes de armazenamento ja
existentes continuam sendo verificadas.

## Investigacao: causas e correcoes

| Problema identificado | Causa no projeto fornecido | Correcao e evidencia |
|---|---|---|
| Primeiro inicio depende de ativacao manual | A suite somente inscrevia o controlador; nao habilitava `auto_play` | Habilitacao inicial unica e sincronizacao do checkbox. Defeito reproduzido no loader original; teste de runtime corrigido |
| Estado de vitoria permanece na vida seguinte | Troca de corpo depois do terminal apenas marcava bloqueio; `nativeWon/terminal` permaneciam ativos | Nova vida reconhecida por corpo/jogador/rodada e pelo pacote de nascimento. Defeito reproduzido; testes com e sem pacote de spawn |
| Movimentos antigos continuam na troca de sala | Reproducao tratava 5/2, mas nao 5/21 | Troca de sala interrompe, cancela carregamento e espera mapa/nascimento valido |
| Inicio antes de recursos estarem prontos | Espera fixa de 250 ms, sem estabilidade do objeto; dimensao temporariamente ausente virava falha permanente | Prontidao baseada em estado, duas observacoes, 100 ms estaveis e espera recuperavel por dimensoes |
| Estados consumidos antes de o jogo processa-los | Timer de 5 ms e ENTER_FRAME avancavam a mesma rota; estados vencidos podiam ser agrupados | Uma rotina de quadro por documento, uma amostra de movimento por quadro, sem os dois timers de polling |
| Segundo salto curto descartado | Limite de 30 ms negava o pulso, mas o estado da rota ja era consumido | Pulsos de compatibilidade ficam pendentes; novas gravacoes usam a tecla real. Defeito reproduzido no original e testado no corrigido |
| Gravacao nao representa a tecla de salto | Campo `jump` era estado/animacao aerea observado, nao a duracao de Up/W | Campo opcional booleano `up`, com captura das transicoes reais de teclado, incluindo pressionar/soltar rapido |
| Captura perde transicoes curtas | Polling de 10 ms e leitura no envio de movimento nao garantiam observar todas as teclas | Eventos de teclado capturados, ignorando eventos sinteticos; amostragem de estado/outgoing continua para compatibilidade e outros jogadores |
| Atraso comprime intervalos seguintes | Prazos absolutos vencidos permaneciam apos uma transicao atrasada | Transicoes e stalls acima de 50 ms ajustam o prazo; uma amostra nao e agrupada com a seguinte |
| Arredondamento por quadro acumula atraso | Rebase indiscriminado a cada amostra tambem reduziria a fidelidade | Heartbeats mantem a linha temporal. Regressao executada com 100 amostras e cadencias de 16 e 33 ms |
| Robot fica em carregamento sem limite | URLLoader de leitura nao tinha prazo nem recuperacao garantida | Prazo de 25 s, cancelamento, retries de 500 ms ate 10 s, sem remover cache valido. Testes HTTP reais locais |
| Resposta antiga substitui nova gravacao | Callback de leitura ainda podia escrever no cache depois de REC/setRoutes/SAVE do mesmo mapa | Cancelamento antes da substituicao e guarda de identidade do pedido. Teste de resposta atrasada no mesmo mapa |
| Perda da rota ao reiniciar/trocar muitos mapas | Cache em memoria; apenas o ultimo rascunho era preservado quando SAVE era tentado | Catalogo local duravel por mapa/usuario, escrito na conclusao. Testes de reinicio sem cache, isolamento e 20 escritas concorrentes |
| SAVE pendente publica dados de outra gravacao | Esperar a escrita local sem guardar uma copia permitiria usar o `completed` posterior | Trabalho de publicacao guarda codigo, JSON e passos imutaveis. Teste conclui outra gravacao antes do SAVE anterior |
| Pequeno desvio/obstaculo vira parada prolongada | Comparacao esparsa e nenhuma medida continua de progresso | Posicao comparada, recuperacao por teclado e deteccao de falta de progresso por 1,8 s; espera limitada e ate tres recuperacoes por vida |
| Possibilidade de repeticao infinita na correcao | Recuperacoes podiam ser reabertas sem um orcamento da tentativa | Cada recuperacao tem prazo ativo de 4 s, limite por vida e parada com controles liberados |
| Eventos/referencias sobrevivem ao documento | Listeners anonimos no Stage nao eram removidos junto com o timer; cadeias tinham donos separados | Runtime unico, handlers removiveis, restauracao dos hooks, cancelamento antes do descarte e invalidacao de callbacks |
| Eventos de um componente afetam o restante | Captura, observacao e reproducao compartilham callbacks nativos | Encadeamento preserva cursor/retorno/prioridade e isola erros. Fake Lag e troca de dispatcher foram exercitados |
| Cache/logs crescem sem limite | Dicionarios de rotas locais/remotas sem politica unica de retencao | Cache LRU de 32 mapas; historico/fila de logs de 200 eventos, lotes de 20, rotacao em 2 MiB |
| Validacao do cliente e do servidor diverge | Cliente aceitava ate 100.000 passos e servidor ate 1.800 | Limites alinhados, campos/tipos conferidos, numeros assinados e espelhamento preservados; extensao `up` opcional |
| DELETE/LIST nao atuam nas rotas novas | Botoes ainda chamavam armazenamento legado, que nao alimentava esse controlador | Handlers dos quatro botoes apontam ao gravador atual; API local lista/desativa o mapa correto |
| Dificuldade para explicar falhas intermitentes | Status visual e pouco historico persistente | Eventos por mapa, tentativa e passo, historico limitado e envio com confirmacao/repeticao; teste de falha temporaria de log |

A conclusao de queijo/toca ja dependia de eventos nativos no projeto fornecido.
Essa propriedade foi preservada e testada, incluindo ID de outro jogador,
quantidade de queijo negativa/zero, morte e ponteiro local temporariamente ausente.
Nao foi apresentada como um defeito corrigido quando a logica existente estava correta.

## Arquivos alterados e adicionados

Alterados no projeto original:

- `DisneyClient/public/ChargeurTransformice.swf`: loader recompilado e verificado.
- `DisneyClient/api/github_routes.py`: extensao `up`, leitura local, persistencia,
  exclusao/lista local e recepcao de logs; publicacao GitHub preservada.
- `DisneyClient/BUILD-ID.txt`: identificacao da entrega.
- `ARQUIVOS-SHA256.json`: novo manifesto da entrega.

No invólucro do ZIP, `extrair_e_iniciar.py` passa a preservar explicitamente as
pastas de rotas locais e pendentes; o payload, as instrucoes iniciais e os hashes
foram atualizados. Os inicializadores BAT foram preservados.

Adicionados:

- `DisneyClient/api/robot_storage.py`.
- `fontes-robot-atual/RobotSuiteCurrent.as`.
- `fontes-robot-atual/RobotControllerCurrent.as`.
- `fontes-robot-atual/RobotInputCurrent.as`.
- `fontes-robot-atual/RobotRouteCurrent.as`.
- `fontes-robot-atual/RouteRecorderCurrent.as`.
- `fontes-robot-atual/RobotTrace.as`.
- Nessa mesma pasta: base original, build/verificador, suites, runner, README,
  fixtures e resultados reais. O inventario completo esta em `ARQUIVOS-SHA256.json`.
- `ROBOT-ATUAL-INSTALACAO.txt` e este relatorio.

Nao houve alteracao de banco, credenciais, configuracoes pessoais, protocolo do
jogo ou fontes das outras funcionalidades. O verificador compara os metodos do
SWF original com o novo: so muda a chamada de inicializacao e REC/SAVE/DELETE/LIST.
Seis classes novas foram adicionadas; 141 novos corpos de metodo tiveram pilha e
escopo verificados. As outras instrucoes existentes permanecem iguais.

## Testes executados

Os resultados finais, codigos de saida e saidas integrais estao em
`fontes-robot-atual/resultados/testes.json` e nos respectivos arquivos `.log`.
A tabela abaixo e gerada dos resultados reais, apos conclusao de todas as suites.

| Suite | Quantidade | Resultado |
|---|---:|---|
| API e armazenamento (testes Python) | 23 | Passou |
| Loader original: reproducao de defeitos/controles | 5 | Passou |
| Reproducao do Robot | 105 | Passou |
| Gravacao, rascunhos e publicacao | 35 | Passou |
| Ciclo de vida, fidelidade e 300 rodadas | 944 | Passou |
| HTTP, respostas antigas, timeout e logs | 6 | Passou |
| Fake Lag e hooks nativos | 33 | Passou |
| Follow | 27 | Passou |
| Visual | 18 | Passou |
| Fly | 32 | Passou |
| AutoBest | 37 | Passou |
| Interface | 37 | Passou |

Sao 23 testes Python e 1.274 verificacoes ActionScript no codigo corrigido.
Os cinco probes do loader original sao separados: tres defeitos, um controle
e uma verificacao adicional do cursor do pacote.

A suite de estabilidade executa 300 rodadas simuladas consecutivas, com
reinicializacao, vitoria, retencao da preferencia e limites de historico.
Ela tambem verifica morte/renascimento, troca de mapa e retorno, sala nova,
ativacao/desativacao, loading parcial, teclas, quadros atrasados, recuperacao,
travamento e cadencias de quadro diferentes.

As suites HTTP usam requisicoes reais contra servidores locais de teste.
GitHub, autenticacao e objetos fisicos sao simulados; nao foram usadas credenciais
reais nem feitas publicacoes de rotas de teste no GitHub.

A verificacao de bytecode nao permite chamadas do novo Robot para teleporte,
escrita de posicao/velocidade ou pacotes forcados de coleta/vitoria/morte.

## O que ainda exige validacao em uso real

Nao houve partida autenticada no Adobe Flash conectado ao servidor real, teste
com todos os mapas ou teste dos servicos externos de musica/login. As suites de
Follow, Fly, AutoBest, visual, interface e Fake Lag executadas sao simuladas;
as instrucoes existentes dessas funcionalidades tambem foram comparadas.

Nao e possivel garantir erro zero sob qualquer lag/FPS, colisao ou rota
incompativel. A fisica decide a aceitacao dos saltos; teclado remoto nao e
observavel ao gravar outro jogador. Em uma recuperacao inviavel o Robot para e
registra a causa, em vez de inventar movimento ou ficar em um loop.

A persistencia no disco so esta confirmada apos o ACK local. O projeto mantem
as permissoes existentes de armazenamento. Falha de disco/permissao aparece
como erro e deixa a rota pendente em memoria enquanto o cliente continua aberto.

Instalacao: `ROBOT-ATUAL-INSTALACAO.txt`.
Compilacao e repeticao dos testes: `fontes-robot-atual/README.md`.
