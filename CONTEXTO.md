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
- Célula fotoacústica "Camara": cilindro 2 cm × 5 mm de diâmetro, furo de ~1 mm no meio da altura (INMP441
  com o-rings de um lado, furo de equalização do outro, fechado nas medidas), janela de lâmina de 1 mm.

## Estrutura
- `firmware/` — STM32Cube (HAL + USB Device da ST em `src/usb`), PlatformIO com `framework = stm32cube`.
  OPT101 bruto a 200 kS/s com o estado do laser no bit 15; INMP441 a 48 kHz. Binário em `binarios/`.
- `interface/soi_controller.py` — PySide6/PyQt + pyqtgraph, lock-in em software, modo simulado.
  `interface/soi_i18n.py` — idioma (pt/en pelo Windows, `SOI_LANG` força) e tabela pt→en.
- `rodar_interface.bat`, `varredura.bat`, `campanha_deriva.bat` — atalhos (miniconda).
- Pasta local do PC (`Projetos\Claude\SOI`) agora é um clone git do repositório: atualiza com `git pull` do
  `main`. Medidas, dados e backups ficam fora do git (não versionados).
- `docs/01..08` (inglês; 07 = calibração, 08 = exemplos com medidas reais), `examples/` (CSVs + script das
  figuras), `docs/tests/`, `packaging/` + `.github/workflows` (executável nas Releases).

## Versões
- `main`: 2.3.0 (PR #5, 17/11), firmware 2.0.0. v1.0.0 publicada em 2026-10-27; ainda sem release da 2.3.0.
- Versões de firmware e interface são independentes (ver CLAUDE.md).

## Próximo PR (só quando o Marcos pedir)
Nada pendente: tudo o que estava aprovado entrou no PR #5.

## Campanha de deriva (16–17/11, alumínio) — descobertas
Dados + relatório: `interface\Medidas\Campanha_deriva_20261116\Campanha_deriva_20261116.zip`
(relatório: Claude Doc "Campanha de deriva 16-17/11").
- Abaixo de ~30–40 Hz domina ruído acústico do ambiente, aditivo e independente do laser (fundo a 10 Hz ≈ 1/3 do
  sinal no Al; a ≥ 100 Hz, 1–5 %). Baixar o PWM só piora o SNR: medir a 100 %. Inox dá mais sinal (melhor no grave).
- Deriva = aquecimento depois que o laser liga: S −14 % com T ≈ 4,4 min a 10 Hz (OPT101 −4 %, T ≈ 1 min); depois
  estável por 1 h. Pouco efeito a 300–1000 Hz. Daí o "Aguardar warm-up" (300 s).
- Ruído branco até ~4 min de média (Allan 12 % em 5 s → 1,7 % em 4 min a 10 Hz; piso ~1,4 %).
- Varreduras a 1/2/4 %: concordam em ~2 % acima de 40 Hz; 5–11 % abaixo. A flutuação da janela não é a incerteza
  do ponto (subestima no grave, superestima no agudo). Proposta de regra com blocos e incerteza u: no relatório,
  ainda não implementada.
- 300 Hz (harmônico de 60 Hz) tem fundo no OPT101: evitar múltiplos de 60 Hz em frequência fixa.

## INMP441 em baixa frequência
- Datasheet: especificado para f > 60 Hz. Mede abaixo, mas com mais ruído próprio, somado ao ruído da sala.
- Ruído da sala varia com o horário (aulas até 23h; depois, tráfego na rodovia em frente ao laboratório).
- Dois microfones (em breve): um segundo INMP441 de referência (fora da célula, ou numa célula cega) permite
  subtrair o ruído ambiente coerente; dois na célula, em média, reduzem o ruído próprio ~√2. Os dois cabem no
  mesmo barramento I2S (pino L/R: canal esquerdo e direito); o firmware passa a ler os dois canais.

## SNR e incerteza por ponto (análise de 17/11, `dados_artigo/ANALISE_20261117.md`)
- Ruído do INMP441 ~10⁻⁵ FS em todas as amostras; o que muda é o sinal (Al/Inox ~10⁻³ FS, acrílico/OPC ~10⁻⁴).
- Erro do ponto (f < 500 Hz): < 15 dB ~44 %, 15–25 dB 10–25 %, ≥ 25 dB ≲ 10 % (piso ~7 %, ruído acústico/deriva).
  Cores do SNR na interface: verde ≥ 25, amarelo 15–25, vermelho < 15 dB. Reavaliar com τ maior (τ = 2 s dá +3 dB).

## Calibração (notas)
- Calibração da câmara por duas amostras grossas (Al + Inox 316L; latão/grafite como alternativas): razão S_A/S_B
  plana (±1 dB, ±10°, ≥ 1 década) verifica; H = média geométrica de S·f das duas; f0 iguais (±3 %). Modo OPC
  mantido, com duas folhas finas (nunca folha de inox). A calibração da câmara não serve para o OPC.
- O f⁻² visto no Inox/Al em 13/11 vinha da calibração com negro de fumo (o negro de fumo bruto sobe ~f^+0,9),
  não da amostra. Não usar aquela calibração.
- Inox lado B dá 0,57× o lado A e só concorda com o Al até ~130 Hz: usar sempre a mesma face.

## Ressonância da célula (notas, 16/11)
- f0 salta entre estados por montagem: ~1,05–1,12 kHz (todas de 13/11, latão e Ni+filme de 16/11),
  ~1,53–1,55 kHz (Al e Inox de 16/11 de manhã) e ~1,79 kHz (Ni 10h11). Mesmas peças mudam de estado entre dias:
  é montagem/geometria acústica, não material nem temperatura; não tem assinatura de vazamento.
- A CAL Al-Inox de 16/11 09h16 foi feita no estado alto e não vale acima de ~500 Hz para medidas no estado baixo.
  Conferir f0 antes de aplicar uma calibração (a interface avisa "Ressonância deslocada"). Gráfico: `analises/ressonancia_estados_20261116.png` (pasta do projeto).

## Pendências / ideias
- LEMBRETE: medida de 24 h do ruído acústico (fundo com PWM 0, Sinal x t em ~10, 30 e 100 Hz) para ver a
  variação com o horário (aulas, rodovia).
- Segundo INMP441 (referência de ruído ambiente) — será feito em breve.
- Regra do τ com blocos e incerteza u (proposta no relatório da campanha), se aprovada.
- Subtração do fundo do ventilador no modo óptico (feixe bloqueado); firmware opcional com entrada TTL no bit 14.
- Itens ⚠ em docs/01 e docs/02: driver do laser, alimentação do OPT101, descrição da célula.
- Entrada limitada a 0–3,3 V (avaliar condicionamento de sinal).
- Aba HP 34401A (RS-232/SCPI) — ideia, não iniciada.
- Lâmpada flash Hamamatsu L9456-01 (trigger pelo STM32), pulsos lidos pelo OPT101 a ~200 kS/s.
- Esta interface é a referência de estilo para QuadPV e TipGas.
