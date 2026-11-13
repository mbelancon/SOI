# 3. Firmware do STM32

Código: [`firmware/src/main.c`](../firmware/src/main.c). Projeto PlatformIO com o framework **STM32Cube** (HAL da ST), sem o STM32duino. O USB usa a biblioteca USB Device da ST (V2.11.6, copiada em `firmware/src/usb`, licença em `src/usb/LICENSE.md`).

A partir da versão 2.0.0 o firmware **não faz sobreamostragem**: ele envia todas as amostras do ADC (12 bits, 200 kS/s) com o estado do laser em cada uma, e a interface tira a média do número de amostras escolhido (ver [Interface](04_Interface.md#sobreamostragem)). Assim o firmware fica sempre o mesmo e a sobreamostragem muda sem regravar a placa.

> Por que sair do STM32duino: o USB CDC dele travava em ~190 kB/s na Black Pill. Com a pilha da ST, transferências longas e buffer duplo, o mesmo hardware chegou a ~1,1 MB/s sem perdas (teste de 05/11/2026). O fluxo da 2.0.0 é de ~550 kB/s, metade disso.

## Configuração do PlatformIO

```ini
[env:blackpill_f401cc]
platform = ststm32
board = blackpill_f401cc
framework = stm32cube
upload_protocol = stlink
build_flags =
    -O2
    -Wall
    -I src/usb/Core/Inc
    -I src/usb/Class/CDC/Inc
```

## Gravação

1. Ligue o ST-Link aos pinos SWD da Black Pill ([ligações](02_Hardware_e_Ligacoes.md#gravador-st-link)).
2. No VS Code, abra a pasta `firmware/` com o PlatformIO.
3. Clique em **Upload** (ou rode `pio run -t upload` dentro de `firmware/`). Na primeira vez o PlatformIO baixa o pacote `framework-stm32cubef4`.
4. Desligue o ST-Link (opcional) e conecte a placa pelo USB-C. Deve aparecer uma porta COM "Dispositivo serial USB" (VID 0483, PID 5740).

## Relógios

| Domínio | Frequência | Origem |
|---|---|---|
| HSE (cristal) | 25 MHz | Placa WeAct |
| SYSCLK / HCLK | 84 MHz | PLL principal (25 MHz / 25 × 336 / 4) |
| Timers APB1 (TIM3, TIM4) | 84 MHz | APB1 × 2 |
| Timer APB2 (TIM1) | 84 MHz | APB2 |
| ADC | 21 MHz | PCLK2 / 4 |
| PLLI2S → I2SCLK | 76,8 MHz | 25 MHz / **M=25** × **N=384** / **R=5** |
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
| Resolução da modulação | < 100 Hz: meio período em µs inteiros. ≥ 100 Hz: ticks de 95 ns (84 MHz / 8). São os mesmos arredondamentos da 1.0.0, e a interface os replica (`actual_mod_freq`). |
| Sincronismo | **PB0** = estado da modulação (1 = ligado) |
| Estado inicial | 5 Hz, 0,4 % |

> Acima de ~1 kHz cada meio período tem poucos ciclos da portadora de 5 kHz (a 1 kHz são 2,5 ciclos). Para modulações altas, prefira PWM = 100 %, que deixa o laser contínuo dentro do meio período ligado.

### Canal óptico: ADC1 + TIM3 + DMA2

| Parâmetro | Valor |
|---|---|
| Entrada | **PA0** (ADC1_IN0), 12 bits, tempo de amostragem de 84 ciclos (4 µs) |
| Gatilho | TRGO do **TIM3** a **200 kHz** (84 MHz / 420) |
| Transferência | **DMA2 Stream0 Canal 0**, circular, interrupção a cada meia janela de 512 amostras (2,56 ms, prioridade 1) |
| Sobreamostragem | **Nenhuma no firmware.** Cada amostra vai crua ao PC (12 bits, 0 a 4095) |
| Taxa de saída | **200 000 amostras/s** (400 kB/s) |
| Referência | O estado do laser é registrado na mesma grade de amostras do ADC (bit 15 de cada palavra) |
| Buffer | Anel de 8192 amostras (41 ms). Se o PC atrasar, as mais antigas são descartadas e o salto do SEQ avisa a interface. |

Parâmetros no topo do `main.c`: `ADC_RATE_HZ` e `LASER_PWM_HZ`. O `_Static_assert` exige que a taxa do ADC divida 84 MHz. **Se mudar `ADC_RATE_HZ`, mude também `RAW_FS` no Python.**

### Canal acústico: I2S2 + DMA1

| Parâmetro | Valor |
|---|---|
| Periférico | SPI2 em modo **I2S mestre RX**, padrão **Philips** |
| Pinos | PB13 = CK, PB12 = WS, PB15 = SD (AF5) |
| Formato | Dados de **24 bits** em quadro de 64 bits (2 × 32), só o slot **esquerdo** |
| Taxa | **48 kHz exatos**: 76,8 MHz / (64 × 25), com I2SDIV = 12 e ODD = 1. (Até a 1.0.0 eram 31 994,05 Hz, −186 ppm.) |
| BCLK | 3,072 MHz |
| Transferência | **DMA1 Stream3 Canal 0**, circular, interrupção a cada 256 quadros (5,3 ms, prioridade 2) |
| Buffer | Anel de 2048 amostras (43 ms). Se o PC atrasar, as amostras mais antigas são sobrescritas (o número de sequência mostra a lacuna). |

### Sincronização de fase entre os dois canais

Quando a frequência muda (comando `F`), o TIM4 é configurado e fica **parado**. Na **próxima interrupção do DMA do I2S**, o firmware espera, com as interrupções bloqueadas, o DMA começar um quadro I2S novo e liga o TIM4 nesse instante (espera máxima de ~40 µs). O número desse quadro, calculado pelo `NDTR` do DMA, é enviado ao PC no **marcador de modulação**. Assim a latência da interrupção não entra na fase. O lock-in do INMP441 usa esse número como origem de fase, então as fases do OPT101 e do INMP441 ficam na mesma referência (borda de subida do laser).

> Até a versão de 23/10/2026, o marcador supunha que a partida era na fronteira de meio buffer. Na prática ela acontecia ~3 quadros (≈ 100 µs) depois, porque a ISR primeiro copia as 256 amostras. As calibrações do microfone feitas antes dessa data incluem esse atraso no `td` e devem ser refeitas.

### Prioridades de interrupção

| IRQ | Prioridade | Motivo |
|---|---|---|
| TIM4 (modulação) | 0 | Borda do laser sem jitter |
| DMA2 Stream0 (ADC) | 1 | — |
| DMA1 Stream3 (I2S) | 2 | — |
| USB (OTG_FS) | 3 | Abaixo de todas as que marcam tempo |

A cópia do anel de áudio no laço principal bloqueia só as prioridades ≥ 2 (`BASEPRI`), não todas as interrupções. Assim a borda do laser (TIM4) não sofre atraso durante a cópia.

## Protocolo USB (STM32 → PC)

Um único fluxo de bytes pelo USB CDC (o baud rate é ignorado). O laço principal monta pacotes num de dois buffers de 6 KB enquanto o outro é enviado. O canal óptico tem prioridade: perder amostras ópticas atrapalha o PLL do lock-in. Tudo é little-endian, e o CRC é o CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) dos bytes entre o cabeçalho de 4 bytes e o próprio CRC.

> O protocolo mudou na 2.0.0 (os quadros `55 AA` de 5 bytes deixaram de existir). Firmware e interface precisam ser da mesma versão maior.

**Pacote óptico (até 1036 bytes)**, ≈390 por segundo (≈400 kB/s):

| Bytes | Conteúdo |
|---|---|
| 0–3 | `A5 5A 4F 50` (“OP”) |
| 4–7 | SEQ: número absoluto da 1ª amostra desde a partida (uint32). Um salto indica amostras perdidas. |
| 8–9 | N amostras (uint16, de 64 a 512) |
| 10 … 10+2N−1 | N palavras uint16: bits 0–11 = ADC, bit 15 = laser (1 = ligado), bits 12–14 = 0 |
| últimos 2 | CRC16 |

**Pacote de áudio (780 bytes)**, 187,5 por segundo (≈146 kB/s):

| Bytes | Conteúdo |
|---|---|
| 0–3 | `A5 5A 49 32` (“I2”) |
| 4–7 | SEQ: número da 1ª amostra (uint32) |
| 8–9 | N amostras (uint16, = 256) |
| 10 … 10+3N−1 | Amostras PCM com sinal de 24 bits |
| últimos 2 | CRC16 |

**Marcador de modulação (10 bytes)**, enviado a cada partida da modulação:

| Bytes | Conteúdo |
|---|---|
| 0–3 | `A5 5A 4D 4B` (“MK”) |
| 4–7 | SEQ da amostra I2S na borda de subida (uint32) |
| 8–9 | CRC16 dos bytes 4–7 |

Banda total ≈ 550 kB/s, metade do que o USB FS entregou no teste. Com a porta fechada no PC (DTR desligado), o firmware descarta os dados e não trava.

## Comandos (PC → STM32)

Texto ASCII terminado em `\n` (o `\r` é ignorado). Até 23 caracteres. Comandos inválidos são ignorados em silêncio.

| Comando | Faixa | Efeito |
|---|---|---|
| `F<hz>` | `0` ou `0.1`–`5000` | Frequência da modulação. `F0` = contínuo. Reinicia a onda quadrada e envia um novo marcador. |
| `P<pct>` | `0`–`100` | Potência (duty do PWM), resolução de 0,1 %. |

Exemplos: `F5\n`, `F137.5\n`, `P40\n`. A interface manda `F` e `P` toda vez que conecta.
