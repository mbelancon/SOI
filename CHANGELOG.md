# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [semantic versioning](https://semver.org/): MAJOR.MINOR.PATCH.

- **MAJOR:** incompatible change, for example in the serial protocol between firmware and interface.
- **MINOR:** new feature that does not break what already existed.
- **PATCH:** bug fix.

The interface and the firmware share the same version number. It appears in `__version__` (interface, window title) and in `FIRMWARE_VERSION` (firmware). Each published version gets a `vX.Y.Z` tag on GitHub.

## [Unreleased]

## [2.1.0] - 2026-11-13

Minor version: only the interface changes. The firmware is still 2.0.0 (`binarios/soi_firmware_v2.0.0.bin`) and the USB protocol is the same. Old calibrations and sweeps still open.

### Interface (`interface/soi_controller.py`)

#### Bilingual interface
- **Portuguese and English**, chosen automatically from the Windows display language (Portuguese if Windows is in Portuguese, English otherwise). `SOI_LANG=pt` or `SOI_LANG=en` forces one. Data file names, CSV columns and header keys stay in Portuguese in both languages, so files are compatible. The translation table is in `interface/soi_i18n.py`.

#### Reorganized Dual Mode (2026-11-13; replaces the arrangement described under "Changed" below)
- **Top of the tab:** three buttons, in working order: **Sweep ▸** (frequency sweep; the matched PWM sweep is under "Matched PWM ▸"), **Calibration ▸** and **Fit ▸**. Calibration no longer repeats the sweep or the fits.
- **Calibration without "Fit standard":** M(f) = S·fⁿ with the reference's n, normalized by the system's flat range; the reference phase is the mean Δφ over the same range. The panel shows only the reference, one line of instructions and the **Generate calibration curve**, **Verify with this measurement** and **Advanced** buttons.
- **New Fit model, "Range with S ∝ f⁻ⁿ"**: given the sample's expected n, finds the widest continuous range where a free fit gives |n − expected n| ≤ 0.15, deviation ≤ 1.5 dB rms and constant phase (± 10° rms). The range is shaded on both plots.
- **Verification:** with the calibration applied, the second reference must follow f⁻ⁿ (same criteria) over at least one decade.
- **Layout:** the calibration panel no longer leaves an empty grey area (its height follows the panel's real width and readjusts when the window is resized) and the cell diagram is smaller. In the INMP441 tab, the **Sweeps ▸** button moved to the start of the Display row.
- "Save calibration" was renamed **Generate calibration curve**.

#### Added
- **Microphone calibration references** ("Microphone calibration" panel, Dual Mode tab): thin Al foil (OPC mode, S ∝ f⁻¹·⁵), thick Al inside the chamber, thin Al foil inside the chamber (on an insulating backing), carbon black (recommended) and matte black tape, kept separate so one can check the other, matte black painted Al (f⁻¹ above ~100 Hz; below, the paint lets heat reach the Al) (all in the chamber, S ∝ f⁻¹, Rosencwaig–Gersho), and Custom (S ∝ f⁻ⁿ). Editable thickness, diffusivity or n, with the expected curve, μ = √(α/πf) and the thin-foil limit f₁ = α/(πL²).
- **"Cell: OPC | Chamber" selector** on the top row. The reference selects the cell; the calibration records its cell and the interface warns if it is used in the other. Dual Mode CSVs record `# Celula = …`.
- **Mounting diagram** next to the reference: a generic drawing showing whether the sample closes the cell (OPC) or sits inside, under the glass window, with the air gap, plus mounting tips.
- **Behaviour check** after "Fit standard": exponent n compared with the expected one (±0.15), constant phase after removing fc and td (±15°) and a reliable range of at least one decade. Later turned into information (orange note): in the chamber the system response enters the shape, and verification moved to the second reference. Every new calibration starts as not verified (⚠ in the list, in the PNG and whenever it is used).
- Theoretical curve of the reference (dotted grey) on the plot.
- **Cell resonance fit** in "Fit with models": damped oscillator + complex background with delay, on magnitude and phase. Automatic peak or "Mark peak (2 clicks)". Shows f₀, Q, width f₀/Q and peak gain over background, with uncertainties.
- **No PC sleep during measurements (Windows):** sweeps and the Resolution test prevent sleep and hibernation due to inactivity (`SetThreadExecutionState`) and release it at the end. Before, a long sweep was interrupted when the PC went to sleep.
- **"Normalize by OPT101"** (Dual Mode, frequency sweep): turns on or off the division by the OPT101 R and the subtraction of its phase in plots and fits. When off, the microphone calibration is inactive. The CSV records `# Normalizacao pelo OPT101 no gráfico/ajuste = sim|nao`.
- **"Show each sensor's signals"** (Dual Mode): second row of plots with the amplitude (R ÷ sweep median) and the unwrapped phase of the INMP441 and the OPT101, separately.
- **"Diagnostics" button** (Dual Mode, frequency sweep): separates the photoacoustic signal (S ∝ f⁻ⁿ) from a flat background (light on the microphone, driver noise, electrical coupling) with a complex fit that includes the microphone high-pass, the delay and the cell resonance. Draws the components and shows where the background dominates, fc, delay, f₀ and Q, with a suggested test.
- **Verification with a second reference** ("Verify with this measurement"): with the calibration applied, a reference of a different material, measured in the same setup, must give f⁻ⁿ with constant phase (|Δn| ≤ 0.15, ≤ 1.5 dB rms, ± 10° rms). Only this marks the calibration as verified; the result goes into the file (`# Verificacao_2a_referencia`). With the same reference, it only measures repeatability.
- **"Range: from … to"** in the fits and in the verification (replaces "Fit up to"), to leave out low-frequency noise and the resonance.
- **Resonance f₀ in the calibration** (`# Ressonancia_f0_Hz`) and a warning when the corrected sweep has its resonance shifted by more than 3 % (sample height different from the reference).
- **Closed-chamber models** in "Fit with models": opaque sample (f⁻¹) and transparent, thermally thick sample (f⁻¹·⁵), for test samples such as glass.
- **SOI icon** made from the LCTM logo (molecule and prism in yellow on a dark background): shown in the window, dialogs and taskbar (also when running through `python.exe`). Files in `interface/icones/` (`soi.ico` with 16, 20, 24, 32, 40, 48, 64, 128 and 256 px, and `soi_256.png`). From 16 to 32 px the icon shows only the prism, with a thicker stroke, to stay legible.

#### Changed
- **Calibration:** M(f) = S(f)·fⁿ with the reference's n (before, always f¹·⁵). Points with enough SNR are included even outside the model (before, points rejected by the fit were left out and the resonance was interpolated). The file gains the lines `Referencia`, `Referencia_ID`, `Celula`, `Expoente_teorico`, `L_um`, `alpha_cm2_s`, `Verificada`, `Verificacao`, the `No_Ajuste` column and the cell in the name (`CAL_…_microfone_<OPC|Camara>_…`). Old calibrations are read as "Al foil, OPC".
- The "Aluminum foil calibration" panel was renamed "Microphone calibration".
- **Dual Mode layout:** plots on top, text results below; opening panels no longer hides the plots. Shorter verification texts (details in the tooltip). The cell diagram scales with the Windows font, and the mounting tips no longer overlap the drawing.
- **Double-click** on any plot resets the axes/zoom (in Dual Mode, both plots together).
- **Warning before the calibration sweep** if PWM is not at 100 %, if any 60 Hz filter is on or if "Use" is ticked, with "Fix and run", "Run anyway" or "Cancel".
- Shorter fit text: "PAS cut-off" instead of "Microphone/cell cut-off (fc)".
- **Calibration:** no "Calibration parameters" button. The calibration sweep always opens with 5–2440 Hz, 35 log points and τ = 2 s. Nothing is saved until the calibration button is clicked.
- **Frequency sweeps without the "Measurement" option**: always long integration, with a τ field linked to the INMP441 τ (changing any of them changes the others). The matched PWM sweep keeps the choice.
- **Refine resonance** (frequency sweep panel): fits the cell resonance above 250 Hz on the current sweep (or one opened from disk) and measures N new points (12 by default) within the peak width, f0 ± f0/(2Q). The points are inserted in order into the same sweep, exclusions are kept, and the CSV is written again with all of them and a "# Refino da ressonância" line.
- **Frequency sweep plot arrangement** (right-click): side by side, stacked (shared x axis, frequency scale on top of the upper plot and at the bottom of the lower one, no gap between them) or overlaid, with S on the left and the phase on the right axis. Saved. The axes take the colours of the curves (S blue, phase red).
- **Dual Mode top row:** "Run sweeps" gave way to separate panel buttons, the controls that used to sit below the plots were removed, the plots take all the free height, and text results appear in a floating box over them that can be dragged by its title and collapsed (position saved). The Calibration panel scrolls horizontally on narrow screens instead of widening the window beyond the screen. (Superseded by the reorganization above.)
- **Simplified optical channel** (Dual Mode): the long effective-τ line became a short "Light (OPT101)" line with the light level, the variation over the sweep and the optical bandwidth; details are in the tooltip and the CSV. "Subtract sensor τ" and "Measure…" moved to "Advanced ▸" in the calibration panel (only needed when changing the OPT101 resistor); the checkbox was removed, and τ = 0 means no correction.

### Executable and documentation
- `packaging/soi_controller.spec`: the .exe uses `interface/icones/soi.ico` as its icon and bundles the `icones` folder.
- **Documentation translated into English** (README, `docs/`, CHANGELOG). The guides were renamed: `docs/01_Materials.md`, `02_Hardware_and_Wiring.md`, `03_STM32_Firmware.md`, `04_Interface.md`, `05_Components.md`, `06_Performance_and_Applications.md`; images are in `docs/images/` and test procedures in `docs/tests/`.
- Documentation revised for the STM32Cube firmware: README (flashing with PlatformIO, `framework = stm32cube`, or the `.bin` in `binarios/`, version compatibility); no more references to the Arduino/STM32duino framework or to `main.cpp`.
- `CONTEXT_SOI.md`: short context file for developers and AI assistants (goal, hardware, layout, conventions, state, open issues).
- README with the icon at the top and the LCTM logo at the bottom (`docs/images/logo_lctm.svg` is the original; `logo_lctm.png` and `soi_icone.png` are derived).

## [2.0.0] - 2026-11-13

Published on GitHub together with 2.1.0 (in testing since 2026-11-05).

Major version: **the USB protocol changed**. Firmware 2.0.0 only works with interface 2.0.0 or later, and vice versa. To go back to 1.0.0, reflash the old firmware.

### Firmware (`firmware/`)
- **Rewritten with STM32Cube** (ST HAL and ST USB Device library V2.11.6, in `firmware/src/usb`), without STM32duino. `src/main.cpp` was replaced by `src/main.c`, plus configuration in `include/` and `src/usbd_*.c`. In the Black Pill throughput test, USB CDC went from ~190 kB/s (STM32duino) to ~1.1 MB/s.
- **Raw OPT101:** every ADC sample, 12 bits at **200 kS/s**, each with the laser state (bit 15). Oversampling moved from the firmware to the interface, so changing the rate no longer requires reflashing the board.
- **New optical packet** `A5 5A 4F 50`, with an absolute sequence number (a loss shows as a visible jump) and CRC-16. The 5-byte `55 AA` frames no longer exist.
- **INMP441 at exactly 48 kHz** (PLLI2S 76.8 MHz, I2SDIV 12 with ODD), instead of 31,994 Hz (−186 ppm).
- Total stream ~550 kB/s, half of what USB can carry. Memory: ~31 KB of flash and ~50 KB of RAM (optical ring of 8192 samples, 41 ms).
- Same as 1.0.0: `F` and `P` commands, 5 kHz PWM on PA8, modulation range and rounding (0.1–5000 Hz, TIM4), PB0 as reference, INMP441 phase marker and interrupt priorities (USB has the lowest).
- The board shows up in Windows as "SOI OPT101/INMP441 (STM32F401)", VID 0483, PID 5740.

### Interface (`interface/soi_controller.py`)

#### Added
- **Oversampling chosen in the interface** (OPT101 tab): 1x to 64x, from 200 to 3.125 kS/s. The 16x default reproduces the 12.5 kS/s of 1.0.0. The scale stays 0–16,380, and the averaging (boxcar) amplitude correction and the reference delay follow the OSR.
- **Resolution test** (OPT101 tab): with a steady signal, records raw samples and shows the noise of averages of N samples (Allan deviation) against the ideal 1/√N, the gain in bits, the effective bits and the histogram of ADC codes. Warns when dither is missing (σ < 0.3 LSB) or when the laser was modulating, discards the recording if there was a loss, and saves CSV and PNG.
- **Status bar warnings:** orange when the modulation exceeds FS/4 and red above 0.4·FS, with the largest safe OSR suggested; also a warning when the modulation exceeds 1 kHz with PWM below 100 %. The rate in use is shown in the bar too.
- **Click and zoom in both FFTs:** a click shows the frequency and magnitude of the nearest point; the wheel zooms, dragging pans, double-click returns to auto scale and right-click clears the marker.
- **Lock-in with τ** (from PR #3): the lock-in low-pass (OPT101, INMP441 and Dual Mode long integration) is chosen by the time constant τ, in the 1–3–10 sequence from 1 ms to 100 s. Next to it: the −3 dB cut-off, the ENBW and the 9τ wait.
- Lock-In CSVs record the OSR, rate and τ in the header.

#### Changed
- **The interface script is now `interface/soi_controller.py`** (formerly `interface/stm32_opt_inmmp_novo.py`), matching the program, `.spec` and executable names. The version lives only inside the file, in `__version__`. Saved preferences remain valid.
- **USB reading in a separate process:** screen stalls no longer lose data. `SOI_SERIAL_THREAD=1` goes back to the old (thread) mode.
- Reading of the new protocol with CRC check. A real loss is filled by repeating the last sample (time and PLL stay correct), counted in the status bar and logged in the terminal with time and duration. The sequence jump at the start of the connection does not count as a loss.
- **48 kHz audio:** INMP441 lock-in at the exact rate, blocks of 2400 samples (still 20 points/s) and spectrum up to 24 kHz.
- Performance at 200 kS/s: the oscilloscope keeps at most 120 thousand points (averaged per point for long windows), the full FFT grows with the rate, the zoomed FFT is limited to 2¹⁹ points, the Hann window is cached and the Average mode keeps only the running sum of the cycles.
- The automatic τ on frequency change is rounded to 0.3 s, 1 s or 3 s. Preferences store τ; the cut-off in Hz saved by 1.0.0 is ignored once.
- The simulator generates raw 200 kS/s samples, like the new firmware.

#### Fixed
- The τ field also works with PyQt6 (before, only with PySide6).
- The INMP441 phase no longer rotates over time (treating the 31,994 Hz rate as 32 kHz caused the drift).

### Documentation
- The test procedure moved to `docs/tests/test_2.0.0.md`, and the firmware binary is now named `soi_firmware_v2.0.0.bin`.
- `docs/03` rewritten: STM32Cube, clocks (PLLI2S for 48 kHz), ADC without oversampling, new protocol and priorities.
- `docs/04` gained the Oversampling and Resolution test sections, the status bar and updated specifications.
- `docs/05`, `docs/06` and `README.md` updated (rate, 48 kHz audio, firmware layout).

### Tests (2026-11-05, on the Black Pill)
- Direct port reading for 2 × 60 s (551 kB/s, 200.2 kS/s optical and 48.0 kS/s audio), with no losses and no CRC errors, even with a busy CPU.
- Resolution test with constant light: 8.4 LSB of noise per sample; noise falls as 1/√N up to N = 64, from 7.1 to 10.4 effective bits. Above that, mains noise appears (multiples of 60 Hz, present with the OPT101 covered), of electrical origin.
- Modulation on with the laser off does not change the noise and does not appear in the OPT101 FFT: there is no electrical leakage from the modulation into the optical channel.

### Known issue
- Dual Mode sweeps with the new firmware give a frequency exponent n near 0 (e.g. the aluminum foil calibration of 2026-11-05 gave n = 0.20–0.31, far from the expected 1.5). The main suspect is an air leak in the cell, still under investigation.

## [1.0.0] - 2026-10-27

First published version.

### Interface (`interface/stm32_opt_inmmp_novo.py`)
- Python lock-in on both channels: OPT101 (with a software PLL) and INMP441.
- OPT101 tab: oscilloscope, Lock-In and Average (with 1- or 2-exponential fit), ADC FFT with peak fit, frequency and PWM sweeps.
- INMP441 tab: Lock-In, Noise/SNR, FFT with peak fit, frequency and PWM sweeps with calibration correction.
- Dual Mode: both lock-ins in the same step, signal normalized by the OPT101, microphone calibration with aluminum foil, model fitting and opening of saved sweeps.
- Standardized CSV/PNG export with the sample name, and "Finish experiment" (session ZIP).
- Automatic port detection, reconnection and simulated mode without the STM32.

### Firmware (`firmware/`)
- STM32F401 Black Pill (STM32duino): 5 kHz laser PWM (0–100 %, 0.1 % steps) and square-wave modulation from 0.1 to 5000 Hz.
- OPT101 ADC at 12.5 kS/s with 14 effective bits (oversampling) and laser reference by DMA.
- INMP441 over I2S at ≈32 kS/s, 24 bits, with a modulation-start marker for the phase.
- USB CDC output.

### Added to main after the release (same number)
- Windows executable: PyInstaller spec in `packaging/` and a workflow that attaches the `.exe` and `.zip` to Releases (PR #1, 2026-10-27).
- Minimum CPU requirement documented: x86-64-v2 / SSE4.2 (PR #2, 2026-10-29).

[Unreleased]: https://github.com/mbelancon/SOI/compare/v2.1.0...HEAD
[2.1.0]: https://github.com/mbelancon/SOI/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/mbelancon/SOI/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/mbelancon/SOI/releases/tag/v1.0.0
