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
- Célula fotoacústica "Camara": cilindro 2 cm × 5 mm de diâmetro, furo de ~1 mm no meio da altura,
  janela de lâmina de 1 mm. Desde 23/11 sem a câmara do microfone e com nova fixação do INMP441 (canal menor):
  sem ressonância até ~3 kHz e sem a flutuação em baixa frequência.
- Peças de Al (todas termicamente grossas): disco "pequena" ~12–15 × ~5 mm (~2 g, medir exato), 30×20×18 mm
  (~29 g) e 120×20×18 mm (~117 g).
- A ventoinha do laser gera 170,2 Hz + harmônicos (340, 510, 681, 851, 1021 Hz; f0 varia 169,6–171,8 Hz), que
  chegam ao INMP441 também pela bancada.

## Estrutura
- `firmware/` — STM32Cube (HAL + USB Device da ST em `src/usb`), PlatformIO com `framework = stm32cube`.
  OPT101 bruto a 200 kS/s com o estado do laser no bit 15; INMP441 a 48 kHz. Binário em `binarios/`.
- `interface/soi_controller.py` — PySide6/PyQt + pyqtgraph, lock-in em software, modo simulado.
  `interface/soi_i18n.py` — idioma (pt/en pelo Windows, `SOI_LANG` força) e tabela pt→en.
  Na 2.4.0: `interface/soi_serie.py` (aba Medidas em Série) e `interface/soi_ruido.py` (detectar ruídos de fundo).
- `rodar_interface.bat`, `varredura.bat`, `campanha_deriva.bat` — atalhos (miniconda).
- Pasta local do PC padrão (sbook2, `Projetos\Claude\SOI`) é um clone git e se atualiza só por git (checkout da
  branch em teste ou `git pull`), sem cópias de arquivos. Medidas e dados ficam fora do git.
- `docs/01..08` (inglês; 07 = calibração, 08 = exemplos com medidas reais), `examples/` (CSVs + script das
  figuras), `docs/tests/`, `packaging/` + `.github/workflows` (executável nas Releases).

## Versões
- `main`: 2.3.0 (PR #5, 17/11), firmware 2.0.0. v1.0.0 publicada em 2026-10-27; v2.3.0 publicada em 17/11 (Releases, exe + zip).
- Em desenvolvimento: interface 2.4.0 (firmware 2.0.0 intacto) na branch `claude/project-thread-nvsgcv`, sem PR;
  no sbook2 desde 19/11 (commit 9af511b). Testada no modo simulado e em medidas reais de 19/11.
- Versões de firmware e interface são independentes (ver CLAUDE.md).

## Próximo PR (só quando o Marcos pedir; tudo aprovado, Marcos ainda quer mexer antes)
Interface 2.4.0, branch `claude/project-thread-nvsgcv` (lista completa no CHANGELOG, seção 2.4.0): aba Medidas em
Série, varredura embaralhada com mediana, faixas excluídas e "Detectar ruídos de fundo", descarte por vizinhas opcional.
Depois do merge: PR só de reorganização dividindo o `soi_controller.py` em módulos (aprovado 20/11; ver relatório
"SOI — como gastar menos tokens").

## Medidas
- As medidas até 23/11 estavam sujeitas a vazamento da célula, provavelmente pelo ponto do microfone, o que
  comprometia o desempenho em baixa frequência.
- Tudo até 23/11 está arquivado (dados de 23/11 não confiáveis): resumo em
  `arquivo/ate_20261123/RESUMO_ate_20261123.md` (pasta do projeto) e `Projetos\Claude\SOI_arquivo\ate_20261123\` no PC.
- Lições de método a conferir no sistema novo: PWM 100 %, warm-up, evitar múltiplos de 60 Hz e a série da ventoinha
  (170,2 Hz + harmônicos), ordem embaralhada com mediana, calibração Al + Inox na mesma face.
- Quinta, 26/11: bateria consolidada para as análises de ruído, parâmetros do lock-in (τ, médias) e τ adaptativo.

## Planos próximos
- Semana de 23/11 (SOI volta da apresentação): melhorias mecânicas medidas antes/depois (isopor sob o board de metal,
  laser fora do board parafusado na madeira; detector rápido, fundo em 170/681/851/160 Hz, varredura τ 1 s);
  15 repetições embaralhadas na peça de 120 mm à noite; aquecimento noturno; medir o disco pequeno.
- Avaliar offline a correção de deriva entre blocos (normalizar cada repetição) com as 15 repetições.
- PC Ubuntu com tela 1366×768 para deixar o SOI no lab: testar layout (rolagem/compacto), `rodar_interface.sh`,
  `/dev/ttyACM0` + grupo dialout, dependências. Não iniciado.
- Apresentação: slides "SOI — fotoacústica portátil com STM32" (ênfase em portátil, sem lock-in/chopper).

## Pendências / ideias
- LEMBRETE: medida de 24 h do ruído acústico (fundo com PWM 0, Sinal x t em ~10, 30 e 100 Hz) para ver a
  variação com o horário (aulas, rodovia).
- Segundo INMP441 de referência fora da célula (L/R no mesmo I2S): subtração no PC com H calibrado ou LMS;
  calibrar com chirp numa caixa de som em várias posições. Verificar banda USB para 2 canais a 48 kHz.
- Sensor NTC na parede da célula lido pelo ADC1 (canal injetado no PA1, sem perder amostras) — proposta,
  aguarda aprovação (muda firmware e interface).
- Célula diferencial (tipo Miklós) para cancelar ruído ambiente — ideia futura.
- Regra do τ com blocos e incerteza u (proposta no relatório da campanha), se aprovada.
- Subtração do fundo do ventilador no modo óptico (feixe bloqueado); firmware opcional com entrada TTL no bit 14.
- Itens ⚠ em docs/01 e docs/02: driver do laser, alimentação do OPT101, descrição da célula.
- Entrada limitada a 0–3,3 V (avaliar condicionamento de sinal).
- Aba HP 34401A (RS-232/SCPI) — ideia, não iniciada.
- Lâmpada flash Hamamatsu L9456-01 (trigger pelo STM32), pulsos lidos pelo OPT101 a ~200 kS/s.
- Esta interface é a referência de estilo para QuadPV e TipGas.
