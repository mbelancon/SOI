# Measurements of 2026-11-17

Raw files written by the SOI Controller (interface 2.3.0 development builds, firmware 2.0.0), chamber cell,
532 nm laser at PWM 100 %, Dual Mode frequency sweeps 40–2440 Hz with 35 points. Discussed in
[docs/07_Calibration.md](../../docs/07_Calibration.md) and [docs/08_Measurement_Examples.md](../../docs/08_Measurement_Examples.md).

- `CAL_Al-Inox_…csv`: two-sample calibration (Al 10 mm × stainless steel 316L 3 mm). In this copy the thicknesses in
  the header were corrected to the real values (see the `# Correcao_espessuras` line).
- `*_DUPLO_freq_…csv`: one sweep per sample. Columns and header keys are in Portuguese, as in the interface:
  `Frequencia_Hz`, `OPT101_R`, `INMP441_R`, `*_DP` (1 SD), `*_Fase_Graus`, plus per-point τ and fluctuation.
  The data are raw; the calibration named in the header was applied only to the plot and fit.
- `make_figures.py`: regenerates the figures in `docs/images/` (`python examples/2026-11-17/make_figures.py`).

Open any sweep in the interface with **Open sweep…** (Dual Mode tab) to see it, apply the calibration and fit models.
