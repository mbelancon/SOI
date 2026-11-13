# SOI 2.1.0: test procedure (calibration references and reorganized Dual Mode)

Firmware: the same as 2.0.0. Run the interface with `python interface/soi_controller.py`.

1. **Language.** With Windows in Portuguese the interface opens in Portuguese; with any other language, in English. `set SOI_LANG=en` (or `pt`) before starting forces one.
2. **Open an old sweep.** Dual Mode → Open sweep… → a `*_DUPLO_freq_*.csv`. Open **Calibration ▸**. Change the **Reference** and check that the diagram, the tips, the expected curve and the **Cell** (top row) change together.
3. **Generate calibration curve** (with **Use** unticked). Check in the Medidas folder the name `CAL_…_microfone_<OPC|Camara>_…`, the `Referencia`, `Celula` and `Verificada` lines in the CSV, and the PNG title.
4. **Use the calibration.** Tick **Use**: the corrected S should follow the reference curve and the phase should be constant. Switch the Cell to the other configuration: the different-cell warning should appear. A non-verified calibration shows ⚠ in the list and a red warning.
5. **Verify.** With **Use** ticked, open a sweep of a second reference, choose it in **Reference** and click **Verify with this measurement**. Check the result line and the `# Verificada` line in the calibration file.
6. **Old calibration.** A `CAL_microfone_*.csv` from 2.0.0 should appear as `[OPC]`.
7. **Resonance.** Untick **Use**, open **Fit ▸**, choose "Cell resonance". Without a Range, the peak should be found automatically; with "Mark peak (2 clicks)", two clicks on the left plot fill in the Range. Check f₀, Q, width and gain. Reference for the new cell (2026-11-10, 35 points): f₀ ≈ 1.57 kHz, Q ≈ 6.5.
8. **Range with S ∝ f⁻ⁿ.** In **Fit ▸**, choose this model with the expected n; the range found should be shaded on both plots.
9. **Chamber models.** "Chamber: opaque sample" and "Chamber: transparent" should draw the curve and show the residuals.
10. **Preferences.** Close and reopen: reference, L, α, n, Range and Cell should come back as they were.
