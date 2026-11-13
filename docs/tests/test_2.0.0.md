# SOI 2.0.0: test procedure

Firmware and interface 2.0.0 go together: the USB protocol changed, so firmware 1.0.0 does not work with this interface (and vice versa).

## 1. Flash the firmware

- PlatformIO: open the `firmware/` folder and Upload. If Windows blocks `pio.exe`, use
  `%USERPROFILE%\.platformio\penv\Scripts\python.exe -m platformio run -t upload` inside `firmware/`.
  The first time, PlatformIO downloads `framework-stm32cubef4`.
- Or flash `binarios/soi_firmware_v2.0.0.bin` at address **0x08000000** (STM32CubeProgrammer or PlatformIO).
- The device shows up as "SOI OPT101/INMP441 (STM32F401)", VID 0483, PID 5740.
- To go back to the old firmware, flash a backup of the previous flash contents at 0x08000000.

## 2. Open the interface

`python interface/soi_controller.py` (same dependencies as 1.0.0). The title should read **SOI Controller 2.x**.

## 3. What to check

1. OPT101 status bar: "12.5 kS/s (OSR 16)" and **no** red "USB losses" warning after a few minutes.
2. Change **Oversampling** from 16x to 1x, 4x and 64x: the oscilloscope and lock-in should stay smooth, and the lock-in R should stay the same (the amplitude correction follows the OSR).
3. With OSR 1 (200 kS/s), look at the laser edges in the oscilloscope and in Average mode (5 µs step).
4. **Resolution test**: laser at PWM 0 % (or constant light), Measure for 4 s. See up to which N the points follow the 1/√N line, and look at the code histogram. Save the CSV/PNG. Repeat with another OPT101 gain to compare, if you like.
5. INMP441 tab: status at 48 kHz, lock-in and FFT working; the INMP441 phase should be stable (it no longer rotates over time).
6. A short frequency sweep in Dual Mode, to check that nothing changed in the results.

Note any loss, freeze or odd value.
