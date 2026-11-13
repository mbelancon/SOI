# 6. Performance and applications

This guide summarizes what the system can measure in time with the optical channel (OPT101) and evaluates, with numbers, three applications: **thermal lens**, **thermal mirror** and **luminescence decay**. Acquisition values come from the firmware ([`main.c`](../firmware/src/main.c)) and the interface ([`soi_controller.py`](../interface/soi_controller.py)). OPT101 values come from the Texas Instruments datasheet, for the internal 1 MΩ resistor.

> The application estimates below are design estimates, not validation measurements. Before publishing results based on them, check the system response with a sample of known time constant.

## Optical acquisition chain

| Stage | Value | Effect in time |
|---|---|---|
| STM32 ADC (PA0) | 12 bits, **200 kS/s**, triggered by TIM3; 84-cycle sampling at 21 MHz (4 µs) | Each sample instant fixed by the crystal, no jitter |
| Oversampling (in the interface, 2.0.0) | Average of OSR samples, OSR 1 to 64; default 16 → **12.5 kS/s** (scale 0 to 16,380) | Each point is the average over OSR × 5 µs (**80 µs** with OSR 16; 5 µs with OSR 1) |
| Laser reference | Laser state recorded by DMA with each ADC sample; majority of the OSR samples per point | The laser edge is known in steps of OSR × 5 µs (5 µs with OSR 1) |
| USB CDC (ST stack) | 400 kB/s optical + ≈146 kB/s audio ≈ **550 kB/s** | Half of the ~1.1 MB/s measured on the Black Pill |
| OPT101, internal 1 MΩ | **14 kHz** bandwidth, rise time (10–90 %) ≈ **28 µs**, 0.45 A/W at 650 nm | Smooths edges faster than ~30 µs |
| Laser modulation (TIM4) | 50 % square wave, **0.1 to 5000 Hz**, 95 ns resolution | Defines the window of each pulse |
| Laser PWM (TIM1, PA8) | **5 kHz** carrier (200 µs period) | Below 100 % the "on" light is chopped at 5 kHz |

**Intensity scale.** With the 1 MΩ resistor, one count (≈ 0.20 mV) corresponds to ≈ 0.45 nW at 650 nm, and full scale (3.3 V) to ≈ 7 µW. Responsivity drops at the edges of the silicon range: the OPT101 responds from ~300 to 1100 nm, with little signal above ~1000 nm.

## Time-domain measurements: Valor Médio mode

In the OPT101 tab, **Valor Médio** (average) mode averages the ADC waveform over N pulses (1 to 1000), aligned on the laser rising edge, with adjustable pre-trigger. **Análise da curva** (curve analysis) fits 1 or 2 exponentials to the *On* or *Off* segment and shows τ and R².

**Effective time resolution.** Three effects add up (values for the default OSR 16):

1. each point is an 80 µs average;
2. the laser edge is only located in 80 µs steps. If the modulation period is not an exact multiple of 80 µs, the alignment varies from pulse to pulse and averaging broadens the edge by up to 80 µs (≈ 23 µs rms);
3. the OPT101 rise time, ≈ 28 µs.

The result is a system response with a rise time on the order of **0.1 ms** (smaller OSR shortens items 1 and 2). In practice:

| Time constant τ | Situation |
|---|---|
| τ ≥ 0.5 ms | Direct measurement, with at least ~6 points per τ and small shape error |
| 0.1 ms ≤ τ < 0.5 ms | Possible, but the fit must skip the first ~0.1–0.2 ms after the edge or convolve the model with the system response |
| τ < 0.1 ms | Out of reach of Valor Médio mode |

**What limits the maximum τ.** The decay must finish within the half-period in which the laser is off (or on): half-period ≥ 5τ, i.e. f ≤ 1/(10τ). With the minimum f of 0.1 Hz, this reaches τ ≈ 1 s.

**Precautions.**
- Use **PWM = 100 %** for time-domain measurements. With lower PWM, the 5 kHz carrier shows up as a 200 µs ripple on the signal.
- Choose f so that the period is a multiple of the point spacing (with OSR 16, 80 µs: e.g. 25 Hz = 40 ms, 50 Hz, 125 Hz), so the edge always falls on the same point and averaging does not broaden the rise.
- The laser and driver themselves have a rise time. Measure the laser light directly on the OPT101 to know the response of the whole chain before interpreting short τ.
- Averaging N pulses reduces random noise by √N.

## Frequency-domain measurements: lock-in

The OPT101 lock-in gives magnitude and phase at the fundamental modulation frequency, up to **5 kHz**. For a first-order process, tan φ = 2πfτ, so phase versus frequency measures τ without having to resolve the edge in time. The interface already compensates the digital delay of the reference (constant `OPT_REF_DELAY`). The remaining delays (oversampling boxcar and OPT101 bandwidth) are the same for any sample and can be removed by measuring the laser light directly, without a sample.

In principle, this extends the reach to **τ of a few tens of µs** (at 5 kHz, τ = 30 µs gives φ ≈ 43°). It has not yet been validated on the system. The frequency sweep in the OPT101 tab already performs this measurement, and the model fitting in Modo Duplo is a starting point.

## Applications

### Thermal lens

The characteristic time is t_c = w²/(4D), where w is the excitation beam radius at the sample and D is the thermal diffusivity.

| Sample | D (m²/s) | w = 50 µm | w = 100 µm | w = 200 µm |
|---|---|---|---|---|
| Water | 1.4 × 10⁻⁷ | 4.5 ms | 18 ms | 71 ms |
| Ethanol | 0.9 × 10⁻⁷ | 7 ms | 28 ms | 110 ms |
| Polymers (PMMA) | 1.1 × 10⁻⁷ | 6 ms | 23 ms | 90 ms |
| Optical glasses | 4–6 × 10⁻⁷ | 1–1.6 ms | 4–6 ms | 17–25 ms |

**Conclusion: measurable.** All these values are well above 0.5 ms. The transient fits in a 1 to 20 Hz modulation and is resolved with tens to hundreds of points. Only very tightly focused beams (w ≲ 25 µm) in glasses get close to the limit.

Setup: the OPT101 measures the probe beam intensity at the center, behind a pinhole. The laser modulated by the STM32 is the excitation beam. Transient analysis (Shen model) is not yet in the interface; for now, export the Valor Médio CSV and fit it elsewhere.

### Thermal mirror

The characteristic time has the same form, t_c = w²/(4D), but D is that of the opaque or surface-absorbing sample:

| Sample | D (m²/s) | w = 100 µm | w = 500 µm |
|---|---|---|---|
| Glasses and polymers | 1–6 × 10⁻⁷ | 4–25 ms | 0.1–0.6 s |
| Semiconductors (Si) | 8.8 × 10⁻⁵ | 28 µs | 0.7 ms |
| Metals (Al) | 9.7 × 10⁻⁵ | 26 µs | 0.6 ms |

**Conclusion: measurable for glasses, polymers and low-diffusivity materials.** In metals and semiconductors, t_c is below 0.1 ms with ~100 µm beams. In those cases, increase w (≳ 0.5 mm) or use the frequency-domain lock-in.

### Luminescence decay

The OPT101 measures the sample luminescence, with a filter that blocks the excitation light. The modulated laser excites, and the decay is observed during the off half-period.

| Emitter | Typical lifetime | Wavelength | Situation |
|---|---|---|---|
| Eu³⁺ (⁵D₀ → ⁷F₂) | 0.5–2 ms | ~612 nm | Measurable |
| Tb³⁺ (⁵D₄) | 1–3 ms | ~545 nm | Measurable |
| Cr³⁺ (ruby) | ~3 ms | 694 nm | Measurable |
| Mn²⁺ | 1–20 ms | 500–650 nm | Measurable |
| Yb³⁺ | 0.5–2 ms | ~980 nm | Measurable, with reduced sensitivity |
| Nd³⁺ (⁴F₃/₂) | 0.1–0.4 ms | 880 / 1064 nm | At the limit: short lifetime and weak silicon response at 1064 nm |
| Er³⁺ (⁴I₁₃/₂) | 2–10 ms | ~1530 nm | **No**: outside the silicon range (needs an InGaAs detector) |
| Organic dyes, quantum dots, fluorescence in general | ns to tens of ns | visible | **No**: ~10⁴ times faster than the resolution |

**Conclusion: the system works for lifetimes from ~0.2 ms to ~1 s.** That covers rare-earth ions and transition metals emitting in the visible and near infrared up to ~1000 nm. Nanosecond fluorescence and emission beyond 1100 nm are out of reach.

**Signal.** Luminescence is usually weak. One ADC count corresponds to ≈ 0.45 nW at 650 nm. Signals of a few nW need many averages (noise falls as √N) or a larger external feedback resistor on the OPT101, which raises the gain but reduces the bandwidth.

## Going further

These changes are not implemented and would require changing firmware and interface together:

- **Higher optical rate.** Done in 2.0.0: the firmware sends the raw 200 kS/s and the oversampling is chosen in the interface (OSR 1 = 200 kS/s, 5 µs points).
- **Exact reference edge.** With OSR 1 the edge is already known in 5 µs steps. Recording the exact edge instant (as in the INMP441 marker) would only matter at high OSR.
- **Faster detector.** Below ~30 µs, the OPT101 becomes the limit. A photodiode with a faster transimpedance amplifier and an external ADC would be needed.
