# 3. Firmware do STM32

Código: [`firmware/src/main.cpp`](../firmware/src/main.cpp). Projeto PlatformIO com o framework Arduino-STM32 (STM32duino). Os periféricos críticos são configurados direto pelo HAL e pelos registradores.

## Configuração do PlatformIO

```ini
[env:blackpill_f401cc]
platform = ststm32
board = blackpill_f401cc
framework = arduino
upload_protocol = stlink
build_flags =
    -O2
    -D PIO_FRAMEWORK_ARDUINO_ENABLE_CDC   ; Serial = USB CDC
    -D USBCON
    -D HAL_PCD_MODULE_ENABLED
    -D USBD_VID=0x0483
    -D USBD_PID=0x5740
```

## Gravação

1. Ligue o ST-Link aos pinos SWD da Black Pill ([ligações](02_Hardware_e_Ligacoes.md#gravador-st-link)).
2. No VS Code, abra a pasta `firmware/` com o PlatformIO.
3. Clique em **Upload** (ou rode `pio run -t upload` dentro de `firmware/`).
4. Desligue o ST-Link (opcional) e conecte a placa pelo USB-C. Deve aparecer uma porta COM "Dispositivo serial USB" (VID 0483, PID 5740).

## Relógios

| Domínio | Frequência | Origem |
|---|---|---|
| HSE (cristal) | 25 MHz | Placa WeAct |
| SYSCLK / HCLK | 84 MHz | PLL principal (padrão do STM32duino) |
| Timers APB1 (TIM3, TIM4) | 84 MHz | APB1 × 2 |
| Timer APB2 (TIM1) | 84 MHz | APB2 |
| ADC | 21 MHz | PCLK2 / 4 |
| PLLI2S → I2SCLK | 86 MHz | 25 MHz / **M=25** × **N=258** / **R=3** |
| USB | 48 MHz | PLL principal |

O HAL deixa PLLI2SM = 0 neste chip. Por isso o firmware grava **M = 25** direto no `RCC->PLLI2SCFGR`.

## Periféricos

### Laser (TIM1 + TIM4)

| Parâmetro | Valor |
|---|---|
| Portadora PWM | TIM1_CH1 em **PA8**, **5 kHz** |
| Potência | Comando `P` de 0 a 100 %, passo de 0,1 %. O valor é escrito direto no CCR1 (sem preload), então vale na hora. |
| Modulação | Onda quadrada de 50 % gerada pela interrupção do **TIM4** (prioridade 0, a maior) |
| Faixa de modulação | **0,1 a 5000 Hz**. `F0` = laser contínuo |
| Resolução da modulação | < 100 Hz: meio período em µs inteiros. ≥ 100 Hz: ticks de 95 ns (84 MHz / 8). A interface replica esse arredondamento (`actual_mod_freq`). |
| Sincronismo | **PB0** = estado da modulação (1 = ligado) |
| Estado inicial | 5 Hz, 0,4 % |

> Acima de ~1 kHz cada meio período tem poucos ciclos da portadora de 5 kHz (a 1 kHz são 2,5 ciclos). Para modulações altas, prefira PWM = 100 %, que deixa o laser contínuo dentro do meio período ligado.

### Canal óptico: ADC1 + TIM3 + DMA2

| Parâmetro | Valor |
|---|---|
| Entrada | **PA0** (ADC1_IN0), 12 bits, tempo de amostragem de 84 ciclos (4 µs) |
| Gatilho | TRGO do **TIM3** a **200 kHz** (84 MHz / 420) |
| Transferência | **DMA2 Stream0 Canal 0**, circular, interrupção a cada meia janela de 64 amostras (prioridade 1) |
| Oversampling | OSR = 16 (`OVS_BITS = 2`): soma de 16 amostras >> 2 |
| Taxa de saída | **12 500 amostras/s** |
| Resolução efetiva | **14 bits**, de 0 a 16 380 (≈ 0,2 mV/LSB com 3,3 V) |
| Referência | O estado do laser é registrado na mesma grade de amostras do ADC. O bit REF do quadro é a maioria dos 16 sub-quadros. |
| Buffer | Anel de 4096 quadros. Se o PC atrasar, os quadros novos são descartados. |

Parâmetros ajustáveis no topo do `main.cpp`: `OVS_BITS`, `FS_HZ` e `LASER_PWM_HZ`. Os `static_assert` impedem uma taxa de ADC acima de 200 kHz ou que não divida 84 MHz. **Se mudar `FS_HZ` ou `OVS_BITS`, mude também `FS` e `ADC_FULL_SCALE` no Python.**

### Canal acústico: I2S2 + DMA1

| Parâmetro | Valor |
|---|---|
| Periférico | SPI2 em modo **I2S mestre RX**, padrão **Philips** |
| Pinos | PB13 = CK, PB12 = WS, PB15 = SD (AF5) |
| Formato | Dados de **24 bits** em quadro de 64 bits (2 × 32), só o slot **esquerdo** |
| Taxa | Nominal de 32 kHz. **Real = 86 MHz / (64 × 42) = 31 994,05 Hz** (−186 ppm). A interface usa a taxa real. |
| BCLK | ≈ 2,048 MHz |
| Transferência | **DMA1 Stream3 Canal 0**, circular, interrupção a cada 256 quadros (prioridade 2) |
| Buffer | Anel de 4096 amostras. Se o PC atrasar, as amostras mais antigas são sobrescritas (o número de sequência mostra a lacuna). |

### Sincronização de fase entre os dois canais

Quando a frequência muda (comando `F`), o TIM4 é configurado e fica **parado**. Na **próxima interrupção do DMA do I2S**, o firmware espera, com as interrupções bloqueadas, o DMA começar um quadro I2S novo e liga o TIM4 nesse instante (espera máxima de ~40 µs). O número desse quadro, calculado pelo `NDTR` do DMA, é enviado ao PC no **marcador de modulação**. Assim a latência da interrupção não entra na fase. O lock-in do INMP441 usa esse número como origem de fase, então as fases do OPT101 e do INMP441 ficam na mesma referência (borda de subida do laser).

> Até a versão de 23/10/2026, o marcador supunha que a partida era na fronteira de meio buffer. Na prática ela acontecia ~3 quadros (≈ 100 µs) depois, porque a ISR primeiro copia as 256 amostras. As calibrações do microfone feitas antes dessa data incluem esse atraso no `td` e devem ser refeitas.

### Prioridades de interrupção

| IRQ | Prioridade | Motivo |
|---|---|---|
| TIM4 (modulação) | 0 | Borda do laser sem jitter |
| DMA2 Stream0 (ADC) | 1 | — |
| DMA1 Stream3 (I2S) | 2 | — |
| USB | padrão do STM32duino | — |

A cópia do anel de áudio no `loop()` bloqueia só as prioridades ≥ 2 (`BASEPRI`), não todas as interrupções. Assim a borda do laser (TIM4) não sofre atraso durante a cópia.

## Protocolo USB (STM32 → PC)

Um único fluxo de bytes pelo USB CDC (o baud rate é ignorado). Cada `write` junta até 1000 quadros ópticos, um marcador opcional e até 3 pacotes de áudio. O canal óptico tem prioridade: perder quadros ópticos atrapalha o PLL do lock-in.

**Quadro óptico (5 bytes)**, 12 500 por segundo (62,5 kB/s):

| Byte | 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| Conteúdo | `0x55` | `0xAA` | ADC_L | ADC_H | REF (0/1) |

**Pacote de áudio (780 bytes)**, ≈125 por segundo (≈97,5 kB/s):

| Bytes | Conteúdo |
|---|---|
| 0–3 | `A5 5A 49 32` (“I2”) |
| 4–7 | SEQ: número da 1ª amostra (uint32, little-endian) |
| 8–9 | N amostras (uint16, = 256) |
| 10 … 10+3N−1 | Amostras PCM com sinal de 24 bits, little-endian |
| últimos 2 | CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) dos bytes 4 até o fim das amostras |

**Marcador de modulação (10 bytes)**, enviado a cada partida da modulação:

| Bytes | Conteúdo |
|---|---|
| 0–3 | `A5 5A 4D 4B` (“MK”) |
| 4–7 | SEQ da amostra I2S na borda de subida (uint32 LE) |
| 8–9 | CRC-16/CCITT-FALSE dos bytes 4–7 |

Banda total ≈ 160 kB/s. Com a porta fechada no PC, o firmware descarta os dados e não trava.

## Comandos (PC → STM32)

Texto ASCII terminado em `\n` (o `\r` é ignorado). Até 23 caracteres. Comandos inválidos são ignorados em silêncio.

| Comando | Faixa | Efeito |
|---|---|---|
| `F<hz>` | `0` ou `0.1`–`5000` | Frequência da modulação. `F0` = contínuo. Reinicia a onda quadrada e envia um novo marcador. |
| `P<pct>` | `0`–`100` | Potência (duty do PWM), resolução de 0,1 %. |

Exemplos: `F5\n`, `F137.5\n`, `P40\n`. A interface manda `F` e `P` toda vez que conecta.
