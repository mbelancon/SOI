# 2. Hardware and wiring

## Black Pill pinout

| Pin | STM32 function | Connected to | Direction |
|---|---|---|---|
| **PA0** | ADC1_IN0 (analog) | **OPT101** output (Vout) | input |
| **PA8** | TIM1_CH1 (5 kHz PWM) | **Laser driver** input | output |
| **PB0** | GPIO (laser state, 0/1) | Oscilloscope (sync), optional | output |
| **PB12** | I2S2_WS | INMP441 **WS** | output |
| **PB13** | I2S2_CK | INMP441 **SCK** | output |
| **PB15** | I2S2_SD | INMP441 **SD** | input |
| PA11 / PA12 | USB D− / D+ | Board USB-C connector | — |
| PA13 / PA14 | SWDIO / SWCLK | ST-Link | — |
| 3V3 / GND | Power | INMP441, ground references | — |

All logic signals are **3.3 V**.

> **Note:** the "D12/D13/D15" Arduino silkscreen names are **not** the I2S pins, and D12 is used by USB. Use the names **PB12, PB13 and PB15**.

## INMP441

| INMP441 | Black Pill |
|---|---|
| VDD | 3V3 |
| GND | GND |
| SCK | PB13 |
| WS | PB12 |
| SD | PB15 |
| L/R | **GND** (left channel; the firmware only reads the left slot) |

- Keep wires short (BCLK ≈ 2.05 MHz). If CRC errors appear in the INMP441 status bar, shorten the wires or improve the ground.
- With L/R tied to 3V3, the microphone transmits in the right slot and the interface receives only zeros.

## OPT101

Typical OPT101 (DIP-8) wiring with the internal 1 MΩ resistor:

| OPT101 | Connection |
|---|---|
| Pin 1 (V+) | Supply ⚠ (see warning below) |
| Pin 3 (−V) | GND |
| Pin 8 (Common) | GND |
| Pin 4 (1 MΩ) ↔ Pin 5 (Output) | Jumper between them (internal 1 MΩ feedback) |
| Pin 5 (Output) | **PA0** |

⚠ **Confirm and document the actual assembly here** (supply voltage, external resistor/capacitor, RC filter on the output).

> **Watch the ADC range:** the STM32 ADC reads 0 to 3.3 V, and PA0 in analog mode does **not** tolerate 5 V. With the OPT101 powered from 5 V, the output can exceed 3.3 V under strong light. Use a resistive divider or limit the laser power. The interface shows **"SATURAÇÃO DO ADC"** (ADC saturation) when the signal reaches full scale.

The firmware uses a long ADC sampling time (84 cycles ≈ 4 µs) to tolerate higher-impedance sources, such as an RC filter on the OPT101 output.

## Laser

- **PA8** generates a **5 kHz** PWM with 0 to 100 % duty (0.1 % steps). This is the power control ("PWM (%)" in the interface).
- The lock-in modulation is a **50 % square wave** that switches this PWM on and off: in the "on" half-period PA8 outputs the chosen duty, and in the "off" half-period it outputs 0.
- PA8 only delivers a 3.3 V logic signal and a few mA. Always use a **driver** (transistor/MOSFET or the TTL input of a laser driver). ⚠ Document the driver used.
- **PB0** mirrors the modulation state (1 = laser on). Use this pin as the oscilloscope trigger.

## ST-Link programmer

| ST-Link | Black Pill (SWD header) |
|---|---|
| SWDIO | DIO (PA13) |
| SWCLK | CLK (PA14) |
| GND | GND |
| 3.3V | 3V3 (optional, if the board is not on USB) |

## Wiring diagram

```
                    ┌──────────────────────────┐
   OPT101 Vout ────►│ PA0                  3V3 │────► INMP441 VDD
                    │                      GND │────► INMP441 GND, L/R ; OPT101 GND
 Laser driver ◄─────│ PA8                 PB13 │────► INMP441 SCK
 Oscilloscope ◄─────│ PB0                 PB12 │────► INMP441 WS
                    │                     PB15 │◄──── INMP441 SD
                    │   STM32F401 Black Pill   │
                    │  SWD: DIO CLK GND 3V3    │◄──── ST-Link
                    │         USB-C            │◄───► PC
                    └──────────────────────────┘
```
