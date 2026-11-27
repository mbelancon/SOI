# CONTEXTO — SOI

Estado atual do projeto, para o Claude e para quem for mexer no código. Curto e atualizado; regras de
trabalho no CLAUDE.md, instruções para usuários no README.

## Objetivo
STM32 como "osciloscópio com funções extras" para técnicas fototérmicas e fotoacústicas de baixo custo
(fotoacústica, lente/espelho térmico, efeito miragem, z-scan, luminescência resolvida no tempo) com lasers de
diodo baratos, sem lock-in nem chopper comerciais. Meta: sistema pequeno e portátil.

## Hardware
- WeAct Black Pill STM32F401CCU6 (cristal 25 MHz), USB-C CDC (VID 0483 / PID 5740).
- OPT101 → PA0 (ADC, 0–3,3 V). Saída de ~7,5 mV a Vs − 1,3 V: com Vs = 3,3 V, máx. ~2,0 V.
- INMP441 (I2S): SCK PB13, WS PB12, SD PB15.
- Modulação do laser: PWM em PA8 (via driver); sincronismo em PB0. Laser 532 nm.
- **PA8 → entrada TTL/PWM de módulos de laser baratos: SEMPRE resistor em série** (24/11 dois drivers queimaram com
  ligação direta, 12 V). O módulo tem pull-up interno (TTL solto = 3,88 V) e injeta ~2 Vpp de ruído. Montagem que
  funciona: 1 kΩ em série + pull-down 5 kΩ, terra comum; capacitor 1–10 nF sugerido. Ligar o STM32 antes dos 12 V.
  Registrado em docs/02.
- Célula fotoacústica "Camara": cilindro 2 cm × 5 mm de diâmetro, furo de ~1 mm no meio da altura (furo de
  equalização do outro lado, fechado nas medidas), janela de lâmina de 1 mm. Desde 23/11: sem a câmara do
  microfone e com nova fixação do INMP441 (acabou o vazamento que prejudicava a baixa frequência).
  Estado baixo em 19/11 (célula antiga): f0 = 1052 Hz, Q ≈ 4,2.
- Peças de Al (todas termicamente grossas): disco "pequena" ~12–15 × ~5 mm (~2 g, medir exato), 30×20×18 mm
  (~29 g) e 120×20×18 mm (~117 g).
- A ventoinha do laser gera 170,2 Hz + harmônicos (340, 510, 681, 851, 1021 Hz; f0 varia 169,6–171,8 Hz), que
  chegam ao INMP441 também pela bancada.
- 2º SOI montado (em uso desde 24/11); o 1º foi para teste de um amigo.
- PC do lab (fica com o SOI): laptop Windows 10, tela 1366×768 (Ubuntu descartado em 23/11). PC oficial de
  desenvolvimento e testes (desde 26/11): "Ideapad" (i3-6100U), `C:\Users\marco\Desktop\Claude\SOI`.

## Estrutura
- `firmware/` — STM32Cube (HAL + USB Device da ST em `src/usb`), PlatformIO com `framework = stm32cube`.
  OPT101 bruto a 200 kS/s com o estado do laser no bit 15; INMP441 a 48 kHz. Binário em `binarios/`.
- `interface/soi_controller.py` — PySide6/PyQt + pyqtgraph, lock-in em software, modo simulado. É o arquivo que se
  roda (janela principal, main()); código dividido em soi_const/analise/dsp/serial/sim/widgets/headless + soi_win_*
  (métodos da janela por assunto).
  `interface/soi_i18n.py` — idioma (pt/en pelo Windows, `SOI_LANG` força) e tabela pt→en.
  `soi_serie.py` (aba Medidas em Série), `soi_ruido.py` (detectar ruídos de fundo), `soi_layout.py` (2.5.0:
  painel lateral com seções recolhíveis, ajuste à tela). `docs/tests/check_window_size.py` confere 1366×768 a 125 %.
- `rodar_interface.bat`, `varredura.bat`, `campanha_deriva.bat` — atalhos (miniconda).
- Pasta local do PC oficial (Ideapad, `Desktop\Claude\SOI`) é um clone git e se atualiza só por git (checkout da
  branch em teste ou `git pull`), sem cópias de arquivos. Medidas e dados ficam fora do git.
- `docs/01..08` (inglês; 07 = calibração, 08 = exemplos com medidas reais), `examples/` (CSVs + script das
  figuras), `docs/tests/`, `packaging/` + `.github/workflows` (executável nas Releases).

## Versões
- `main`: interface 2.4.0 (PR #8, 25/11), firmware 2.0.0. Releases publicadas: v1.0.0 (27/10) e v2.3.0 (17/11).
  A 2.4.0 e a 2.5.0 não terão release própria.
- Release 2.5.1 (27/11, firmware 2.0.0 intacto): branch `claude/project-thread-8d8oy5` (inclui a 2.5.0: janela para
  1366×768, simulado automático, remoções; e a 2.5.1: varreduras da aba OPT101/INMP441 no padrão do Modo Duplo,
  warm-up 600 s, Configurações enxuta). PR para main; tag v2.5.1 e executável Windows só depois do OK do Marcos.
- Versões de firmware e interface são independentes (ver CLAUDE.md).

## Descobertas principais (detalhes em NOTAS_MEDIDAS.md)
- Dados até 23/11 não confiáveis (arquivados). Com a célula nova a baixa frequência mede bem.
- Campanha noturna 26–27/11 (48/48 medidas): 1 repetição basta; warm-up de 120 s basta para o S normalizado
  (Modo Duplo), mas 600 s por sensor isolado (OPT101 leva 600–1200 s); τ adaptativo = precisão do fixo em metade do
  tempo; PWM a partir de 40 %; o limite é a deriva entre horas → referência no mesmo bloco de tempo; zerar filtros
  funciona nas varreduras embaralhadas.
- Deriva de S ao ligar o laser: aquecimento local sob o feixe. Evitar múltiplos de 60 Hz e a série da ventoinha (170,2 Hz).
- SNR do ponto: verde ≥ 25 dB (erro ≲ 10 %), amarelo 15–25, vermelho < 15 dB.
- Calibração por duas amostras (Al + Inox, sempre a mesma face); conferir f0 da célula antes de aplicar.
  Trocar a amostra altera o alinhamento: não comparar intensidades entre amostras, só forma e fase.

## Planos próximos
- Próximo passo: chopper mecânico com cooler PC de 4 fios controlado pelo STM32 (PWM do cooler no firmware,
  varredura automática; referência óptica pelo OPT101 já existe em Config → Trigger → Óptico). Cuidado com o ruído do
  cooler coerente com a modulação. Entra no mesmo firmware (2.1.0) que o desligamento automático do laser.
- Obter medidas experimentais válidas nos próximos dias para um artigo (Marcos pedirá ajuda com dados e gráficos).
- Laptop do lab (Windows 10, 1366×768): validar a 2.5.1. Medir o trimpot de ganho do OPT101 (500k // 1M interno).
- PCB do SOI em standby.

## Pendências / ideias
- LEMBRETE: medida de 24 h do ruído acústico (fundo com PWM 0, Sinal x t em ~10, 30 e 100 Hz) para ver a
  variação com o horário (aulas, rodovia).
- Segundo INMP441 de referência fora da célula (L/R no mesmo I2S): subtração no PC com H calibrado ou LMS;
  calibrar com chirp numa caixa de som em várias posições. Verificar banda USB para 2 canais a 48 kHz.
- Célula diferencial (tipo Miklós) para cancelar ruído ambiente — ideia futura.
- Subtração do fundo do ventilador no modo óptico (feixe bloqueado); firmware opcional com entrada TTL no bit 14.
- Itens ⚠ em docs/01 e docs/02: driver do laser, alimentação do OPT101, descrição da célula.
- Entrada limitada a 0–3,3 V (avaliar condicionamento de sinal).
- Aba HP 34401A (RS-232/SCPI) — ideia, não iniciada.
- Lâmpada flash Hamamatsu L9456-01 (trigger pelo STM32), pulsos lidos pelo OPT101 a ~200 kS/s.
- Abandonadas em 27/11 (a célula nova melhorou muito o sistema): sensor NTC na câmara, célula com espaçador,
  célula de volume mínimo, modelo de duas camadas, correção de deriva entre blocos.
- Aguardam OK / firmware 2.1.0 (junto com o chopper): desligamento automático do laser.
- Separar ruído da sala × vibração por coerência entre dois INMP441 (Marcos testará).
- Esta interface é a referência de estilo para QuadPV e TipGas.
