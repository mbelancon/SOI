# Components of the photoacoustic lock-in system

## Microcontroller

A microcontroller is a complete computer in a single integrated circuit. The same chip holds the processor, program memory (flash), data memory (RAM) and several peripherals: analog-to-digital converters (ADC), timers, DMA controllers and communication interfaces (USB, I2S, SPI, UART). A personal computer runs a general-purpose operating system, subject to unpredictable delays. A microcontroller runs a single dedicated program with deterministic timing on the nanosecond scale. That makes it suitable for generating control signals and sampling sensors at strictly defined instants. In this system, the microcontroller modulates the laser, samples both sensors in sync and sends the data to the computer, which does the numerical processing (lock-in) and the display.

## STM32F401 "Black Pill"

The Black Pill board uses the STM32F401CCU6, which has an 84 MHz ARM Cortex-M4 core with a floating-point unit and DSP instructions. It has 256 KB of flash and 64 KB of RAM. The board costs a few dollars and is programmed with open tools (PlatformIO with the STM32Cube framework, ST HAL). For this project, the decisive features are:

- **12-bit ADC up to 2.4 MS/s**, triggered by a timer and read by **DMA**. Samples are collected without CPU intervention and without jitter. The firmware sends the raw 200 kS/s, and the interface applies the chosen oversampling (default: average of 16 samples, **12.5 kS/s**, 14-bit scale).
- **I2S interface with a dedicated PLL**, which reads the digital microphone at 48 kS/s with 24 bits. The ADC and I2S clocks come from the same crystal, so both channels share a common time base. This makes it possible to compare their phases.
- **Advanced timers**, which generate the laser power PWM (5 kHz, 0.1 % steps) and the modulation square wave (0.1 to 5000 Hz, 95 ns resolution).
- **Native USB 2.0 Full Speed (12 Mbit/s)**, which carries both streams (≈550 kB/s) without an external converter.

## OPT101: optical reference

The OPT101 (Texas Instruments) integrates in one package a 2.29 × 2.29 mm photodiode and a transimpedance amplifier with an internal 1 MΩ feedback resistor. The integration removes the capacitance and noise pickup of the wiring between photodiode and amplifier, which are the main error sources in discrete builds. Typical datasheet characteristics:

- **Linearity:** ±0.01 % of full-scale nonlinearity. The output voltage is proportional to the incident optical power, so the OPT101 can be used as an intensity reference to normalize the acoustic signal.
- **Speed:** 14 kHz bandwidth with the 1 MΩ gain, far above the modulation frequencies used.
- **Sensitivity:** 0.45 A/W responsivity at 650 nm, i.e. 0.45 V/µW with the internal resistor. The spectral response spans ~300 to 1100 nm.
- **Simplicity:** single 2.7 to 36 V supply and 120 µA consumption. The analog output goes straight to the ADC.

## INMP441: photoacoustic detection

The INMP441 (TDK InvenSense) is an omnidirectional MEMS microphone that contains the transducer, preamplifier, sigma-delta converter and anti-aliasing filter. Its output is digital, I2S, 24 bits. Because the signal leaves the package already digitized, it is immune to electromagnetic interference and to attenuation along the wires to the microcontroller. Typical datasheet characteristics:

- **Accuracy:** 61 dBA SNR, −26 dBFS sensitivity at 94 dB SPL with ±1 dB unit-to-unit tolerance, and −75 dBFS power-supply noise rejection.
- **Dynamic range:** acoustic overload point at 120 dB SPL.
- **Frequency response:** flat from ~60 Hz to 15 kHz. Below 60 Hz there is a high-pass roll-off; the response of the microphone plus cell is corrected by calibration against a reference sample.
- **Integration:** 1.8 to 3.3 V supply, 1.4 mA consumption and a size of a few millimeters, which makes it easy to fit inside the photoacoustic cell.

## Summary

| | STM32 Black Pill | OPT101 | INMP441 |
|---|---|---|---|
| Role | Control, sync and acquisition | Measures the laser intensity | Measures the photoacoustic signal |
| Speed | 84 MHz; ADC up to 2.4 MS/s | 14 kHz bandwidth | 48 kS/s; bandwidth up to 15 kHz |
| Resolution in the system | 14 bits (optical, default) and 24 bits (audio) | 14 bits via ADC | Native 24 bits |
| Linearity / accuracy | Common time base for both channels | ±0.01 % FS | 61 dBA SNR, ±1 dB |
| Main advantage | Low cost; native DMA, I2S and USB | Integrated photodiode and amplifier | Digital output immune to interference |

Together, the three components form a compact, low-cost system. Lock-in demodulation is done in software and recovers, in amplitude and phase, signals far smaller than the noise, over a modulation range from 0.1 Hz to a few kilohertz.
