"""Figures of docs/07_Calibration.md and docs/08_Examples.md from the CSV files in this folder.

Run from anywhere:  python examples/2026-11-17/make_figures.py
Writes PNGs to docs/images/. Needs numpy and matplotlib.
The CSVs are the raw files written by the SOI Controller (Dual Mode frequency sweeps and the
microphone calibration); column names and header keys are in Portuguese, as in the interface.
"""
import csv
import glob
import os

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from cycler import cycler

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', '..', 'docs', 'images')
COLORS = ['dodgerblue', 'coral', 'palegreen', 'gold', 'violet', 'gray', 'saddlebrown', 'teal']
EDGE = {'palegreen': 'forestgreen', 'gold': 'darkgoldenrod'}


def style():
    names = {f.name for f in font_manager.fontManager.ttflist}
    font = next((n for n in ('Times New Roman', 'Liberation Serif', 'Nimbus Roman', 'DejaVu Serif') if n in names),
                'serif')
    plt.rcParams.update({'font.family': font, 'mathtext.fontset': 'stix', 'font.size': 12,
                         'axes.prop_cycle': cycler(color=COLORS), 'xtick.direction': 'in',
                         'ytick.direction': 'in', 'xtick.top': True, 'ytick.right': True,
                         'legend.frameon': False, 'savefig.bbox': 'tight'})


def edge(c):
    return EDGE.get(c, c)


def load(pattern):
    path = glob.glob(os.path.join(HERE, pattern))[0]
    lines = [ln for ln in open(path, encoding='utf-8', errors='replace') if not ln.startswith('#')]
    rows = list(csv.DictReader(lines))
    return {k: np.array([float(r[k]) if r[k] not in ('', 'nan', None) else np.nan for r in rows])
            for k in rows[0] if k}


def S(d):
    """Normalized photoacoustic signal S = R_INMP441 / R_OPT101."""
    return d['INMP441_R'] / d['OPT101_R']


def dphi(d):
    return np.degrees(np.unwrap(np.radians(d['INMP441_Fase_Graus'] - d['OPT101_Fase_Graus'])))


def finish(ax):
    ax.grid(True, which='major', color='#d8d8d4', lw=0.5)
    ax.grid(True, which='minor', color='#eeeeea', lw=0.3)
    ax.tick_params(which='both', direction='in', top=True, right=True)


def save(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, name), dpi=150)
    plt.close(fig)


def fig_calibration(cal):
    a, b = load('Al_DUPLO*.csv'), load('Inox_DUPLO*.csv')
    f = a['Frequencia_Hz']
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.6))
    for d, lab, c, m in ((a, 'Al (10 mm)', COLORS[0], 'o'), (b, 'Stainless steel 316L (3 mm)', COLORS[1], 's')):
        sf = S(d) * f
        a1.plot(f, sf / np.nanmedian(sf), color=c, marker=m, ms=5, lw=0, mfc='none', label=f'{lab}: S·f')
    r = S(a) / S(b)
    a1.plot(f, r / np.nanmedian(r), color='k', marker='.', ms=6, lw=1, label='ratio S$_A$/S$_B$ (normalized)')
    a1.axvline(cal_f0(cal), color='#999', ls='--', lw=0.8)
    a1.text(cal_f0(cal) * 1.05, 0.2, 'cell\nresonance', fontsize=10, color='#666')
    a1.set_xscale('log'); a1.set_yscale('log'); a1.set_ylim(0.15, 80)
    a1.set_xlabel('Frequency (Hz)'); a1.set_ylabel('Relative value')
    a1.set_title('(a) Two references, same mounting', loc='left'); a1.legend(fontsize=10, loc='upper left')
    cf, M, Me, ph = cal['Frequencia_Hz'], cal['Sensibilidade_Rel'], cal['Sensibilidade_Rel_DP'], cal['Fase_Sistema_Graus']
    a2.errorbar(cf, M, yerr=Me, color=COLORS[0], mec=edge(COLORS[0]), marker='o', ms=4, lw=1, capsize=2,
                label='M(f) = √(S$_A$·S$_B$)·f')
    a2.set_xscale('log'); a2.set_yscale('log'); a2.set_xlabel('Frequency (Hz)')
    a2.set_ylabel('Relative response M(f) of microphone + cell')
    b2 = a2.twinx()
    b2.plot(cf, ph, color=COLORS[1], marker='s', ms=3, lw=0.8, label='system phase')
    b2.set_ylabel('System phase (°)', color=edge(COLORS[1])); b2.tick_params(direction='in')
    a2.set_title('(b) Stored calibration (CAL Al × stainless)', loc='left')
    h1, l1 = a2.get_legend_handles_labels(); h2, l2 = b2.get_legend_handles_labels()
    a2.legend(h1 + h2, l1 + l2, fontsize=10, loc='center left', bbox_to_anchor=(0.2, 0.62))
    for ax in (a1, a2):
        finish(ax)
    save(fig, 'calibration_20261117.png')


def cal_f0(cal_path_dict):
    for ln in open(glob.glob(os.path.join(HERE, 'CAL_*.csv'))[0], encoding='utf-8'):
        if ln.startswith('# Ressonancia_f0_Hz'):
            return float(ln.split('=')[1])
    return np.nan


def fig_metals(cal):
    cf, M, cv = cal['Frequencia_Hz'], cal['Sensibilidade_Rel'], cal['Valido'] > 0.5
    series = [('Al (10 mm)', 'Al_DUPLO*.csv', COLORS[0], 'o', True),
              ('Stainless 316L (3 mm)', 'Inox_DUPLO*.csv', COLORS[1], 's', True),
              ('Ni (10 mm), adaptive τ', 'Ni_DUPLO*.csv', COLORS[2], '^', False),
              ('Ni (10 mm), τ = 1 s', 'Ni_Fast*.csv', COLORS[3], 'D', False),
              ('Ti (1 mm)', 'Ti_DUPLO*.csv', COLORS[4], 'v', False),
              ('Brass (10 mm)', 'Latao_DUPLO*.csv', COLORS[5], 'P', False),
              ('Al kitchen foil', 'Al_Papel*.csv', COLORS[6], 'X', False)]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 5), sharey=True)
    out = []
    for lab, pat, c, m, ref in series:
        d = load(pat); f = d['Frequencia_Hz']; s = S(d)
        kw = dict(color=c, mec=edge(c), marker=m, ms=6, lw=0, mfc='none' if ref else c, mew=1.0)
        a1.plot(f, s / s.max(), label=lab, **kw)
        ok = np.interp(f, cf, cv.astype(float)) > 0.5
        sc = s / np.interp(f, cf, M); sc = sc / sc[ok].max()
        a2.plot(f[ok], sc[ok], **kw)
        p, cov = np.polyfit(np.log10(f[ok]), np.log10(sc[ok]), 1, cov=True)
        n, un = -p[0], np.sqrt(cov[0, 0])
        ff = np.geomspace(f[ok].min(), f[ok].max(), 50)
        a2.plot(ff, 10 ** np.polyval(p, np.log10(ff)), color=edge(c), lw=1.2, label=f'{lab}: n = {n:.2f} ± {un:.2f}')
        out.append((lab, round(n, 2), round(un, 2)))
    d = load('Ni_Furo*.csv')
    a1.plot(d['Frequencia_Hz'], S(d) / S(d).max(), 'k.', ms=6, mfc='none', label='Ni, vent hole open (diagnostic)')
    for ax in (a1, a2):
        ax.set_xscale('log'); ax.set_yscale('log'); ax.set_xlabel('Frequency (Hz)'); finish(ax)
    a1.set_ylabel('Normalized signal  S/S$_{max}$')
    a1.set_title('(a) Raw signal  S = R$_{mic}$/R$_{OPT101}$', loc='left')
    a2.set_title('(b) Calibrated and fit  $S \\propto f^{-n}$', loc='left')
    a1.legend(fontsize=10, loc='lower left'); a2.legend(fontsize=10, loc='lower left')
    save(fig, 'metals_20261117.png')
    return out


def fig_ni_film(cal):
    M = cal['Sensibilidade_Rel']
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.6))
    ref = None
    for lab, pat, c, m in (('Ni (τ = 1 s)', 'Ni_Fast*.csv', COLORS[0], 'D'),
                           ('Ni (adaptive τ)', 'Ni_DUPLO*.csv', COLORS[1], '^'),
                           ('Ni + dark film (τ = 1 s)', 'Ni_Filme*.csv', 'k', 'o')):
        d = load(pat); f = d['Frequencia_Hz']; s = S(d) / M
        ref = s[0] if ref is None else ref
        p = np.polyfit(np.log10(f), np.log10(s), 1)
        a1.plot(f, s / ref, color=c, marker=m, ms=4, lw=0, mfc='none' if 'adaptive' in lab else c,
                label=f'{lab}: n = {-p[0]:.2f}')
        a1.plot(f, 10 ** np.polyval(p, np.log10(f)) / ref, color=c, lw=1)
    A, B = load('Ni_Fast*.csv'), load('Ni_Filme*.csv')
    f = A['Frequencia_Hz']
    a2.plot(f, S(B) / S(A), 'o-', color='k', ms=4, lw=1)
    dp = (dphi(B) - dphi(A) + 180) % 360 - 180
    ins = a2.inset_axes([0.55, 0.12, 0.42, 0.35])
    ins.semilogx(f, dp, '.-', color=COLORS[1], ms=3, lw=0.8); ins.axhline(0, color='#999', lw=0.5)
    ins.set_ylabel('Δφ film − Ni (°)', fontsize=9); ins.tick_params(labelsize=9)
    for ax in (a1, a2):
        ax.set_xscale('log'); ax.set_yscale('log'); ax.set_xlabel('Frequency (Hz)'); finish(ax)
    a1.set_ylabel('Calibrated S (relative to Ni at 40 Hz)')
    a2.set_ylabel('Amplitude ratio film / Ni')
    a1.set_title('(a) Ni and Ni with a dark film', loc='left'); a1.legend(fontsize=10, loc='lower left')
    a2.set_title('(b) Ratio film / Ni (same mounting)', loc='left')
    save(fig, 'ni_film_20261117.png')


def fig_snr():
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 5.4))
    for lab, pat, c, m in (('Stainless', 'Inox_DUPLO*.csv', COLORS[1], 's'),
                           ('Al kitchen foil', 'Al_Papel*.csv', COLORS[4], 'X'),
                           ('Black acrylic (melting)', 'Acrilico*.csv', COLORS[0], 'o'),
                           ('Al foil, OPC + glass', 'Al_OPC_Vidro_D*.csv', COLORS[3], 'v')):
        d = load(pat); f = d['Frequencia_Hz']
        a1.plot(f, d['INMP441_R'], color=c, mec=edge(c), marker=m, ms=5, lw=1, label=f'{lab}: signal')
        a1.plot(f, d['INMP441_R_DP'], color=edge(c), marker=m, ms=4, lw=0.8, ls=':', mfc='none')
    a1.plot([], [], color='k', ls=':', lw=0.6, label='dotted = noise σ (same τ)')
    a1.set_xscale('log'); a1.set_yscale('log'); a1.set_xlabel('Frequency (Hz)')
    a1.set_ylabel('Microphone amplitude (full scale)')
    a1.set_title('(a) Signal and noise of the INMP441', loc='left')
    a1.legend(fontsize=10, loc='upper center', bbox_to_anchor=(0.5, -0.2), ncol=2)
    X, Y = [], []
    for path in sorted(glob.glob(os.path.join(HERE, '*DUPLO*.csv'))):
        d = load(os.path.basename(path)); fr = d['Frequencia_Hz']
        snr = 20 * np.log10(d['INMP441_R'] / d['INMP441_R_DP'])
        x, y = np.log10(fr), np.log(S(d))
        for i in range(len(x)):
            k = [j for j in range(max(0, i - 3), min(len(x), i + 4)) if j != i]
            if fr[i] >= 500 or len(k) < 5:
                continue
            p = np.polyfit(x[k], y[k], 2); X.append(snr[i]); Y.append(abs(y[i] - np.polyval(p, x[i])) * 100)
    X, Y = np.array(X), np.array(Y)
    for lo, hi, c in ((-5, 15, '#f6d5d5'), (15, 25, '#fbefcc'), (25, 80, '#d8efd8')):
        a2.axvspan(lo, hi, color=c, lw=0)
    a2.semilogy(X, Y, 'o', ms=3, color='#555', alpha=0.6, mew=0, label='points below 500 Hz')
    cx, cy = [], []
    for lo in np.arange(0, 55, 5):
        k = (X >= lo) & (X < lo + 5)
        if k.sum() >= 4:
            cx.append(lo + 2.5); cy.append(np.sqrt(np.mean(Y[k] ** 2)))
    a2.semilogy(cx, cy, '-s', color=COLORS[0], ms=5, lw=1.5, label='rms deviation per 5 dB bin')
    ss = np.linspace(0, 55, 100)
    a2.semilogy(ss, 100 * 10 ** (-ss / 20), '--', color=COLORS[1], lw=1, label='1/SNR')
    a2.axhline(7, color='forestgreen', ls=':', lw=1)
    a2.text(52, 7.6, 'floor ~7 %', ha='right', fontsize=10, color='forestgreen')
    a2.set_xlim(0, 55); a2.set_ylim(0.1, 300)
    a2.set_xlabel('Point SNR  20·log(R/σ)  (dB)'); a2.set_ylabel('Deviation from neighbouring points (%)')
    a2.set_title('(b) Real point error vs SNR', loc='left'); a2.legend(fontsize=10, loc='lower left')
    for t, xx in (('red', 7.5), ('yellow', 20), ('green', 40)):
        a2.text(xx, 200, t, ha='center', fontsize=11)
    for ax in (a1, a2):
        finish(ax)
    save(fig, 'snr_20261117.png')
    return list(zip(cx, np.round(cy, 1)))


if __name__ == '__main__':
    style()
    cal = load('CAL_*.csv')
    fig_calibration(cal)
    print('metals n:', fig_metals(cal))
    fig_ni_film(cal)
    print('SNR bins:', fig_snr())
