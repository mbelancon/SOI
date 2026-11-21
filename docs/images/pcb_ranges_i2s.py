"""Figure for docs/09_PCB_Requirements.md: OPT101 gain ranges and I2S cable timing budget.

Estimates only (assumptions in the doc and below). Run: python pcb_ranges_i2s.py
"""
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import font_manager
from cycler import cycler

CORES = ['dodgerblue', 'coral', 'palegreen', 'gold', 'violet']
nomes = {f.name for f in font_manager.fontManager.ttflist}
plt.rcParams['font.family'] = next((n for n in ('Times New Roman', 'Liberation Serif') if n in nomes), 'serif')
plt.rcParams.update({'mathtext.fontset': 'stix', 'font.size': 12, 'axes.prop_cycle': cycler(color=CORES),
                     'xtick.direction': 'in', 'ytick.direction': 'in', 'xtick.top': True,
                     'legend.frameon': False, 'savefig.dpi': 300, 'savefig.bbox': 'tight'})

# (a) OPT101 ranges. Full scale = 2.0 V at the OPT101 output (Vs = 3.3 V), responsivity ~0.30 A/W at 532 nm.
# Bandwidth: 14 kHz at 1 MOhm (datasheet); TIA scaling f ~ 1/sqrt(Rf) as a first estimate.
R = np.logspace(4, 7.3, 200)
resp = 0.30
p_fs = 2.0 / (R * resp) * 1e6                  # uW
bw = 14e3 * np.sqrt(1e6 / R)                   # Hz
rng = np.array([1e4, 1e5, 1e6, 1e7])

fig, (a, b) = plt.subplots(1, 2, figsize=(10, 3.8))
a.loglog(R, p_fs, color='dodgerblue', label='Full-scale power (532 nm)')
a.loglog(rng, 2.0 / (rng * resp) * 1e6, 'o', color='dodgerblue')
a.set_xlabel(r'Feedback resistor $R_f$ ($\Omega$)')
a.set_ylabel(r'Full-scale optical power ($\mu$W)', color='dodgerblue')
for r in rng:
    a.annotate({1e4: '10 k', 1e5: '100 k', 1e6: '1 M', 1e7: '10 M'}[r], (r, 2.0 / (r * resp) * 1e6),
               textcoords='offset points', xytext=(6, 4), fontsize=10)
a2 = a.twinx()
a2.loglog(R, bw / 1e3, '--', color='coral', label='Bandwidth (estimate)')
a2.axhline(5, color='gray', lw=0.8, ls=':')
a2.text(1.2e4, 5.4, 'max. modulation 5 kHz', fontsize=9, color='gray')
a2.set_ylabel('Bandwidth (kHz)', color='coral')
a.set_ylim(0.1, 3000); a2.set_ylim(1, 300)
a.set_title('(a) OPT101 gain ranges', fontsize=12)
h1, l1 = a.get_legend_handles_labels(); h2, l2 = a2.get_legend_handles_labels()
a.legend(h1 + h2, l1 + l2, loc='lower left', fontsize=10)

# (b) I2S timing: BCLK 3.072 MHz -> half period 163 ns. STM32 samples SD on the rising edge;
# the microphone changes SD after the falling edge.
L = np.linspace(0, 5, 200)
half = 1e9 / (2 * 3.072e6)
t_mic, t_setup, t_pd = 60.0, 5.0, 5.0          # ns, ns, ns/m (assumed)
c_m = 100e-12                                   # F/m, unshielded multi-core (twisted pair ~50 pF/m)
direct = half - t_mic - t_setup - 2 * t_pd * L - 0.69 * 200 * c_m * L * 1e9   # weak SD driver ~200 Ohm (assumed)
buffered = half - t_mic - t_setup - 8 - 2 * t_pd * L - 0.69 * 25 * c_m * L * 1e9
b.plot(L, direct, color='dodgerblue', label='Microphone drives the cable')
b.plot(L, buffered, color='coral', label='Buffer on the microphone board')
b.axhline(0, color='k', lw=0.8)
b.axvspan(0, 1, color='palegreen', alpha=0.35, lw=0)
b.text(0.08, -32, 'recommended $\\leq$ 1 m', fontsize=10)
b.set_xlabel('Cable length (m)')
b.set_ylabel('Timing margin (ns)')
b.set_xlim(0, 5); b.set_ylim(-40, 110)
b.set_title('(b) I2S timing budget (BCLK 3.07 MHz)', fontsize=12)
b.legend(loc='upper right', fontsize=10)

fig.tight_layout()
fig.savefig('pcb_ranges_i2s.png')
