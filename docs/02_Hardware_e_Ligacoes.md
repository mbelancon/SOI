# 2. Hardware e ligações

## Pinagem usada na Black Pill

| Pino | Função no STM32 | Ligado a | Direção |
|---|---|---|---|
| **PA0** | ADC1_IN0 (analógico) | Saída do **OPT101** (Vout) | entrada |
| **PA8** | TIM1_CH1 (PWM 5 kHz) | Entrada do **driver do laser** | saída |
| **PB0** | GPIO (estado do laser, 0/1) | Osciloscópio (sincronismo), opcional | saída |
| **PB12** | I2S2_WS | INMP441 **WS** | saída |
| **PB13** | I2S2_CK | INMP441 **SCK** | saída |
| **PB15** | I2S2_SD | INMP441 **SD** | entrada |
| PA11 / PA12 | USB D− / D+ | Conector USB-C da placa | — |
| PA13 / PA14 | SWDIO / SWCLK | ST-Link | — |
| 3V3 / GND | Alimentação | INMP441, referências de terra | — |

Todos os sinais lógicos são de **3,3 V**.

> **Atenção:** os nomes "D12/D13/D15" da serigrafia Arduino **não** são os pinos I2S, e o D12 é usado pelo USB. Use os nomes **PB12, PB13 e PB15**.

## INMP441

| INMP441 | Black Pill |
|---|---|
| VDD | 3V3 |
| GND | GND |
| SCK | PB13 |
| WS | PB12 |
| SD | PB15 |
| L/R | **GND** (canal esquerdo; o firmware só lê o slot esquerdo) |

- Fios curtos (BCLK ≈ 2,05 MHz). Se aparecerem erros de CRC na barra de status do INMP441, encurte os fios ou reforce o GND.
- Com L/R ligado ao 3V3, o microfone passa a transmitir no slot direito e a interface recebe só zeros.

## OPT101

Ligação típica do OPT101 (DIP-8) com o resistor interno de 1 MΩ:

| OPT101 | Ligação |
|---|---|
| Pino 1 (V+) | Alimentação ⚠ (ver aviso abaixo) |
| Pino 3 (−V) | GND |
| Pino 8 (Comum) | GND |
| Pino 4 (1 MΩ) ↔ Pino 5 (Saída) | Jumper entre os dois (realimentação interna de 1 MΩ) |
| Pino 5 (Saída) | **PA0** |

⚠ **Confirme e documente aqui a montagem real** (tensão de alimentação, resistor/capacitor externo, filtro RC na saída).

> **Cuidado com a faixa do ADC:** o ADC do STM32 lê de 0 a 3,3 V, e o PA0 em modo analógico **não** tolera 5 V. Com o OPT101 alimentado em 5 V, a saída pode passar de 3,3 V em luz forte. Use um divisor resistivo ou limite a potência do laser. A interface avisa **"SATURAÇÃO DO ADC"** quando o sinal chega ao fundo de escala.

O firmware usa um tempo de amostragem longo no ADC (84 ciclos ≈ 4 µs) para tolerar fontes de impedância mais alta, como um filtro RC na saída do OPT101.

## Laser

- O **PA8** gera um PWM de **5 kHz** com duty de 0 a 100 % (passos de 0,1 %). É o controle de potência ("PWM (%)" na interface).
- A modulação lock-in é uma **onda quadrada de 50 %** que liga e desliga esse PWM: no meio período "ligado" o PA8 sai com o duty escolhido e no meio período "desligado" sai em 0.
- O PA8 entrega só sinal lógico de 3,3 V e poucos mA. Use sempre um **driver** (transistor/MOSFET ou a entrada TTL de um driver de laser). ⚠ Documente o driver usado.
- O **PB0** repete o estado da modulação (1 = laser ligado). Use esse pino no osciloscópio como gatilho.

## Gravador ST-Link

| ST-Link | Black Pill (conector SWD) |
|---|---|
| SWDIO | DIO (PA13) |
| SWCLK | CLK (PA14) |
| GND | GND |
| 3.3V | 3V3 (opcional, se a placa não estiver no USB) |

## Diagrama de ligações

```
                    ┌──────────────────────────┐
   OPT101 Vout ────►│ PA0                  3V3 │────► INMP441 VDD
                    │                      GND │────► INMP441 GND, L/R ; OPT101 GND
 Driver laser ◄─────│ PA8                 PB13 │────► INMP441 SCK
 Osciloscópio ◄─────│ PB0                 PB12 │────► INMP441 WS
                    │                     PB15 │◄──── INMP441 SD
                    │   STM32F401 Black Pill   │
                    │  SWD: DIO CLK GND 3V3    │◄──── ST-Link
                    │         USB-C            │◄───► PC
                    └──────────────────────────┘
```
