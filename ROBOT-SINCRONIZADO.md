# Robot sincronizado 7

Baixe [DisneyClient-Robot-Sincronizado.zip](DisneyClient-Robot-Sincronizado.zip), extraia em uma pasta nova, copie sua configuracao `.env` anterior e execute `INICIAR_CLIENT.bat`.

O Robot acompanha os quadros do jogo, preserva intervalos apos atrasos e aguarda aproximacao a posicao registrada antes de mudar de direcao ou iniciar novo salto quando ha desvio. Mantem confirmacoes nativas de queijo e chegada. Perder foco pausa a rota: mantenha o Flash em foco.

Validacao: 119 verificacoes do controlador, 26 do gravador/rascunhos e 27 do Follow em simulacao Ruffle. Integridade do ZIP e 508 arquivos extraidos verificados. Ainda requer teste em partida real; nao garante ausencia de erros sob qualquer lag.

O pacote inclui fontes, testes, instrucoes de compilacao e instalador. Consulte `ROBOT-SINCRONIZADO-LEIA-ME.txt` e `fontes-robot-sincronizado/README.md` dentro do projeto extraido.
