# CLAUDE.md — SOI

Regras permanentes de trabalho neste repositório. O estado atual do projeto (versão, o que está aprovado,
medidas em andamento) fica no CONTEXTO.md, importado abaixo.

@CONTEXTO.md

## Antes de começar
- Ler o CONTEXTO.md (já vem pela linha acima) e o CHANGELOG.md, seção da versão em desenvolvimento.
- Conversar com o Marcos em português. Documentação do repositório (README, docs/, CHANGELOG) em inglês.

## Código
- Firmware novo de STM32: sempre STM32Cube (HAL/LL), nunca Arduino/STM32duino, salvo pedido explícito.
- Interface Python (`interface/soi_controller.py`): o modo simulado tem que continuar funcionando sempre.
  Testar sem janela (`QT_QPA_PLATFORM=offscreen`, `find_arduino_port` sem porta, modo simulado) e conferir
  capturas de tela antes de entregar.
- A janela tem que caber em 1366×768 a 125 % (laptop do lab): rodar `docs/tests/check_window_size.py` quando
  mudar o layout.
- Texto novo na interface: string em português no código e tradução em `EN` de `interface/soi_i18n.py`.
- Arquivos de dados mantêm nomes, colunas e chaves de cabeçalho em português (`Medidas/`, `Frequencia_Hz`,
  `# Celula = …`), em qualquer idioma da interface, para os arquivos antigos continuarem abrindo.

## Versão e CHANGELOG
- Firmware e interface têm versões independentes (semver): a do firmware (`FIRMWARE_VERSION` em
  `firmware/src/main.c`) só muda quando o firmware é modificado; a da interface é `__version__`. MAJOR igual
  nos dois = mesmo protocolo USB (MAJOR muda quando o protocolo muda) (regra do Marcos, 17/11).
- Toda mudança atualiza o CHANGELOG.md (Keep a Changelog) junto com a versão, no mesmo commit.

## Aprovação e fluxo
- O Marcos aprova cada recurso novo antes de ele entrar num PR. O que não foi aprovado fica na branch,
  listado no CONTEXTO.md como "aguardando aprovação".
- Não manter cópias de versões anteriores ("estrela"): o histórico fica no git (decisão do Marcos, 17/11).
- PR só quando o Marcos pedir. Release (tag + executável) também só a pedido dele.
- Pasta local de trabalho e testes: `C:\Users\marco\Desktop\Claude\SOI` (roda o script Python,
  não o executável; a interface grava em `interface\Medidas`). Mudanças testadas lá voltam ao repositório por
  PR antes de cada release.
- A pasta local se atualiza só por git (`git fetch` + checkout da branch em teste, ou `git pull`), nunca copiando
  arquivos. Antes, anotar o commit anterior (é o backup: voltar = checkout dele). Nunca atualizar durante medidas.
- PC oficial do projeto: Ideapad (`C:\Users\marco\Desktop\Claude\SOI`). Na pasta SOI dele nunca usar `git push --tags` nem `--mirror` (tags antigas
  apagadas voltariam ao GitHub): empurrar só branches ou tags específicas.
- No Ideapad, a pasta SOI só é atualizada com a interface fechada e fora de medidas.

## Medidas
- Grade de frequências: evitar múltiplos de 60 Hz e a série da ventoinha do laser (170 Hz × k).
- Recurso novo de análise (descarte, correções) é avaliado offline com dados reais antes de propor na interface.

## Apresentações
- Ênfase em portátil, sem lock-in nem chopper externos, velocidade/estabilidade do STM32; "baixo custo" não é o
  ponto principal.

## Segurança do hardware
- A entrada analógica do STM32F401 (PA0) não tolera 5 V. O OPT101 pode ser alimentado com 5 V para ganhar
  resolução (saída máx. ~3,7 V), mas só com proteção no ADC: 1 kΩ em série + Schottky BAT54 para 3,3 V.
  Sempre avisar do risco de queimar o STM32 ao sugerir essa opção. Padrão: Vs = 3,3 V, saída máx. ~2,0 V.
- O laser é sempre acionado por driver, nunca direto pelo PA8. Entre o PA8 e a entrada TTL de módulo de laser barato
  sempre resistor em série (~1 kΩ) + pull-down (ver docs/02).

## Economia de tokens
- Uma thread por recurso ou análise; assunto novo vai para thread nova. Ler só o trecho/módulo necessário do código
  (grep antes de ler). Descobertas de medidas ficam no NOTAS_MEDIDAS.md, lido só quando o trabalho é de medida.
- Memória do projeto: índice curto, um arquivo por assunto, sem logs de cópias ou md5.

## CONTEXTO.md e conversas longas
- Ao fim de uma sessão em que algo mudou, propor a atualização do CONTEXTO.md como diff curto e só gravar
  depois do OK do Marcos.
- Avisar o Marcos quando a conversa ficar longa e sugerir "resetar": resumir no CONTEXTO.md e começar outra.
