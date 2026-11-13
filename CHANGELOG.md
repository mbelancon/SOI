# Histórico de versões

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto usa [versionamento semântico](https://semver.org/lang/pt-BR/): MAIOR.MENOR.CORREÇÃO.

- **MAIOR:** mudança incompatível, por exemplo no protocolo serial entre firmware e interface.
- **MENOR:** função nova que não quebra o que já existia.
- **CORREÇÃO:** conserto de erro.

A interface e o firmware compartilham o mesmo número de versão. O número aparece em `__version__` (interface, título da janela) e em `FIRMWARE_VERSION` (firmware). Cada versão publicada ganha uma tag `vX.Y.Z` no GitHub.

## [Não lançado]

## [2.1.0] - 2026-11-13

Versão menor: só a interface muda. O firmware continua o 2.0.0 (`binarios/soi_firmware_v2.0.0.bin`) e o protocolo USB é o mesmo. Calibrações e varreduras antigas continuam abrindo.

### Interface (`interface/soi_controller.py`)

#### Adicionado
- **Referências de calibração do microfone** (painel "Calibração do microfone", aba Modo Duplo): Folha de Al fina (modo OPC, S ∝ f⁻¹·⁵), Al espesso dentro da câmara, folha de Al fina dentro da câmara (sobre apoio isolante), negro de fumo (recomendada) e fita preta fosca, separadas para que uma confira a outra, Al pintado de preto fosco (f⁻¹ acima de ~100 Hz; abaixo, a tinta deixa o calor chegar ao Al) (todas na câmara, S ∝ f⁻¹, Rosencwaig–Gersho) e Personalizada (S ∝ f⁻ⁿ). Espessura, difusividade ou n editáveis, com a curva esperada, μ = √(α/πf) e o limite f₁ = α/(πL²) da folha fina.
- **Seletor "Célula: OPC | Câmara"** na linha superior. A referência escolhe a célula; a calibração registra a sua e a interface avisa se for usada na outra. Os CSV do Modo Duplo gravam `# Celula = …`.
- **Esquema da montagem** ao lado da referência: desenho genérico mostrando se a amostra fecha a célula (OPC) ou fica dentro, sob a janela de vidro, com a folga de ar, mais dicas de montagem.
- **Verificação do comportamento** depois do "Fitar padrão": expoente n comparado com o esperado (±0,15), fase constante depois de descontar fc e td (±15°) e faixa confiável de pelo menos uma década. Se falhar, aviso vermelho de que o modelo não foi verificado experimentalmente nesta montagem, com as causas prováveis. Depois virou informação (aviso laranja): na câmara, a resposta do sistema entra na forma, e a verificação passou para a segunda referência. Toda calibração nova nasce não verificada (⚠ na lista, no PNG e sempre que for usada).
- Curva teórica da referência (cinza pontilhada) no gráfico.
- **Ajuste da ressonância da célula** no "Ajuste com modelos": oscilador amortecido + fundo complexo com atraso, em magnitude e fase. Pico automático ou "Marcar pico (2 cliques)". Mostra f₀, Q, largura f₀/Q e ganho do pico sobre o fundo, com incertezas.
- **PC sem suspensão durante medidas (Windows):** varreduras e Teste de resolução impedem a suspensão e a hibernação por inatividade (`SetThreadExecutionState`) e liberam no fim. Antes, uma varredura longa era interrompida quando o PC suspendia.
- **"Normalizar pelo OPT101"** (Modo Duplo, varredura em frequência): liga ou desliga a divisão pelo R do OPT101 e o desconto da fase dele nos gráficos e ajustes. Desligada, a calibração do microfone e o "Fitar padrão" ficam inativos. O CSV registra `# Normalizacao pelo OPT101 no gráfico/ajuste = sim|nao`.
- **"Mostrar sinais de cada sensor"** (Modo Duplo): segunda fileira de gráficos com a amplitude (R ÷ mediana da varredura) e a fase desenrolada do INMP441 e do OPT101, separadas.
- **Botão "Diagnóstico"** (Modo Duplo, varredura em frequência): separa o sinal fotoacústico (S ∝ f⁻ⁿ) de um fundo plano (luz no microfone, chiado do driver, acoplamento elétrico) com um ajuste complexo que inclui o passa-alta do microfone, o atraso e a ressonância da célula. Desenha as componentes e mostra onde o fundo domina, fc, atraso, f₀ e Q, com o teste sugerido.
- **Verificação com uma segunda referência** (passo 5 do painel de calibração, botão "Verificar calibração"): com a calibração aplicada, uma referência de material diferente, medida na mesma montagem, tem de dar f⁻ⁿ com fase constante (|Δn| ≤ 0,15, ≤ 1,5 dB rms, ± 10° rms). Só ela marca a calibração como verificada; o resultado vai para o arquivo (`# Verificacao_2a_referencia`). Com a mesma referência, mede só a repetibilidade.
- **"Faixa: de … até"** no ajuste do padrão e na verificação (substitui o "Fit até"), para deixar fora o ruído de baixa frequência e a ressonância.
- **f₀ da ressonância na calibração** (`# Ressonancia_f0_Hz`) e aviso quando a varredura corrigida tem a ressonância deslocada mais de 3 % (amostra com altura diferente da referência).
- **Modelos de câmara fechada** no "Ajuste com modelos": amostra opaca (f⁻¹) e transparente termicamente grossa (f⁻¹·⁵), para amostras de teste como vidro.

- **Ícone do SOI** feito a partir do logo do LCTM (molécula e prisma em amarelo sobre fundo escuro): aparece na janela, nos diálogos e na barra de tarefas (também rodando pelo `python.exe`). Arquivos em `interface/icones/` (`soi.ico` com 16, 20, 24, 32, 40, 48, 64, 128 e 256 px, e `soi_256.png`). De 16 a 32 px o ícone mostra só o prisma, com traço mais grosso, para continuar legível.

#### Alterado
- **Calibração:** M(f) = S(f)·fⁿ com o n da referência (antes, sempre f¹·⁵). Pontos com SNR suficiente entram mesmo fora do modelo (antes, os rejeitados pelo ajuste ficavam fora e a ressonância era interpolada). O arquivo ganha as linhas `Referencia`, `Referencia_ID`, `Celula`, `Expoente_teorico`, `L_um`, `alpha_cm2_s`, `Verificada`, `Verificacao`, a coluna `No_Ajuste` e a célula no nome (`CAL_…_microfone_<OPC|Camara>_…`). Calibrações antigas são lidas como "Folha de Al, OPC".
- O painel "Calibração de papel alumínio" passou a se chamar "Calibração do microfone".
- **Modo Duplo reorganizado:** gráficos em cima e resultados em texto embaixo; abrir os painéis não esconde mais os gráficos. Textos de verificação encurtados (detalhes na dica). O esquema da célula escala com a fonte do Windows, e as dicas de montagem não se sobrepõem mais ao desenho.
- **Duplo clique** em qualquer gráfico volta os eixos/zoom ao padrão (no Modo Duplo, os dois gráficos juntos).
- **Aviso antes da varredura da calibração** se o PWM não estiver em 100 %, se algum filtro de 60 Hz estiver ligado ou se "Usar" estiver marcado, com "Corrigir e rodar", "Rodar assim" ou "Cancelar".
- Texto do Fit padrão mais curto: "Corte PAS" no lugar de "Corte do microfone/célula (fc)".
- **Calibração:** sem o botão "Parâmetros de calibração". A varredura da calibração sempre abre com 5–2440 Hz, 35 pontos log e τ = 2 s. "Gerar calibração do microfone" virou **Guardar calibração** (só grava quando clicado).
- **Varreduras em frequência sem a opção "Medida"**: sempre integração longa, com um campo τ ligado ao τ do INMP441 (mudar em qualquer um dos três campos muda os outros). A casada em PWM mantém a escolha.
- **Refinar ressonância** (quadro da varredura em frequência da calibração): ajusta a ressonância da célula acima de 250 Hz na varredura atual (ou aberta do disco) e mede N pontos novos (12 por padrão) dentro da largura do pico, f0 ± f0/(2Q). Os pontos entram em ordem na mesma varredura, as exclusões são mantidas, e o CSV é gravado de novo com todos e uma linha "# Refino da ressonância".
- **Arranjo dos gráficos da varredura em frequência** (botão direito): lado a lado, empilhado (eixo x compartilhado, escala de frequência em cima no de cima e embaixo no de baixo, sem espaço entre eles) ou sobrepostos, com S à esquerda e a fase no eixo da direita. Fica salvo. Os eixos têm as cores das curvas (S azul, fase vermelha).
- **Topo do Modo Duplo reorganizado:** "Executar varreduras" deu lugar a dois botões. **Calibração ▸** abre o quadro da calibração (referência, esquema, passos) com a varredura em frequência da calibração ao lado e liga o Fitar padrão. **Varreduras ▸** abre uma varredura em frequência de medida, com parâmetros próprios, e a casada em PWM. **Ajuste com modelos ▸** também foi para o topo. Os botões e quadros que ficavam abaixo dos gráficos saíram; os gráficos ocupam toda a altura livre (sem o divisor arrastável), e os resultados em texto aparecem num quadro flutuante sobre eles, que se arrasta pelo título e se recolhe (posição salva). O painel Calibração ganha rolagem horizontal em telas estreitas, em vez de alargar a janela além da tela.
- **Canal óptico simplificado** (Modo Duplo): a linha longa do τ efetivo virou uma linha curta "Luz (OPT101)" com o nível da luz, a variação na varredura e a banda óptica; os detalhes ficam na dica e no CSV. "Descontar τ do sensor" e "Medir…" foram para "Avançado ▸" no painel de calibração (só servem ao trocar o resistor do OPT101); a caixa de marcar saiu, e τ = 0 significa sem correção.

### Executável e documentação
- `packaging/soi_controller.spec`: o .exe usa `interface/icones/soi.ico` como ícone e leva a pasta `icones` junto.
- Documentação revisada para o firmware em STM32Cube: README (gravação pelo PlatformIO com `framework = stm32cube` ou pelo `.bin` em `binarios/`, compatibilidade de versões), `docs/01_Materiais.md`, `docs/05_Componentes.md` e `docs/06_Desempenho_e_Aplicacoes.md` não citam mais o framework Arduino/STM32duino nem o `main.cpp`.
- README com o ícone no topo e o logo do LCTM no rodapé (`docs/imagens/logo_lctm.svg` é o original; `logo_lctm.png` e `soi_icone.png` são derivados).

## [2.0.0] - 2026-11-13

Publicada no GitHub junto com a 2.1.0 (estava em teste desde 2026-11-05).

Versão maior: **o protocolo USB mudou**. O firmware 2.0.0 só funciona com a interface 2.0.0, e vice-versa. Para voltar à 1.0.0, regrave o firmware antigo.

### Firmware (`firmware/`)
- **Reescrito em STM32Cube** (HAL da ST e biblioteca USB Device da ST V2.11.6, em `firmware/src/usb`), sem o STM32duino. `src/main.cpp` deu lugar a `src/main.c`, mais a configuração em `include/` e `src/usbd_*.c`. No teste de vazão da Black Pill, o USB CDC passou de ~190 kB/s (STM32duino) para ~1,1 MB/s.
- **OPT101 cru:** todas as amostras do ADC, 12 bits a **200 kS/s**, cada uma com o estado do laser (bit 15). A sobreamostragem saiu do firmware e foi para a interface, então mudar a taxa não exige mais regravar a placa.
- **Pacote óptico novo** `A5 5A 4F 50`, com número de sequência absoluto (uma perda vira um salto visível) e CRC-16. Os quadros `55 AA` de 5 bytes deixaram de existir.
- **INMP441 a 48 kHz exatos** (PLLI2S 76,8 MHz, I2SDIV 12 com ODD), no lugar de 31 994 Hz (−186 ppm).
- Fluxo total de ~550 kB/s, metade do que o USB aguenta. Memória: ~31 KB de flash e ~50 KB de RAM (anel óptico de 8192 amostras, 41 ms).
- Iguais à 1.0.0: comandos `F` e `P`, PWM de 5 kHz em PA8, faixa e arredondamentos da modulação (0,1–5000 Hz, TIM4), PB0 como referência, marcador de fase do INMP441 e prioridades de interrupção (o USB entra com a menor).
- A placa aparece no Windows como "SOI OPT101/INMP441 (STM32F401)", VID 0483, PID 5740.

### Interface (`interface/soi_controller.py`)

#### Adicionado
- **Sobreamostragem escolhida na interface** (aba OPT101): 1x a 64x, de 200 a 3,125 kS/s. O padrão 16x reproduz os 12,5 kS/s da 1.0.0. A escala continua 0–16 380, e a correção de amplitude da média (boxcar) e o atraso da referência acompanham o OSR.
- **Teste de resolução** (aba OPT101): com sinal estável, grava as amostras cruas e mostra o ruído das médias de N amostras (desvio de Allan) contra o ideal 1/√N, o ganho em bits, os bits efetivos e o histograma dos códigos do ADC. Avisa quando falta dither (σ < 0,3 LSB) ou quando o laser estava modulando, descarta a gravação se houver perda e salva CSV e PNG.
- **Avisos na barra de status:** laranja quando a modulação passa de FS/4 e vermelho acima de 0,4·FS, com sugestão do maior OSR seguro; aviso também quando a modulação passa de 1 kHz com PWM abaixo de 100 %. A taxa em uso também aparece na barra.
- **Clique e zoom nas duas FFTs:** um clique mostra a frequência e a magnitude do ponto mais próximo; a rodinha dá zoom, arrastar move, o duplo clique volta à escala automática e o botão direito apaga o marcador.
- **Lock-in com τ** (vindo do PR #3): o passa-baixas dos lock-ins (OPT101, INMP441 e integração longa do Modo Duplo) é escolhido pela constante de tempo τ, na sequência 1–3–10 de 1 ms a 100 s. Ao lado aparecem o corte de −3 dB, a ENBW e a espera de 9τ.
- Os CSVs do Lock-In registram o OSR, a taxa e o τ no cabeçalho.

#### Alterado
- **O script da interface passou a se chamar `interface/soi_controller.py`** (antes `interface/stm32_opt_inmmp_novo.py`), igual ao nome do programa, do `.spec` e do executável. A versão fica só dentro do arquivo, em `__version__`. O conteúdo não mudou com a troca de nome, e as preferências salvas continuam valendo.
- **Leitura USB num processo separado:** travadas da tela não fazem mais perder dados. `SOI_SERIAL_THREAD=1` volta ao modo antigo (thread).
- Leitura do protocolo novo com verificação de CRC. Uma perda real é preenchida repetindo a última amostra (o tempo e o PLL seguem certos), contada na barra de status e registrada no terminal com horário e duração. O salto de sequência no início da conexão não conta como perda.
- **Áudio a 48 kHz:** lock-in do INMP441 com a taxa exata, blocos de 2400 amostras (continua com 20 pontos/s) e espectro até 24 kHz.
- Desempenho a 200 kS/s: o osciloscópio guarda no máximo 120 mil pontos (média por ponto quando a janela é longa), a FFT completa cresce com a taxa, a FFT com zoom é limitada a 2¹⁹ pontos, a janela Hann fica em cache e o Valor Médio guarda só a soma corrente dos ciclos.
- O τ automático ao mudar a frequência é arredondado para 0,3 s, 1 s ou 3 s. As preferências guardam o τ; o corte em Hz salvo pela 1.0.0 é ignorado uma vez.
- O simulador gera as amostras cruas de 200 kS/s, como o firmware novo.

#### Corrigido
- O campo τ também funciona com PyQt6 (antes só com PySide6).
- A fase do INMP441 não gira mais com o tempo (a taxa de 31 994 Hz tratada como 32 kHz causava a deriva).

### Documentação
- O roteiro de teste foi para `docs/testes/teste_2.0.0.md`, e o binário do firmware passou a se chamar `soi_firmware_v2.0.0.bin`.
- `docs/03_Firmware_STM32.md` reescrito: STM32Cube, relógios (PLLI2S para 48 kHz), ADC sem sobreamostragem, protocolo novo e prioridades.
- `docs/04_Interface.md` ganhou as seções de Sobreamostragem e Teste de resolução, a barra de status e as especificações atualizadas.
- `docs/05`, `docs/06` e `README.md` atualizados (taxa, áudio a 48 kHz, estrutura do firmware).

### Testes feitos (05/11/2026, na Black Pill)
- Leitura direta da porta por 2 × 60 s (551 kB/s, 200,2 kS/s ópticos e 48,0 kS/s de áudio), sem perdas e sem erros de CRC, inclusive com a CPU ocupada.
- Teste de resolução com luz constante: 8,4 LSB de ruído por amostra; o ruído cai como 1/√N até N = 64, de 7,1 para 10,4 bits efetivos. Acima disso aparece ruído da rede (múltiplos de 60 Hz, presente com o OPT101 tampado), de origem elétrica.
- Modulação ligada com o laser apagado não muda o ruído nem aparece na FFT do OPT101: não há vazamento elétrico da modulação para o canal óptico.

### Pendente antes de publicar
- Conferir as varreduras do Modo Duplo com o firmware novo (a calibração com folha de alumínio de 05/11 deu n = 0,20–0,31, longe do 1,5 esperado; suspeita de alinhamento/acoplamento, ainda em investigação).

## [1.0.0] - 2026-10-27

Primeira versão publicada.

### Interface (`interface/stm32_opt_inmmp_novo.py`)
- Lock-in em Python dos dois canais: OPT101 (com PLL em software) e INMP441.
- Aba OPT101: osciloscópio, Lock-In e Valor Médio (com ajuste de 1 ou 2 exponenciais), FFT do ADC com fit do pico, varreduras em frequência e em PWM.
- Aba INMP441: Lock-In, Ruído/SNR, FFT com fit do pico, varreduras em frequência e em PWM com correção pela calibração.
- Modo Duplo: os dois lock-ins no mesmo passo, sinal normalizado pelo OPT101, calibração do microfone com folha de alumínio, ajuste de modelos e abertura de varreduras salvas.
- Exportação padronizada em CSV/PNG com o nome da amostra e "Finalizar experimento" (ZIP da sessão).
- Detecção automática da porta, reconexão e modo simulado sem o STM32.

### Firmware (`firmware/`)
- STM32F401 Black Pill (STM32duino): PWM do laser de 5 kHz (0–100 %, passo de 0,1 %) e modulação em onda quadrada de 0,1 a 5000 Hz.
- ADC do OPT101 a 12,5 kS/s com 14 bits efetivos (sobreamostragem) e referência do laser por DMA.
- INMP441 por I2S a ≈32 kS/s, 24 bits, com marcador de início da modulação para a fase.
- Envio por USB CDC.

### Acrescentado na main depois do lançamento (sem mudar o número)
- Executável Windows: spec do PyInstaller em `packaging/` e workflow que anexa o `.exe` e o `.zip` às Releases (PR #1, 27/10/2026).
- Requisito mínimo de processador documentado: x86-64-v2 / SSE4.2 (PR #2, 29/10/2026).

[Não lançado]: https://github.com/mbelancon/SOI/compare/v2.1.0...HEAD
[2.1.0]: https://github.com/mbelancon/SOI/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/mbelancon/SOI/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/mbelancon/SOI/releases/tag/v1.0.0
