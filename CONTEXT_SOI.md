# CONTEXT — SOI Controller

File for Claude (and for anyone working on the code). Short and up to date; the README is for users.

## Goal
An STM32 as an "oscilloscope with extra functions" for low-cost photothermal and photoacoustic techniques
(photoacoustics, thermal lens/mirror, mirage effect, z-scan, time-resolved luminescence)
with cheap diode lasers, without commercial lock-in amplifiers or choppers. Target: a small, portable system.

## Hardware
- WeAct Black Pill STM32F401CCU6 (25 MHz crystal), USB-C CDC (VID 0483 / PID 5740)
- OPT101 → PA0 (ADC, 0–3.3 V input only)
- INMP441 (I2S): SCK PB13, WS PB12, SD PB15
- Laser modulation: PWM on PA8 (always through a driver); sync on PB0
- Photoacoustic cell in use (Nov 2026): cylinder 2 cm high × 5 mm diameter, ~1 mm through-hole at mid-height
  (INMP441 with o-rings on one side, equalization hole on the other, closed during measurements),
  1 mm microscope-slide window, 532 nm laser. Helmholtz resonance ~1.4–1.6 kHz, depends on sample height.

## Layout
- `firmware/` — STM32Cube (ST HAL + ST USB Device library in `src/usb`), PlatformIO with `framework = stm32cube`.
  `src/main.c`; raw OPT101 at 200 kS/s with the laser state in bit 15, INMP441 at exactly 48 kHz.
  Prebuilt binary in `binarios/soi_firmware_vX.Y.Z.bin`.
- `interface/soi_controller.py` — PySide6/PyQt + pyqtgraph, software lock-in, simulated mode, icons in `interface/icones/`.
  `interface/soi_i18n.py` — language choice and the Portuguese→English table; the code keeps Portuguese strings and
  `install()` translates only what Qt/pyqtgraph show. New UI text: add it to `EN` (fixed pieces for f-strings).
- `docs/01..06` — materials, wiring, firmware, interface, components, performance (English). `docs/tests/` — test procedures per version.
- `packaging/` + `.github/workflows` — Windows executable (PyInstaller) attached to Releases.

## Conventions
- Firmware and interface share the version number (semver; CHANGELOG in Keep a Changelog format).
  `__version__` in the interface (window title), `FIRMWARE_VERSION` in `main.c`. A MAJOR change = USB protocol change.
- The interface finds the port by itself (VID/PID); always keep simulated mode working.
- STM32 firmware: always STM32Cube (HAL/LL), never Arduino/STM32duino, unless explicitly requested.
- Data files keep Portuguese names, column names and header keys (`Medidas/`, `CAL_*microfone_*.csv`,
  `Frequencia_Hz`, `# Celula = …`) whatever the interface language, so old files keep loading.
- Documentation in English. Interface: Portuguese and English, chosen from the Windows display language
  (`SOI_LANG=pt|en` forces one).
- Test interface changes headless (`QT_QPA_PLATFORM=offscreen`, patch `find_arduino_port` to return no port,
  tick simulated mode) and check screenshots before handing them over.

## State (2026-11-13)
- v1.0.0 published 2026-10-27 (STM32duino firmware).
- 2.0.0 (STM32Cube firmware, new USB protocol, OSR 1–64 in the interface, 48 kHz audio, Resolution test) and
  2.1.0 (interface: calibration references, cell diagram, two-reference verification, resonance fit and refinement,
  Diagnostics, reorganized Dual Mode with Sweep / Calibration / Fit, "Range with S ∝ f⁻ⁿ" model,
  "Generate calibration curve") go to `main` through PR #4. Tags/Releases v2.0.0 and v2.1.0 are created by hand after the merge.
- Calibration (chamber): M(f) = S(f)·fⁿ of the reference, normalized by the flat range; verification with a second,
  different reference (|Δn| ≤ 0.15, ≤ 1.5 dB rms, phase ± 10° rms over ≥ 1 decade). Recommended: carbon black to
  generate, black tape to verify.
- This interface is the style reference for QuadPV and TipGas.

## Open issues / ideas
- All sweeps since 2026-11-05 show n ≈ 0 instead of the expected 1–1.5. Main hypothesis: air leak in the cell
  (high-pass ~1 kHz). Next: seal o-rings, window and side hole with silicone grease, reassemble, repeat.
- Pending ⚠ items in docs/01 and docs/02: laser driver, OPT101 supply, cell description.
- Input limited to 0–3.3 V (consider signal conditioning).
- HP 34401A tab (RS-232/SCPI, own port, auto-detect via `*IDN?`) — idea, not started.
- Test the Hamamatsu L9456-01 flash lamp (triggered by the STM32), then read the pulses with the OPT101 at ~200 kS/s.
