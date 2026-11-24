# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [semantic versioning](https://semver.org/): MAJOR.MINOR.PATCH.

- **MAJOR:** incompatible change, for example in the serial protocol between firmware and interface.
- **MINOR:** new feature that does not break what already existed.
- **PATCH:** bug fix.

The interface and the firmware share the same version number. It appears in `__version__` (interface, window title) and in `FIRMWARE_VERSION` (firmware). Each published version gets a `vX.Y.Z` tag on GitHub.

## [Unreleased]

## [2.4.0] - 2026-11-18

Minor version: only the interface changes. The firmware is still 2.0.0 and the USB protocol is the same.

### Interface (`interface/soi_controller.py`, new `interface/soi_serie.py` and `interface/soi_layout.py`)

#### Added: Measurement Series tab ("Medidas em Série")
- **Why:** long campaigns (drift, noise, repeated sweeps) were run from .bat files with the headless mode, with
  nothing to watch on screen. The new tab builds, saves and runs the same sequences inside the interface.
- Step types: **Sweep f** (the Dual Mode frequency sweep: start/end f, log points, τ max + precision or fixed τ,
  allow averages, PWM, warm-up), **Signal vs t** (frequency, PWM, τ, point every, duration, warm-up; the frequency
  accepts a list such as `37;113;487`, one measurement per frequency, `{f}` in the name), **Pause** (PWM 0 for N
  minutes, not recorded) and **Notice** (shows a text and waits for Continue, e.g. to change the sample).
- Each step can be repeated N times (`_rep1`, `_rep2`...), the whole series N times (`_ciclo1`...), and the series
  can wait for a start time (laser stopped meanwhile; the next time the clock shows it). Optional PWM 0 at the end
  of each step and of the series.
- Measurements are added with a single **"＋ Configure new measurement..."** button that opens a configuration window:
  choose the sensor (Dual Mode, OPT101, INMP441, Pause/notice), what to vary (frequency, time, PWM) and the
  parameters (time, repetitions, averages). Double-click a row (or Edit...) to change it; the panel on the right
  shows the selected measurement.
- Run controls: Start, Pause after this step, Continue, Skip step and Stop (the measurement in progress is ended
  and saved with the points already measured). Status line with the remaining time of the step and of the series
  and the expected end time; a plot of the measurement in progress; the other tabs and the top bar are locked
  while the series runs. Closing the window during a series asks first and saves what was measured.
- Each run gets its own folder `Medidas\Serie_<base name>_<date_time>\` with the CSV/PNG files (names: base name +
  step name, same formats and columns as before), a copy of the series file (open it again to repeat the run)
  and `resumo.csv` (one line per measurement: start, end, status, file).
- Series file `*.serie.txt` (UTF-8 text, default folder `interface\Series`): one step per line with the same
  options as the headless command line (`sinal-t --nome 2_f{f} --f 37;113;487 --duracao 20`, `varredura --fmin 20
  --fmax 2440 --n 25 --tau 4 --precisao 2 --repetir 3`, `pausa --duracao 10`, `aviso "text"`), header keys
  `nome_base`, `inicio`, `repetir`, `fim`; `#!` marks an unchecked step. Keys stay in Portuguese in both languages.
- **Transient (OPT101)** step: the OPT101 Mean Value mode run unattended. One average of N pulses every
  interval (e.g. 64 pulses every 60 s or every 10 s; 0 = back to back) for a total duration. Saves `<stem>.csv`
  (time + one column per average, start time of each in the header), `<stem>_medias.csv` (one line per average:
  time, min, max, amplitude and, optionally, a 1- or 2-exponential fit of the laser-on half period: τ, A, R²), a PNG
  and, optionally, the individual transients (`<stem>_individuais/M001.csv`...: the N pulses of each average). The
  tab goes back to Lock-In mode at the end. Options `--pulsos`, `--intervalo`, `--duracao`, `--ajuste 0|1|2`,
  `--individuais`.
- PWM list (power scan) in Signal vs t and Transient: `--pwm 25;50;100`, one measurement per power (`{pwm}` in the
  name), combined with the frequency list and with Repeat.
- Sweeps of the other tabs as steps: **OPT101 × f**, **OPT101 × PWM**, **INMP441 × f**, **INMP441 × PWM** (the
  lock-in sweeps of the OPT101 and INMP441 tabs, linear start/end/step, with the filters set in that tab) and
  **Dual Mode × PWM** (the "Signal vs PWM" panel: S and Δφ at each PWM, fixed frequency, τ > 0 = long
  integration). Options `--inicio`, `--fim`, `--passo` (plus `--pwm` or `--f`, `--tau`, `--aquecer`). Same files
  and columns as the sweeps started from the tabs, saved in the series folder; the result window is not opened
  during a series.
- Completed measurements on the tab plot: after a series (or when a series file is opened from the folder of a
  run, using its `resumo.csv`), clicking a completed step draws its saved data in the tab plot: S vs f / t / PWM
  for Dual Mode steps, R vs f / PWM for OPT101/INMP441 sweeps, and every average (first blue to last red) for a
  Transient. Steps with several measurements (frequency/PWM lists, Repeat) show one curve each, with a legend.
  The Status column shows the states from `resumo.csv`. During a series, clicking a completed step shows it; clicking
  the running step goes back to the live plot.
- Headless: `soi_controller.py --serie file.serie.txt [--amostra name] [--simulado]` runs the same file without
  a window (a Notice waits for Enter in the terminal).
- Simulated mode works as usual (same sweep and Signal vs t code).

#### Added: sweep repetitions with median (noise campaign, 2026-11-18)
- **Why:** between 40 and 200 Hz the sweep errors are isolated points off by 8–15 % (room sounds lasting a few
  seconds), at different frequencies in each sweep; a longer τ does not remove them, the median of separate sweeps does.
- Dual Mode frequency sweeps: **Repetitions** field (default 3). Each repetition saves its CSV (`_rep1`, `_rep2`…);
  at the end a `_mediana` CSV with the point-by-point median and the new columns `S`, `N_repeticoes`,
  `Incerteza_S_Pct` (100·1.25·SD/√N/median) and `Incerteza_Fase_Graus`. The plot shows the repetitions in grey and the
  median with error bars of u. Headless `--repeticoes N`; series step option `--repeticoes N`.
- Mains harmonics: fixed-frequency fields within ±3 Hz of a multiple of 60 Hz (excitation bar, Signal vs t, series
  steps and lists) show an orange warning with a **Shift** button (k·60 ± 5 Hz); sweeps move such points to k·60 ± 4 Hz
  by default (*Avoid multiples of 60 Hz*), listed in the CSV header. Headless `--sem-evitar-rede`.

#### Added: room-noise rejection by the neighbouring frequencies (approved 2026-11-18)
- **Why:** intermittent room sounds (seconds long) leave isolated points off by 8–15 % between 40 and 200 Hz; the
  lock-in fluctuation catches only a few of them. A sound shows up at the neighbouring frequencies at the same time.
- Every 1 s, on the raw INMP441 (2 s Hann window): q = rms(R at f·0.93, R at f·1.07) / R at f, neighbours moved away
  from multiples of 60 Hz. In the Dual Mode frequency sweeps (*Discard stretches with room sounds*; off by default since 2026-11-19, because the offline test with the night audio showed no gain) the part of a
  point's average with q > 2 × the point's median q is discarded; with more than 30 % discarded the average is redone
  (up to 2×). Limits from the 2026-11-18 heating campaign: rms deviation 27 → 15 % at 37 Hz and 14 → 7 % at 113 Hz,
  discarding 7–15 %; ≥ 487 Hz discards ≤ 1.4 %. Broadband energy did not correlate and is not used.
- New CSV columns `Ruido_vizinhas_q` (median q of the point; the typical |error| is ~0.3·q), `Descartado_Pct`,
  `Refeito_ruido`. Headless `--descartar` turns it on (`--sem-descarte` is kept and is now the default).

#### Added: shuffled measurement order and extra frequencies to avoid (approved 2026-11-19)
- **Why:** with an ascending sweep a slow drift (cell warm-up) turns into a false slope of the curve. Measuring the
  frequencies in a new random order in each repetition turns the drift into scatter that the median of the
  repetitions reduces. The 2026-11-19 noise study also found a noise source at ~170 Hz (probably the laser fan).
- *Order* box next to *Repetitions* in the Dual Mode frequency sweep: Ascending (default), Descending or Shuffled.
  Shuffled draws a new permutation in each repetition (`random.Random(seed).shuffle` of the ascending indices; seed
  + k − 1 in repetition k), written in the CSV header (`# Ordem = embaralhada; semente = …`). The plot and the CSVs
  stay in frequency order.
- New CSV columns `Ordem_medida` (position in which the point was measured) and `Hora_ponto` (end time of the
  point) in every frequency sweep CSV; in the `_mediana` CSV, `Ordem_medida` lists one position per repetition
  separated by ";".
- *Avoid (Hz)* field: frequencies of known noise sources (e.g. `170,7`); sweep points within ±2 % of them (at least ±3 Hz, proportional window approved 2026-11-19) move 1 Hz beyond the window edge,
  on the side they were on, and are listed in the CSV header. Saved with the settings.
- Headless: `--ordem crescente|decrescente|embaralhada`, `--semente N`, `--evitar "170.7;341.4"`.

#### Added: Detect background noise (approved 2026-11-19)
- **Why:** the 2026-11-19 noise study found a tone series at ~170.2 Hz (probably the laser fan: 170, 340, 510, 681,
  851 Hz). Sweep points on such tones pick up noise unrelated to the sample.
- *Detect background noise...* button in the INMP441 tab opens its own window (new `interface/soi_ruido.py`). Quick
  mode: laser at PWM 0, records the INMP441 (default 20 s, 12 kS/s), Welch PSD with 4 s Hann windows (0.25 Hz),
  background = running median of the dB spectrum (±20 Hz), tones > 10 dB above it (adjustable), harmonic series =
  f0 with ≥ 3 peaks at k·f0 (0.5 %, k ≤ 10), 60 Hz and multiples marked as mains. Comparative mode (like the
  two-sample calibration): record without the noise source, then with it; the source's tones are those ≥ 6 dB
  higher in the second recording. Table + spectrum with marks; *Send to Avoid (Hz)* adds the selected tones (or the
  whole series, k·f0 up to k = 10) to the sweep's *Avoid (Hz)* field. Each analysis saves
  `<sample>_Ruido_fundo_<date>.csv` (header with the tones; columns `Frequencia_Hz,PSD_dB,Fundo_dB`, plus
  `PSD_sem_fonte_dB` in the comparative mode) and the raw audio `.bin` (AudioRecorder format) in `Medidas`.
- *Detect noise during warm-up* (Dual Mode frequency sweep, on by default): with *Wait for warm-up*, the audio of the
  last 3 min of the warm-up is analysed the same way, ignoring the laser frequency and its harmonics (±0.15 Hz: the
  modulation is exact in the I2S clock; ±1 Hz would hide 40 % of the spectrum with the laser at 5 Hz). The tones and
  series found are avoided in that sweep and its repetitions (the *Avoid (Hz)* field is not changed) and are written in
  the CSV header (`# Ruidos detectados = …`). Headless `--aquecer` does the same; `--sem-detectar-ruido` turns it off.
- Headless: `--detectar-ruido [--duracao S] [--comparar] [--limiar DB]` prints the tones and a ready `--evitar` list.
- Simulation: `SOI_SIM_RUIDO=<f0>` adds a fan-like harmonic series to the simulated INMP441.

#### Fixed: raw audio blocks not multiple of 4
- The 4-sample average of the raw audio recording dropped the remainder of each block, which made phase jumps when
  a block length was not a multiple of 4. The remainder now goes to the next contiguous block. The board always sends
  256-sample blocks, so only the simulation was affected.

#### Added: optional raw INMP441 audio recording
- **Why:** offline analysis of the room's acoustic noise (neighbouring frequencies, broadband energy) to define a rule
  for discarding noisy points. Off by default; turned on with the environment variable `SOI_GRAVAR_AUDIO=<folder>`
  (GUI or headless). One file per run, `audio_<sample or soi>_<YYYYMMDD_HHMMSS>.bin`: per block a little-endian header
  `uint32 sequence` (I2S index of the first sample), `uint32 n_out`, `float64 t_pc` (time.time() on arrival), then
  `n_out` float32 = mean of every 4 samples / 8388608 (12 kS/s, ~170 MB/h). Written by its own thread (flush every
  ~1 s); the file name goes to the log. Headless `--amostra` renames the file if it was already open with the
  sample name saved in the interface.

#### Changed: sweep defaults reviewed on 2026-11-19 (approved)
- *Order* is **Shuffled** by default (and saved with the settings): each repetition is a complete sweep in a new
  random order, a randomized complete block design, so a slow drift spreads evenly over the frequencies instead of
  becoming a slope. τ = 1 s fixed and 3 repetitions with median stay. Headless `--ordem` defaults to `embaralhada`.
  The interface applies these defaults once on the first start of this version.
- *Discard stretches with room sounds* moved to **Settings → Sweeps** ("Show … in the frequency sweep", off by
  default): off, the box disappears from the Dual Mode sweep and the discard stays off; on, the box shows as before.
  With τ = 1 s it brought no gain in the 2026-11-18/19 tests; it may help with longer τ. Headless `--descartar`
  still turns it on.
- *Avoid (Hz)* window proportional to frequency (±2 %, at least ±3 Hz) instead of a fixed ±3 Hz → ±4 Hz, also for
  the tones found during the warm-up.

#### Changed: noise detection excludes bands by itself, mains included (approved 2026-11-19)
- **Detected noise is used without "Send":** the tones of the last *Detect background noise* window are excluded from
  the next Dual Mode frequency sweeps (whole series, k·f0, k ≤ 10) until the next detection or until the interface is
  closed, together with the warm-up detection. The box *Exclude detected noise* (was *Detect noise during warm-up*)
  turns both off; it shows how many bands and the time of the last detection. The window button became *Write to
  Excluded bands (Hz)* (to keep them in the saved field). On 2026-11-19 the sweep at 15:22 used the old field and not
  the 15:19 detection (117 Hz and 497 Hz were left in).
- **Mains in the detection:** the detection records the OPT101 together with the INMP441 and keeps its mains tones
  (60 Hz and multiples; the mains background is electrical, in the OPT101), listed as *mains (OPT101)*. Mains tones
  found in either sensor are excluded like the others. The *Avoid multiples of 60 Hz* box was removed: with no
  detection that analysed the OPT101, every multiple of 60 Hz is excluded for safety (as before); the CSV header says
  which rule applied (`# Rede = …`). The warm-up detection also analyses the OPT101 when the laser harmonics do not
  cover the multiples of 60 Hz. Simulation: the simulated OPT101 also has a small 300 Hz tone.
- **"Exclude" instead of "Avoid":** *Avoid (Hz)* became **Excluded bands (Hz)** (no point is measured in the band of
  ±2 %, at least ±3 Hz, around each frequency). Headless `--excluir` (alias of `--evitar`); CSV header
  `# Faixas excluidas …` (was `# Frequências evitadas …`; old files keep opening, the line is informative).

#### Changed: no sleep and log of every point during measurements (approved 2026-11-19)
- The sbook2 entered Modern Standby several times during the 2026-11-19 sweeps (Kernel-Power 506/507). On such PCs
  Windows goes to standby when the screen turns off, even with `ES_SYSTEM_REQUIRED`, so the interface now also keeps
  the screen on (`ES_DISPLAY_REQUIRED`) while a measurement runs. "Measurement running" now also covers the warm-up,
  the gap between repetitions and the whole Measurement Series (also between steps). The log records when the block
  starts and ends.
- Every Dual Mode point also goes to `soi.log` when using the window (frequency, S, Δφ, τ, time, fluctuation), as the
  headless mode already printed, so a lost point can be traced.

#### Changed: narrower Dual Mode window (Marcos's test, 2026-11-19)
- The *Signal x f (Hz)* box was wider than the screen. *Spacing*, *N points* and *Order* moved to the first row,
  right after *Start*/*End*; the second row has *Avoid multiples of 60 Hz*, *Avoid (Hz)* and *Detect noise during
  warm-up*; the third has τ, *Repetitions* and the adaptive options. The fit *Model* list is narrower (the drop-down
  still shows the full names). Dual Mode tab minimum width 2021 → 1534 px.
- A second *Detect background noise…* button after *Signal x t (s)* in the Dual Mode (same window as the INMP441 tab).

#### Fixed: median of the repetitions matched points by position (found in the 2026-11-19 sweep)
- `_mediana` paired the repetitions by row position, so a repetition with missing points mixed different
  frequencies, cut the range (the file name came out "40_1333.03Hz") and gave false uncertainties up to 114 %. The
  repetitions are now matched by frequency (0.01 Hz); a point missing in one repetition uses only the ones that exist
  (`N_repeticoes` per point, `Ordem_medida` shows `-` for the missing one) and the header lists
  `# Repetições incompletas: …`.

#### Fixed: points without data were skipped silently
- A point where one of the sensors sent no data (USB/serial stall) was skipped with only a 3 s status message, so a
  repetition could lose points with nothing in `soi.log`. Now the point is measured again up to 2 times; the log
  says how many OPT101/INMP441 blocks arrived; if it still fails the point is skipped and listed in the CSV header
  (`# Pontos pulados …`).

#### Changed: sweep defaults from the 2026-11-18 noise campaign
- Fixed τ = 1 s (adaptive τ off by default, still available), τ = 4 s below 40 Hz (7τ wait, 3τ average),
  3 repetitions + median, 600 s warm-up (was 300 s), start at 40 Hz, avoid multiples of 60 Hz. Above τ = 4 s an orange
  "τ > 4 s does not help: use repetitions" appears (largest useful τ, from the Allan deviation). Saved preferences are
  switched to the new defaults once. Headless: adaptive τ only with `--adaptativo` or `--precisao`; series files
  written before keep their meaning (a `varredura` line without `--tau-fixo` is still adaptive, one sweep).

#### Changed
- Unattended runs: during a series the "below 40 Hz" confirmation and the calibration-conditions check of the
  frequency sweep do not open dialogs (the warning goes to the log).
- The Dual Mode PNG is drawn at screen size even when the Dual Mode tab is hidden.

#### Fixed
- Window opened maximized with the top bar (Excitation, Calibration, Simulate sampling, Settings) cut off on the
  right and the rest of the window badly sized, until it was restored and maximized again (seen on a laptop with
  high Windows display scaling). Two causes, both fixed:
  - The top bar was a single row about 1600 px wide, which set the window's minimum width. With 125–200 % scaling
    that is wider than the screen, so the maximized window could not fit its content. The top bar now wraps into
    two rows when the window is narrow (groups: excitation, sample, calibration, cell, SNR, and Simulate/Settings
    kept at the right). The row at the top of the Measurement Series tab wraps the same way. Minimum window width
    went from ~1600 to ~960 px.
  - A window closed maximized was restored already maximized, before it existed on screen. It now opens at its
    saved normal size (fitted to the screen) and is maximized right after `show()`. This replaces an
    earlier workaround (restore + maximize again on a timer), which did not help on that laptop.
- "Detect background noise" window: dragging or zooming the spectrum could run off to absurd scales (frequency axis
  from 10^-307 to 10^308 Hz, PSD around 10^9 dB), and the long axis labels made the plot much wider. The view is now
  limited to the measured spectrum (±0.1 decade, PSD ±40 dB), the left axis has a fixed width, near-zero bins (the
  -300 dB log floor) are clipped 30 dB below the 1st percentile so they no longer stretch the y axis, and a double
  click on the plot goes back to the full spectrum, as in the other plots.
- Sweep boxes (Dual Mode "Signal vs f", Calibration, PWM and the OPT101/INMP441 sweep panels): when the window was
  narrower than a row of fields (high Windows scaling, or after the orange "high SNR at f < 40 Hz" notice appeared),
  the spin boxes overlapped the labels "End:" and "Spacing:" and the notice was cut. Each label + field pair is now a
  group and the row wraps onto a new line instead of overlapping.
- Dual Mode plots: the y axis was fitted to the points drawn before the newest one (the curves were updated after
  the fit), so the point just measured could stay off the scale. It showed up with shuffled sweeps that go below
  40 Hz, whose low-frequency points have much smaller S and Δφ (e.g. 4 points measured, 2 visible; the 5 Hz point in
  the CSV but not in the plot). The axes are now fitted after the curves are updated.
- Warnings and status texts made the window wider than the screen when they appeared (e.g. the red "Resonance
  shifted" badge, "⚠ N warning(s)", "ℹ Results", a long file name in the status bar of a tab). The row under the
  Dual Mode controls now wraps onto a second line, and the status bars of the OPT101, INMP441 and Dual Mode tabs, the
  refine note and the manual-sweep readout shrink (cut at the edge or wrap) instead of raising the window's minimum
  width.
  (A first version of these wrapping rows left an empty group, one whose only label was hidden, as an invisible
  640×480 widget over the top of the Dual Mode tab, so no field there reacted to clicks. Empty groups now get zero
  size; a test clicks every button, field and box of all tabs.)
- Window and panels resized badly during use until the window was restored and maximized again. The wrapping rows
  above reported, as their minimum, the height of one group per line, which pushed the window's minimum height to
  ~990 px (more than a 1080p screen at 125 % scaling, or a Surface Book at 200 %); they now report one line and get
  their real height from the width they receive. The Calibration panel of the Dual Mode is capped at 40 % of the
  screen height (with a vertical scroll bar), and the estimated-time label no longer widens the sweep box when
  "Wait for warm-up" is ticked. Measured offscreen at 1500×950: minimum window size 1119×654 (was 1668×654 in
  the first 2.4.0 build), 1119×840 with the Calibration panel open. As a safety net, a maximized window whose frame
  ends up larger than the screen after a layout change is restored and maximized again automatically (once every
  3 s at most, and only if its minimum size fits the screen).
- Dual Mode sweeps with "Wait for warm-up": the confirmations ("sweep below 40 Hz" and the calibration conditions
  check) opened only at the end of the warm-up, and the measurement waited there, with the laser on, until someone
  clicked OK. They are now asked when the sweep button is clicked, before the warm-up, and the sweep starts by
  itself when the warm-up ends.

## [2.3.0] - 2026-11-17

Minor version: only the interface changes. The firmware is still 2.0.0 (`binarios/soi_firmware_v2.0.0.bin`) and the USB protocol is the same.

#### Added: calibration and examples documentation
- `docs/07_Calibration.md` (two-sample calibration) and `docs/08_Measurement_Examples.md` (measurements of 2026-11-17: metals, Ni with a dark film, carbon black, SNR vs point error), with the raw CSVs and `make_figures.py` in `examples/2026-11-17/`. `docs/04_Interface.md` updated for 2.3.0 (τ / τ max, Allow averages, SNR readout, PWM buttons, warnings, manual zoom); the old single-reference calibration text was replaced by a summary.

#### Fixed: informative results after removing the floating box
- Diagnostics, the Signal vs t summary, the PWM fit, the applied calibration and the excluded points were left without a place when the floating Results box was removed; they now appear in a blue "ℹ Results" label (text in the tooltip) next to the warnings label.

#### Changed: project context files
- `CLAUDE.md` (working rules) and `CONTEXTO.md` (current state, in Portuguese) replace `CONTEXT_SOI.md`.
- Version rule: firmware and interface are versioned independently; the firmware number changes only when the firmware changes (same MAJOR = same USB protocol). README updated.

### Interface (`interface/soi_controller.py`)

#### Added: optical modulation (chopper)
- **Why:** to measure with a light source that SOI does not modulate (LED or laser in continuous mode with a mechanical chopper or a fan), without a reference output from the chopper.
- **Trigger choice** in the new **⚙ Settings** window: **Electronic** (STM32 PWM) or **Optical** (chopper). Applies to the three tabs. In optical mode PWM is hidden and its place shows the detected frequency.
- **Reference from the OPT101:** the frequency is the largest peak of the OPT101 FFT in a search range (OPT101 tab, default 20–5000 Hz); a second-order PLL on the OPT101 signal (bandwidth f/50, 0.5–10 Hz, updated in blocks of a whole number of periods) gives the reference phase of both lock-ins. Errors of the reference cancel in S and Δφ. The detected frequency and the lock state appear on the excitation bar (deviation and phase wander in the tooltip) and in the OPT101 status; the scope's green trace becomes the PLL reference.
- **Microphone alignment without new firmware:** in optical mode the interface sends `P0` + `F1`; the 1 Hz "beacon" on the reference bit and the I2S marker give the offset between the optical and the audio streams (exact rate ratio, same crystal), with < 1 µs error. The serial reader now numbers the optical words and records where each marker arrives in the optical stream. The beacon is resent if the alignment is missing.
- **Same phase convention as electronic modulation** (Δφ, calibrations and fits valid in both modes): checked in simulation and with emulated firmware packets, Δφ within 0.3° of the electronic-mode value up to 1.5 kHz.
- **Dual Mode, manual frequency sweep:** points recorded automatically when the frequency is stable and far enough from the last point (or with **Record point**); 9τ wait and 1τ average; point discarded if the frequency moves or the PLL unlocks. CSV `DUPLO_freq_…_optica_…` with `# Modulacao = optica` and the column `Frequencia_DP_Hz`. **Measure A/B** of the two-sample calibration uses the manual sweep.
- **Simulation:** simulated fan (drift, uneven blades, trapezoidal light) and beacon; Freq is the knob of the simulated chopper.
- OPT101 and INMP441 sweeps and **Refine resonance** are disabled in optical mode.

#### Added: adaptive τ in the Dual Mode frequency sweeps
- **Why:** in the sweeps of 2026-11-16 (Al, stainless steel, brass, Ni, Ni film; τ = 2 s) the scatter between neighbouring points below 40 Hz was 5–35 %, much larger than the scatter inside each point (1–8 %): the low-frequency acoustic noise is slow and needs a longer τ. Above 400 Hz the signal was clean (0.04–0.4 %) and the 18 s wait was wasted.
- **How:** **adaptive τ** option (on by default) next to τ, which becomes the initial τ (default 4 s). After each point the fluctuation of S and Δφ during the measurement (standard deviation or first/second-half drift; OPT101 interpolated at the INMP441 instants, so laser power cancels) sets the τ of the next point (fluctuation at 70 % of **Precision**, default 2 % / 1.15°; at most 3× change per point; minimum ~3 periods, 100 ms). Above 2× Precision the point is measured again with a larger τ (up to 2× the initial τ). Each point: 7τ wait, max(1 s, 3τ) average. The header records the initial τ and the range used.
- Off: the previous behaviour. Same phases as the fixed mode in simulation (within 0.02°); an 8-point sweep 10 Hz–2 kHz with a clean simulated signal took 84 s from τ = 4 s (fixed τ = 2 s: 2.7 min).

#### Added: timing and fluctuation per point in the Dual Mode CSV
- Automatic sweeps (frequency and matched PWM, adaptive τ on or off) write new columns `Tau_s` (lock-in τ of the point), `Tempo_ponto_s` (wait + average, including redos), `Refeito` (times adaptive τ measured the point again), `Flutuacao_S_Pct` and `Flutuacao_Fase_Graus` (fluctuation of S and Δφ during the average, as used by adaptive τ), plus a header line `# Inicio = …; Fim = …; Duracao = … s`. **Open sweep…** reads them back, so **Save again** keeps them; older files still open.

#### Added: headless sweep (command line)
- `python soi_controller.py --varredura [--amostra NOME] [--fmin HZ] [--fmax HZ] [--n PONTOS] [--tau S] [--precisao %] [--tau-fixo] [--pwm %] [--celula Camara|OPC] [--cal ARQUIVO|nenhuma] [--porta COMx] [--simulado]` runs a Dual Mode frequency sweep without a window (same code as the interface, Qt offscreen): electronic modulation, **PWM 100 %** by default, adaptive τ unless `--tau-fixo`; options left out take the interface's saved values. It prints one line per point (S, Δφ, τ, time, redos, fluctuation) and the CSV path, and saves CSV + PNG in `Medidas` with the usual name. It does not change the interface preferences.
- Before starting it checks the serial port and stops with a clear message if the port is busy (interface or serial monitor open) or the board is not found. Exit codes: 0 saved, 2 no board, 3 port busy, 4 no connection, 5 calibration not found, 6/7 sweep not started/not saved, 130 Ctrl+C.
- `varredura.bat` (next to `rodar_interface.bat`) passes its arguments to it.

#### Changed: logarithmic frequency axes
- Decades are labelled 10ˣ and the ticks between them only with the digit (2 … 9) instead of 2·10ˣ, which overlapped on wide ranges. With less than one decade in view the full value is shown (200, 300 …); when ticks get too close only 2, 3, 5 (or 2, 5, or only decades) are labelled. Applies to every log x axis (tabs, Dual Mode, saved PNG); y axes unchanged.

#### Added: log file and launch without terminal
- Everything that went to the terminal (messages, warnings, errors with traceback, Qt messages) also goes to `interface/logs/soi.log`, with date and time on each line. When it passes 2 MB it is rotated at start-up (keeps `soi.log.1` … `.3`). Uncaught errors in Qt slots and threads are logged instead of closing the program.
- `rodar_interface.bat` opens the interface with `pythonw` (no terminal window); `rodar_interface.bat terminal` opens it with the terminal, `rodar_interface.bat instalar` installs the dependencies. `varredura.bat` (headless sweep) stays in the console.

#### Added: calibration and measurement error bars
- With a microphone calibration applied, the frequency sweep plots show two error bars per point (±1 SD): **green**, wide, behind = calibration (its `Sensibilidade_Rel_DP` and `Fase_DP` interpolated at the frequency); **gray** = this measurement. The Results box says which is which. The CSV (when a calibration is applied) gets `Cal_S_DP_Pct` and `Cal_Fase_DP_Graus` (nan outside the calibration range).
- Log axes: the 9 label is dropped when it would touch 10ˣ (then 2 … 8; 2, 3, 5; or 2, 5 as space shrinks).

#### Fixed
- Error bars kept options from the previous plot (`ErrorBarItem.setData` accumulates them): opening a sweep after a frequency sweep raised an error and the PWM sweep could show bars of the wrong size.

#### Changed: adaptive τ rule and default Precision (2 %)
- **Default Precision 2 %** (S; 1.15° in Δφ), was 1 %. Sweeps of 2026-11-16 (Al, closed cell, τ from 4 s): the real scatter between neighbouring points was 2 % below 40 Hz and 0.6 % at 40–400 Hz, of the same order as the per-point fluctuation, and the microphone calibration itself is uncertain by several % / degrees at low frequency; with white noise, halving the precision cuts τ by 4×. Existing installations switch to 2 % once at start-up (setting `adapt_tol_2pct`).
- The next τ uses the **median of the last 3 points** (scaled to the current τ) instead of only the last point, and rises at most 2× per point (was 3×): one noisy point no longer pushes the following points to the τ ceiling.

#### Added: slow drift handling in adaptive τ
- At low frequency the amplitude can keep drifting after the lock-ins settle (sample/cell warming up, pressure equalising); a larger τ does not fix that. The fluctuation is now split into a **random** part (SD, falls with τ) and a **drift** part (difference between the halves of the average). When drift dominates and exceeds Precision, the point is averaged again with the same τ and no new wait, up to 4 times, until it stops (status: *drift S … (OPT101 …, microphone …): redoing the average…*, also in the log). τ follows only the random part.
- New CSV columns `Deriva_S_Pct`, `Deriva_Fase_Graus`, `Deriva_OPT101_Pct`, `Deriva_INMP441_Pct` (signed, last average of the point): drift in the OPT101 means light (laser/LED), drift only in the microphone means sample/cell. `Refeito` counts both kinds of redo.

#### Added: Signal vs t (s), and renamed Dual Mode buttons
- Top row of the Dual Mode: **Signal vs f (Hz) ▸** (was *Sweep*), Fit, Open sweep…, Calibration, **Signal vs PWM (%) ▸** (the matched PWM sweep, was a sub-button inside *Sweep*) and the new **Signal vs t (s) ▸**. Box titles follow the same names.
- **Signal vs t**: fixed frequency, PWM and τ; every *Point every* seconds it records the mean and SD of OPT101 R, microphone R and both phases (S and Δφ plotted vs time with ±1 SD error bars, sensor signals in *Show each sensor*), for *Duration* minutes (0 = until Stop). The first 7τ (lock-in settling) are discarded; time counts from the start. Results: change of S, Δφ, OPT101 and microphone between start and end, drift of S in the last third (%/min) and a fit S(t) = A + B·e^(−t/T). CSV `…_DUPLO_tempo_f…Hz_pwm…` (first column `Tempo_s`, per-point and drift columns) + PNG; **Open sweep…** reads it back. Electronic modulation only.
- Headless: `soi_controller.py --sinal-t --f HZ --pwm % --tau S --dt S --duracao MIN [--desligar]`; `--desligar` (also for `--varredura`) sets PWM 0 at the end. `campanha_deriva.bat [sample]`: overnight drift campaign (~7.5 h; 10 blocks of 10 min at PWM 0 + 20 min at 10 Hz 100/50/25 % and at 5, 30, 100, 300, 1000, 2000 Hz, plus 60 min at 10 Hz; then adaptive sweeps at Precision 1, 2 and 4 %).
- Adaptive τ: drift is now only recorded (`Deriva_*` columns), not waited for (`ADAPT_MAX_DRIFT_WAIT = 0`): 4 extra averages held a 6 Hz point for minutes. A new rule will come from the drift campaign.

#### Changed: fit boxes instead of the Fit button
- The **Fit ▸** button is gone: its box (model, target, thickness, range, mark peak) is now a column to the right of the **Signal vs f** box, active whenever a model is chosen.
- **Signal vs PWM** gets its own **Fit** box: polynomial of degree 1, 2 or 3 (or none) on INMP441 × OPT101 (left plot), OPT101 × PWM (right plot) or both, with coefficients ± error, R² and the maximum deviation; written to the CSV header. Signal vs t has no fit box (its Results keep the start/end change and the exponential).

#### Added: low-frequency mode of adaptive τ and warning below 40 Hz
- **Why:** the drift campaign of 2026-11-16/17 showed that below ~40 Hz the room's acoustic noise (additive, slow) dominates; the fluctuation measured in a point underestimates the real error there and adaptive τ never converges.
- New check box **only f > 40 Hz** next to **adaptive τ** (on by default): adaptive τ applies only above 40 Hz; below, τ is preset per band (8 s below 15 Hz, 4 s from 15 to 40 Hz; 7τ wait, 3τ average) and adaptive τ restarts from 1 s above 40 Hz. Recorded in the CSV header. Headless: `--adapt-tudo` turns it off.
- Orange text **high SNR at f < 40 Hz** next to the range when the sweep goes below 40 Hz, and a warning (OK/Cancel) at the start of a frequency sweep or calibration with points below 40 Hz.

#### Added: wait for warm-up before sweeps
- **Why:** after the laser turns on, the photoacoustic signal drops ~14 % with a ~4.4 min time constant (10 Hz, campaign of 2026-11-16/17) while the sample and the cell warm up.
- Every sweep box (OPT101, INMP441 and Dual Mode: frequency, PWM, Signal vs t) has **Wait for warm-up** with a time field (default 300 s): the laser goes on at the measurement PWM (the highest PWM in a PWM sweep) and the sweep starts after the wait; the button shows the countdown and cancels. Headless: `--aquecer S`.
- The time label shows one text: **Estimated time xx:xx (+warm-up yy:yy)**, with the warm-up counting down during the wait. Before, it alternated between the warm-up and the estimated time and moved part of the window; the label now sits at the end of the row (after the warm-up field) and wraps instead of widening the window (2026-11-17).

#### Changed: adaptive τ capped at 4 s
- The adaptive τ never goes above **4 s** (initial τ, increases and redos). The preset τ below 40 Hz is now 4 s in the whole band (was 8 s below 15 Hz and 4 s from 15 to 40 Hz) (2026-11-17).

#### Added: Allow averaging (adaptive τ)
- **Why:** above ~4 s what remains is slow drift, which a longer τ does not remove.
- **Allow averaging × N** (default 3) next to Precision: when the adaptive τ is already at 4 s and the fluctuation is still above Precision, the point takes another measurement with the same τ (no new settling, nothing discarded) instead of raising τ, up to N, and records the mean of all. Below 40 Hz (preset τ) every point takes N measurements. The extra measurements count in the `Refeito` column; the CSV header records the option. Headless: `--medias N` (2026-11-17).

#### Added: SNR indicator in the top bar
- **SNR OPT/INMP (dB)** between Cell and Settings, updated every second: SNR = 20·log10(|⟨Z⟩|/σ) of each lock-in output Z = X + jY over the last 10τ (4 to 30 s), σ = standard deviation per quadrature (same criterion as the INMP441 Noise/SNR plot). Each value is green ≥ 30 dB (noise ≤ ~3 % of the signal), yellow ≥ 20 dB (~3–10 %), red below (2026-11-17).

#### Changed: double-click auto-range in the Dual Mode plots
- Double-click on a Dual Mode plot sets x to the sweep range and y to the measured points only (theory curves, fits, models and the out-of-calibration regions no longer stretch the axes). The same y rule is used while the sweep runs (2026-11-17).

#### Added: warning in the Fit box without calibration
- With the calibration not applied ("Use" unchecked, or signal not normalized by the OPT101) the Fit box shows an orange warning that the models only make sense with the calibrated signal; fits are still allowed (2026-11-17).
- The Frequency sweep and Fit boxes have the same height, and the warning wraps inside the Fit box (2026-11-17).

#### Changed: calibration display options
- The **Advanced** button next to **Generate calibration** is gone (the OPT101 sensor τ row only appears if a non-zero τ was saved). In its place: **Show calibration error bars** and **Uncalibrated region in red**, both off by default. With the second off, points outside the calibrated range appear hollow in the normal colour, without the reddish background. Both are saved and restored in the next session (2026-11-17).

#### Changed: SNR OPT/INMP colour limits
- Green ≥ 25 dB, yellow 15–25 dB, red < 15 dB (were 30/20 dB), from the point-error analysis of the 17/11 measurements: ≥ 25 dB is already near the ~7 % low-frequency floor, 15–25 dB gives ~10–25 % per point, < 15 dB ≳ 40 % (2026-11-17).

#### Changed: CSV states when the calibration was not applied
- Dual Mode frequency-sweep CSVs now always say whether the microphone calibration was applied to the plot/fit: besides the existing calibration-file line, a "not applied" line with the reason ("Use" unchecked, no OPT101 normalization, or no valid calibration). The data columns are raw in both cases (2026-11-17).

#### Changed: sweep τ is remembered
- The frequency-sweep τ / τ max (linked to the INMP441 τ) now reopens with the last value used instead of the 4 s default; the default is used only when nothing was saved (2026-11-17).

#### Changed: sweep τ field is "τ" or "τ max"
- In the frequency sweeps the τ field is labelled "τ" (fixed τ) with adaptive τ off, and "τ max" with it on. With adaptive τ it now sets the ceiling: the sweep starts at τ max and never goes above it (also the preset τ below 40 Hz and the trigger for "Allow averages"); the fixed 4 s cap is now just the default value. CSV header writes "tau max" (old files with "tau inicial" still load); `--tau` in the windowless sweep is τ max with adaptive τ (2026-11-17).

#### Added: "Resonance shifted" warning
- With a calibration applied, the Dual Mode compares the cell resonance of the sweep with the calibration's (from the file, or from the peak of its sensitivity curve). If they differ by more than 5 % (or 1.5 sweep steps), or the resonance shows up in only one of them, a red "⚠ Resonance shifted: check the cell assembly" badge appears in the options row (reason in the tooltip) and a status message is flashed (2026-11-17).

#### Changed: manual zoom in the Dual Mode plots is kept
- If the user zooms or pans a Dual Mode plot, new points no longer reset the axes; the automatic range comes back with a double-click or a new measurement (2026-11-17).

#### Changed: floating Results box removed
- The movable "Results" box over the Dual Mode plots is gone. Its ⚠ warnings (wrong cell, unverified/legacy calibration, resonance mismatch) now appear as an orange "⚠ N measurement warning(s)" indicator next to "Show each sensor's signals", with the full text in the tooltip; purely informative lines were dropped (fit results stay in the Fit box) (2026-11-17).

#### Added: one-click PWM buttons
- **Why:** aligning the optics means switching the laser off, to 10 % or to 100 % many times.
- Segmented buttons **0 / 10 / [PWM field] / 100** next to the PWM field: one click applies the value; the button of the current PWM turns blue (none lights with a typed intermediate value). They follow the field: disabled during sweeps and hidden in optical modulation (2026-11-17).

#### Changed: Dual Mode layout
- **Calibration ▸** is now the last button on the right (Sweep, Fit, Open sweep…, Calibration).
- The mounting diagram (Chamber/OPC) moved from the calibration box to the **Frequency sweep** box, The fluctuation of S and Δφ of the point being measured (updated every second) and of the last point, with the τ in use, appears in a status bar at the top of the Dual Mode tab, like the sensor tabs (green within Precision, yellow up to 2×, red above). **Measure A/B** opens the Sweep panel.
- Frequency sweep plots show **error bars** (±1 SD) on S and Δφ, as the matched PWM sweep already did.
- The x axis of the Dual Mode plots follows the sweep range (planned + measured points; Signal vs t: 0 to the duration) instead of starting at ~1 Hz when the first points arrive; auto-range stays on the y axis (2026-11-17).
- With a calibration applied, frequency sweep points outside the calibrated range are no longer hidden: the plots of S and Δφ get a **reddish background** outside that range (shown already before the sweep), and those points appear as hollow red markers, corrected with the value at the calibration edge and left out of the fits and of the verification. Sweeps outside the calibrated range stay allowed (2026-11-17).

#### Added: Settings window
- **⚙ Settings** button at the end of the excitation bar, in place of **Finish experiment** (which moved into the window). The window has the lock-in trigger (electronic or optical), the OPT101 supply and Finish experiment, each with a short explanation.
- **OPT101 supply:** 3.3 V (default; output up to ≈ 2.0 V) or 5 V (output up to ≈ 3.7 V, above the ADC; adjust gain or light for a ≈ 3.0 V peak). Choosing 5 V asks for confirmation and shows a warning: PA0 needs a 1 kΩ series resistor and a BAT54 Schottky diode to 3.3 V, or the STM32 can burn. The choice is remembered.
- **OPT101 scope in volts at PA0** (replaces the ADC counts axis), with a red dashed line **Max OPT101 output** at the signal ceiling: 2.0 V with the 3.3 V supply (OPT101 saturation) or 3.3 V with 5 V (ADC limit). The axis follows the signal as before, so the line is out of view with a low signal; from 80 % of the ceiling the axis takes in the line. Option **Oscilloscope scale fixed from 0 to 3.3 V** (off by default).
- **Status bar:** **Peak** in % of the ceiling and in volts (replaces **%ADC**): orange from 80 %, red from 90 % with *Near OPT101 saturation* / *OPT101 SATURATION* (3.3 V) or *Near the ADC limit* (5 V). *Low signal* is now a mean level below 5 % of the ceiling.

## [2.2.0] - 2026-11-13

Minor version: only the interface changes. The firmware is still 2.0.0 (`binarios/soi_firmware_v2.0.0.bin`) and the USB protocol is the same. Old calibrations and sweeps still open and apply.

### Interface (`interface/soi_controller.py`)

#### Changed: calibration with two samples (replaces the single-reference calibration)
- **Why:** a single reference cannot be checked by itself. On 2026-11-13 a carbon-black calibration (its raw signal rose ≈ f^+0.9, mounted at another height) produced a false f⁻² in Al and stainless steel.
- **How:** the Calibration panel now asks for **Sample A** and **Sample B**, two materials measured in the same setup. Both follow S = K·H(f)·f⁻ⁿ (n = 1 in the chamber, opaque thick metal; n = 1.5 in OPC, thin foil), so the ratio S_A/S_B must be a complex constant. The widest range where it is constant (|slope| ≤ 0.15, ≤ 1.5 dB rms, phase ± 10° rms, at least one decade) is the verification. The calibration is M(f) = √(S_A·S_B)·fⁿ, normalized by the flat range; the system phase is the mean of both Δφ. Every new calibration is born verified or not verified; the separate "Verify with this measurement" step is gone.
- **Materials:** chamber: aluminium, stainless steel (304/316/316L), titanium, nickel, brass, graphite; OPC: Al foil 12 µm, Al foil 25 µm, Cu foil 35 µm. The Sample B list shows in **green** the materials recommended as a pair for A (α at least 3× different in the chamber; f_c = α/(πL²) at least 3× different in OPC) and in **red** those that are not (same material, or similar α, e.g. Ti with stainless steel), with the reason in the tooltip. Red ones can still be used; the calibration file then records a warning.
- **Thickness check:** chamber, L ≥ 2μ at the lowest frequency (μ = √(α/πf)); OPC, f_c ≥ 10× the highest frequency.
- **Buttons per sample:** **▶ Measure** (loads the calibration sweep parameters, runs the frequency sweep and stores it), **Use current** (the sweep on screen) and **Open…** (a saved `*DUPLO_freq_*.csv`, refused if it was made in another cell).
- **CAL file:** named `CAL_<A>-<B>_microfone_<cell>_..._<date>.csv`, with new header keys `Metodo = duas_amostras`, `Amostra_A`, `Amostra_B`, `Razao_AB` and `Faixa_concordancia_Hz`, and a new last column `Concorda` (1 inside the range where the two samples agree). When a measurement uses points outside that range, the interface warns that the correction was not verified there. Files without the column load as before.
- **Resonance check:** if the cell resonance of A and B differ by more than 3 %, the result says the samples probably have different heights.
- **Simulation:** with "Simulate sampling", Measure A/B simulates the chosen material (different K, same system response), so the whole flow can be tested without the STM32.

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
