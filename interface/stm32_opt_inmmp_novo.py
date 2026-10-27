# -*- coding: utf-8 -*-
'''
SOI Controller - LCTM (lock-in com Software PLL em Python + interface PyQt/pyqtgraph)

Dependências:  pip install pyqtgraph numpy scipy pyserial PySide6   (ou PyQt5/PyQt6)
Lock-in: Python (numpy/scipy), neste mesmo arquivo (classes PyLockIn e AudioLockIn).

Principais diferenças em relação à versão com Matplotlib:
  * pyqtgraph no lugar de Matplotlib (redesenho incremental, muito mais leve);
  * leitura serial em thread própria (nenhum byte é perdido se a GUI atrasar);
  * GUI dirigida por QTimer (sem while/sleep/flush_events);
  * processamento em lote com NumPy (sem laços Python por amostra);
  * osciloscópio com ring buffer e duas fatias (sem o laço de ERASE_GAP);
  * Modo Valor Médio vetorizado;
  * sem tkinter/matplotlib (executável PyInstaller menor).
'''
import binascii
import os
import re
import sys
import threading
import time
import zipfile
from collections import deque, namedtuple
from datetime import datetime

import numpy as np
from scipy.signal import iirnotch, lfilter, sosfilt, sosfilt_zi
import serial
from serial.tools import list_ports

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

# Executáveis empacotados sem console (PyInstaller --windowed) não têm stdout/stderr.
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

# ----------------------------------------------------------------------------
# Constantes
# ----------------------------------------------------------------------------
BAUD_RATE = 500000        # Ignorado pelo USB CDC do STM32
ARDUINO_VIDS = {0x0483, 0x2341, 0x2A03, 0x1A86}  # 0x0483 = STM32 CDC.
RECONNECT_INTERVAL = 3.0

FS = 12500.0              # Taxa de amostragem do STM32 (Hz) = FS_HZ do firmware
DECIMATION = 250          # Decimação da saída do lock-in (12500 -> 50 Hz)
ADC_OVS_FACTOR = 1.0  # OVS_BITS=2: o firmware envia 4095 * 4; a interface exibe a escala com oversampling
ADC_FULL_SCALE = 16380.0
ADC_VREF = 3.3
AUDIO_FS = 32000          # = AUDIO_FS_HZ do firmware (nominal)
# Taxa real do I2S: PLLI2S = 1 MHz * 258 / 3 = 86 MHz; quadro de 64 bits; divisor inteiro do HAL
# = round(86e6 / 64 / 32000) = 42 -> 31994,05 Hz (-186 ppm). A referência numérica do lock-in de
# áudio precisa da taxa real: com 32000 a fase gira em f * 186e-6 Hz (ex.: 1 volta a cada ~18 min a 5 Hz).
I2S_CLK_HZ = 1e6 * 258 / 3
AUDIO_FS_REAL = I2S_CLK_HZ / 64.0 / round(I2S_CLK_HZ / 64.0 / AUDIO_FS)
MOD_TIMER_CLK_HZ = 84e6   # TIM4 (APB1 x2), mesmo cristal do I2S
# Atraso da referência do lock-in do OPT101 em relação à luz (cadeia digital do firmware): a fase do PLL
# vale 0 no centro do quadro em que o REF (maioria das 16 amostras) sobe, em média 7,5 amostras do ADC
# (200 kHz) depois da borda do rótulo; o rótulo segue a escrita do DMA, 12 ciclos do ADC (21 MHz) depois
# do instante amostrado, e o CCR1 do laser muda ~0,2 µs depois do rótulo. Soma +360°·f·OPT_REF_DELAY à
# fase do OPT101 (conferido com simulação do firmware: erro < 0,05° até 1,7 kHz).
OPT_REF_DELAY = 7.5 / 200000.0 - 12.0 / 21e6 - 0.2e-6
AUDIO_PACKET_MAGIC = b'\xA5\x5A\x49\x32'
# Marcador A5 5A 4D 4B + SEQ (uint32) + CRC16: amostra I2S em que a onda quadrada do laser começou
# (borda de subida). Dá ao lock-in do INMP441 a mesma origem de fase do OPT101 (PLL na borda).
MOD_MARKER_MAGIC = b'\xA5\x5A\x4D\x4B'
MOD_MARKER_SIZE = 10
AUDIO_PACKET_HEADER_SIZE = 10
AUDIO_PACKET_MAX_SAMPLES = 256
AUDIO_QUEUE_MAX_SAMPLES = AUDIO_FS * 2
AUDIO_DISPLAY_SAMPLES = AUDIO_FS // 10
AUDIO_FFT_SIZE = 4096        # FFT da faixa completa (resolução ~7,8 Hz)
AUDIO_FFT_HISTORY_SEC = 4.0  # histórico de áudio; a FFT com zoom usa todo ele (resolução ~0,25 Hz)
AUDIO_LOCKIN_BLOCK = 1600     # amostras por ponto do lock-in de áudio (0,05 s a 32 kHz -> 20 Hz)
AUDIO_LOCKIN_SPAN = 10.0    # s exibidos no gráfico do lock-in de áudio (padrão; ajustável na aba)
LOW_SIGNAL_SNR_DB = 10.0    # alerta de sinal baixo abaixo deste SNR (~3 sigma)
ALERT_COLOR = '#ffd6d6'
AUDIO_MAX_POINTS = int(round(AUDIO_LOCKIN_SPAN * AUDIO_FS / AUDIO_LOCKIN_BLOCK)) + 1
AUDIO_NOISE_SPAN = 60.0     # s de histórico do lock-in de áudio usados no gráfico de ruído/SNR
AUDIO_NOISE_POINTS = int(round(AUDIO_NOISE_SPAN * AUDIO_FS / AUDIO_LOCKIN_BLOCK))
AUTO_PHASE_SPAN = 1.0       # s de média usados pela auto-fase
AUDIO_FFT_INTERVAL = 0.25     # s entre FFTs (só roda com a opção ligada)
OPT_FFT_SIZE = 4096          # FFT da faixa completa do ADC do OPT101 (resolução ~3,1 Hz)
OPT_FFT_HISTORY_SEC = 4.0    # histórico do ADC; a FFT com zoom usa todo ele (resolução ~0,25 Hz)
# Varredura recomendada para a calibração do microfone (padrão de alumínio), aba Modo Duplo.
# 5 Hz fica bem abaixo do corte do microfone/célula (~40 Hz); 35 pontos log até 2440 Hz ficam a >= 4 Hz
# de todo múltiplo de 60 Hz e longe das frequências em que o período cai num número inteiro de amostras
# do OPT101 (ex.: 2500 Hz = 5 amostras), onde a grade de 80 us deixa erro residual no R.
# PWM 100 %: o laser fica contínuo no meio período ligado (sem a portadora de 5 kHz).
CAL_SWEEP_F0 = 5.0
CAL_SWEEP_F1 = 2440.0
CAL_SWEEP_N = 35
CAL_SWEEP_TAU = 2.0
CAL_SWEEP_PWM = 100.0
MEDIDAS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, 'frozen', False)
    else os.path.dirname(os.path.abspath(__file__)), 'Medidas')
MAX_POINTS = 200          # Pontos exibidos de R e Fase
MAX_BATCH_SAMPLES = 40900
MAX_RX_BYTES = 1_000_000  # Proteção contra acúmulo de bytes se a GUI travar
GUI_INTERVAL_MS = 40      # 25 FPS (indistinguível de 30 para este sinal)
STATUS_INTERVAL = 0.15    # s entre atualizações do texto de status
RANGE_INTERVAL = 0.5      # s entre reajustes automáticos de escala Y
REDUCED_VIEW_HZ = 50.0    # acima desta frequência o osciloscópio mostra só MAX_SCOPE_CYCLES ciclos
MAX_SCOPE_CYCLES = 50

OK_COLOR = '#e6ffe6'
WARN_COLOR = '#fff3cd'


def get_effective_cutoffs(f):
    '''Cortes adaptativos de filtro conforme a frequência de modulação.'''
    lp = float(np.clip(f * 0.05, 0.08, 0.50))
    hp = float(np.clip(f * 0.02, 0.01, 0.05))
    return lp, hp


def lp_tau(cutoff, fs):
    '''Constante de tempo (s) de cada polo do passa-baixas do lock-in, y[k] = a*x[k] + (1-a)*y[k-1]
    com a = 2*pi*fc/fs: tau = -1/(fs*ln(1-a)), que tende a 1/(2*pi*fc) quando fc << fs.'''
    a = 2.0 * np.pi * cutoff / fs
    return float('inf') if a >= 1.0 else -1.0 / (fs * np.log1p(-a))


def actual_mod_freq(f):
    '''Frequência real da onda quadrada gerada pelo TIM4 no firmware (startModulation), com os
    mesmos arredondamentos inteiros. O lock-in do INMP441 não tem PLL: precisa da frequência exata.'''
    if f <= 0:
        return f
    if f >= 100.0:
        tick = MOD_TIMER_CLK_HZ / 8                   # prescaler 8 -> 10,5 MHz
        half = int(tick / (2.0 * f) + 0.5)
        return tick / (2.0 * half)
    half_us = int(500000.0 / f + 0.5)                 # setOverflow(.., MICROSEC_FORMAT) do STM32duino
    cycles = half_us * int(MOD_TIMER_CLK_HZ // 1e6)
    psc = cycles // 0x10000 + 1
    return MOD_TIMER_CLK_HZ / (2.0 * psc * (cycles // psc))


def hann_kernel(d):
    '''|Espectro| da janela Hann normalizado (1 em d = 0), com d em bins:
    sinc(d) + (sinc(d - 1) + sinc(d + 1)) / 2  (= sinc(d) / (1 - d^2), sem singularidade em d = ±1).'''
    d = np.asarray(d, dtype=np.float64)
    return np.abs(np.sinc(d) + 0.5 * (np.sinc(d - 1.0) + np.sinc(d + 1.0)))


# Pico da FFT considerado ausente abaixo desta razão pico/piso (mesmo limiar do alerta de sinal baixo)
FFT_FIT_MIN_SNR_DB = LOW_SIGNAL_SNR_DB


def fit_hann_at(freq, spec, f0, half_window_bins=20):
    '''Ajusta só a amplitude A de A*|W((f - f0)/df)| com f0 fixo (frequência da excitação), por mínimos
    quadrados nos 5 bins em torno de f0; não pula para picos vizinhos. spec em amplitude linear.
    Piso de ruído = mediana do espectro em ±half_window_bins de f0, sem ±4 bins de f0 e sem o lóbulo do DC.
    Devolve (estado, A, piso): estado 'ok', 'baixo' (A/piso abaixo de FFT_FIT_MIN_SNR_DB),
    'fora' (f0 fora da faixa da FFT) ou 'dc' (f0 dentro do lóbulo do DC nesta resolução).'''
    df = freq[1] - freq[0]
    c = f0 / df
    k = int(round(c))
    if f0 <= 0 or k + 2 > len(spec) - 1:
        return 'fora', None, None
    if k < 4:
        return 'dc', None, None
    idx = np.arange(k - 2, k + 3)
    h = hann_kernel(idx - c)
    amp = float(np.dot(spec[idx], h) / np.dot(h, h))
    i = np.arange(max(3, k - half_window_bins), min(len(spec), k + half_window_bins + 1))
    i = i[np.abs(i - k) > 4]
    floor = float(np.median(spec[i])) if i.size else float('nan')
    if not (np.isfinite(amp) and np.isfinite(floor)) or floor <= 0 or amp < floor * 10.0 ** (FFT_FIT_MIN_SNR_DB / 20.0):
        return 'baixo', amp, floor
    return 'ok', amp, floor


def find_flat_band(f, sens, good, tol_db=1.0):
    '''Faixa de resposta plana: o maior trecho contíguo (em log f) de pontos válidos cuja sensibilidade
    fica dentro de ±tol_db em torno da média do trecho (max/min ≤ 2·tol_db). f deve estar em ordem crescente.
    Devolve (i0, i1, ref) com os índices inclusivos e a média geométrica do trecho, ou None.'''
    ldb = 20.0 * np.log10(np.maximum(sens, 1e-30))
    best = None
    for i in range(f.size):
        if not good[i]:
            continue
        lo = hi = ldb[i]
        for j in range(i + 1, f.size):
            if not good[j]:
                break
            lo, hi = min(lo, ldb[j]), max(hi, ldb[j])
            if hi - lo > 2.0 * tol_db:
                break
            span = np.log(f[j] / f[i])
            if best is None or span > best[0]:
                best = (span, i, j)
    if best is None:
        return None
    _, i0, i1 = best
    return i0, i1, float(10.0 ** (np.mean(ldb[i0:i1 + 1]) / 20.0))


def load_mic_calibration(path):
    '''Lê uma calibração CAL_[amostra_]microfone_*.csv. Devolve dict com 'path', 'f',
    'sens' (sensibilidade relativa), 'phase' (graus), 'opt_tau' (τ do sensor OPT101 descontado, em s; 0 se
    não houve correção) e 'legacy' (True sem a chave OPT101_tau_sensor_s: calibração feita com o firmware
    anterior ao marcador de modulação corrigido, ou com a correção pelo τ efetivo; a fase não é comparável),
    ou None se o arquivo for inválido.'''
    if not path:
        return None
    opt_tau = None
    try:
        with open(path, encoding='utf-8') as fh:
            raw = [ln.strip() for ln in fh if ln.strip()]
        for ln in raw:
            m = re.match(r'#\s*OPT101_tau_sensor_s\s*=\s*(\S+)', ln)
            if m:
                opt_tau = float(m.group(1))
        lines = [ln for ln in raw if not ln.startswith('#')]
        head = lines[0].split(',')
        data = np.array([[float(v) for v in ln.split(',')] for ln in lines[1:]])
        f = data[:, head.index('Frequencia_Hz')]
        sens = data[:, head.index('Sensibilidade_Rel')]
        ph = data[:, head.index('Fase_Sistema_Graus')]
        ok = (data[:, head.index('Valido')] > 0) & (sens > 0)
    except (OSError, ValueError, IndexError):
        return None
    if ok.sum() < 2:
        return None
    k = np.argsort(f[ok])
    return {'path': path, 'f': f[ok][k], 'sens': sens[ok][k], 'phase': ph[ok][k],
            'opt_tau': opt_tau or 0.0, 'legacy': opt_tau is None}


DUAL_COLUMNS = ('OPT101_R', 'OPT101_R_DP', 'INMP441_R', 'INMP441_R_DP', 'INMP441_Fase_Graus',
                'INMP441_Fase_DP', 'OPT101_Fase_Graus', 'OPT101_Fase_DP')


def load_dual_csv(path):
    '''Lê um CSV do Modo Duplo (varredura em frequência ou casada em PWM, inclusive os formatos antigos).
    Devolve (tipo 'F' ou 'P', linhas (valor, 8 colunas de DUAL_COLUMNS), parâmetros da varredura).
    Levanta ValueError se o arquivo não for do Modo Duplo.'''
    with open(path, encoding='utf-8') as fh:
        lines = [ln.strip() for ln in fh if ln.strip()]
    i_head = next((i for i, ln in enumerate(lines) if not ln.startswith('#')), None)
    if i_head is None:
        raise ValueError('arquivo sem dados')
    cols = lines[i_head].split(',')
    kind = {'Frequencia_Hz': 'F', 'PWM_Pct': 'P'}.get(cols[0])
    if kind is None or not all(c in cols for c in DUAL_COLUMNS):
        raise ValueError('não é uma varredura do Modo Duplo (colunas de OPT101 e INMP441 não encontradas)')
    idx = [0] + [cols.index(c) for c in DUAL_COLUMNS]
    rows = []
    for ln in lines[i_head + 1:]:
        v = ln.split(',')
        rows.append(tuple(float(v[i]) for i in idx))
    if not rows:
        raise ValueError('arquivo sem pontos')
    header = '\n'.join(lines[:i_head])
    name = os.path.basename(path)

    def num(pattern, *texts):
        for t in texts:
            m = re.search(pattern, t)
            if m:
                return float(m.group(1))
        return None
    mode = re.search(r'# Medida:\s*([^;\n]+)', header)
    params = {'kind': kind, 'values': [r[0] for r in rows],
              # nome do arquivo primeiro (mesmo formato desde o início), cabeçalho como alternativa
              'pwm': num(r'_pwm([\d.]+)_', name) if kind == 'F' else None,
              'freq': num(r'_f([\d.]+)Hz_', name) if kind == 'P' else None,
              'mode': mode.group(1).strip() if mode else 'não registrada',
              'tau': num(r'tau = ([\d.eE+-]+) s \(integração longa\)', header)}
    if kind == 'F' and params['pwm'] is None:
        params['pwm'] = num(r'PWM\s*([\d.]+)\s*%', header) or 0.0
    if kind == 'P' and params['freq'] is None:
        params['freq'] = num(r'modulação\s*([\d.]+)\s*Hz', header) or 0.0
    return kind, rows, params


def list_mic_calibrations(folder=None):
    '''Calibrações válidas da pasta Medidas, da mais recente para a mais antiga. A data vem do nome
    (_AAAAMMDD_HHMMSS.csv), que sobrevive a cópias e sincronização; sem ela, a data de modificação.'''
    folder = folder or MEDIDAS_DIR
    try:
        files = [os.path.join(folder, n) for n in os.listdir(folder)
                 if n.startswith('CAL_') and '_microfone_' in n and n.endswith('.csv')]
    except OSError:
        return []

    def stamp(path):
        m = re.search(r'_(\d{8}_\d{6})\.csv$', path)
        return m.group(1) if m else datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y%m%d_%H%M%S')
    return [p for p in sorted(files, key=stamp, reverse=True) if load_mic_calibration(p) is not None]


def circ_stats_deg(p):
    '''Média e desvio-padrão circulares de fases em graus (a média aritmética falha perto de ±180°).'''
    u = np.exp(1j * np.radians(np.asarray(p, dtype=np.float64)))
    m = u.mean()
    rbar = min(max(abs(m), 1e-12), 1.0)
    return float(np.degrees(np.angle(m))), float(np.degrees(np.sqrt(-2.0 * np.log(rbar))))


def fit_sweep(x, y, model):
    '''Ajuste da varredura. model: 'pow' -> y = A*x^n (mínimos quadrados em log-log, só pontos > 0);
    'lin' -> y = a + b*x. Devolve (função, texto) ou None.'''
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if model == 'pow':
        ok = (x > 0) & (y > 0)
        if ok.sum() < 2:
            return None
        lx, ly = np.log10(x[ok]), np.log10(y[ok])
        (n, la), cov = np.polyfit(lx, ly, 1, cov=True) if ok.sum() > 3 else (np.polyfit(lx, ly, 1), None)
        r2 = 1.0 - np.sum((ly - (la + n * lx)) ** 2) / max(np.sum((ly - ly.mean()) ** 2), 1e-300)
        a = 10.0 ** la
        sn = f' ± {np.sqrt(cov[0, 0]):.3f}' if cov is not None else ''
        return (lambda xx: a * np.power(xx, n)), f'y = A·x<sup>n</sup><br>n = {n:.3f}{sn}<br>A = {a:.4g}<br>R² (log) = {r2:.4f}'
    if x.size < 2:
        return None
    (b, a), cov = np.polyfit(x, y, 1, cov=True) if x.size > 3 else (np.polyfit(x, y, 1), None)
    r2 = 1.0 - np.sum((y - (a + b * x)) ** 2) / max(np.sum((y - y.mean()) ** 2), 1e-300)
    sb = f' ± {np.sqrt(cov[0, 0]):.3g}' if cov is not None else ''
    return (lambda xx: a + b * xx), f'y = a + b·x<br>b = {b:.4g}{sb}<br>a = {a:.4g}<br>R² = {r2:.4f}'


def fit_pa_standard(f, s, s_rel, dphi, dphi_e, snr, snr_min, use_phase=True):
    '''Fit do padrão (papel alumínio, termicamente fino e opaco) na varredura em frequência normalizada.
    Amplitude S(f) = A·f^-n·H(f), H = passa-altas de 1ª ordem de corte fc (microfone/célula);
    fase Δφ(f) = φ0 + atan(fc/f) - 360°·f·td (td = atraso de propagação acústica).
    Pontos com SNR < snr_min ou resíduo > 3σ ficam fora do ajuste e da faixa confiável.
    Devolve dict com 'amp', 'phase' (funções), 'good' (máscara) e 'text', ou None.'''
    from scipy.optimize import least_squares
    f = np.asarray(f, dtype=np.float64)
    ls = np.log(np.asarray(s, dtype=np.float64))
    sig_l = np.maximum(np.asarray(s_rel, dtype=np.float64), 0.01)
    dphi = np.asarray(dphi, dtype=np.float64)
    sig_p = np.maximum(np.asarray(dphi_e, dtype=np.float64), 1.0)
    lo, hi = np.log(f.min() / 100.0), np.log(f.max())

    def amp_l(p, ff):
        x = ff / np.exp(p[2])
        return p[0] - p[1] * np.log(ff) + np.log(x) - 0.5 * np.log1p(x * x)

    def phase(p, ff):
        return p[4] + np.degrees(np.arctan(np.exp(p[2]) / ff)) - 360.0 * ff * p[3]

    def resid(p, m):
        r = (amp_l(p, f[m]) - ls[m]) / sig_l[m]
        if use_phase:
            r = np.concatenate((r, wrap_deg(phase(p, f[m]) - dphi[m]) / sig_p[m]))
        return r

    good = np.asarray(snr) >= snr_min
    if good.sum() < 4:
        good = np.ones(f.size, dtype=bool)
    k = np.argsort(f)
    n0 = -np.polyfit(np.log(f[k][-max(2, f.size // 2):]), ls[k][-max(2, f.size // 2):], 1)[0]
    p0 = np.array([ls.max() + np.log(f.max()) * n0, float(np.clip(n0, 0.0, 3.0)), np.log(f.min() / 3.0), 0.0, 0.0])
    p0[2] = np.clip(p0[2], lo, hi)
    if use_phase:
        # Ponto de partida da fase: Δφ desenrolada ≈ a + b·log10 f + c·f -> td = -c/360; evita mínimos
        # locais criados pela volta de ±180°
        un = np.degrees(np.unwrap(np.radians(dphi[k])))
        c = np.linalg.lstsq(np.c_[np.ones(f.size), np.log10(f[k]), f[k]], un, rcond=None)[0]
        p0[3] = float(np.clip(-c[2] / 360.0, -0.0099, 0.0099))
        p0[4] = circ_stats_deg(dphi - np.degrees(np.arctan(np.exp(p0[2]) / f)) + 360.0 * f * p0[3])[0]
    bounds = ([-np.inf, 0.0, lo, -0.01, -720.0], [np.inf, 3.0, hi, 0.01, 720.0])
    sol = None
    for _ in range(2):                 # 2ª passada sem os pontos com resíduo > 3σ
        if good.sum() < 4:
            return None
        sol = least_squares(resid, p0, bounds=bounds, args=(good,))
        p0 = sol.x
        r_all = np.abs((amp_l(sol.x, f) - ls) / sig_l)
        if use_phase:
            r_all = np.maximum(r_all, np.abs(wrap_deg(phase(sol.x, f) - dphi)) / sig_p)
        # Outlier: resíduo > 3x a dispersão típica (MAD), não só 3σ estatístico, que ignora erros sistemáticos
        thr = 3.0 * max(1.0, 1.4826 * float(np.median(r_all[good])))
        new_good = good & (r_all <= thr)
        if new_good.sum() == good.sum() or new_good.sum() < 4:
            break
        good = new_good
    if sol is None or not sol.success:
        return None
    p = sol.x
    dof = max(1, sol.fun.size - (5 if use_phase else 3))
    chi2 = float(np.sum(sol.fun ** 2) / dof)
    J = sol.jac if use_phase else sol.jac[:, :3]
    try:
        cov = np.linalg.pinv(J.T @ J) * max(chi2, 1.0)
        err = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    except np.linalg.LinAlgError:
        err = np.full(J.shape[1], np.nan)
    fc, fc_err = np.exp(p[2]), np.exp(p[2]) * err[2]
    fc_txt = (f'Corte do microfone/célula (fc) = {fc:.3g} ± {fc_err:.2g} Hz' if p[2] > lo + 0.05
              else f'Corte do microfone/célula (fc) abaixo de {f.min():g} Hz')
    # Classificação pelo expoente: ≈1 amostra sobre suporte espesso, ≈1,5 folha fina livre (capacidade térmica)
    if 0.75 <= p[1] < 1.25:
        amostra = 'Amostra fina sobre suporte espesso'
    elif 1.25 <= p[1] < 1.75:
        amostra = 'Amostra fina livre'
    else:
        amostra = 'Fora dos regimes padrão (n ≈ 1 ou 1,5)'
    text = (f'<b>Fit padrão:</b> <b>{amostra}</b> &nbsp; n = {p[1]:.2f} ± {err[1]:.2f} &nbsp; {fc_txt}')
    if use_phase:
        text += (f' &nbsp; Atraso luz→microfone (td) = {p[3] * 1e6:.0f} ± {err[3] * 1e6:.0f} µs')
    text += (f'<br>Faixa confiável: {f[good].min():.4g} a {f[good].max():.4g} Hz '
             f'({int(good.sum())} de {f.size} pontos); x vermelho = ponto excluído')
    return {'amp': lambda ff: np.exp(amp_l(p, np.asarray(ff, dtype=np.float64))),
            'phase': (lambda ff: phase(p, np.asarray(ff, dtype=np.float64))) if use_phase else None,
            'good': good, 'text': text, 'params': p, 'errors': err, 'chi2': chi2}


def opt_digital_phase(f, hp_cutoff, mains=False, fs=FS):
    '''Fase (graus) que a cadeia digital soma à fundamental do OPT101 em f (frequência real): atraso da
    referência (OPT_REF_DELAY), passa-altas de remoção do DC e, onde ligados, os notches de rede.
    hp_cutoff e mains podem ser escalares ou um valor por frequência.'''
    f = np.atleast_1d(np.asarray(f, dtype=np.float64))
    hp = np.broadcast_to(np.asarray(hp_cutoff, dtype=np.float64), f.shape)
    mains = np.broadcast_to(np.asarray(mains, dtype=bool), f.shape)
    zinv = np.exp(-2j * np.pi * f / fs)
    a = 2.0 * np.pi * hp / fs
    h = 1.0 - a / (1.0 - (1.0 - a) * zinv)          # x - LP(x), y[k] = a*x[k] + (1-a)*y[k-1]
    for i in np.flatnonzero(mains):
        z = zinv[i]
        for b0, b1, b2, _, a1, a2 in mains_notch_sos(fs, f[i]).values():
            h[i] *= (b0 + b1 * z + b2 * z * z) / (1.0 + a1 * z + a2 * z * z)
    return 360.0 * f * OPT_REF_DELAY + np.degrees(np.angle(h))


def fit_opt_tau(f, phase, phase_e, digital, r=None):
    '''Constante de tempo efetiva do canal óptico (sensor + driver/laser) pela fase do lock-in do OPT101 numa
    varredura em frequência. Modelo de 1 polo: φ(f) = φ0 + digital(f) - atan(2π·f·τ), φ0 ≈ -90° (onda
    quadrada que liga no início do período). Diagnóstico: o atraso do driver/laser também entra aqui, mas
    é comum ao microfone e se cancela em Δφ; para corrigir o sensor use fit_sensor_tau.
    Com r (R do OPT101), ajusta também τ pela queda de amplitude 1/√(1 + (2π·f·τ)²), como verificação.
    Devolve dict ('tau', 'tau_err', 'phi0', 'rms', 'valid', 'tau_amp', 'tau_amp_err', 'text') ou None.'''
    from scipy.optimize import least_squares
    f = np.asarray(f, dtype=np.float64)
    if f.size < 4:
        return None
    k = np.argsort(f)
    f = f[k]
    w = 2.0 * np.pi * f
    y = np.degrees(np.unwrap(np.radians(wrap_deg(np.asarray(phase, dtype=np.float64)[k] - np.asarray(digital)[k]))))
    sig = np.maximum(np.asarray(phase_e, dtype=np.float64)[k], 0.05)

    def model(p):
        return p[0] - np.degrees(np.arctan(w * p[1]))

    def errors(sol, npar, weighted=True):
        '''Desvios dos parâmetros. Resíduos sem peso: a escala vem toda da dispersão dos resíduos.'''
        chi2 = float(np.sum(sol.fun ** 2) / max(1, f.size - npar))
        try:
            scale = max(chi2, 1.0) if weighted else chi2
            return np.sqrt(np.clip(np.diag(np.linalg.pinv(sol.jac.T @ sol.jac) * scale), 0.0, None))
        except np.linalg.LinAlgError:
            return np.full(npar, np.nan)

    # Partida: inclinação da fase com a frequência (atan(x) ≈ x)
    tau0 = float(np.clip(-np.polyfit(w, y, 1)[0] * np.pi / 180.0, 1e-7, 1e-3))
    sol = least_squares(lambda p: (model(p) - y) / sig, [float(y[0]), tau0], bounds=([-720.0, 0.0], [720.0, 1e-3]))
    if not sol.success:
        return None
    phi0, tau = (float(v) for v in sol.x)
    err = errors(sol, 2)
    out = {'tau': tau, 'tau_err': float(err[1]), 'phi0': phi0,
           'rms': float(np.sqrt(np.mean((y - model(sol.x)) ** 2))),
           'valid': bool(np.isfinite(err[1]) and tau > 2.0 * err[1]),
           'tau_amp': None, 'tau_amp_err': None}
    fc = 1.0 / (2.0 * np.pi * tau) if tau > 0 else np.inf
    text = (f'<b>Canal óptico (sensor + driver/laser):</b> τ efetivo = {tau * 1e6:.3g} ± {err[1] * 1e6:.2g} µs '
            f'pela fase (1 polo) &nbsp; '
            f'banda (-3 dB) = {fc / 1e3:.3g} kHz &nbsp; subida 10–90 % = {tau * np.log(9.0) * 1e6:.3g} µs &nbsp; '
            f'φ0 = {phi0:.1f}° &nbsp; resíduo rms = {out["rms"]:.2f}°')
    if not out['valid']:
        text += (f'<br><span style="color:#d00000;">τ não determinado: a fase até {f.max():g} Hz não separa o polo '
                 f'do ruído (varra até frequências maiores).</span>')
    if r is not None and np.all(np.asarray(r) > 0):
        la = np.log(np.asarray(r, dtype=np.float64)[k])
        sol_a = least_squares(lambda p: p[0] - 0.5 * np.log1p((w * p[1]) ** 2) - la, [float(la.max()), tau],
                              bounds=([-np.inf, 0.0], [np.inf, 1e-3]))
        if sol_a.success:
            out['tau_amp'], out['tau_amp_err'] = float(sol_a.x[1]), float(errors(sol_a, 2, weighted=False)[1])
            text += f'<br>Verificação: τ pela queda de amplitude = {out["tau_amp"] * 1e6:.3g} ± {out["tau_amp_err"] * 1e6:.2g} µs'
            if abs(tau - out['tau_amp']) > 3.0 * np.hypot(err[1], out['tau_amp_err']):
                text += (' &nbsp; <span style="color:#d00000;">⚠ fase e amplitude incompatíveis com um polo único: '
                         'atraso puro (driver/laser) ou potência do laser variando com a frequência. '
                         'O τ da fase é efetivo e inclui esse atraso.</span>')
    out['text'] = text
    return out


def fit_sensor_tau(f, ph, ph_e, r, f_ref, ph_ref, ph_ref_e, r_ref):
    '''τ do sensor (polo do OPT101) pela diferença de fase entre duas varreduras em frequência com a mesma
    luz (mesmo PWM e alinhamento) e resistores de realimentação diferentes. A cadeia digital, o driver e o
    laser são comuns e se cancelam. O polo é ∝ R_eq, e a razão g = R_eq/R_eq,ref sai da razão dos R:
    Δφ(f) = c - atan(ω·τ) + atan(ω·τ/g), com τ o τ do sensor da varredura atual (f, ph, r).
    Só usa as frequências presentes nas duas. Devolve dict ('tau', 'tau_err', 'tau_ref', 'g', 'n', 'text') ou None.'''
    from scipy.optimize import least_squares
    a = {round(float(v), 2): i for i, v in enumerate(f_ref)}
    pairs = [(i, a[round(float(v), 2)]) for i, v in enumerate(f) if round(float(v), 2) in a]
    if len(pairs) < 4:
        return None
    i, j = (np.array(p) for p in zip(*pairs))
    ff = np.asarray(f, dtype=np.float64)[i]
    w = 2.0 * np.pi * ff
    g = float(np.median(np.asarray(r, dtype=np.float64)[i] / np.asarray(r_ref, dtype=np.float64)[j]))
    if not 0.0 < g or abs(np.log(g)) < np.log(1.3):
        return {'tau': None, 'g': g, 'n': ff.size,
                'text': f'τ do sensor: os ganhos das duas varreduras são próximos demais (razão {g:.2f}); '
                        f'use resistores que mudem o ganho pelo menos 1,3×.'}
    dp = wrap_deg(np.asarray(ph, dtype=np.float64)[i] - np.asarray(ph_ref, dtype=np.float64)[j])
    sig = np.hypot(np.maximum(np.asarray(ph_e, dtype=np.float64)[i], 0.05),
                   np.maximum(np.asarray(ph_ref_e, dtype=np.float64)[j], 0.05))

    def resid(p):
        return (p[0] - np.degrees(np.arctan(w * p[1])) + np.degrees(np.arctan(w * p[1] / g)) - dp) / sig
    sol = least_squares(resid, [0.0, 1e-5], bounds=([-30.0, 0.0], [30.0, 1e-3]))
    if not sol.success:
        return None
    chi2 = float(np.sum(sol.fun ** 2) / max(1, ff.size - 2))
    try:
        err = float(np.sqrt(np.linalg.pinv(sol.jac.T @ sol.jac)[1, 1] * max(chi2, 1.0)))
    except np.linalg.LinAlgError:
        err = float('nan')
    tau = float(sol.x[1])
    return {'tau': tau, 'tau_err': err, 'tau_ref': tau / g, 'g': g, 'n': ff.size,
            'text': f'τ do sensor = {tau * 1e6:.3g} ± {err * 1e6:.2g} µs nesta varredura '
                    f'({tau / g * 1e6:.3g} µs na de referência; razão de ganho {g:.3f}; {ff.size} frequências em comum)'}


# Modelos físicos da resposta da amostra na varredura em frequência (Modo Duplo, painel "Ajuste com modelos").
# Com a calibração aplicada, S e Δφ já são referidos à folha fina de alumínio (∝ f^-1,5), então cada modelo
# descreve a amostra a menos de uma constante complexa (amplitude e fase livres). x = √(f/f1), f1 = α/(πL²).
FREQ_MODELS = {
    'pow': 'Lei de potência  S ∝ f⁻ⁿ',
    'pow2': 'Duas leis de potência (com quebra)',
    'diff': 'Difusão térmica (placa, detecção traseira)',
    'te': 'Flexão termoelástica (Perondi–Miranda)',
}
FREQ_MODEL_TIPS = {
    'pow': 'S ∝ f⁻ⁿ com fase constante. Ajusta só o expoente n (descritivo, sem modelo físico).',
    'pow2': ('Duas retas em log-log, contínuas na frequência de quebra fb: S ∝ f^-n1 abaixo de fb e f^-n2 acima.\n'
             'Ajusta n1, n2 e fb (só a magnitude). Útil para separar regimes: por exemplo, a flexão termoelástica\n'
             'de uma placa grossa (n ≈ 1) e uma contribuição de fundo que domina em frequência alta (n ≈ 0).\n'
             'Use a Faixa para analisar cada parte com mais cuidado.'),
    'diff': ('Difusão do calor através de uma placa iluminada numa face, com o gás do microfone na outra\n'
             '(célula aberta, OPC): S ∝ f^-0,5 / [σL·sinh(σL)], σL = (1+i)·√(f/f1).\n'
             'Baixa frequência (placa termicamente fina): S ∝ f^-1,5, como a folha de alumínio.\n'
             'Alta frequência: a amplitude cai como exp(−√(f/f1)) e a fase atrasa √(f/f1) radianos.'),
    'te': ('Flexão termoelástica de uma placa termicamente grossa em célula aberta (OPC):\n'
           'S ∝ f⁻¹·[(1 − 1/x) + i/x], x = √(f/f1). Costuma dominar em placas metálicas.\n'
           'A fase cai ~90° em torno de f1 e se estabiliza acima dela.\n'
           'Ref.: L. F. Perondi, L. C. M. Miranda, J. Appl. Phys. 62, 2955 (1987);\n'
           'G. Rousset, F. Lepoutre, L. Bertrand, J. Appl. Phys. 54, 2383 (1983).'),
}


def _log_sinh(q):
    '''log(sinh(q)) complexo sem overflow para Re(q) grande.'''
    q = np.asarray(q, dtype=np.complex128)
    big = q.real > 20.0
    out = np.empty_like(q)
    out[big] = q[big] - np.log(2.0)
    out[~big] = np.log(np.sinh(q[~big]))
    return out


def freq_model_log(model, f, shape):
    '''log do modelo (complexo, sem a constante): Re = log da amplitude, Im = fase em rad.'''
    f = np.asarray(f, dtype=np.float64)
    if model == 'pow':
        return -shape * np.log(f) + 0j
    x = np.sqrt(f / shape)
    if model == 'diff':
        q = (1 + 1j) * x
        return -0.5 * np.log(f) - np.log(q) - _log_sinh(q)
    return -np.log(f) + np.log((1.0 - 1.0 / x) + 1j / x)          # 'te'


def fit_freq_model(f, s, s_rel, dphi, dphi_e, model, target):
    '''Ajusta um modelo de FREQ_MODELS à magnitude S, à fase Δφ (graus) ou às duas ('mag', 'phase', 'both').
    Parâmetros: log da amplitude, fase φ0 e o de forma (n ou log f1). Devolve dict com 'func' (modelo
    complexo nos f dados, com as constantes), 'shape', 'shape_err', 'rms_mag', 'rms_phase', ou None.'''
    from scipy.optimize import least_squares
    f = np.asarray(f, dtype=np.float64)
    ls = np.log(np.asarray(s, dtype=np.float64))
    sig_l = np.maximum(np.asarray(s_rel, dtype=np.float64), 0.01)
    ph = np.radians(np.asarray(dphi, dtype=np.float64))
    sig_p = np.radians(np.maximum(np.asarray(dphi_e, dtype=np.float64), 1.0))
    use_mag, use_ph = target in ('mag', 'both'), target in ('phase', 'both')
    if f.size < 3 or not np.all(np.isfinite(ls)):
        return None

    def shape_of(p):
        return p[2] if model == 'pow' else float(np.exp(p[2]))

    def resid(p):
        g = freq_model_log(model, f, shape_of(p))
        r = []
        if use_mag:
            r.append((p[0] + g.real - ls) / sig_l)
        if use_ph:
            r.append(np.angle(np.exp(1j * (p[1] + g.imag - ph))) / sig_p)
        return np.concatenate(r)

    if model == 'pow':
        starts, lb, ub = [0.5, 1.0, 1.5], -5.0, 5.0
    else:
        starts = np.log(np.geomspace(f.min() / 30.0, f.max() * 3.0, 12))
        lb, ub = np.log(f.min() / 1000.0), np.log(f.max() * 100.0)
    best = None
    for s0 in starts:
        g0 = freq_model_log(model, f, s0 if model == 'pow' else float(np.exp(s0)))
        p0 = [float(np.median(ls - g0.real)), float(np.angle(np.mean(np.exp(1j * (ph - g0.imag))))), s0]
        try:
            sol = least_squares(resid, p0, bounds=([-np.inf, -np.inf, lb], [np.inf, np.inf, ub]))
        except ValueError:
            continue
        if best is None or sol.cost < best.cost:
            best = sol
    if best is None:
        return None
    p = best.x
    dof = max(1, best.fun.size - 3)
    cov = np.linalg.pinv(best.jac.T @ best.jac) * 2.0 * best.cost / dof
    err = float(np.sqrt(max(cov[2, 2], 0.0)))
    shape = shape_of(p)
    g = freq_model_log(model, f, shape)
    rms_mag = float(np.sqrt(np.mean((p[0] + g.real - ls) ** 2)))
    rms_ph = float(np.degrees(np.sqrt(np.mean(np.angle(np.exp(1j * (p[1] + g.imag - ph))) ** 2))))

    def func(ff):
        return np.exp(p[0] + 1j * p[1] + freq_model_log(model, ff, shape))
    return {'func': func, 'shape': shape, 'shape_err': err if model == 'pow' else shape * err,
            'rms_mag': rms_mag, 'rms_phase': rms_ph, 'n': f.size}


def fit_broken_power(f, s, s_rel):
    '''Duas leis de potência contínuas em log-log: log S = c − n1·log f + (n1 − n2)·max(0, log f − log fb).
    Devolve dict com 'func', 'n1', 'n1_err', 'n2', 'n2_err', 'fb', 'fb_err', 'rms_mag', 'n', ou None.'''
    from scipy.optimize import least_squares
    f = np.asarray(f, dtype=np.float64)
    if f.size < 5:
        return None
    lf = np.log(f)
    ls = np.log(np.asarray(s, dtype=np.float64))
    sig = np.maximum(np.asarray(s_rel, dtype=np.float64), 0.01)
    if not np.all(np.isfinite(ls)):
        return None

    def model(p, x):
        return p[0] - p[1] * x + (p[1] - p[2]) * np.maximum(0.0, x - p[3])
    lo, hi = lf.min(), lf.max()
    best = None
    for lfb in np.linspace(lo, hi, 17)[1:-1]:          # quebra estritamente dentro da faixa
        try:
            sol = least_squares(lambda p: (model(p, lf) - ls) / sig, [ls[0] + lf[0], 1.0, 1.0, lfb],
                                bounds=([-np.inf, -5, -5, lo], [np.inf, 5, 5, hi]))
        except ValueError:
            continue
        if best is None or sol.cost < best.cost:
            best = sol
    if best is None:
        return None
    p = best.x
    e = np.sqrt(np.maximum(np.diag(np.linalg.pinv(best.jac.T @ best.jac) * 2 * best.cost / max(1, f.size - 4)), 0))
    fb = float(np.exp(p[3]))
    return {'func': lambda ff: np.exp(model(p, np.log(ff))) + 0j,
            'n1': p[1], 'n1_err': e[1], 'n2': p[2], 'n2_err': e[2], 'fb': fb, 'fb_err': fb * e[3],
            'rms_mag': float(np.sqrt(np.mean((model(p, lf) - ls) ** 2))), 'n': f.size}


def wrap_deg(a):
    '''Ângulo(s) em graus no intervalo [-180, 180).'''
    return (np.asarray(a) + 180.0) % 360.0 - 180.0


def rolling_noise(z, w):
    '''Estatística móvel (janela de w pontos) da saída complexa Z = X + jY do lock-in.
    Devolve (|<Z>|, sigma por quadratura) para cada janela completa.'''
    z = np.asarray(z, dtype=np.complex128)
    if w < 2 or z.size < w:
        return np.empty(0), np.empty(0)
    c1 = np.concatenate(([0j], np.cumsum(z)))
    c2 = np.concatenate(([0.0], np.cumsum(np.abs(z) ** 2)))
    mean = (c1[w:] - c1[:-w]) / w
    p2 = (c2[w:] - c2[:-w]) / w
    var = np.maximum(p2 - np.abs(mean) ** 2, 0.0) * w / (w - 1)
    return np.abs(mean), np.sqrt(var / 2.0)


def fmt_tau(tau):
    if not np.isfinite(tau):
        return 'τ = —'
    return f'τ = {tau * 1e3:.3g} ms' if tau < 1.0 else f'τ = {tau:.3g} s'


LP_TIP = ('Passa-baixas aplicado depois da demodulação (2 polos em cascata): define a banda do lock-in.\n'
          'Corte menor = menos ruído e leitura mais estável, porém resposta mais lenta (τ maior).\n'
          'Deve ficar bem abaixo de 2× a frequência de modulação, para rejeitar o resíduo em 2f.\n'
          'Ao mudar a frequência, volta ao automático: 5 % da frequência, entre 0,08 e 0,5 Hz.')
HP_TIP = ('Passa-altas de 1 polo antes da demodulação: estima e remove o nível DC do sinal\n'
          '(luz ambiente, offset do sensor), deixando só a parte modulada.\n'
          'Precisa ficar bem abaixo da frequência de modulação: corte alto atenua e adianta a fase do sinal.\n'
          'No OPT101 o DC estimado também é o usado em R/DC e na coluna DC_Offset das varreduras.\n'
          'Ao mudar a frequência, volta ao automático: 2 % da frequência, entre 0,01 e 0,05 Hz.')
TAU_TIP = ('Constante de tempo de cada polo do passa-baixas, calculada a partir do corte (τ ≈ 1/(2π·corte)).\n'
           'Após um degrau, a saída atinge ~95% em 4,7τ e ~99% em 6,6τ.\n'
           'As varreduras esperam 9τ antes de medir cada ponto.')


# ============================================================================
# PURE-BEGIN  (classes sem Qt/serial: testáveis isoladamente)
# ============================================================================
# ----------------------------------------------------------------------------
# Lock-in (antigo lockin_py.py): OPT101 (com PLL) e INMP441 (referência numérica)
# ----------------------------------------------------------------------------
Result = namedtuple('Result', 'adc ref r phase dc consumed')

PLL_KP = 0.05
PLL_KI = PLL_KP * PLL_KP / 4.0
PLL_ERR_UNLOCK = 1.1
PLL_ERR_ALPHA = 0.15
PLL_FREQ_CLAMP = 0.05
TWO_PI = 2.0 * np.pi


def _wrap_pi(x):
    '''Leva o ângulo (rad) ao intervalo [-pi, pi).'''
    return (x + np.pi) % TWO_PI - np.pi


_E_U16 = np.empty(0, np.uint16)
_E_U8 = np.empty(0, np.uint8)
_E_F = np.empty(0, np.float64)


MAINS_HZ = 60.0
MAINS_MAX_HZ = 1500.0     # harmônicas rejeitadas até esta frequência
MAINS_BW_HZ = 2.0         # largura (-3 dB) de cada notch
MAINS_GUARD_HZ = 5.0      # notches a menos disso da modulação são omitidos (preservam o sinal)


def mains_notch_sos(fs, ref_freq):
    '''Notches em 60 Hz e múltiplos até MAINS_MAX_HZ, sem os que caem a menos de MAINS_GUARD_HZ da
    modulação. Devolve {harmônica: linha sos (b0 b1 b2 a0 a1 a2)}.'''
    nyq = fs / 2.0
    out = {}
    for h in range(1, int(min(MAINS_MAX_HZ, 0.95 * nyq) // MAINS_HZ) + 1):
        f0 = h * MAINS_HZ
        if abs(f0 - ref_freq) > MAINS_GUARD_HZ:
            b, a = iirnotch(f0, f0 / MAINS_BW_HZ, fs)
            out[h] = np.concatenate((b, a))
    return out


class _MainsFilterMixin:
    '''Notches em 60 Hz e múltiplos (usa self.fs, self.ref_freq e self.mains_zi).'''

    supports_mains = True

    def set_mains_filter(self, enabled):
        self.mains_enabled = bool(enabled)
        self.mains_zi = {}

    mains_enabled = False

    def _mains_filter(self, x):
        '''Notches em 60 Hz e múltiplos, só no caminho do lock-in. Omite os que caem sobre a modulação.'''
        notches = mains_notch_sos(self.fs, self.ref_freq)
        hs = list(notches)
        self.mains_zi = {h: z for h, z in self.mains_zi.items() if h in hs}
        if not hs:
            return x
        secs, zis = [], []
        for h in hs:
            sos = notches[h][None, :]
            secs.append(sos)
            z = self.mains_zi.get(h)
            zis.append(sosfilt_zi(sos)[0] * x[0] if z is None else z)
        sos_all = np.concatenate(secs)
        y, zf = sosfilt(sos_all, x, zi=np.array(zis))
        self.mains_zi = {h: zf[i] for i, h in enumerate(hs)}
        return y


class PyLockIn(_MainsFilterMixin):
    def __init__(self, fs, ref_freq, cutoff_lp, cutoff_hp):
        self.init(fs, ref_freq, cutoff_lp, cutoff_hp)

    # --------------------------------------------------------------- estado
    def init(self, fs, ref_freq, cutoff_lp, cutoff_hp):
        self.fs = float(fs)
        self.ref_freq = ref_freq
        self.alpha_lp = TWO_PI * cutoff_lp / self.fs
        self.alpha_hp = TWO_PI * cutoff_hp / self.fs
        self.d_theta = TWO_PI * ref_freq / self.fs
        self.dc_offset = 512.0
        self.dc_init = False
        self.theta = 0.0
        self.last_ref = 0
        self.lp1 = 0j
        self.lp2 = 0j
        self.sample_count = 0
        self.edge_count = 0
        self.measured_freq = ref_freq
        self.pll_locked = False
        self.err_avg = 0.0
        self.mains_zi = {}

    def update_params(self, ref_freq, cutoff_lp, cutoff_hp):
        self.ref_freq = ref_freq
        self.alpha_lp = TWO_PI * cutoff_lp / self.fs
        self.alpha_hp = TWO_PI * cutoff_hp / self.fs
        self.edge_count = 0
        self._unlock()

    def _nominal_step(self):
        return TWO_PI * self.ref_freq / self.fs

    def _unlock(self):
        self.pll_locked = False
        self.err_avg = 0.0
        self.d_theta = self._nominal_step()
        self.measured_freq = self.ref_freq

    # --------------------------------------------------------------- quadros
    @staticmethod
    def _parse(buf):
        '''Extrai quadros 0x55 0xAA ADC_L ADC_H REF; devolve (adc, ref, bytes_consumidos).'''
        raw = np.frombuffer(buf, dtype=np.uint8)
        size = raw.size
        if size < 5:
            return _E_U16, _E_U8, 0
        m = size // 5
        fr = raw[:m * 5].reshape(m, 5)
        if (fr[:, 0] == 0x55).all() and (fr[:, 1] == 0xAA).all():
            adc = fr[:, 2].astype(np.uint16) | (fr[:, 3].astype(np.uint16) << 8)
            return adc, fr[:, 4].copy(), m * 5
        # Fora de sincronismo: aceita cada 0x55 0xAA sem sobreposição de quadros
        cand = np.flatnonzero((raw[:-1] == 0x55) & (raw[1:] == 0xAA))
        starts, end = [], 0
        for c in cand:
            if c >= end and c + 5 <= size:
                starts.append(c)
                end = c + 5
        if not starts:
            return _E_U16, _E_U8, size - 4
        st = np.asarray(starts)
        adc = raw[st + 2].astype(np.uint16) | (raw[st + 3].astype(np.uint16) << 8)
        return adc, raw[st + 4].copy(), (end if size - end < 5 else size - 4)

    # ------------------------------------------------------------------- PLL
    def _phase(self, ref):
        '''Fase do demodulador em cada amostra. O estado do PLL avança a cada borda de subida.'''
        n = ref.size
        prev = np.empty(n, dtype=np.uint8)
        prev[0] = self.last_ref
        prev[1:] = ref[:-1]
        edges = np.flatnonzero((prev == 0) & (ref == 1)).tolist()
        self.last_ref = int(ref[-1])

        limit = int(self.fs * 10.0)
        nominal_n = self.fs / self.ref_freq if self.ref_freq > 0 else 0.0
        tol = 2.0 + 0.001 * nominal_n

        # Segmentos de fase linear: (início, theta no início, passo)
        starts, thetas, steps = [0], [self.theta], [self.d_theta]
        s, th, d = 0, self.theta, self.d_theta   # segmento corrente
        c, p = self.edge_count, 0                # contador de amostras desde a última borda, a partir de p

        for e in edges + [None]:
            end = e if e is not None else n
            # Perda de referência por mais de 10 s antes de 'end': volta à frequência nominal
            j = p + max(0, limit - c)
            while j < end:
                th += d * (j - s); s = j
                self.d_theta = d; self._unlock(); d = self.d_theta
                starts.append(s); thetas.append(th); steps.append(d)
                c, p = 0, j + 1
                j = p + max(0, limit - c)
            if e is None:
                break
            N = c + (e - p) + 1
            th += d * (e - s); s = e
            c, p = 0, e + 1
            if abs(N - nominal_n) > tol or nominal_n <= 0.0:
                self.d_theta = d; self._unlock(); d = self.d_theta
            elif not self.pll_locked:
                th, d = 0.0, self._nominal_step()
                self.pll_locked, self.err_avg = True, 0.0
            else:
                err = _wrap_pi(th)
                self.err_avg += PLL_ERR_ALPHA * (abs(err) - self.err_avg)
                if self.err_avg > PLL_ERR_UNLOCK:
                    self.d_theta = d; self._unlock(); d = self.d_theta
                else:
                    nom = self._nominal_step()
                    th -= PLL_KP * err
                    d -= PLL_KI * err / nominal_n
                    d = min(max(d, nom * (1.0 - PLL_FREQ_CLAMP)), nom * (1.0 + PLL_FREQ_CLAMP))
                    self.measured_freq = d * self.fs / TWO_PI
            starts.append(s); thetas.append(th); steps.append(d)

        th_end = (th + d * (n - s)) % TWO_PI
        self.theta, self.d_theta, self.edge_count = th_end, d, c + (n - p)

        if len(starts) == 1:
            return thetas[0] + steps[0] * np.arange(n)
        st = np.asarray(starts)
        lens = np.diff(np.append(st, n))
        return (np.repeat(thetas, lens) + np.repeat(steps, lens)
                * (np.arange(n) - np.repeat(st, lens)))

    # ------------------------------------------------------------------ DSP
    def process(self, buf, decimation, enable_lockin, normalize):
        adc, ref, consumed = self._parse(buf)
        if adc.size == 0 or not enable_lockin:
            return Result(adc, ref, _E_F, _E_F, _E_F, consumed)
        n = adc.size
        x = adc.astype(np.float64)

        theta = self._phase(ref)
        if self.mains_enabled:
            x = self._mains_filter(x)
            adc = x.astype(np.float32)
        # Remoção de DC: passa-baixas de 1 polo; y[k] = a*x[k] + (1-a)*y[k-1]
        if not self.dc_init:
            self.dc_offset, self.dc_init = float(x[0]), True
        a = self.alpha_hp
        dc = lfilter([a], [1.0, a - 1.0], x, zi=[(1.0 - a) * self.dc_offset])[0]
        self.dc_offset = float(dc[-1])

        # Demodulação em quadratura, em um único vetor complexo (x + jy)
        z = (2.0 * (x - dc)) * np.exp(-1j * theta)

        # Passa-baixas de 2 polos em cascata
        a = self.alpha_lp
        b_lp, a_lp = [a], [1.0, a - 1.0]
        z1 = lfilter(b_lp, a_lp, z, zi=[(1.0 - a) * self.lp1])[0]
        z2 = lfilter(b_lp, a_lp, z1, zi=[(1.0 - a) * self.lp2])[0]
        self.lp1, self.lp2 = complex(z1[-1]), complex(z2[-1])

        # Decimação: uma saída a cada 'decimation' amostras (contador persistente)
        first = decimation - self.sample_count - 1
        self.sample_count = (self.sample_count + n) % decimation
        idx = np.arange(first, n, decimation)
        zo = z2[idx]
        # Cada quadro do firmware é a média de OSR amostras do ADC numa janela de 1/FS (80 us):
        # a fundamental chega atenuada por sinc(f/FS) (-1 % em 1 kHz, -9 % em 3 kHz). Desfaz aqui.
        r = np.abs(zo) / np.sinc(self.ref_freq / self.fs)
        phase = np.degrees(np.angle(zo))
        dco = dc[idx]
        if normalize:
            r = r / np.maximum(dco, 1.0) * 100.0
        return Result(adc, ref, r, phase, dco, consumed)


class AudioLockIn(_MainsFilterMixin):
    '''Lock-in do INMP441: mesma cadeia do PyLockIn (passa-altas de 1 polo para o DC, notches de
    rede opcionais, demodulação em quadratura e passa-baixas de 2 polos), mas com referência
    numérica: a fase vem do número de sequência da amostra I2S, sem PLL.'''

    def __init__(self, fs, ref_freq, cutoff_lp, cutoff_hp):
        self.init(fs, ref_freq, cutoff_lp, cutoff_hp)

    def init(self, fs, ref_freq, cutoff_lp, cutoff_hp):
        self.fs = float(fs)
        self.ref_freq = actual_mod_freq(ref_freq)
        self.alpha_lp = TWO_PI * cutoff_lp / self.fs
        self.alpha_hp = TWO_PI * cutoff_hp / self.fs
        self.dc_offset = 0.0
        self.dc_init = False
        self.lp1 = 0j
        self.lp2 = 0j
        self.sample_count = 0
        self.mains_zi = {}
        self.phase_origin = 0     # nº da amostra I2S da borda de subida do laser (marcador do firmware)

    def update_params(self, ref_freq, cutoff_lp, cutoff_hp):
        # Os estados dos filtros são mantidos: ao trocar a frequência a saída transita até estabilizar
        self.ref_freq = actual_mod_freq(ref_freq)
        self.alpha_lp = TWO_PI * cutoff_lp / self.fs
        self.alpha_hp = TWO_PI * cutoff_hp / self.fs

    def process(self, sequence, samples, decimation):
        '''samples: int32 (PCM 24 bits). Devolve (r, fase em graus), uma saída a cada 'decimation'
        amostras (contador persistente), em fração da escala completa.'''
        x = np.asarray(samples, dtype=np.float64) / 8388608.0
        n = float((sequence - self.phase_origin) & 0xFFFFFFFF) + np.arange(x.size, dtype=np.float64)
        theta = TWO_PI * np.mod(self.ref_freq * n / self.fs, 1.0)
        if self.mains_enabled:
            x = self._mains_filter(x)
        if not self.dc_init:
            self.dc_offset, self.dc_init = float(x[0]), True
        a = self.alpha_hp
        dc = lfilter([a], [1.0, a - 1.0], x, zi=[(1.0 - a) * self.dc_offset])[0]
        self.dc_offset = float(dc[-1])

        z = (2.0 * (x - dc)) * np.exp(-1j * theta)

        a = self.alpha_lp
        b_lp, a_lp = [a], [1.0, a - 1.0]
        z1 = lfilter(b_lp, a_lp, z, zi=[(1.0 - a) * self.lp1])[0]
        z2 = lfilter(b_lp, a_lp, z1, zi=[(1.0 - a) * self.lp2])[0]
        self.lp1, self.lp2 = complex(z1[-1]), complex(z2[-1])

        first = decimation - self.sample_count - 1
        self.sample_count = (self.sample_count + x.size) % decimation
        zo = z2[np.arange(first, x.size, decimation)]
        return np.abs(zo), np.degrees(np.angle(zo))


class RawRing:
    '''Ring buffer do osciloscópio. Em vez de apagar um 'rastro' com NaN
    amostra por amostra, o desenho usa duas fatias que deixam um vão à frente
    do cursor; o custo por lote é constante, independente do tamanho do vão.'''

    def __init__(self, window_sec, fs):
        self.fs = fs
        self.resize(window_sec)

    def resize(self, window_sec):
        self.window = float(window_sec)
        self.n = max(2, int(self.window * self.fs))
        self.gap = max(5, int(0.02 * self.n))
        self.adc = np.zeros(self.n, dtype=np.float32)
        self.ref = np.zeros(self.n, dtype=np.float32)
        self.t = np.linspace(0.0, self.window, self.n, dtype=np.float32)
        self.head = 0
        self.wrapped = False

    def push(self, adc, ref):
        '''Insere um lote. Retorna True se o cursor deu a volta na janela.'''
        N = self.n
        n = len(adc)
        if n >= N:
            adc, ref, n = adc[-N:], ref[-N:], N
        h = self.head
        end = h + n
        if end <= N:
            self.adc[h:end] = adc
            self.ref[h:end] = ref
        else:
            k = N - h
            self.adc[h:] = adc[:k]
            self.adc[:end - N] = adc[k:]
            self.ref[h:] = ref[:k]
            self.ref[:end - N] = ref[k:]
        self.head = end % N
        wrapped_now = end >= N
        if wrapped_now:
            self.wrapped = True
        return wrapped_now

    def segments(self):
        '''(fatia_a, fatia_b) a desenhar; fatia_b pode ser None.'''
        N, h, g = self.n, self.head, self.gap
        a0 = max(0, h + g - N) if self.wrapped else 0
        a = slice(a0, h)
        b = slice(h + g, N) if (self.wrapped and h + g < N) else None
        return a, b

    def cursor_x(self):
        return self.head / self.n * self.window


class AverageAccumulator:
    '''Forma de onda média por pulso, vetorizada por lote.

    Um ciclo vai de (borda_k - pré) até a borda_{k+1} (exclusive), exatamente
    como no algoritmo original amostra a amostra.
    '''

    def __init__(self, fs):
        self.fs = fs
        self.pulses = 8
        self.pre = 0
        self.reset()

    def reset(self):
        self.cycles = []
        self.tail_adc = np.empty(0, dtype=np.float32)
        self.tail_ref = np.empty(0, dtype=np.uint8)
        self.tail_prev_ref = 0
        self.open_idx = -1
        self.values = np.empty(0)
        self.time = np.empty(0)

    def current_len(self):
        return len(self.tail_adc) if self.open_idx >= 0 else 0

    def push(self, adc, ref):
        '''Processa um lote. Retorna True quando uma nova média ficou pronta.'''
        a = np.concatenate((self.tail_adc, np.asarray(adc, dtype=np.float32)))
        r = np.concatenate((self.tail_ref, np.asarray(ref, dtype=np.uint8)))
        n_old = len(self.tail_adc)
        rp = np.concatenate((np.array([self.tail_prev_ref], dtype=np.uint8), r))
        edges = np.flatnonzero((rp[1:] == 1) & (rp[:-1] == 0))
        edges = edges[edges >= n_old]

        pre = self.pre
        open_idx = self.open_idx
        ready = False
        for e in edges.tolist():
            if open_idx >= 0 and open_idx - pre >= 0:
                self.cycles.append(a[open_idx - pre:e].copy())
                if len(self.cycles) >= self.pulses:
                    spc = min(len(c) for c in self.cycles)
                    stack = np.stack([c[:spc] for c in self.cycles])
                    self.values = stack.mean(axis=0)
                    self.time = (np.arange(spc) - pre) / self.fs
                    self.cycles = []
                    ready = True
            open_idx = e

        if open_idx >= 0:
            start = max(open_idx - pre, 0)
        else:
            start = max(len(a) - (pre + 1), 0)
        if start > 0:
            self.tail_prev_ref = int(r[start - 1])
        self.tail_adc = a[start:].copy()
        self.tail_ref = r[start:].copy()
        self.open_idx = open_idx - start if open_idx >= 0 else -1
        return ready
# ============================================================================
# PURE-END
# ============================================================================


# ----------------------------------------------------------------------------
# Serial em thread
# ----------------------------------------------------------------------------
def find_arduino_port():
    configured_port = os.environ.get('TL_ARDUINO_PORT')
    ports = list(list_ports.comports())
    if configured_port and any(p.device.upper() == configured_port.upper() for p in ports):
        return configured_port, ports
    # STM32 (VID 0x0483) primeiro, depois as outras placas conhecidas; só portas USB.
    # Nomes genéricos ("serial", "usb serial") não bastam: pegavam Bluetooth e adaptadores USB-serial.
    usb = [p for p in ports if p.vid is not None]
    for vids in ({0x0483}, ARDUINO_VIDS):
        for port in usb:
            if port.vid in vids:
                return port.device, ports
    for port in usb:
        ident = ' '.join(filter(None, [port.description, port.manufacturer])).lower()
        if any(k in ident for k in ('arduino', 'stm32', 'stmicro')):
            return port.device, ports
    if len(usb) == 1:
        return usb[0].device, ports
    return None, ports


class SerialLink(threading.Thread):
    '''Lê a porta serial continuamente e reconecta sozinha se necessário.
    A GUI só chama take() para pegar os bytes acumulados.'''

    def __init__(self, get_params):
        super().__init__(daemon=True)
        self.get_params = get_params          # () -> (freq_hz, power_pct)
        self.ser = None
        self.connected = False
        self.port = None                      # porta em uso (exibida na barra de status)
        self.last_error = None
        self._parse_buf = bytearray()
        self._opt_buf = bytearray()
        self._audio_chunks = deque()
        self._audio_queued_samples = 0
        self._audio_queue_drops = 0
        self.audio_crc_errors = 0
        self._lock = threading.Lock()         # protege as filas de saída
        self._wlock = threading.Lock()        # protege escrita/fechamento
        self._stop_evt = threading.Event()

    # -- API para a GUI --
    def take_optical(self):
        with self._lock:
            optical = bytes(self._opt_buf)
            self._opt_buf.clear()
        return optical

    def take_audio(self):
        with self._lock:
            audio = list(self._audio_chunks)
            self._audio_chunks.clear()
            self._audio_queued_samples = 0
            dropped = self._audio_queue_drops
            self._audio_queue_drops = 0
        return audio, dropped

    @staticmethod
    def _crc16_ccitt(data):
        # CRC-16/CCITT-FALSE em C (o laço em Python saturava a CPU e a thread serial)
        return binascii.crc_hqx(bytes(data), 0xFFFF)

    def _parse_received(self, data):
        self._parse_buf.extend(data)
        optical = bytearray()
        audio = []
        pos = 0
        size = len(self._parse_buf)

        while pos < size:
            remaining = size - pos
            if remaining == 1 and self._parse_buf[pos] == 0x55:
                break
            if remaining < len(AUDIO_PACKET_MAGIC):
                tail = self._parse_buf[pos:]
                if AUDIO_PACKET_MAGIC.startswith(tail) or MOD_MARKER_MAGIC.startswith(tail):
                    break
            elif self._parse_buf[pos:pos + len(MOD_MARKER_MAGIC)] == MOD_MARKER_MAGIC:
                if remaining < MOD_MARKER_SIZE:
                    break
                crc = int.from_bytes(self._parse_buf[pos + 8:pos + 10], 'little')
                if self._crc16_ccitt(self._parse_buf[pos + 4:pos + 8]) == crc:
                    audio.append((int.from_bytes(self._parse_buf[pos + 4:pos + 8], 'little'), None))
                    pos += MOD_MARKER_SIZE
                    continue
                pos += 1
                continue
            elif self._parse_buf[pos:pos + len(AUDIO_PACKET_MAGIC)] == AUDIO_PACKET_MAGIC:
                if remaining < AUDIO_PACKET_HEADER_SIZE:
                    break
                sequence = int.from_bytes(self._parse_buf[pos + 4:pos + 8], 'little')
                count = int.from_bytes(self._parse_buf[pos + 8:pos + 10], 'little')
                if not 1 <= count <= AUDIO_PACKET_MAX_SAMPLES:
                    pos += 1
                    continue
                payload_start = pos + AUDIO_PACKET_HEADER_SIZE
                packet_end = payload_start + count * 3 + 2
                if size < packet_end:
                    break
                packet_crc = int.from_bytes(self._parse_buf[packet_end - 2:packet_end], 'little')
                if self._crc16_ccitt(self._parse_buf[pos + 4:packet_end - 2]) != packet_crc:
                    self.audio_crc_errors += 1
                    pos += 1
                    continue

                packed = np.frombuffer(
                    self._parse_buf, dtype=np.uint8, count=count * 3, offset=payload_start
                ).reshape(count, 3).astype(np.int32)
                samples = packed[:, 0] | (packed[:, 1] << 8) | (packed[:, 2] << 16)
                samples = (samples ^ 0x800000) - 0x800000
                audio.append((sequence, samples))
                pos = packet_end
                continue

            if remaining >= 2 and self._parse_buf[pos:pos + 2] == b'\x55\xAA':
                if remaining < 5:
                    break
                if self._parse_buf[pos + 4] <= 1:
                    optical.extend(self._parse_buf[pos:pos + 5])
                    pos += 5
                    continue
            pos += 1

        if pos:
            del self._parse_buf[:pos]

        if optical or audio:
            with self._lock:
                self._opt_buf.extend(optical)
                if len(self._opt_buf) > MAX_RX_BYTES:
                    del self._opt_buf[:-MAX_RX_BYTES]
                for sequence, samples in audio:      # samples None = marcador de modulação
                    self._audio_chunks.append((sequence, samples))
                    self._audio_queued_samples += 0 if samples is None else len(samples)
                    while self._audio_queued_samples > AUDIO_QUEUE_MAX_SAMPLES:
                        _, discarded = self._audio_chunks.popleft()
                        self._audio_queued_samples -= 0 if discarded is None else len(discarded)
                        self._audio_queue_drops += len(discarded)

    def write(self, text):
        with self._wlock:
            ser = self.ser
            if ser is None:
                return
            try:
                ser.write(text.encode())
            except Exception as e:
                print(f"Conexão com o Arduino perdida ao escrever: {e}")
                self._close_locked()

    def stop(self):
        self._stop_evt.set()
        self.join(timeout=2.0)
        with self._wlock:
            self._close_locked()

    # -- internos --
    def _close_locked(self):
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.connected = False

    def _try_connect(self):
        port, _ = find_arduino_port()
        if port is None:
            return
        new = None
        try:
            print(f"Conectando à porta {port}...")
            new = serial.Serial(port, BAUD_RATE, timeout=0.05)
            try:
                new.set_buffer_size(rx_size=1 << 20, tx_size=1 << 14)
            except Exception:
                pass
            # STM32 USB CDC não reinicia com DTR; espera curta só para estabilizar.
            if self._stop_evt.wait(0.3):
                new.close()
                return
            new.reset_input_buffer()
            f, p = self.get_params()
            new.write(f"F{f}\n".encode())
            time.sleep(0.05)
            new.write(f"P{p}\n".encode())
            self._parse_buf.clear()
            with self._lock:
                self._opt_buf.clear()
                self._audio_chunks.clear()
                self._audio_queued_samples = 0
                self.audio_crc_errors = 0
            with self._wlock:
                self.ser = new
                self.port = port
                self.connected = True
                self.last_error = None
            print(f"Conectado! Parâmetros enviados: F={f} Hz, PWM={p}%")
            # Uma troca feita na GUI durante a conexão foi descartada por write() (ser ainda era None)
            f2, p2 = self.get_params()
            if f2 != f:
                self.write(f"F{f2}\n")
            if p2 != p:
                self.write(f"P{p2}\n")
        except Exception as e:
            self.last_error = f"{port}: {e}"
            print(f"Erro ao abrir porta serial ({port}): {e}")
            if new is not None:
                try:
                    new.close()
                except Exception:
                    pass

    def run(self):
        last_try = 0.0
        while not self._stop_evt.is_set():
            ser = self.ser
            if ser is None:
                now = time.monotonic()
                if now - last_try >= RECONNECT_INTERVAL:
                    last_try = now
                    self._try_connect()
                else:
                    self._stop_evt.wait(0.1)
                continue
            try:
                # Bloqueia até chegar ao menos 1 byte (ou 50 ms de timeout).
                data = ser.read(max(1, ser.in_waiting))
            except Exception as e:
                print(f"Conexão com o Arduino perdida ao ler: {e}")
                with self._wlock:
                    self._close_locked()
                continue
            if data:
                self._parse_received(data)


# ----------------------------------------------------------------------------
# Janela principal
# ----------------------------------------------------------------------------
class SignalSimulator:
    '''Gera quadros 0x55 0xAA ADC_L ADC_H REF como o firmware, sem STM32.
    Referência quadrada; com laser ligado o sinal sobe exponencialmente até uma saturação
    proporcional à potência (100 % -> SIM_FULL_POWER_FRAC do fundo de escala).'''
    SIM_FULL_POWER_FRAC = 0.70
    TAU = 0.05            # s, constante de tempo do crescimento
    BASELINE = 0.02       # fração do fundo de escala (escuro)
    NOISE = 0.004         # desvio padrão (fração do fundo de escala)

    def __init__(self, fs):
        from scipy.signal import lfilter
        self._lfilter = lfilter
        self.fs = fs
        self.rng = np.random.default_rng()
        self.a = float(np.exp(-1.0 / (fs * self.TAU)))
        self.reset()

    def reset(self):
        self.t_last = None
        self.n = 0
        self.y = 0.0

    def generate(self, now, freq, power_pct):
        if self.t_last is None:
            self.t_last = now
            return b''
        m = int((now - self.t_last) * self.fs)
        if m <= 0:
            return b''
        m = min(m, int(self.fs))
        self.t_last += m / self.fs
        idx = self.n + np.arange(m)
        self.n += m
        if freq > 0:
            ref = ((idx * freq / self.fs) % 1.0 < 0.5).astype(np.uint8)
        else:
            ref = np.ones(m, dtype=np.uint8)
        top = self.SIM_FULL_POWER_FRAC * max(0.0, min(power_pct, 100.0)) / 100.0
        target = ref * top
        a = self.a
        y, zf = self._lfilter([1.0 - a], [1.0, -a], target, zi=[a * self.y])
        self.y = float(y[-1])
        t = idx / self.fs
        sig = (self.BASELINE + y + 0.003 * np.sin(2 * np.pi * 60.0 * t)
               + self.NOISE * self.rng.standard_normal(m))
        adc = np.clip(sig * ADC_FULL_SCALE * ADC_OVS_FACTOR, 0, 65535).astype('<u2')
        frames = np.empty((m, 5), dtype=np.uint8)
        frames[:, 0] = 0x55
        frames[:, 1] = 0xAA
        frames[:, 2] = adc & 0xFF
        frames[:, 3] = adc >> 8
        frames[:, 4] = ref
        return frames.tobytes()


class AudioSimulator:
    '''Gera áudio PCM de 24 bits a AUDIO_FS, como os pacotes I2S do INMP441 enviados pelo STM32.
    Sinal típico de microfone em silêncio (pequeno DC + ruído branco + ruído 1/f + resquício de 60 Hz)
    somado a um tom na frequência de excitação, com amplitude proporcional à potência do laser e
    dependente da frequência (resposta passa-baixas).'''
    NOISE_RMS = 3e-5          # ruído branco, fração do fundo de escala (~ -90 dBFS)
    PINK_CORNER_HZ = 300.0    # acima disto o ruído é branco; abaixo, sobe a 10 dB/década (1/f em potência)
    PINK_FMIN_HZ = 0.01       # o 1/f se estende até esta frequência
    DC = 0.004                # offset DC típico do INMP441
    HUM = 2e-5                # resquício de rede (60 Hz)
    TONE_FULL_POWER = 2e-3    # amplitude do tom com laser a 100 % (~ -54 dBFS)
    TONE_TAU = 2e-4           # s, resposta passa-baixas de 1ª ordem do tom (corte ~800 Hz): amplitude e fase variam com a frequência
    CHUNK = AUDIO_PACKET_MAX_SAMPLES

    def __init__(self):
        self.rng = np.random.default_rng()
        self.reset()

    def reset(self):
        self.t_last = None
        self.n = 0
        self.phase = 0.0
        self.freq = None          # última frequência: a troca reinicia a onda do laser (como o firmware)
        self.n0 = 0
        self._init_pink()

    def _init_pink(self):
        '''Ruído 1/f = soma de processos AR(1) (Lorentzianas) com polos espaçados de uma oitava e
        variâncias iguais. A escala faz a DEP 1/f igualar a DEP do ruído branco em PINK_CORNER_HZ.'''
        n_poles = int(np.ceil(np.log2(0.3 * AUDIO_FS / self.PINK_FMIN_HZ)))
        fk = self.PINK_FMIN_HZ * 2.0 ** np.arange(n_poles)
        self._pink_p = np.exp(-2.0 * np.pi * fk / AUDIO_FS)
        s_white = self.NOISE_RMS ** 2 / (AUDIO_FS / 2.0)                  # DEP unilateral (1/Hz)
        shape = np.sum(2.0 / (np.pi * fk) / (1.0 + (self.PINK_CORNER_HZ / fk) ** 2))
        self._pink_sigma = float(np.sqrt(s_white / shape))
        # Estado inicial já estacionário (sem transitório de partida)
        self._pink_y = self.rng.normal(0.0, self._pink_sigma, n_poles)

    def _pink(self, m):
        out = np.zeros(m)
        for k, p in enumerate(self._pink_p):
            w = self.rng.standard_normal(m) * (self._pink_sigma * np.sqrt(1.0 - p * p))
            y, _ = lfilter([1.0], [1.0, -p], w, zi=[p * self._pink_y[k]])
            self._pink_y[k] = y[-1]
            out += y
        return out

    def generate(self, now, freq, power_pct):
        '''Retorna lista de (sequência, amostras int32 de 24 bits com sinal).'''
        if self.t_last is None:
            self.t_last = now
            return []
        m = int((now - self.t_last) * AUDIO_FS)
        if m <= 0:
            return []
        m = min(m, AUDIO_FS)
        self.t_last += m / AUDIO_FS
        markers = []
        if freq != self.freq:
            # O firmware reinicia o TIM4 num instante arbitrário e informa a amostra I2S da borda
            self.freq = freq
            self.n0 = self.n + int(self.rng.integers(0, 256))
            markers.append((self.n0 & 0xFFFFFFFF, None))
        idx = self.n + np.arange(m)
        # Fase travada na referência (número da amostra). A resposta do sistema (passa-baixas de 1ª
        # ordem, como a do sinal do OPT101) reduz a amplitude e atrasa a fase conforme a frequência sobe.
        w = 2.0 * np.pi * freq * self.TONE_TAU
        gain = 1.0 / np.sqrt(1.0 + w * w)
        # Como no hardware: taxa I2S real, frequência quantizada pelo TIM4 e onda quadrada que começa
        # (borda de subida) em n0. A fundamental da onda quadrada é sen(wt) = cos(wt - 90°).
        ph = (2.0 * np.pi * np.mod(actual_mod_freq(freq) * (idx - self.n0) / AUDIO_FS_REAL, 1.0)
              - np.pi / 2.0 - np.arctan(w))
        amp = gain * self.TONE_FULL_POWER * max(0.0, min(power_pct, 100.0)) / 100.0
        x = (self.DC + amp * np.cos(ph)
             + self.HUM * np.sin(2.0 * np.pi * 60.0 * idx / AUDIO_FS)
             + self.NOISE_RMS * self.rng.standard_normal(m)
             + self._pink(m))
        pcm = np.clip(np.rint(x * 8388607.0), -8388608, 8388607).astype(np.int32)
        chunks = markers + [((self.n + k) & 0xFFFFFFFF, pcm[k:k + self.CHUNK]) for k in range(0, m, self.CHUNK)]
        self.n += m
        return chunks


class TimeAxis(pg.AxisItem):
    '''Eixo de tempo com unidade nos rótulos (s ou ms).'''
    lockin_time = True
    base_label = 'Tempo antes do instante atual'
    _unit = None

    def tickStrings(self, values, scale, spacing):
        if not self.lockin_time:
            return super().tickStrings(values, scale, spacing)
        ms = abs(spacing) < 0.1
        unit = 'ms' if ms else 's'
        if unit != self._unit:
            self._unit = unit
            QtCore.QTimer.singleShot(0, lambda: self.lockin_time and self.setLabel(f'{self.base_label} ({self._unit})'))
        return [f'{v * 1000:g}' if ms else f'{v:g}' for v in values]


class ModeSwitch(QtWidgets.QAbstractButton):
    '''Chave vertical: em cima = Lock-In, embaixo = Valor Médio.'''

    def __init__(self, tip='Clique para alternar: cima = Lock-In, baixo = Valor Médio', parent=None):
        super().__init__(parent)
        self.down = False
        self.setFixedSize(34, 64)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tip)

    def setDown(self, down):
        self.down = bool(down)
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        track = QtCore.QRectF(3, 3, self.width() - 6, self.height() - 6)
        p.setPen(QtGui.QPen(QtGui.QColor('#777'), 1))
        p.setBrush(QtGui.QColor('#4a90d9' if not self.down else '#3fa34d'))
        p.drawRoundedRect(track, 14, 14)
        d = track.width() - 6
        y = track.bottom() - 3 - d if self.down else track.top() + 3
        p.setBrush(QtGui.QColor('white'))
        p.drawEllipse(QtCore.QRectF(track.left() + 3, y, d, d))


class ToggleSwitch(QtWidgets.QAbstractButton):
    '''Chave horizontal liga/desliga.'''

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(52, 26)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        track = QtCore.QRectF(2, 2, self.width() - 4, self.height() - 4)
        p.setPen(QtGui.QPen(QtGui.QColor('#777'), 1))
        p.setBrush(QtGui.QColor('#e0952b' if self.isChecked() else '#b8b8b8'))
        p.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        d = track.height() - 6
        x = track.right() - 3 - d if self.isChecked() else track.left() + 3
        p.setBrush(QtGui.QColor('white'))
        p.drawEllipse(QtCore.QRectF(x, track.top() + 3, d, d))


class RefreshComboBox(QtWidgets.QComboBox):
    '''QComboBox que atualiza a lista (refresh()) logo antes de abrir.'''

    def __init__(self, refresh):
        super().__init__()
        self._refresh = refresh

    def showPopup(self):
        self._refresh()
        super().showPopup()


class StepThread(threading.Thread):
    '''Chama step() repetidamente em thread própria até stop().'''

    def __init__(self, step, interval=0.005):
        super().__init__(daemon=True)
        self.step = step
        self.interval = interval
        self._stop_evt = threading.Event()

    def run(self):
        while not self._stop_evt.is_set():
            try:
                self.step()
            except Exception as e:
                print(f"Erro na thread de processamento: {e}")
            self._stop_evt.wait(self.interval)

    def stop(self):
        self._stop_evt.set()
        self.join(timeout=2.0)


class LockInWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('SOI Controller - LCTM')
        self.resize(1280, 1000)

        # --- Parâmetros ---
        self.ref_freq = 5.0
        self.laser_power = 0.4
        self.cutoff_lp, self.cutoff_hp = get_effective_cutoffs(self.ref_freq)
        self.normalize_mode = False

        # --- DSP do OPT101 (PyLockIn, definido neste arquivo) ---
        self.dsp = PyLockIn(FS, self.ref_freq, self.cutoff_lp, self.cutoff_hp)
        self.rx_bytes = bytearray()
        self.dsp_lock = threading.Lock()      # protege dsp e rx_bytes (thread do OPT101)
        self.opt_results = deque()

        # --- Lock-in do INMP441 (parâmetros próprios, independentes do OPT101) ---
        self.audio_freq = self.ref_freq
        self.audio_block_sec = AUDIO_LOCKIN_BLOCK / AUDIO_FS   # intervalo entre pontos plotados
        self.audio_max_points = AUDIO_MAX_POINTS
        self.audio_span = AUDIO_LOCKIN_SPAN
        self.audio_snr_db = None              # SNR da janela mais recente (alerta de sinal baixo)
        self.audio_snr_alert = LOW_SIGNAL_SNR_DB
        # Filtros do lock-in do INMP441: começam iguais aos do OPT101, mas são independentes
        self.audio_cutoff_lp = self.cutoff_lp
        self.audio_cutoff_hp = self.cutoff_hp
        self.audio_mains = False
        self.audio_lock = threading.Lock()    # protege o estado do áudio (thread do INMP441)

        # --- Dados ---
        self.raw = RawRing(5.0, FS)
        self.user_window = 5.0
        # FFT do sinal bruto do ADC (aba OPT101): histórico circular, só alimentado com a opção ligada
        self.opt_history = np.zeros(int(FS * OPT_FFT_HISTORY_SEC), dtype=np.float32)
        self.opt_write_index = 0
        self.opt_valid_samples = 0
        self.opt_fft_enabled = False
        self.opt_fft_full = False             # False = zoom em torno da referência
        self.last_opt_fft_t = 0.0
        self.opt_fft_fit_html = None
        self.opt_fft_missing = None
        self.audio_history = np.zeros(int(AUDIO_FS * AUDIO_FFT_HISTORY_SEC), dtype=np.int32)
        self.audio_fft_full = False           # False = zoom em torno da referência
        self.audio_write_index = 0
        self.audio_valid_samples = 0
        self._audio_reset_lockin()
        self.audio_fft_enabled = False        # padrão: só o gráfico do lock-in
        self.audio_lockin_enabled = True      # lock-in roda se o gráfico do lock-in ou o de ruído estiver ligado
        self.audio_xy = False                 # False = R e Fase, True = X e Y
        self.audio_phase_offset = 0.0         # graus subtraídos da fase (auto-fase ou manual)
        # Estatística de ruído/SNR na mesma janela do gráfico (limitada à metade do histórico guardado)
        self.audio_noise_window = min(AUDIO_LOCKIN_SPAN, AUDIO_NOISE_SPAN / 2)
        self.last_fft_t = 0.0
        self.audio_last_sequence = None
        self.audio_gap_samples = 0
        self.audio_received_samples = 0
        self.audio_queue_drops = 0
        self.audio_link_connected = False
        self.audio_wait_started = time.perf_counter()

        # Novas variáveis para taxa de dados e varredura do INMP441
        self.sweep_target = 'OPT'
        self.audio_sweep_r = []
        self.audio_sweep_p = []
        self.audio_sweep_count = 0
        self.last_audio_status_now = time.perf_counter()
        self.last_audio_received_samples_stat = 0

        self.last_audio_status_t = 0.0
        self.r_arr = np.empty(0, dtype=np.float32)
        self.phase_arr = np.empty(0, dtype=np.float32)
        self.lockin_dirty = False

        self.average_mode = False
        self.peak_hist = deque()
        self.avg = AverageAccumulator(FS)
        self.avg_dirty = False
        self.average_pretrigger_sec = 0.0

        # --- Varredura ---
        self.sweep_active = False
        self.sweep_state = 'IDLE'
        self.sweep_freqs = []
        self.sweep_idx = 0
        self.sweep_timer = 0.0
        self.sweep_settle_time = 1.0
        self.sweep_measure_time = 1.0
        self.sweep_chunks_r = []
        self.sweep_chunks_p = []
        self.sweep_chunks_dc = []
        self.sweep_count = 0
        self.sweep_results = []
        self.sweep_params = {}
        self.sweep_status_text = ''
        self.result_windows = []

        # --- Controle de atualização da UI ---
        self.last_status_t = 0.0
        self.last_range_t = 0.0
        self.last_status_text = None
        self.last_status_color = None
        self.flash_text = None
        self.flash_until = 0.0

        # --- Serial em thread ---
        self.link = SerialLink(lambda: (self.ref_freq, self.laser_power))
        self.simulator = SignalSimulator(FS)
        self.audio_sim = AudioSimulator()
        self.simulating = False
        self._pll_bad_since = None            # desde quando o PLL do OPT101 não trava (conectado)
        self.session_files = []               # arquivos salvos nesta sessão (ZIP do "Finalizar experimento")

        self._build_ui()
        self.load_settings()
        # Só depois das preferências: a conexão envia F/P com a frequência restaurada, não com a padrão
        self.link.start()

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(GUI_INTERVAL_MS)

        self.opt_thread = StepThread(self._optical_step)
        self.audio_thread = StepThread(self._audio_step)
        self.opt_thread.start()
        self.audio_thread.start()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        pg.setConfigOptions(antialias=False, background='w', foreground='k')
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        central_layout = QtWidgets.QVBoxLayout(central)
        central_layout.setContentsMargins(6, 6, 6, 6)

        # Excitação (comum a todas as abas): frequência e potência
        self.sp_freq = self._dspin(0.0, 5000.0, self.ref_freq, 3, 0.1, self.on_freq)
        self.sp_power = self._dspin(0.0, 100.0, self.laser_power, 1, 0.1, self.on_power)
        excitation = QtWidgets.QHBoxLayout()
        lbl_exc = QtWidgets.QLabel('Excitação:')
        lbl_exc.setStyleSheet('font-weight:bold;')
        excitation.addWidget(lbl_exc)
        for label, w in (('Freq (Hz):', self.sp_freq), ('PWM (%):', self.sp_power)):
            excitation.addWidget(QtWidgets.QLabel(label))
            excitation.addWidget(w)
        excitation.addSpacing(8)
        lbl_sample = QtWidgets.QLabel('Amostra:')
        lbl_sample.setStyleSheet('font-weight:bold;')
        excitation.addWidget(lbl_sample)
        self.ed_sample = QtWidgets.QLineEdit()
        self.ed_sample.setPlaceholderText('nome da amostra')
        self.ed_sample.setFixedWidth(150)
        self.ed_sample.setToolTip('Todos os arquivos salvos na pasta Medidas começam com este nome.\n'
                                  'Caracteres inválidos em nomes de arquivo viram "_". Vazio = sem prefixo.')
        excitation.addWidget(self.ed_sample)
        # Calibração do microfone: começa na mais recente da pasta, marcada para uso
        excitation.addSpacing(8)
        lbl_cal = QtWidgets.QLabel('Calibração:')
        lbl_cal.setStyleSheet('font-weight:bold;')
        excitation.addWidget(lbl_cal)
        self.cmb_mic_cal = RefreshComboBox(self.refresh_mic_cal)
        self.cmb_mic_cal.setFixedWidth(250)
        self.cmb_mic_cal.currentIndexChanged.connect(lambda _: self._show_dual_results())
        excitation.addWidget(self.cmb_mic_cal)
        self.chk_mic_cal = QtWidgets.QCheckBox('Usar')
        self.chk_mic_cal.setChecked(True)
        self.chk_mic_cal.setToolTip('Corrige a varredura em frequência do Modo Duplo pela calibração escolhida:\n'
                                    'S é dividido pela sensibilidade relativa e Δφ é descontado da fase do sistema.\n'
                                    'Desmarque para gerar uma calibração nova (ela usa os dados brutos).')
        self.chk_mic_cal.toggled.connect(lambda _: self._show_dual_results())
        excitation.addWidget(self.chk_mic_cal)
        excitation.addStretch(1)
        self.chk_sim = QtWidgets.QCheckBox('Simular amostragem')
        self.chk_sim.setStyleSheet('QCheckBox{font-weight:bold;color:#006400;}')
        self.chk_sim.setToolTip('Gera um sinal simulado (com ruído) quando não há STM32 conectado.')
        self.chk_sim.toggled.connect(self.on_simulate)
        self.chk_sim.setVisible(False)
        excitation.addWidget(self.chk_sim)
        self.btn_finish = QtWidgets.QPushButton('Finalizar experimento')
        self.btn_finish.setStyleSheet('QPushButton{font-weight:bold;padding:3px 12px;background:#d4edda;'
                                      'border:1px solid #2e7d32;border-radius:4px;}'
                                      'QPushButton:hover{background:#b8e0c2;}')
        self.btn_finish.setToolTip('Compacta num ZIP (pasta Medidas, nome = amostra + data) todos os arquivos salvos\n'
                                   'desde que a interface abriu (ou desde o último "Finalizar experimento"),\n'
                                   'junto com a calibração do microfone em uso.')
        self.btn_finish.clicked.connect(self.finish_experiment)
        excitation.addWidget(self.btn_finish)
        central_layout.addLayout(excitation)

        tabs = QtWidgets.QTabWidget()
        self.tabs = tabs
        central_layout.addWidget(tabs)
        tabs.currentChanged.connect(self.refresh_mic_cal)

        optical_page = QtWidgets.QWidget()
        tabs.addTab(optical_page, 'OPT101')
        root = QtWidgets.QVBoxLayout(optical_page)
        root.setContentsMargins(6, 6, 6, 6)

        # Status
        self.lbl_status = QtWidgets.QLabel('Inicializando...')
        self.lbl_status.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setTextFormat(QtCore.Qt.TextFormat.RichText)
        root.addWidget(self.lbl_status)

        # Janela do osciloscópio (topo da aba OPT101); Freq e PWM ficam na linha "Excitação"
        top = QtWidgets.QHBoxLayout()
        self.sp_window = self._dspin(0.005, 30.0, self.raw.window, 3, 0.5, self.on_window)
        for label, w in (('Janela (s):', self.sp_window),):
            top.addWidget(QtWidgets.QLabel(label))
            top.addWidget(w)
        self.chk_mains = QtWidgets.QCheckBox('Filtro 60 Hz')
        self.chk_mains.setToolTip('Rejeita 60 Hz e múltiplos (até 1,5 kHz) no sinal bruto e no lock-in.\n'
                                  'Notches que caem sobre a frequência de modulação são omitidos.')
        self.chk_mains.setChecked(False)
        self.chk_mains.toggled.connect(self.on_mains)
        if not getattr(self.dsp, 'supports_mains', False):
            self.chk_mains.setEnabled(False)
            self.chk_mains.setToolTip('Disponível apenas no lock-in em Python.')
        top.addWidget(self.chk_mains)
        top.addStretch(1)
        root.addLayout(top)

        # Osciloscópio
        self.plot_raw = pg.PlotWidget()
        pi = self.plot_raw.getPlotItem()
        # Legenda no título: dentro do gráfico ela ficava em cima do traço
        pi.setTitle('Sinal bruto do ADC (PA0, <span style="color:#000;">preto</span>) e referência do laser '
                    '(<span style="color:#009600;">verde tracejado</span>, 0/1) - osciloscópio em tempo real')
        pi.setLabel('left', 'ADC (0-16380, 14 bits)')
        pi.setLabel('bottom', 'Tempo (s)')
        pi.getAxis('bottom').enableAutoSIPrefix(False)
        pi.showGrid(x=True, y=True, alpha=0.3)
        pi.setMouseEnabled(False, False)
        pi.setMenuEnabled(False)
        pi.hideButtons()
        pi.setXRange(0, self.raw.window, padding=0)
        pi.setYRange(0, ADC_FULL_SCALE * 1.003, padding=0)
        self.txt_sat = pg.TextItem('Limiar de Saturação', color=(208, 0, 0), anchor=(0.5, 0.5))
        self.txt_sat.setFont(QtGui.QFont('Arial', 20, QtGui.QFont.Weight.Bold))
        self.txt_sat.setZValue(100)
        self.txt_sat.setVisible(False)
        pi.addItem(self.txt_sat, ignoreBounds=True)

        pen_adc = pg.mkPen('k', width=1)
        self.c_adc_a = pi.plot(pen=pen_adc)
        self.c_adc_b = pi.plot(pen=pen_adc)
        # Referência do laser em um segundo ViewBox (equivalente ao twinx)
        self.ref_vb = pg.ViewBox()
        pi.scene().addItem(self.ref_vb)
        self.ref_vb.setXLink(pi)
        self.ref_vb.setYRange(-0.05, 1.25, padding=0)
        self.ref_vb.setMouseEnabled(False, False)
        self.ref_vb.setMenuEnabled(False)
        pen_ref = pg.mkPen(color=(0, 150, 0, 140), style=QtCore.Qt.PenStyle.DashLine)
        self.c_ref_a = pg.PlotDataItem(pen=pen_ref)
        self.c_ref_b = pg.PlotDataItem(pen=pen_ref)
        self.ref_vb.addItem(self.c_ref_a)
        self.ref_vb.addItem(self.c_ref_b)
        self.lbl_reduced = pg.TextItem('Visualização reduzida, f>50 Hz', color=(255, 0, 0, 120),
                                       anchor=(0.5, 0.5))
        self.lbl_reduced.setFont(QtGui.QFont('Arial', 22, QtGui.QFont.Weight.Bold))
        self.lbl_reduced.setZValue(100)
        self.lbl_reduced.setVisible(False)
        self.ref_vb.addItem(self.lbl_reduced, ignoreBounds=True)

        def sync_views():
            self.ref_vb.setGeometry(pi.vb.sceneBoundingRect())
            self.ref_vb.linkedViewChanged(pi.vb, self.ref_vb.XAxis)
        pi.vb.sigResized.connect(sync_views)
        sync_views()

        for c in (self.c_adc_a, self.c_adc_b, self.c_ref_a, self.c_ref_b):
            c.setDownsampling(auto=True, method='peak')
            c.setClipToView(True)

        self.cursor = pg.InfiniteLine(pos=0, angle=90,
                                      pen=pg.mkPen((255, 0, 0, 200), style=QtCore.Qt.PenStyle.DashLine))
        pi.addItem(self.cursor)
        root.addWidget(self.plot_raw, 3)

        # Magnitude (esquerda, azul) e Fase (direita, vermelho) no mesmo gráfico, na metade esquerda
        self.plot1 = pg.PlotWidget(axisItems={'bottom': TimeAxis(orientation='bottom')})
        p1 = self.plot1.getPlotItem()
        p1.setLabel('left', 'Magnitude (u.a.)', color='b')
        p1.setLabel('bottom', f'{TimeAxis.base_label} (s)')
        p1.getAxis('left').setPen('b')
        p1.getAxis('left').setTextPen('b')
        p1.getAxis('bottom').enableAutoSIPrefix(False)
        p1.showGrid(x=True, y=True, alpha=0.3)
        p1.setMouseEnabled(False, False)
        p1.setMenuEnabled(False)
        p1.hideButtons()
        self.lockin_span = MAX_POINTS * DECIMATION / FS
        p1.setXRange(-self.lockin_span, 0, padding=0)
        p1.setYRange(0, 1, padding=0)
        self.line_r = p1.plot(pen=pg.mkPen('b', width=1), symbol='o', symbolSize=4,
                              symbolBrush='b', symbolPen='b')
        p1.showAxis('right')
        ax_r = p1.getAxis('right')
        ax_r.setLabel('Fase (Graus)', color='r')
        ax_r.setPen('r')
        ax_r.setTextPen('r')
        ax_r.setGrid(False)
        self.phase_vb = pg.ViewBox()
        p1.scene().addItem(self.phase_vb)
        ax_r.linkToView(self.phase_vb)
        self.phase_vb.setXLink(p1)
        self.phase_vb.setYRange(-180, 180, padding=0)
        self.phase_vb.setMouseEnabled(False, False)
        self.phase_vb.setMenuEnabled(False)
        self.line_phase = pg.PlotDataItem(pen=pg.mkPen('r', width=1), symbol='o', symbolSize=4,
                                          symbolBrush='r', symbolPen='r')
        self.phase_vb.addItem(self.line_phase)
        self.line_ref_avg = pg.PlotDataItem(pen=pg.mkPen(color=(0, 150, 0, 140),
                                                         style=QtCore.Qt.PenStyle.DashLine))
        self.line_ref_avg.setVisible(False)
        self.phase_vb.addItem(self.line_ref_avg)

        def sync_phase():
            self.phase_vb.setGeometry(p1.vb.sceneBoundingRect())
            self.phase_vb.linkedViewChanged(p1.vb, self.phase_vb.XAxis)
        p1.vb.sigResized.connect(sync_phase)
        sync_phase()

        bottom = QtWidgets.QHBoxLayout()
        left = QtWidgets.QVBoxLayout()
        self.paused = False
        view_row = QtWidgets.QHBoxLayout()
        # Modo do gráfico inferior: botões lado a lado (antes era uma chave vertical no rodapé)
        self.btn_mode_li = QtWidgets.QPushButton('Lock-In')
        self.btn_mode_avg = QtWidgets.QPushButton('Valor Médio')
        self.btn_mode_li.setToolTip('Magnitude e fase do lock-in ao longo do tempo.')
        self.btn_mode_avg.setToolTip('Forma de onda média do ADC sobre vários pulsos (permite o ajuste exponencial).')
        mode_group = QtWidgets.QButtonGroup(self)
        mode_group.setExclusive(True)
        for b, avg in ((self.btn_mode_li, False), (self.btn_mode_avg, True)):
            b.setCheckable(True)
            b.setStyleSheet('QPushButton{padding:3px 14px;border:1px solid #888;background:#f2f2f2;}'
                            'QPushButton:checked{background:#1f5fbf;color:white;font-weight:bold;}')
            b.clicked.connect(lambda _=False, a=avg: self.set_display_mode(a))
            mode_group.addButton(b)
            view_row.addWidget(b)
        view_row.setSpacing(0)
        self.btn_mode_li.setChecked(True)
        view_row.addSpacing(24)
        view_row.addWidget(QtWidgets.QLabel('Pausa:'))
        self.sw_pause = ToggleSwitch()
        self.sw_pause.toggled.connect(self.on_pause)
        view_row.addWidget(self.sw_pause)
        self.btn_save_view = QtWidgets.QPushButton('Salvar')
        self.btn_save_view.setToolTip('CSV e PNG serão salvos na pasta Medidas')
        self.btn_save_view.clicked.connect(self.save_view)
        view_row.addSpacing(6)
        view_row.addWidget(self.btn_save_view)
        view_row.addSpacing(16)
        self.chk_opt_fft = QtWidgets.QCheckBox('FFT')
        self.chk_opt_fft.setToolTip('Espectro do sinal bruto do ADC (coluna da direita).')
        self.chk_opt_fft.toggled.connect(self.on_opt_fft)
        view_row.addWidget(self.chk_opt_fft)
        view_row.addStretch(1)
        self.btn_opt_sweeps = QtWidgets.QPushButton('Varreduras ▸')
        self.btn_opt_sweeps.setCheckable(True)
        self.btn_opt_sweeps.setToolTip('Mostra ou esconde as varreduras em frequência e PWM do OPT101.')
        self.btn_opt_sweeps.toggled.connect(self.on_opt_sweeps_panel)
        view_row.addWidget(self.btn_opt_sweeps)
        left.addLayout(view_row)
        # Parâmetros do modo ativo (preenchidos mais abaixo, depois de criar os controles)
        self.mode_params = QtWidgets.QHBoxLayout()
        left.addLayout(self.mode_params)
        left.addWidget(self.plot1, 1)
        bottom.addLayout(left, 1)
        side = QtWidgets.QVBoxLayout()
        self.side_layout = side
        bottom.addLayout(side, 1)
        root.addLayout(bottom, 4)

        self.sp_lp = self._dspin(0.0001, 500.0, self.cutoff_lp, 4, 0.01, self.on_lp)
        self.sp_hp = self._dspin(0.0001, 500.0, self.cutoff_hp, 4, 0.01, self.on_hp)

        # Análise da curva (acessível apenas com o gráfico pausado no modo Valor Médio)
        self.fit = None
        self._fit_toff = 0.0
        # Painel do ajuste: só aparece no Valor Médio; os controles ficam ativos com o gráfico pausado
        self.fit_panel = QtWidgets.QWidget()
        fit_panel_lay = QtWidgets.QVBoxLayout(self.fit_panel)
        fit_panel_lay.setContentsMargins(0, 0, 0, 0)
        self.fit_hint_row = QtWidgets.QWidget()
        hint_lay = QtWidgets.QHBoxLayout(self.fit_hint_row)
        hint_lay.setContentsMargins(0, 0, 0, 0)
        self.lbl_fit_hint = QtWidgets.QLabel('Para ajustar exponenciais, pause o gráfico:')
        hint_lay.addWidget(self.lbl_fit_hint)
        self.btn_fit_pause = QtWidgets.QPushButton('⏸ Pausar e ajustar')
        self.btn_fit_pause.setStyleSheet('background:#cfe2ff;')
        self.btn_fit_pause.clicked.connect(lambda: self.sw_pause.setChecked(True))
        hint_lay.addWidget(self.btn_fit_pause)
        hint_lay.addStretch(1)
        fit_panel_lay.addWidget(self.fit_hint_row)
        self.fit_box = self._group('Análise da curva')
        fit_panel_lay.addWidget(self.fit_box)
        fit_lay = QtWidgets.QVBoxLayout(self.fit_box)
        self.lbl_fit = QtWidgets.QLabel('')
        fit_lay.addWidget(self.lbl_fit)
        row_a = QtWidgets.QHBoxLayout()
        row_a.addWidget(QtWidgets.QLabel('Modelo:'))
        self.cmb_fit = QtWidgets.QComboBox()
        self.cmb_fit.addItems(['1 exponencial', '2 exponenciais'])
        self.cmb_fit.currentIndexChanged.connect(self.on_fit_model)
        row_a.addWidget(self.cmb_fit)
        self.btn_fit = QtWidgets.QPushButton('Fit')
        self.btn_fit.setToolTip('Plota o modelo com os parâmetros atuais (de t=0 até o fim do pulso)')
        self.btn_fit.clicked.connect(self.fit_current)
        row_a.addWidget(self.btn_fit)
        self.btn_opt = QtWidgets.QPushButton('Otimizar')
        self.btn_opt.setToolTip('Ajusta por mínimos quadrados usando os valores atuais como ponto de partida')
        self.btn_opt.clicked.connect(self.fit_optimize)
        row_a.addWidget(self.btn_opt)
        row_a.addStretch(1)
        self.sw_t0 = ModeSwitch('Clique para alternar: cima = Fit do On, baixo = Fit do Off')
        self.sw_t0.clicked.connect(self.on_t0_mode)
        row_a.addWidget(self.sw_t0)
        t0_lbls = QtWidgets.QVBoxLayout()
        t0_lbls.addWidget(QtWidgets.QLabel('Fit do On'))
        t0_lbls.addStretch(1)
        t0_lbls.addWidget(QtWidgets.QLabel('Fit do Off'))
        row_a.addLayout(t0_lbls)
        fit_lay.addLayout(row_a)
        big = 1e9
        self.sp_fy = self._dspin(-big, big, 0.0, 3, 1.0, None, 100)
        self.sp_fa1 = self._dspin(-big, big, 0.0, 3, 1.0, None, 100)
        self.sp_ft1 = self._dspin(1e-4, 1e6, 1.0, 4, 0.1, None, 100)
        self.sp_fa2 = self._dspin(-big, big, 0.0, 3, 1.0, None, 100)
        self.sp_ft2 = self._dspin(1e-4, 1e6, 1.0, 4, 0.1, None, 100)
        # Parâmetros em duas linhas (numa linha só o quadro ocupava ~720 px)
        row_b = QtWidgets.QGridLayout()
        for i, (label, w) in enumerate((('y∞:', self.sp_fy), ('A1:', self.sp_fa1), ('τ1 (ms):', self.sp_ft1),
                                        (None, None), ('A2:', self.sp_fa2), ('τ2 (ms):', self.sp_ft2))):
            if w is None:
                continue
            r, c = divmod(i, 3)
            row_b.addWidget(QtWidgets.QLabel(label), r, 2 * c)
            row_b.addWidget(w, r, 2 * c + 1)
        row_b.setColumnStretch(6, 1)
        fit_lay.addLayout(row_b)
        self.sp_fa2.setEnabled(False)
        self.sp_ft2.setEnabled(False)
        self.fit_box.setEnabled(False)
        self.fit_panel.setVisible(False)
        side.addWidget(self.fit_panel)
        self.line_fit = self.plot1.getPlotItem().plot(pen=pg.mkPen((255, 120, 0), width=2))
        self.line_fit.setVisible(False)

        pen_rng = pg.mkPen((0, 160, 0), width=2)
        self._region_lock = False
        self.fit_lines = []
        for _ in range(2):
            ln = pg.InfiniteLine(angle=90, movable=True, pen=pen_rng,
                                 hoverPen=pg.mkPen((0, 220, 0), width=3))
            ln.setZValue(50)
            ln.setVisible(False)
            ln.sigPositionChanged.connect(self.on_fit_region_moved)
            self.plot1.getPlotItem().addItem(ln, ignoreBounds=True)
            self.fit_lines.append(ln)
        # Quadros de varredura (F = frequência, P = potência), num painel recolhível (botão Varreduras)
        self.sweep_kind = 'F'
        self.eta_labels = {}
        self.btn_sweeps = {}
        self.sweep_spins = {}

        self.sweep_bars = {}
        self.opt_sweeps_panel = QtWidgets.QWidget()
        opt_sw_lay = QtWidgets.QVBoxLayout(self.opt_sweeps_panel)
        opt_sw_lay.setContentsMargins(0, 0, 0, 0)

        def build_box(kind, title, fields):
            box, btn, lbl, bar = self._make_sweep_box(
                title, fields, lambda _=False, k=kind: self.toggle_sweep(k, 'OPT'))
            btn.setToolTip('Requer o Modo Lock-In.')
            for _, sb in fields:
                sb.valueChanged.connect(self.update_eta_idle)
            self.btn_sweeps[kind], self.eta_labels[kind] = btn, lbl
            self.sweep_bars[('OPT', kind)] = bar
            self.sweep_spins[kind] = [sb for _, sb in fields]
            opt_sw_lay.addWidget(box)

        self.sp_f0 = self._dspin(0.1, 5000.0, 0.1, 3, 0.1, None, 110, ' Hz')
        self.sp_f1 = self._dspin(0.1, 5000.0, 60.0, 3, 1.0, None, 110, ' Hz')
        self.sp_df = self._dspin(0.01, 5000.0, 1.0, 3, 0.1, None, 110, ' Hz')
        build_box('F', 'Varredura em frequência (OPT101)',
                  (('Início:', self.sp_f0), ('Fim:', self.sp_f1), ('Passo:', self.sp_df)))
        self.sp_p0 = self._dspin(0.0, 100.0, 10.0, 1, 1.0, None, 110, ' %')
        self.sp_p1 = self._dspin(0.0, 100.0, 100.0, 1, 1.0, None, 110, ' %')
        self.sp_dp = self._dspin(0.1, 100.0, 10.0, 1, 1.0, None, 110, ' %')
        build_box('P', 'Varredura em PWM (OPT101)',
                  (('Início:', self.sp_p0), ('Fim:', self.sp_p1), ('Passo:', self.sp_dp)))
        self.btn_sweep = self.btn_sweeps['F']
        self.btn_sweep_p = self.btn_sweeps['P']
        self.lbl_eta = self.eta_labels['F']
        self.lbl_eta_p = self.eta_labels['P']
        self._set_eta_style(False)
        self.update_eta_idle()
        self.opt_sweeps_panel.setVisible(False)
        side.addWidget(self.opt_sweeps_panel)

        # FFT do sinal bruto do ADC: opções abaixo do gráfico, como no INMP441
        self.opt_fft_panel = QtWidgets.QWidget()
        offt_lay = QtWidgets.QVBoxLayout(self.opt_fft_panel)
        offt_lay.setContentsMargins(0, 0, 0, 0)
        offt_lay.setSpacing(0)
        offt_head = QtWidgets.QHBoxLayout()
        offt_head.addStretch(1)
        self.chk_opt_fft_fit = QtWidgets.QCheckBox('Fit')
        self.chk_opt_fft_fit.setChecked(True)
        self.chk_opt_fft_fit.setToolTip('Ajusta o maior pico perto da referência com a forma exata do pico\n'
                                        'de uma senoide na FFT com janela Hann: frequência e amplitude\n'
                                        'corrigidas, mesmo quando o tom cai entre dois bins.')
        self.chk_opt_fft_fit.toggled.connect(self.on_opt_fft_fit)
        self.chk_opt_fft_full = QtWidgets.QCheckBox('Espectro completo')
        self.chk_opt_fft_full.setToolTip('Desligado: região em torno da frequência de referência, com FFT longa\n'
                                         f'({OPT_FFT_HISTORY_SEC:g} s, resolução fina).\n'
                                         f'Ligado: 0 a {FS / 2:g} Hz, FFT de {OPT_FFT_SIZE} pontos.')
        self.chk_opt_fft_full.toggled.connect(self.on_opt_fft_full)
        offt_head.addWidget(self.chk_opt_fft_fit)
        offt_head.addSpacing(8)
        offt_head.addWidget(self.chk_opt_fft_full)
        offt_head.addStretch(1)
        self.plot_opt_fft = pg.PlotWidget()
        offt_lay.addWidget(self.plot_opt_fft, 1)
        offt_lay.addLayout(offt_head)      # opções abaixo do gráfico
        opt_fft_item = self.plot_opt_fft.getPlotItem()
        opt_fft_item.setTitle('OPT101 - espectro do ADC (FFT)')
        opt_fft_item.setLabel('left', 'Magnitude (dBFS)')
        opt_fft_item.setLabel('bottom', 'Frequência (Hz)')
        opt_fft_item.getAxis('bottom').enableAutoSIPrefix(False)
        opt_fft_item.showGrid(x=True, y=True, alpha=0.3)
        opt_fft_item.setMouseEnabled(False, False)
        opt_fft_item.setMenuEnabled(False)
        opt_fft_item.hideButtons()
        opt_fft_item.setXRange(0, FS / 2, padding=0)
        opt_fft_item.setYRange(-140, 0, padding=0)
        self.curve_opt_fft = opt_fft_item.plot(pen=pg.mkPen('#a33a22', width=1))
        self.curve_opt_fft.setDownsampling(auto=True, method='peak')
        self.curve_opt_fft.setClipToView(True)
        self.opt_fft_ref_line = pg.InfiniteLine(angle=90, pen=pg.mkPen('#888', width=1, style=QtCore.Qt.PenStyle.DashLine))
        opt_fft_item.addItem(self.opt_fft_ref_line)
        self.curve_opt_fft_fit = opt_fft_item.plot(pen=pg.mkPen('#1f5fbf', width=2))
        # Resultado do fit em posição fixa (pixels) no canto do gráfico
        self.txt_opt_fft_fit = pg.TextItem(anchor=(0, 0), fill=pg.mkBrush(255, 255, 255, 210),
                                           border=pg.mkPen('#1f5fbf'))
        self.txt_opt_fft_fit.setParentItem(opt_fft_item.vb)
        self.txt_opt_fft_fit.setPos(8, 8)
        self.txt_opt_fft_fit.setVisible(False)
        self.lbl_opt_fft_missing = self._make_fft_missing_label(opt_fft_item)
        self.opt_fft_panel.setVisible(False)
        side.addWidget(self.opt_fft_panel, 0)
        side.addStretch(1)          # some quando a FFT está visível (on_opt_fft)
        self.update_opt_fft_range()

        # Parâmetros de cada modo, logo acima do gráfico; só o do modo ativo fica visível
        self.li_group = QtWidgets.QWidget()
        li_lay = QtWidgets.QHBoxLayout(self.li_group)
        li_lay.setContentsMargins(0, 0, 0, 0)
        self.lbl_tau = self._filter_row(li_lay, self.sp_lp, self.sp_hp)
        self.update_tau_labels()
        li_lay.addStretch(1)
        self.mode_params.addWidget(self.li_group)

        self.avg_group = QtWidgets.QWidget()
        av_lay = QtWidgets.QHBoxLayout(self.avg_group)
        av_lay.setContentsMargins(0, 0, 0, 0)
        av_lay.addWidget(QtWidgets.QLabel('Pulsos:'))
        self.sp_pulses = QtWidgets.QSpinBox()
        self.sp_pulses.setRange(1, 1000)
        self.sp_pulses.setValue(self.avg.pulses)
        self.sp_pulses.setKeyboardTracking(False)
        self.sp_pulses.setToolTip('Número de pulsos somados na média.')
        self.sp_pulses.valueChanged.connect(self.on_pulses)
        av_lay.addWidget(self.sp_pulses)
        av_lay.addSpacing(12)
        btn_pm = QtWidgets.QPushButton('◀')
        btn_pp = QtWidgets.QPushButton('▶')
        btn_pm.setToolTip('Mostra mais tempo antes do início do pulso (+10 ms de pré-trigger).')
        btn_pp.setToolTip('Mostra menos tempo antes do início do pulso (−10 ms de pré-trigger).')
        btn_pm.setFixedWidth(30)
        btn_pp.setFixedWidth(30)
        btn_pm.clicked.connect(lambda: self.adjust_pretrigger(1))
        btn_pp.clicked.connect(lambda: self.adjust_pretrigger(-1))
        self.lbl_pre = QtWidgets.QLabel('Pré: -0.000 s')
        self.lbl_pre.setToolTip('Pré-trigger: tempo exibido antes da borda de subida do laser.')
        av_lay.addWidget(btn_pm)
        av_lay.addWidget(self.lbl_pre)
        av_lay.addWidget(btn_pp)
        av_lay.addStretch(1)
        self.mode_params.addWidget(self.avg_group)
        self.avg_group.setVisible(False)

        audio_panel = QtWidgets.QWidget()
        audio_layout = QtWidgets.QVBoxLayout(audio_panel)
        self.audio_status = QtWidgets.QLabel('Inicializando áudio...')
        self.audio_status.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.audio_status.setTextFormat(QtCore.Qt.TextFormat.RichText)
        audio_layout.addWidget(self.audio_status)
        # Exibição: gráficos, R/θ ou X/Y e fase
        view_box = self._group('Exibição')
        audio_mode = QtWidgets.QHBoxLayout(view_box)
        audio_mode.setContentsMargins(6, 2, 6, 2)
        audio_mode.addWidget(QtWidgets.QLabel('Gráficos:'))
        self.chk_audio_lockin = QtWidgets.QCheckBox('Lock-In')
        self.chk_audio_lockin.setChecked(True)
        self.chk_audio_noise = QtWidgets.QCheckBox('Ruído/SNR')
        self.chk_audio_noise.setToolTip('Média e desvio-padrão da saída do lock-in numa janela móvel.\n'
                                        'Use uma janela bem maior que τ (≥ 10τ) para uma estimativa confiável.')
        self.chk_audio_fft = QtWidgets.QCheckBox('FFT')
        for chk in (self.chk_audio_lockin, self.chk_audio_noise, self.chk_audio_fft):
            chk.toggled.connect(self.on_audio_views)
            audio_mode.addWidget(chk)
        audio_mode.addSpacing(16)

        # Chave R/Fase <-> X/Y, com auto-fase e offset de fase manual
        self.audio_xy_group = QtWidgets.QWidget()
        xy_lay = QtWidgets.QHBoxLayout(self.audio_xy_group)
        xy_lay.setContentsMargins(0, 0, 0, 0)
        xy_lay.addWidget(QtWidgets.QLabel('R/θ'))
        self.sw_audio_xy = ToggleSwitch()
        self.sw_audio_xy.setToolTip('Exibição do lock-in: R e Fase (esquerda) ou X e Y (direita).\n'
                                    'Ao passar para X/Y a auto-fase é aplicada.')
        self.sw_audio_xy.toggled.connect(self.on_audio_xy)
        xy_lay.addWidget(self.sw_audio_xy)
        xy_lay.addWidget(QtWidgets.QLabel('X/Y'))
        self.btn_audio_autophase = QtWidgets.QPushButton('Auto-fase')
        self.btn_audio_autophase.setToolTip(f'Ajusta o offset de fase para que o sinal fique todo em X (θ ≈ 0),\n'
                                            f'usando a média do último {AUTO_PHASE_SPAN:g} s.')
        self.btn_audio_autophase.clicked.connect(self.audio_auto_phase)
        xy_lay.addWidget(self.btn_audio_autophase)
        xy_lay.addWidget(QtWidgets.QLabel('Offset (°):'))
        self.sp_audio_phase_off = self._dspin(-180.0, 180.0, 0.0, 1, 1.0, self.on_audio_phase_offset, width=70)
        self.sp_audio_phase_off.setWrapping(True)
        xy_lay.addWidget(self.sp_audio_phase_off)
        audio_mode.addWidget(self.audio_xy_group)
        audio_mode.addStretch(1)
        self.btn_audio_sweeps = QtWidgets.QPushButton('Varreduras ▸')
        self.btn_audio_sweeps.setCheckable(True)
        self.btn_audio_sweeps.setToolTip('Mostra ou esconde as varreduras em frequência e PWM do INMP441.')
        self.btn_audio_sweeps.toggled.connect(self.on_audio_sweeps_panel)
        audio_mode.addWidget(self.btn_audio_sweeps)
        audio_layout.addWidget(view_box)

        # Parâmetros do lock-in do INMP441 (mesmos do OPT101, porém independentes)
        self.audio_li_group = self._group('Lock-in')
        audio_params = QtWidgets.QHBoxLayout(self.audio_li_group)
        audio_params.setContentsMargins(6, 2, 6, 2)
        self.sp_audio_lp = self._dspin(0.0001, 500.0, self.audio_cutoff_lp, 4, 0.01, self.on_audio_lp)
        self.sp_audio_hp = self._dspin(0.0001, 500.0, self.audio_cutoff_hp, 4, 0.01, self.on_audio_hp)
        self.lbl_audio_tau = self._filter_row(audio_params, self.sp_audio_lp, self.sp_audio_hp)
        self.update_tau_labels()
        self.chk_audio_mains = QtWidgets.QCheckBox('Filtro 60 Hz')
        self.chk_audio_mains.setToolTip('Rejeita 60 Hz e múltiplos (até 1,5 kHz) no sinal do lock-in.\n'
                                        'Notches que caem sobre a frequência de modulação são omitidos.')
        self.chk_audio_mains.setChecked(self.audio_mains)
        self.chk_audio_mains.toggled.connect(self.on_audio_mains)
        audio_params.addWidget(self.chk_audio_mains)
        audio_params.addSpacing(12)
        audio_params.addWidget(QtWidgets.QLabel('Janela (s):'))
        self.sp_audio_span = self._dspin(1.0, AUDIO_NOISE_SPAN, self.audio_span, 0, 1.0, self.on_audio_span, width=60)
        self.sp_audio_span.setToolTip(f'Tempo exibido nos gráficos do lock-in e do ruído/SNR (até {AUDIO_NOISE_SPAN:g} s).\nA estatística de ruído/SNR usa esta mesma janela (até {AUDIO_NOISE_SPAN / 2:g} s).')
        audio_params.addWidget(self.sp_audio_span)
        audio_params.addStretch(1)
        audio_layout.addWidget(self.audio_li_group)

        # Varreduras do INMP441: painel recolhível (na linha dos controles ele obrigava a janela a ter ~1500 px)
        self.btn_sweeps_aud = {}
        self.eta_labels_aud = {}
        self.sweep_spins_aud = {}
        self.audio_sweeps_panel = QtWidgets.QWidget()
        sw_lay = QtWidgets.QHBoxLayout(self.audio_sweeps_panel)
        sw_lay.setContentsMargins(0, 0, 0, 0)

        def build_audio_sweep_box(kind, title, fields):
            box, btn, lbl, bar = self._make_sweep_box(
                title, fields, lambda _=False, k=kind: self.toggle_sweep(k, 'AUDIO'))
            for _, sb in fields:
                sb.valueChanged.connect(self.update_eta_idle)
            self.btn_sweeps_aud[kind] = btn
            self.eta_labels_aud[kind] = lbl
            self.sweep_bars[('AUDIO', kind)] = bar
            self.sweep_spins_aud[kind] = [sb for _, sb in fields]
            sw_lay.addWidget(box)

        self.sp_aud_f0 = self._dspin(0.1, 5000.0, 0.1, 3, 0.1, None, 110, ' Hz')
        self.sp_aud_f1 = self._dspin(0.1, 5000.0, 60.0, 3, 1.0, None, 110, ' Hz')
        self.sp_aud_df = self._dspin(0.01, 5000.0, 1.0, 3, 0.1, None, 110, ' Hz')
        build_audio_sweep_box('F', 'Varredura em frequência (INMP441)',
                              (('Início:', self.sp_aud_f0), ('Fim:', self.sp_aud_f1), ('Passo:', self.sp_aud_df)))
        self.sp_aud_p0 = self._dspin(0.0, 100.0, 10.0, 1, 1.0, None, 110, ' %')
        self.sp_aud_p1 = self._dspin(0.0, 100.0, 100.0, 1, 1.0, None, 110, ' %')
        self.sp_aud_dp = self._dspin(0.1, 100.0, 10.0, 1, 1.0, None, 110, ' %')
        build_audio_sweep_box('P', 'Varredura em PWM (INMP441)',
                              (('Início:', self.sp_aud_p0), ('Fim:', self.sp_aud_p1), ('Passo:', self.sp_aud_dp)))
        sw_lay.addStretch(1)
        self.audio_sweeps_panel.setVisible(False)
        audio_layout.addWidget(self.audio_sweeps_panel)

        # Sinal, ruído e SNR sempre visíveis enquanto o lock-in roda (atualizam junto com o status, a cada 2 s)
        self.lbl_audio_noise = QtWidgets.QLabel('Ruído/SNR: aguardando dados')
        self.lbl_audio_noise.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_audio_noise.setWordWrap(True)
        self.lbl_audio_noise.setStyleSheet('font-size:11pt;padding:2px 6px;')
        audio_layout.addWidget(self.lbl_audio_noise)

        audio_plots = QtWidgets.QHBoxLayout()

        self.plot_audio_wave = pg.PlotWidget()
        audio_wave_item = self.plot_audio_wave.getPlotItem()
        audio_wave_item.setTitle('INMP441 - Lock-In (Magnitude e Fase)')
        audio_wave_item.setLabel('left', 'Magnitude (escala completa 24 bits)', color='b')
        audio_wave_item.setLabel('bottom', 'Tempo relativo (s)')
        audio_wave_item.getAxis('left').setPen('b')
        audio_wave_item.getAxis('left').setTextPen('b')
        audio_wave_item.showGrid(x=True, y=True, alpha=0.3)
        audio_wave_item.setMouseEnabled(False, False)
        audio_wave_item.setMenuEnabled(False)
        audio_wave_item.hideButtons()
        audio_wave_item.setXRange(-self.audio_span, 0, padding=0)
        self.curve_audio_wave = audio_wave_item.plot(pen=pg.mkPen('b', width=1), symbol='o', symbolSize=4,
                                                     symbolBrush='b', symbolPen='b')
        # Fase (direita, vermelho) em um segundo ViewBox, como no gráfico do OPT101
        audio_wave_item.showAxis('right')
        ax_pr = audio_wave_item.getAxis('right')
        ax_pr.setLabel('Fase (Graus)', color='r')
        ax_pr.setPen('r')
        ax_pr.setTextPen('r')
        ax_pr.setGrid(False)
        self.audio_phase_vb = pg.ViewBox()
        audio_wave_item.scene().addItem(self.audio_phase_vb)
        ax_pr.linkToView(self.audio_phase_vb)
        self.audio_phase_vb.setXLink(audio_wave_item)
        self.audio_phase_vb.setYRange(-180, 180, padding=0)
        self.audio_phase_vb.setMouseEnabled(False, False)
        self.audio_phase_vb.setMenuEnabled(False)
        self.curve_audio_phase = pg.PlotDataItem(pen=pg.mkPen('r', width=1), symbol='o', symbolSize=4,
                                                 symbolBrush='r', symbolPen='r')
        self.audio_phase_vb.addItem(self.curve_audio_phase)

        def sync_audio_phase():
            self.audio_phase_vb.setGeometry(audio_wave_item.vb.sceneBoundingRect())
            self.audio_phase_vb.linkedViewChanged(audio_wave_item.vb, self.audio_phase_vb.XAxis)
        audio_wave_item.vb.sigResized.connect(sync_audio_phase)
        sync_audio_phase()
        # X e Y (modo X/Y) no mesmo eixo da magnitude
        self.curve_audio_y = audio_wave_item.plot(pen=pg.mkPen('r', width=1), symbol='o', symbolSize=4,
                                                  symbolBrush='r', symbolPen='r')
        self.curve_audio_y.setVisible(False)
        self.audio_zero_line = pg.InfiniteLine(pos=0.0, angle=0, pen=pg.mkPen('#888', width=1))
        audio_wave_item.addItem(self.audio_zero_line)
        self.audio_zero_line.setVisible(False)
        self.audio_wave_legend = audio_wave_item.addLegend(offset=(10, 10))
        self.audio_wave_legend.addItem(self.curve_audio_wave, 'X')
        self.audio_wave_legend.addItem(self.curve_audio_y, 'Y')
        self.audio_wave_legend.setVisible(False)

        # Ruído e SNR: gráfico abaixo do lock-in, com o mesmo eixo de tempo; parâmetros logo abaixo
        self.audio_noise_panel = QtWidgets.QWidget()
        noise_lay = QtWidgets.QVBoxLayout(self.audio_noise_panel)
        noise_lay.setContentsMargins(0, 0, 0, 0)
        noise_lay.setSpacing(2)
        self.plot_audio_noise = pg.PlotWidget()
        noise_item = self.plot_audio_noise.getPlotItem()
        noise_item.setLabel('left', 'SNR (dB)', color='#2a7d2a')
        noise_item.setLabel('bottom', 'Tempo relativo (s)')
        noise_item.showGrid(x=True, y=True, alpha=0.3)
        noise_item.setMouseEnabled(False, False)
        noise_item.setMenuEnabled(False)
        noise_item.hideButtons()
        noise_item.setXRange(-self.audio_span, 0, padding=0)   # mesmo eixo de tempo do lock-in (on_audio_span)
        # Eixos com a mesma largura nos dois gráficos para os tempos ficarem alinhados
        noise_item.showAxis('right')
        noise_item.getAxis('right').setStyle(showValues=False)
        noise_item.getAxis('right').setPen(pg.mkPen(0, 0, 0, 0))
        for it in (audio_wave_item, noise_item):
            it.getAxis('left').setWidth(70)
            it.getAxis('right').setWidth(60)
        self.curve_audio_snr = noise_item.plot(pen=pg.mkPen('#2a7d2a', width=1.5))
        self.audio_snr_alert_line = pg.InfiniteLine(pos=self.audio_snr_alert, angle=0,
                                                    pen=pg.mkPen('#c0392b', width=1, style=QtCore.Qt.PenStyle.DashLine))
        noise_item.addItem(self.audio_snr_alert_line)
        noise_lay.addWidget(self.plot_audio_noise, 1)

        noise_row = QtWidgets.QHBoxLayout()
        noise_row.addStretch(1)
        noise_row.addWidget(QtWidgets.QLabel('Alerta SNR < (dB):'))
        self.sp_audio_snr_alert = self._dspin(-20.0, 60.0, self.audio_snr_alert, 1, 1.0,
                                              self.on_audio_snr_alert, width=60)
        self.sp_audio_snr_alert.setToolTip('A barra de status fica vermelha com "SINAL BAIXO" quando o SNR da\n'
                                           'janela de ruído cai abaixo deste valor (linha tracejada vermelha).\n'
                                           '10 dB ≈ sinal 3x maior que o desvio-padrão do ruído (limite prático de detecção).')
        noise_row.addWidget(self.sp_audio_snr_alert)
        noise_lay.addLayout(noise_row)
        self.audio_noise_panel.setVisible(False)

        audio_left = QtWidgets.QVBoxLayout()
        audio_left.setSpacing(0)
        audio_left.addWidget(self.plot_audio_wave, 3)
        audio_left.addWidget(self.audio_noise_panel, 2)
        audio_plots.addLayout(audio_left, 1)

        self.audio_fft_panel = QtWidgets.QWidget()
        fft_lay = QtWidgets.QVBoxLayout(self.audio_fft_panel)
        fft_lay.setContentsMargins(0, 0, 0, 0)
        fft_lay.setSpacing(0)
        fft_head = QtWidgets.QHBoxLayout()
        fft_head.addStretch(1)
        self.chk_audio_fft_full = QtWidgets.QCheckBox('Espectro completo')
        self.chk_audio_fft_full.setToolTip('Desligado: região em torno da frequência de referência, com FFT longa\n'
                                           f'({AUDIO_FFT_HISTORY_SEC:g} s, resolução fina).\n'
                                           f'Ligado: 0 a {AUDIO_FS // 2000} kHz, FFT de {AUDIO_FFT_SIZE} pontos.')
        self.chk_audio_fft_full.toggled.connect(self.on_audio_fft_full)
        self.chk_audio_fft_fit = QtWidgets.QCheckBox('Fit')
        self.chk_audio_fft_fit.setChecked(True)
        self.chk_audio_fft_fit.setToolTip('Ajusta o maior pico perto da referência com a forma exata do pico\n'
                                          'de uma senoide na FFT com janela Hann: frequência e amplitude\n'
                                          'corrigidas, mesmo quando o tom cai entre dois bins.')
        self.chk_audio_fft_fit.toggled.connect(self.on_audio_fft_fit)
        fft_head.addWidget(self.chk_audio_fft_fit)
        fft_head.addSpacing(8)
        fft_head.addWidget(self.chk_audio_fft_full)
        fft_head.addStretch(1)
        self.plot_audio_fft = pg.PlotWidget()
        fft_lay.addWidget(self.plot_audio_fft, 1)
        fft_lay.addLayout(fft_head)      # opções abaixo do gráfico
        audio_fft_item = self.plot_audio_fft.getPlotItem()
        audio_fft_item.setTitle('INMP441 - espectro (FFT)')
        audio_fft_item.setLabel('left', 'Magnitude (dBFS)')
        audio_fft_item.setLabel('bottom', 'Frequência (Hz)')
        audio_fft_item.showGrid(x=True, y=True, alpha=0.3)
        audio_fft_item.setMouseEnabled(False, False)
        audio_fft_item.setMenuEnabled(False)
        audio_fft_item.hideButtons()
        audio_fft_item.setXRange(0, AUDIO_FS / 2, padding=0)
        audio_fft_item.setYRange(-120, 0, padding=0)
        self.curve_audio_fft = audio_fft_item.plot(pen=pg.mkPen('#a33a22', width=1))
        self.curve_audio_fft.setDownsampling(auto=True, method='peak')
        self.curve_audio_fft.setClipToView(True)
        self.audio_fft_ref_line = pg.InfiniteLine(angle=90, pen=pg.mkPen('#888', width=1, style=QtCore.Qt.PenStyle.DashLine))
        audio_fft_item.addItem(self.audio_fft_ref_line)
        self.curve_audio_fft_fit = audio_fft_item.plot(pen=pg.mkPen('#1f5fbf', width=2))
        # Resultado do fit em posição fixa (pixels) no canto do gráfico
        self.txt_audio_fft_fit = pg.TextItem(anchor=(0, 0), fill=pg.mkBrush(255, 255, 255, 210),
                                             border=pg.mkPen('#1f5fbf'))
        self.txt_audio_fft_fit.setParentItem(audio_fft_item.vb)
        self.txt_audio_fft_fit.setPos(8, 8)
        self.txt_audio_fft_fit.setVisible(False)
        self.audio_fft_fit_html = None
        self.audio_fft_missing = None
        self.lbl_audio_fft_missing = self._make_fft_missing_label(audio_fft_item)
        audio_plots.addWidget(self.audio_fft_panel, 1)
        self.audio_fft_panel.setVisible(self.audio_fft_enabled)
        self.update_audio_fft_range()

        audio_layout.addLayout(audio_plots)
        tabs.addTab(audio_panel, 'INMP441')
        self._build_dual_tab(tabs)

        # Barra de status da janela (visível em todas as abas): avisos, tarefa em andamento e conexão
        sb = self.statusBar()
        self.lbl_sb_task = QtWidgets.QLabel('')
        self.lbl_sb_task.setStyleSheet('padding:0 8px;font-weight:bold;color:#b00000;')
        self.lbl_sb_conn = QtWidgets.QLabel('')
        self.lbl_sb_conn.setStyleSheet('padding:0 8px;')
        sb.addPermanentWidget(self.lbl_sb_task)
        sb.addPermanentWidget(self.lbl_sb_conn)
        self.last_sb_state = None

    # ------------------------------------------------------------ Modo Duplo
    def _build_dual_tab(self, tabs):
        '''Aba Modo Duplo: varreduras em que o R do OPT101 (linear na intensidade) é a referência de
        potência óptica e o R do INMP441 (fotoacústico) é medido no mesmo passo.
        'P' = varredura casada em PWM; 'F' = varredura em frequência normalizada pelo OPT101.'''
        self.dual_active = False
        self.dual_state = 'IDLE'
        self.dual_kind = 'P'
        self.dual_values = []
        self.dual_idx = 0
        self.dual_timer = 0.0
        self.dual_settle = self.dual_measure = 1.0
        self.dual_opt = []          # (r, fase, dc) do OPT101 durante a medida
        self.dual_aud = []          # (r, fase) do INMP441 durante a medida (thread de áudio)
        self.dual_results = []
        self.dual_excluded = set()  # índices de dual_results tirados do ajuste com um clique no gráfico
        self.dual_ref_cfg = []      # (corte do passa-altas, notch de rede) do OPT101 em cada ponto
        self.dual_opt_tau = None    # ajuste do τ efetivo do canal óptico (varredura em frequência)
        self.dual_tau_sensor = 0.0  # τ do sensor descontado do OPT101 na última exibição (s)
        self.dual_sensor_fit_txt = None   # resultado do último "Medir…" do τ do sensor
        self.dual_saved_cutoffs = None
        self.dual_fit = None

        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)

        # Medida: cada varredura tem a sua (a calibração pede integração longa; a casada em PWM, em geral, não)
        self.dual_mode_w, self.dual_tau_w = {}, {}
        for kind in ('P', 'F'):
            cmb = QtWidgets.QComboBox()
            cmb.addItems(['Média no tempo (τ atual)', 'Integração longa (τ da varredura)'])
            cmb.setToolTip(
                'Média no tempo: usa os filtros dos dois lock-ins (na varredura em frequência, os cortes automáticos\n'
                'de cada frequência); espera 9τ do mais lento e faz a média por 4τ.\n'
                'Integração longa: durante a varredura os dois passa-baixas passam a ter o τ escolhido (restaurados no fim);\n'
                'espera 9τ e faz a média por 1τ. Menos ruído por ponto, varredura mais lenta.')
            self.dual_mode_w[kind] = cmb
            self.dual_tau_w[kind] = self._dspin(0.001, 100.0, 1.0, 3, 0.5, None, width=70)
        # Nomes fixos: usados pelas preferências (QSettings)
        self.cmb_dual_mode_p, self.cmb_dual_mode_f = self.dual_mode_w['P'], self.dual_mode_w['F']
        self.sp_dual_tau_p, self.sp_dual_tau_f = self.dual_tau_w['P'], self.dual_tau_w['F']

        def sweep_box(title, fields, kind):
            box, btn, eta, bar = self._make_sweep_box(
                title, fields, lambda _=False, k=kind: self.toggle_dual_sweep(k),
                extra=(('Medida:', self.dual_mode_w[kind]), ('τ (s):', self.dual_tau_w[kind])))
            self.dual_bars[kind] = bar
            return box, btn, eta

        self.dual_bars = {}
        self.sp_dual_p0 = self._dspin(0.0, 100.0, 10.0, 1, 1.0, None, 110, ' %')
        self.sp_dual_p1 = self._dspin(0.0, 100.0, 100.0, 1, 1.0, None, 110, ' %')
        self.sp_dual_dp = self._dspin(0.1, 100.0, 10.0, 1, 1.0, None, 110, ' %')
        box_p, btn_p, eta_p = sweep_box('Varredura casada em PWM',
                                        (('Início:', self.sp_dual_p0), ('Fim:', self.sp_dual_p1),
                                         ('Passo:', self.sp_dual_dp)), 'P')
        self.sp_dual_f0 = self._dspin(0.1, 5000.0, CAL_SWEEP_F0, 2, 1.0, None, 110, ' Hz')
        self.sp_dual_f1 = self._dspin(0.1, 5000.0, CAL_SWEEP_F1, 2, 10.0, None, 110, ' Hz')
        self.cmb_dual_fspace = QtWidgets.QComboBox()
        self.cmb_dual_fspace.addItems(['Logarítmico', 'Linear'])
        self.sp_dual_fn = self._dspin(1.0, 5000.0, CAL_SWEEP_N, 1, 1.0, None, 90)
        self.lbl_dual_fn = QtWidgets.QLabel('N pontos:')
        self.cmb_dual_fspace.currentIndexChanged.connect(self._on_dual_fspace)
        box_f, btn_f, eta_f = sweep_box('Varredura em frequência (normalizada pelo OPT101)',
                                        (('Início:', self.sp_dual_f0), ('Fim:', self.sp_dual_f1),
                                         ('Espaçamento:', self.cmb_dual_fspace), (self.lbl_dual_fn, self.sp_dual_fn)), 'F')
        self.dual_btns = {'P': btn_p, 'F': btn_f}
        self.dual_etas = {'P': eta_p, 'F': eta_f}
        # Topo da aba: executar varreduras (painel recolhível) ou abrir uma varredura salva para analisar
        top_row = QtWidgets.QHBoxLayout()
        self.btn_dual_sweeps_panel = QtWidgets.QPushButton('Executar varreduras ▸')
        self.btn_dual_sweeps_panel.setCheckable(True)
        self.btn_dual_sweeps_panel.setToolTip('Mostra ou esconde as varreduras casada em PWM e em frequência.')
        self.btn_dual_sweeps_panel.toggled.connect(self.on_dual_sweeps_panel)
        top_row.addWidget(self.btn_dual_sweeps_panel)
        self.btn_dual_open = QtWidgets.QPushButton('Abrir varredura…')
        self.btn_dual_open.setToolTip('Carrega uma varredura do Modo Duplo já salva (CSV da pasta Medidas) para analisar:\n'
                                      'calibração, ajuste com modelos, exclusão de pontos, Fitar padrão e Salvar de novo.')
        self.btn_dual_open.clicked.connect(self.open_dual_sweep)
        top_row.addWidget(self.btn_dual_open)
        top_row.addStretch(1)
        lay.addLayout(top_row)
        self.dual_sweeps_panel = QtWidgets.QWidget()
        boxes = QtWidgets.QHBoxLayout(self.dual_sweeps_panel)
        boxes.setContentsMargins(0, 0, 0, 0)
        boxes.addWidget(box_p)
        boxes.addWidget(box_f)
        boxes.addStretch(1)
        self.dual_sweeps_panel.setVisible(False)
        lay.addWidget(self.dual_sweeps_panel)
        self.lbl_dual_status = QtWidgets.QLabel('')
        lay.addWidget(self.lbl_dual_status)

        self.dual_plots = QtWidgets.QWidget()
        pl = QtWidgets.QHBoxLayout(self.dual_plots)
        pl.setContentsMargins(0, 0, 0, 0)
        self.pw_dual_a, self.pw_dual_b = pg.PlotWidget(), pg.PlotWidget()
        for pw in (self.pw_dual_a, self.pw_dual_b):
            pw.showGrid(x=True, y=True, alpha=0.3)
            pl.addWidget(pw, 1)
        self.c_dual_a = self.pw_dual_a.plot([], [], pen=None, symbol='o', symbolSize=7,
                                            symbolBrush='royalblue', symbolPen='royalblue')
        self.c_dual_a.setZValue(10)         # acima do fit e dos "x" vermelhos: recebe o clique
        self.c_dual_a.sigPointsClicked.connect(self._on_dual_point_clicked)
        self.e_dual_a = pg.ErrorBarItem(x=np.empty(0), y=np.empty(0), pen=pg.mkPen((120, 120, 120)))
        self.pw_dual_a.addItem(self.e_dual_a)
        self.c_dual_a_fit = self.pw_dual_a.plot([], [], pen=pg.mkPen('#e67e22', width=2,
                                                                     style=QtCore.Qt.PenStyle.DashLine))
        self.c_dual_a_bad = self.pw_dual_a.plot([], [], pen=None, symbol='x', symbolSize=12,
                                                symbolBrush='#d00000', symbolPen=pg.mkPen('#d00000', width=2))
        self.c_dual_b = self.pw_dual_b.plot([], [], pen=pg.mkPen('firebrick', width=1.5), symbol='s', symbolSize=6,
                                            symbolBrush='firebrick', symbolPen='firebrick')
        self.e_dual_b = pg.ErrorBarItem(x=np.empty(0), y=np.empty(0), pen=pg.mkPen((120, 120, 120)))
        self.pw_dual_b.addItem(self.e_dual_b)
        self.c_dual_b_fit = self.pw_dual_b.plot([], [], pen=pg.mkPen('#e67e22', width=2,
                                                                     style=QtCore.Qt.PenStyle.DashLine))
        excl_row = QtWidgets.QHBoxLayout()
        excl_hint = QtWidgets.QLabel('Clique num ponto do gráfico da esquerda para tirá-lo do ajuste '
                                     '(vazado = excluído); clique de novo para incluí-lo.')
        excl_hint.setStyleSheet('color:#606060;')
        excl_row.addWidget(excl_hint)
        self.btn_dual_incl = QtWidgets.QPushButton('Incluir todos')
        self.btn_dual_incl.setToolTip('Volta a usar no ajuste todos os pontos excluídos com clique.')
        self.btn_dual_incl.clicked.connect(self._dual_include_all)
        self.btn_dual_incl.setEnabled(False)
        excl_row.addWidget(self.btn_dual_incl)
        self.btn_dual_resave = QtWidgets.QPushButton('Salvar de novo')
        self.btn_dual_resave.setToolTip('Grava CSV e PNG novos (sufixo _editado) com o ajuste, os pontos excluídos e a\n'
                                        'calibração atuais. O arquivo salvo no fim da varredura não é alterado.')
        self.btn_dual_resave.clicked.connect(lambda: self._export_dual(resave=True))
        self.btn_dual_resave.setEnabled(False)
        excl_row.addWidget(self.btn_dual_resave)
        excl_row.addStretch(1)
        lay.addLayout(excl_row)
        lay.addWidget(self.dual_plots, 1)
        # Aviso enquanto não há resultados (posição fixa em pixels, como o texto do fit da FFT)
        self.txt_dual_empty = []
        for pw in (self.pw_dual_a, self.pw_dual_b):
            t = pg.TextItem('Sem dados: escolha uma varredura acima e clique em ▶ Varredura.',
                            color=(110, 110, 110), anchor=(0, 0))
            t.setParentItem(pw.getPlotItem().vb)
            t.setPos(12, 12)
            self.txt_dual_empty.append(t)

        # Calibração do microfone em passos numerados, num painel recolhível: o modelo do ajuste
        # (folha de alumínio fina e livre) só vale com esse padrão
        cal_row = QtWidgets.QHBoxLayout()
        self.btn_dual_cal_panel = QtWidgets.QPushButton('Calibração de papel alumínio ▸')
        self.btn_dual_cal_panel.setCheckable(True)
        self.btn_dual_cal_panel.setToolTip(
            'Mostra ou esconde a calibração do microfone.\n'
            'O ajuste usado nela (folha de alumínio fina e livre, S ∝ f⁻¹·⁵) só vale com o padrão de papel alumínio:\n'
            'com outras amostras ele dá parâmetros sem sentido físico. Com o painel fechado, "Fitar padrão" não é aplicado.')
        self.btn_dual_cal_panel.toggled.connect(self.on_dual_cal_panel)
        cal_row.addWidget(self.btn_dual_cal_panel)
        cal_row.addStretch(1)
        lay.addLayout(cal_row)
        cal_box = self._group('Calibração de papel alumínio (o modelo só vale para esse padrão)')
        self.dual_cal_box = cal_box
        cal_box.setVisible(False)
        # Duas linhas (passos 1–2 e 3–4): numa só, a caixa exigia ~1600 px e a janela não cabia na tela
        cal_v = QtWidgets.QVBoxLayout(cal_box)
        cal_v.setContentsMargins(6, 2, 6, 2)
        cal_v.setSpacing(2)
        frow = QtWidgets.QHBoxLayout()
        cal_v.addLayout(frow)
        self.lbl_cal_step1 = QtWidgets.QLabel('<b>1.</b> Varredura em frequência')
        self.lbl_cal_step1.setToolTip('Rode a varredura em frequência acima com o padrão de alumínio na célula.')
        frow.addWidget(self.lbl_cal_step1)
        self.btn_cal_preset = QtWidgets.QPushButton('Parâmetros de calibração')
        self.btn_cal_preset.setToolTip(
            f'Preenche a varredura em frequência com os valores recomendados para a calibração:\n'
            f'{CAL_SWEEP_F0:g} a {CAL_SWEEP_F1:g} Hz, {CAL_SWEEP_N} pontos logarítmicos, integração longa com '
            f'τ = {CAL_SWEEP_TAU:g} s,\nPWM {CAL_SWEEP_PWM:g} %, Filtro 60 Hz desligado nos dois lock-ins e '
            f'"Usar" da calibração (linha superior) desmarcado.\nOs campos continuam editáveis. Confira o %ADC do OPT101 '
            f'(aba OPT101) antes de rodar.')
        self.btn_cal_preset.clicked.connect(self.apply_cal_preset)
        frow.addWidget(self.btn_cal_preset)
        frow.addWidget(QtWidgets.QLabel('→ <b>2.</b>'))
        self.chk_dual_std = QtWidgets.QCheckBox('Fitar padrão')
        self.chk_dual_std.setToolTip(
            'Disponível depois de uma varredura em frequência.\n\n'
            'Padrão de papel alumínio (termicamente fino, opaco): S(f) = A·f⁻ⁿ·H(f), com H um passa-altas de 1ª ordem\n'
            '(microfone/célula) de corte fc; fase Δφ(f) = φ0 + atan(fc/f) − 360°·f·td (td = atraso entre a luz e o sinal do microfone: propagação do som + eletrônica).\n'
            'n ≈ 1: amostra fina sobre suporte espesso; n ≈ 1,5: folha fina livre (limitada pela capacidade térmica).\nResíduos atípicos ou SNR baixo marcam os pontos fora da faixa confiável (x vermelho).')
        self.chk_dual_std.toggled.connect(lambda _: self._show_dual_results())
        frow.addWidget(self.chk_dual_std)
        self.chk_dual_std_phase = QtWidgets.QCheckBox('Incluir fase')
        self.chk_dual_std_phase.setChecked(True)
        self.chk_dual_std_phase.setToolTip('Usa a diferença de fase INMP441 − OPT101 no ajuste '
                                           '(precisa do firmware com o marcador de modulação).')
        self.chk_dual_std_phase.toggled.connect(lambda _: self._show_dual_results())
        frow.addWidget(self.chk_dual_std_phase)
        self.chk_dual_opt_tau = QtWidgets.QCheckBox('Descontar τ do sensor:')
        self.chk_dual_opt_tau.setChecked(True)
        tau_tip = ('Polo do OPT101 (depende do resistor de realimentação), descontado do OPT101 antes de S e Δφ:\n'
                   'fase + atan(2π·f·τ) e amplitude × √(1 + (2π·f·τ)²). Assim a calibração vale para qualquer resistor.\n'
                   'O atraso do driver/laser não entra: é comum ao microfone e já se cancela em Δφ.\n'
                   'Vale para o resistor montado agora; troque o valor ao trocar o resistor (0 = sem correção).\n'
                   'Medir…: compara a varredura em frequência atual com outra (mesma luz, outro resistor) e preenche o τ.')
        self.chk_dual_opt_tau.setToolTip(tau_tip)
        self.chk_dual_opt_tau.toggled.connect(lambda _: self._show_dual_results())
        frow.addWidget(self.chk_dual_opt_tau)
        self.sp_dual_tau_sensor = self._dspin(0.0, 500.0, 0.0, 2, 0.5, lambda _: self._show_dual_results(), 90, ' µs')
        self.sp_dual_tau_sensor.setToolTip(tau_tip)
        frow.addWidget(self.sp_dual_tau_sensor)
        self.btn_dual_tau_measure = QtWidgets.QPushButton('Medir…')
        self.btn_dual_tau_measure.setToolTip(tau_tip)
        self.btn_dual_tau_measure.clicked.connect(self.measure_sensor_tau)
        frow.addWidget(self.btn_dual_tau_measure)
        frow.addStretch(1)
        frow = QtWidgets.QHBoxLayout()
        cal_v.addLayout(frow)
        frow.addWidget(QtWidgets.QLabel('→ <b>3.</b>'))
        self.btn_dual_cal = QtWidgets.QPushButton('Gerar calibração do microfone')
        self.btn_dual_cal.setToolTip(
            'Disponível depois de uma varredura em frequência com "Fitar padrão" ligado '
            '(e com "Usar" da calibração, na linha superior, desmarcado).\n\n'
            'Usa a varredura em frequência do padrão de alumínio (folha fina livre, S ∝ f⁻¹·⁵ em teoria) para obter\n'
            'a resposta relativa do sistema microfone + célula: M(f) = S(f)·f¹·⁵, normalizada (máximo da curva ajustada = 1).\n'
            'A fase do sistema é Δφ(f) − φ0 do fit. Salva CSV e PNG na pasta Medidas (prefixo CAL_).')
        self.btn_dual_cal.setEnabled(False)
        self.btn_dual_cal.clicked.connect(self._make_dual_calibration)
        frow.addWidget(self.btn_dual_cal)
        frow.addWidget(QtWidgets.QLabel('Faixa plana ±'))
        self.sp_dual_flat_tol = QtWidgets.QDoubleSpinBox()
        self.sp_dual_flat_tol.setRange(0.1, 6.0)
        self.sp_dual_flat_tol.setDecimals(1)
        self.sp_dual_flat_tol.setSingleStep(0.5)
        self.sp_dual_flat_tol.setValue(1.0)
        self.sp_dual_flat_tol.setSuffix(' dB')
        self.sp_dual_flat_tol.setToolTip('Tolerância para a faixa em que a sensibilidade do microfone é constante '
                                         '(±1 dB ≈ ±12 %). A calibração procura o maior trecho de frequências dentro dela.')
        frow.addWidget(self.sp_dual_flat_tol)
        lbl_step4 = QtWidgets.QLabel('→ <b>4.</b> Escolha a calibração em <b>Calibração:</b> (linha superior) e marque <b>Usar</b>')
        lbl_step4.setToolTip('A calibração nova já aparece selecionada no topo da janela.')
        frow.addWidget(lbl_step4)
        frow.addStretch(1)
        lay.addWidget(cal_box)

        # Ajuste da varredura em frequência com modelos físicos conhecidos (painel recolhível)
        model_row = QtWidgets.QHBoxLayout()
        self.btn_dual_model_panel = QtWidgets.QPushButton('Ajuste com modelos ▸')
        self.btn_dual_model_panel.setCheckable(True)
        self.btn_dual_model_panel.setToolTip('Ajusta a varredura em frequência (magnitude, fase ou as duas) com modelos\n'
                                             'físicos de célula aberta. Use com a calibração aplicada ("Usar").')
        self.btn_dual_model_panel.toggled.connect(self.on_dual_model_panel)
        model_row.addWidget(self.btn_dual_model_panel)
        model_row.addStretch(1)
        lay.addLayout(model_row)
        self.dual_model_box = self._group('Ajuste com modelos (varredura em frequência)')
        self.dual_model_box.setVisible(False)
        mv = QtWidgets.QVBoxLayout(self.dual_model_box)
        mv.setContentsMargins(6, 2, 6, 2)
        mrow = QtWidgets.QHBoxLayout()
        mrow.addWidget(QtWidgets.QLabel('Modelo:'))
        self.cmb_dual_model = QtWidgets.QComboBox()
        self.cmb_dual_model.addItem('Nenhum', None)
        for key, name in FREQ_MODELS.items():
            self.cmb_dual_model.addItem(name, key)
            self.cmb_dual_model.setItemData(self.cmb_dual_model.count() - 1, FREQ_MODEL_TIPS[key],
                                            QtCore.Qt.ItemDataRole.ToolTipRole)
        self.cmb_dual_model.currentIndexChanged.connect(self._on_dual_model)
        mrow.addWidget(self.cmb_dual_model)
        mrow.addSpacing(10)
        mrow.addWidget(QtWidgets.QLabel('Ajustar:'))
        self.cmb_dual_model_target = QtWidgets.QComboBox()
        for name, key in (('Fase', 'phase'), ('Magnitude', 'mag'), ('Fase e magnitude', 'both')):
            self.cmb_dual_model_target.addItem(name, key)
        self.cmb_dual_model_target.setToolTip(
            'Fase: em geral a grandeza mais robusta (não depende da escala da luz nem da absorção da amostra).\n'
            'Magnitude: sensível a desvios de amplitude da referência e da calibração.\n'
            'Na lei de potência só a magnitude é ajustada (o modelo tem fase constante).')
        self.cmb_dual_model_target.currentIndexChanged.connect(lambda _: self._show_dual_results())
        self.cmb_dual_model_target.setEnabled(False)       # habilitado ao escolher um modelo (_on_dual_model)
        mrow.addWidget(self.cmb_dual_model_target)
        mrow.addSpacing(10)
        mrow.addWidget(QtWidgets.QLabel('Espessura L:'))
        self.sp_dual_thick = self._dspin(0.0, 100000.0, 0.0, 1, 10.0, lambda _: self._show_dual_results(), 110, ' µm')
        self.sp_dual_thick.setSpecialValueText('não informada')
        self.sp_dual_thick.setToolTip('Espessura da amostra (meça com micrômetro). Com ela, a difusividade térmica sai\n'
                                      'de f1: α = π·f1·L². Referências: Ti puro ≈ 9,3e-6 m²/s; Ti-6Al-4V ≈ 2,9e-6 m²/s;\n'
                                      'aço inox ≈ 4e-6 m²/s; alumínio ≈ 9,7e-5 m²/s; cobre ≈ 1,1e-4 m²/s.')
        mrow.addWidget(self.sp_dual_thick)
        mrow.addSpacing(10)
        mrow.addWidget(QtWidgets.QLabel('Faixa: de'))
        range_tip = ('Limita o ajuste do modelo a esta faixa de frequência (os outros pontos continuam no gráfico).\n'
                     'Use quando o modelo só vale numa região da varredura. Pontos excluídos com clique também\n'
                     'ficam fora. A curva verde é desenhada só na faixa ajustada.')
        self.sp_dual_model_f0 = self._dspin(0.0, 5000.0, 0.0, 1, 1.0, lambda _: self._show_dual_results(), 90, ' Hz')
        self.sp_dual_model_f0.setSpecialValueText('início')
        self.sp_dual_model_f1 = self._dspin(0.0, 5000.0, 0.0, 1, 10.0, lambda _: self._show_dual_results(), 90, ' Hz')
        self.sp_dual_model_f1.setSpecialValueText('fim')
        for sp in (self.sp_dual_model_f0, self.sp_dual_model_f1):
            sp.setToolTip(range_tip)
        mrow.addWidget(self.sp_dual_model_f0)
        mrow.addWidget(QtWidgets.QLabel('a'))
        mrow.addWidget(self.sp_dual_model_f1)
        mrow.addStretch(1)
        mv.addLayout(mrow)
        self.lbl_dual_model = QtWidgets.QLabel('')
        self.lbl_dual_model.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_dual_model.setWordWrap(True)
        mv.addWidget(self.lbl_dual_model)
        lay.addWidget(self.dual_model_box)
        self.dual_model_txt = None
        pen_model = pg.mkPen('#2e7d32', width=2, style=QtCore.Qt.PenStyle.DashLine)
        self.c_dual_a_model = self.pw_dual_a.plot([], [], pen=pen_model)
        self.c_dual_b_model = self.pw_dual_b.plot([], [], pen=pen_model)
        self.ln_dual_break = pg.InfiniteLine(angle=90, pen=pg.mkPen('#2e7d32', width=1, style=QtCore.Qt.PenStyle.DotLine))
        self.ln_dual_break.setVisible(False)
        self.pw_dual_a.addItem(self.ln_dual_break, ignoreBounds=True)
        self.lbl_dual_tau = QtWidgets.QLabel('')
        self.lbl_dual_tau.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_dual_tau.setWordWrap(True)
        lay.addWidget(self.lbl_dual_tau)
        self.lbl_dual_fit = QtWidgets.QLabel('')
        self.lbl_dual_fit.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_dual_fit.setWordWrap(True)
        lay.addWidget(self.lbl_dual_fit)
        self.lbl_dual_cal = QtWidgets.QLabel('')
        self.lbl_dual_cal.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_dual_cal.setWordWrap(True)
        lay.addWidget(self.lbl_dual_cal)
        self.dual_cal = None
        tabs.addTab(page, 'Modo Duplo')

        for sb in (self.sp_dual_p0, self.sp_dual_p1, self.sp_dual_dp,
                   self.sp_dual_f0, self.sp_dual_f1, self.sp_dual_fn):
            sb.valueChanged.connect(self.update_dual_eta)
        self.cmb_dual_fspace.currentIndexChanged.connect(self.update_dual_eta)
        # τ escolhido para a integração longa de cada varredura
        self.dual_user_tau = {k: w.value() for k, w in self.dual_tau_w.items()}
        for kind in ('P', 'F'):
            self.dual_tau_w[kind].valueChanged.connect(self.update_dual_eta)
            self.dual_tau_w[kind].valueChanged.connect(lambda v, k=kind: self._on_dual_tau(k, v))
            self.dual_mode_w[kind].currentIndexChanged.connect(lambda i, k=kind: self._on_dual_mode(k, i))
            self.dual_tau_w[kind].setEnabled(False)
        self._setup_dual_plots('P')
        self.update_dual_eta()
        self.refresh_mic_cal()

    def apply_cal_preset(self):
        '''Carrega na varredura em frequência do Modo Duplo os parâmetros recomendados para a calibração.'''
        if self.dual_active or self.sweep_active:
            self.flash('Termine ou cancele a varredura em andamento antes de carregar os parâmetros.')
            return
        self.cmb_dual_fspace.setCurrentIndex(0)          # logarítmico (antes do N: muda o sentido do campo)
        self.sp_dual_f0.setValue(CAL_SWEEP_F0)
        self.sp_dual_f1.setValue(CAL_SWEEP_F1)
        self.sp_dual_fn.setValue(CAL_SWEEP_N)
        self.cmb_dual_mode_f.setCurrentIndex(1)          # integração longa (antes do τ: libera o campo)
        self.sp_dual_tau_f.setValue(CAL_SWEEP_TAU)       # só na varredura em frequência
        # Notch ligado em só um dos lock-ins deslocaria a fase de um deles e contaminaria Δφ
        self.chk_mains.setChecked(False)
        self.chk_audio_mains.setChecked(False)
        self.chk_mic_cal.setChecked(False)               # a calibração é gerada com os dados brutos
        self.sp_power.setValue(CAL_SWEEP_PWM)
        self.btn_dual_sweeps_panel.setChecked(True)      # mostra os campos preenchidos
        self.flash(f'Parâmetros de calibração carregados (PWM {CAL_SWEEP_PWM:g} %): '
                   f'confira o %ADC do OPT101 antes de rodar a varredura.', 6.0)

    def _on_dual_tau(self, kind, val):
        if self.dual_mode_w[kind].currentIndex() == 1:
            self.dual_user_tau[kind] = float(val)

    def _on_dual_mode(self, kind, idx):
        '''Integração longa: campo editável com o τ escolhido. Média no tempo: mostra o τ atual (mais lento
        dos dois lock-ins), só para leitura.'''
        self.dual_tau_w[kind].setEnabled(idx == 1 and not self.dual_active)
        if idx == 1:
            self._set_spin(self.dual_tau_w[kind], self.dual_user_tau[kind])
        self.update_dual_eta()

    def _setup_dual_plots(self, kind):
        a, b = self.pw_dual_a, self.pw_dual_b
        if kind == 'P':
            a.setTitle('Fotoacústico × intensidade óptica')
            a.setLabel('left', 'INMP441 R (escala completa 24 bits)')
            a.setLabel('bottom', 'OPT101 R (u.a., ∝ intensidade)')
            b.setTitle('Calibração: intensidade óptica × PWM')
            b.setLabel('left', 'OPT101 R (u.a.)')
            b.setLabel('bottom', 'PWM do laser (%)')
            a.setLogMode(x=False, y=False)
            b.setLogMode(x=False, y=False)
        else:
            a.setTitle('Sinal fotoacústico normalizado (INMP441 R / OPT101 R)')
            a.setLabel('left', 'S = R_INMP441 / R_OPT101')
            a.setLabel('bottom', 'Frequência (Hz)')
            b.setTitle('Diferença de fase INMP441 − OPT101')
            b.setLabel('left', 'Δφ (graus)')
            b.setLabel('bottom', 'Frequência (Hz)')
            a.setLogMode(x=True, y=True)
            b.setLogMode(x=True, y=False)
        # Barras de erro só nos eixos lineares (o pyqtgraph não as transforma em escala log)
        self.e_dual_a.setVisible(kind == 'P')
        self.e_dual_b.setVisible(kind == 'P')
        for c in (self.c_dual_a, self.c_dual_a_fit, self.c_dual_a_bad, self.c_dual_b, self.c_dual_b_fit):
            c.setData([], [])
        for t in self.txt_dual_empty:
            t.setVisible(True)
        # Faixa neutra enquanto não há dados (em vez de -400 a 400 x 0,001)
        if kind == 'P':
            a.setRange(xRange=(0, 1), yRange=(0, 1), padding=0)
            b.setRange(xRange=(0, 100), yRange=(0, 1), padding=0)
        else:
            lf = np.log10(sorted((max(self.sp_dual_f0.value(), 0.1), max(self.sp_dual_f1.value(), 0.1))))
            a.setRange(xRange=tuple(lf), yRange=(-3, 0), padding=0)
            b.setRange(xRange=tuple(lf), yRange=(-180, 180), padding=0)
        self.chk_dual_std.setEnabled(kind == 'F')
        self.chk_dual_std_phase.setEnabled(kind == 'F')
        for w in (self.chk_dual_opt_tau, self.sp_dual_tau_sensor, self.btn_dual_tau_measure):
            w.setEnabled(kind == 'F')
        self.btn_dual_cal.setEnabled(False)
        self.dual_std = None
        self.dual_opt_tau = None
        self.dual_sensor_fit_txt = None
        self.lbl_dual_fit.setText('')
        self.lbl_dual_tau.setText('')

    def _dual_planned(self, kind):
        if kind == 'P':
            return self._planned_range(self.sp_dual_p0.value(), self.sp_dual_p1.value(), self.sp_dual_dp.value())
        f0, f1 = sorted((self.sp_dual_f0.value(), self.sp_dual_f1.value()))
        if self.cmb_dual_fspace.currentIndex() == 0:
            n = max(2, int(round(self.sp_dual_fn.value())))
            return [round(float(v), 3) for v in np.geomspace(f0, f1, n)]
        return self._planned_range(f0, f1, self.sp_dual_fn.value())

    def _dual_times(self, kind, value):
        '''(espera, medida) do ponto. O LP de 2 polos chega a ~1e-3 do degrau em 9τ.'''
        if self.dual_mode_w[kind].currentIndex() == 1:
            tau = self.dual_tau_w[kind].value()
            return 9.0 * tau + 0.3, max(0.5, tau)
        if kind == 'F':
            # A troca de frequência aplica os cortes automáticos nos dois lock-ins (apply_frequency)
            lp = get_effective_cutoffs(value)[0]
            tau = max(lp_tau(lp, FS), lp_tau(lp, AUDIO_FS_REAL))
        else:
            tau = max(lp_tau(self.cutoff_lp, FS), lp_tau(self.audio_cutoff_lp, AUDIO_FS_REAL))
        return max(1.0, 9.0 * tau) + 0.3, max(1.0, 4.0 * tau)

    def update_dual_eta(self, *_):
        if self.dual_active:
            return
        tau_now = max(lp_tau(self.cutoff_lp, FS), lp_tau(self.audio_cutoff_lp, AUDIO_FS_REAL))
        for kind, cmb in self.dual_mode_w.items():
            if cmb.currentIndex() == 0 and abs(self.dual_tau_w[kind].value() - tau_now) > 0.005:
                self._set_spin(self.dual_tau_w[kind], tau_now)
        for kind, lbl in self.dual_etas.items():
            values = self._dual_planned(kind)
            total = sum(sum(self._dual_times(kind, v)) for v in values)
            lbl.setText(f'Tempo estimado: {self._fmt_time(total)}')
            lbl.setToolTip(f'{len(values)} pontos')

    def _dual_set_long_tau(self, kind=None):
        fc = 1.0 / (2.0 * np.pi * self.dual_tau_w[kind or self.dual_kind].value())
        self.sp_lp.setValue(fc)
        self.sp_audio_lp.setValue(fc)

    def toggle_dual_sweep(self, kind):
        if self.dual_active:
            if kind == self.dual_kind:
                self._end_dual_sweep()
                self.flash('Varredura do Modo Duplo cancelada pelo usuário.')
            return
        if self.average_mode:
            self.flash('As varreduras do Modo Duplo precisam do OPT101 no Modo Lock-In.')
            return
        if self.sweep_active:
            self.flash('Já existe uma varredura em andamento.')
            return
        values = self._dual_planned(kind)
        if not values:
            return
        if not self.chk_audio_lockin.isChecked() and not self.chk_audio_noise.isChecked():
            self.chk_audio_lockin.setChecked(True)     # o lock-in do INMP441 precisa estar rodando
        self.dual_restore = self._excitation_snapshot() if kind == 'F' else None
        long_tau = self.dual_mode_w[kind].currentIndex() == 1
        if long_tau:
            self.dual_saved_cutoffs = (self.cutoff_lp, self.audio_cutoff_lp)
            self._dual_set_long_tau(kind)
        self.dual_kind = kind
        self.dual_values = values
        self.dual_idx = 0
        self.dual_results = []
        self.dual_excluded = set()
        self.dual_ref_cfg = []
        self.dual_fit = None
        self.dual_params = {'kind': kind, 'values': values, 'freq': self.ref_freq, 'pwm': self.laser_power,
                            'mode': self.dual_mode_w[kind].currentText(),
                            'tau': self.dual_tau_w[kind].value() if long_tau else None}
        self.dual_active = True
        btn = self.dual_btns[kind]
        btn.setText('⏹ Cancelar')
        btn.setStyleSheet('background:#f8d7da;')
        self.dual_btns['F' if kind == 'P' else 'P'].setEnabled(False)
        for w in ((self.sp_freq, self.sp_power, self.sp_lp, self.sp_audio_lp)
                  + tuple(self.dual_mode_w.values()) + tuple(self.dual_tau_w.values())):
            w.setEnabled(False)
        for b in list(self.btn_sweeps.values()) + list(self.btn_sweeps_aud.values()):
            b.setEnabled(False)
        self.dual_etas[kind].setStyleSheet('font-weight:bold;font-family:Consolas,monospace;color:#d00000;')
        self._setup_dual_plots(kind)
        self.dual_remaining = sum(sum(self._dual_times(kind, v)) for v in values)
        self.dual_bars[kind].setValue(0)
        self.dual_bars[kind].setVisible(True)
        self._dual_go(values[0], time.perf_counter())

    def _dual_go(self, value, now):
        if self.dual_kind == 'P':
            self._set_spin(self.sp_power, value)
            self.laser_power = value
            self.link.write(f"P{value}\n")
        else:
            self._set_spin(self.sp_freq, value)
            self.apply_frequency(value)        # reinicia a modulação (novo marcador de fase)
            if self.dual_saved_cutoffs is not None:
                self._dual_set_long_tau()      # apply_frequency volta aos cortes automáticos
        self.dual_settle, self.dual_measure = self._dual_times(self.dual_kind, value)
        self.dual_state = 'SETTLING'
        self.dual_timer = now
        self.dual_opt = []
        with self.audio_lock:
            self.dual_aud = []

    def _end_dual_sweep(self):
        self.dual_active = False
        self.dual_state = 'IDLE'
        self.btn_dual_resave.setEnabled(bool(self.dual_results))
        if self.dual_saved_cutoffs is not None:
            self.sp_lp.setValue(self.dual_saved_cutoffs[0])
            self.sp_audio_lp.setValue(self.dual_saved_cutoffs[1])
            self.dual_saved_cutoffs = None
        if getattr(self, 'dual_restore', None) is not None:     # varredura em frequência: volta ao início
            self._restore_excitation(self.dual_restore)
            self.dual_restore = None
        for btn in self.dual_btns.values():
            btn.setText('▶ Varredura')
            btn.setStyleSheet('background:#cfe2ff;')
            btn.setEnabled(True)
        for w in (self.sp_freq, self.sp_power, self.sp_lp, self.sp_audio_lp) + tuple(self.dual_mode_w.values()):
            w.setEnabled(True)
        for kind, sp in self.dual_tau_w.items():
            sp.setEnabled(self.dual_mode_w[kind].currentIndex() == 1)
        for b in list(self.btn_sweeps.values()) + list(self.btn_sweeps_aud.values()):
            b.setEnabled(True)
        for lbl in self.dual_etas.values():
            lbl.setStyleSheet('font-family:Consolas,monospace;')
        for bar in self.dual_bars.values():
            bar.setVisible(False)
        self.update_dual_eta()
        self.btn_dual_cal.setEnabled(self.dual_std is not None and self.dual_cal is None)

    def dual_step(self, now):
        elapsed = now - self.dual_timer
        n = len(self.dual_values)
        v = self.dual_values[self.dual_idx]
        rest = sum(sum(self._dual_times(self.dual_kind, x)) for x in self.dual_values[self.dual_idx:]) - elapsed
        self.dual_rest = rest
        self.dual_bars[self.dual_kind].setValue(
            int(1000 * min(1.0, max(0.0, 1.0 - rest / max(self.dual_remaining, 1e-6)))))
        self.dual_etas[self.dual_kind].setText(f'Restante: {self._fmt_time(rest)}')
        head = f'[{self.dual_idx + 1}/{n}] ' + (f'PWM {v:.1f} %' if self.dual_kind == 'P' else f'{v:g} Hz')
        if self.dual_state == 'SETTLING':
            self.lbl_dual_status.setText(f'{head} | estabilizando os lock-ins ({elapsed:.1f}/{self.dual_settle:.1f} s)')
            if elapsed >= self.dual_settle:
                self.dual_state = 'MEASURING'
                self.dual_timer = now
                self.dual_opt = []
                with self.audio_lock:
                    self.dual_aud = []
            return
        self.lbl_dual_status.setText(f'{head} | medindo ({elapsed:.1f}/{self.dual_measure:.1f} s)')
        if elapsed < self.dual_measure:
            return
        with self.audio_lock:
            aud = self.dual_aud
            self.dual_aud = []
        if self.dual_opt and aud:
            r_o = np.concatenate([c[0] for c in self.dual_opt])
            p_o = np.concatenate([c[1] for c in self.dual_opt])
            if self.normalize_mode:   # usa o R bruto: a referência é a intensidade, não R/DC
                r_o = r_o * np.maximum(np.concatenate([c[2] for c in self.dual_opt]), 1.0) / 100.0
            r_a = np.concatenate([c[0] for c in aud])
            p_a = np.concatenate([c[1] for c in aud])
            self.dual_results.append((v, float(r_o.mean()), float(r_o.std()),
                                      float(r_a.mean()), float(r_a.std()),
                                      *circ_stats_deg(p_a), *circ_stats_deg(p_o)))
            self.dual_ref_cfg.append((self.cutoff_hp, self.chk_mains.isChecked()))
            self._show_dual_results()
        else:
            self.flash(f'Modo Duplo: sem dados em {head} (OPT101 e INMP441 conectados?)')
        self.dual_idx += 1
        if self.dual_idx < n:
            self._dual_go(self.dual_values[self.dual_idx], now)
        else:
            self._end_dual_sweep()
            self._export_dual()

    def _dual_arrays(self):
        res = np.array(self.dual_results, dtype=float).reshape(-1, 9)
        return res.T

    def _show_dual_results(self):
        if not getattr(self, 'dual_results', None):     # o seletor de calibração existe antes da aba
            return
        if self.txt_dual_empty[0].isVisible():
            for t in self.txt_dual_empty:
                t.setVisible(False)
            self.pw_dual_a.enableAutoRange()      # a faixa neutra desligou o ajuste automático
            self.pw_dual_b.enableAutoRange()
        x, ro, ro_e, ra, ra_e, pa, pa_e, po, po_e = self._dual_arrays()
        self.dual_fit = None
        self.dual_std = None
        self.dual_cal = None        # só a varredura em frequência aplica a calibração (o CSV registra isso)
        self.btn_dual_cal.setEnabled(False)
        keep = np.ones(x.size, dtype=bool)                # pontos não excluídos com clique
        keep[[i for i in self.dual_excluded if i < x.size]] = False
        self.btn_dual_incl.setEnabled(bool(self.dual_excluded))
        self.btn_dual_resave.setEnabled(not self.dual_active)
        excl_txt = self._dual_excluded_text()
        if self.dual_kind == 'P':
            self._fit_dual_model(np.empty(0), np.empty(0), np.empty(0), np.empty(0), np.empty(0))
            if self.btn_dual_model_panel.isChecked() and self.cmb_dual_model.currentData() is not None:
                self.lbl_dual_model.setText('O ajuste com modelos vale só para a varredura em frequência.')
            self._set_dual_points(ro, ra, np.arange(x.size), keep)
            self.e_dual_a.setData(x=ro, y=ra, height=2 * ra_e, width=2 * ro_e)
            self.c_dual_b.setData(x, ro)
            self.e_dual_b.setData(x=x, y=ro, height=2 * ro_e)
            fit = fit_sweep(ro[keep], ra[keep], 'lin') if keep.sum() >= 2 else None
            if fit is None:
                self.c_dual_a_fit.setData([], [])
                self.lbl_dual_fit.setText(excl_txt)
                return
            func, text = fit
            xx = np.linspace(0.0, float(ro.max()) * 1.05, 100)
            self.c_dual_a_fit.setData(xx, func(xx))
            self.dual_fit = 'Fit INMP441 x OPT101: ' + text.replace('<br>', '; ')
            self.lbl_dual_fit.setText('<span style="color:#b35c00;"><b>Fit INMP441 × OPT101:</b> &nbsp; '
                                      + text.replace('<br>', ' &nbsp; ') + '</span>' + excl_txt)
            return

        fa = np.array([actual_mod_freq(v) for v in x])
        # Diagnóstico: τ efetivo do canal óptico pela fase do OPT101, descontada a cadeia digital de cada ponto
        self.dual_opt_tau = None
        lines = []
        if len(self.dual_ref_cfg) == x.size and x.size >= 4:
            hp, mains = (np.array(c) for c in zip(*self.dual_ref_cfg))
            self.dual_opt_tau = fit_opt_tau(fa, po, po_e, opt_digital_phase(fa, hp, mains), ro)
            if self.dual_opt_tau is not None:
                lines.append(self.dual_opt_tau['text'])
        # Correção pelo polo do sensor (OPT101), na fase e na amplitude da referência óptica
        self.dual_tau_sensor = self._tau_sensor()
        if self.dual_tau_sensor > 0:
            xs = 2.0 * np.pi * fa * self.dual_tau_sensor
            po = po + np.degrees(np.arctan(xs))
            ro, ro_e = ro * np.sqrt(1.0 + xs * xs), ro_e * np.sqrt(1.0 + xs * xs)
            lines.append(f'OPT101 corrigido pelo τ do sensor = {self.dual_tau_sensor * 1e6:.3g} µs '
                         f'(fase e amplitude) antes de S e Δφ.')
        if getattr(self, 'dual_sensor_fit_txt', None):
            lines.append(self.dual_sensor_fit_txt)
        self.lbl_dual_tau.setText('<br>'.join(lines))
        ok = (ro > 0) & (ra > 0)
        s = np.where(ok, ra / np.where(ok, ro, 1.0), np.nan)
        s_rel = np.sqrt((ra_e / np.maximum(ra, 1e-30)) ** 2 + (ro_e / np.maximum(ro, 1e-30)) ** 2)
        # Δφ desenrolada ao longo da frequência (sem os saltos falsos de ±360°)
        order = np.argsort(x)
        dphi = np.empty_like(x)
        dphi[order] = np.degrees(np.unwrap(np.radians(wrap_deg(pa - po)[order])))
        dphi_e = np.hypot(pa_e, po_e)
        cal_txt = ''
        if self.chk_mic_cal.isChecked():
            self.dual_cal = load_mic_calibration(self.cmb_mic_cal.currentData())
            if self.dual_cal is None:
                cal_txt = '<b>Calibração INMP441:</b> nenhuma calibração válida selecionada na linha superior.'
            else:
                c = self.dual_cal
                lf, lc = np.log(np.maximum(x, 1e-9)), np.log(c['f'])
                inside = (x >= c['f'][0] * 0.999) & (x <= c['f'][-1] * 1.001)
                s = s / np.exp(np.interp(lf, lc, np.log(c['sens'])))
                dphi = dphi - np.interp(lf, lc, c['phase'])
                ok &= inside
                cal_txt = (f'<b>Calibração INMP441:</b> {os.path.basename(c["path"])}'
                           + (f' ({int((~inside).sum())} ponto(s) fora da faixa '
                              f'{c["f"][0]:g}–{c["f"][-1]:g} Hz ocultados)' if (~inside).any() else ''))
                if c['legacy']:
                    cal_txt += ('<br><span style="color:#d00000;">⚠ Calibração antiga: feita antes do firmware com o '
                                'marcador de modulação corrigido (23/10/2026 14:43) ou com a correção pelo τ efetivo. '
                                'A fase do sistema não é comparável (td ~100 µs maior); gere uma calibração nova.</span>')
                elif (c['opt_tau'] > 0) != (self.dual_tau_sensor > 0):
                    cal_txt += ('<br><span style="color:#d00000;">⚠ A calibração foi gerada '
                                + ('com' if c['opt_tau'] > 0 else 'sem')
                                + ' a correção pelo τ do sensor, e esta varredura está '
                                + ('com' if self.dual_tau_sensor > 0 else 'sem')
                                + ' ela: S e a fase do sistema ficam inconsistentes.</span>')
        self.lbl_dual_cal.setText(cal_txt)
        self._set_dual_points(x[ok], s[ok], np.flatnonzero(ok), keep[ok])
        self.c_dual_b.setData(x[ok] if self.dual_cal else x, dphi[ok] if self.dual_cal else dphi)
        self.c_dual_a_fit.setData([], [])
        self.c_dual_b_fit.setData([], [])
        self.c_dual_a_bad.setData([], [])
        m = ok & keep                                     # pontos que entram no ajuste
        self._fit_dual_model(x[m], s[m], s_rel[m], dphi[m], dphi_e[m])
        # O fit do padrão só roda com o painel "Calibração de papel alumínio" aberto (modelo só do alumínio)
        std_on = self.chk_dual_std.isChecked() and self.btn_dual_cal_panel.isChecked()
        if not std_on or m.sum() < 4:
            self.lbl_dual_fit.setText(('' if not std_on
                                       else 'Fit padrão: são necessários pelo menos 4 pontos.') + excl_txt)
            return
        snr_min = 10.0 ** (self.audio_snr_alert / 20.0)
        res = fit_pa_standard(x[m], s[m], s_rel[m], dphi[m], dphi_e[m],
                              ra[m] / np.maximum(ra_e[m], 1e-30), snr_min, self.chk_dual_std_phase.isChecked())
        if res is None:
            self.lbl_dual_fit.setText('Fit padrão: o ajuste não convergiu.' + excl_txt)
            return
        ff = np.geomspace(float(x[m].min()), float(x[m].max()), 300)
        self.c_dual_a_fit.setData(ff, res['amp'](ff))
        if res['phase'] is not None:
            model = res['phase'](ff)
            # alinha o modelo (definido a menos de 360°) com a fase desenrolada dos dados
            shift = 360.0 * np.round(np.mean(dphi[m] - res['phase'](x[m])) / 360.0)
            self.c_dual_b_fit.setData(ff, model + shift)
        # 'good' nos pontos exibidos (ok): os excluídos com clique contam como fora da faixa confiável
        good = np.zeros(ok.sum(), dtype=bool)
        good[keep[ok]] = res['good']
        bad = ~good & keep[ok]                            # rejeitados pelo próprio ajuste (x vermelho)
        self.c_dual_a_bad.setData(x[ok][bad], s[ok][bad])
        self.dual_std = {'f': x[ok], 's': s[ok], 's_rel': s_rel[ok], 'dphi': dphi[ok], 'dphi_e': dphi_e[ok],
                         'res': dict(res, good=good)}
        # a calibração deve ser gerada com os dados brutos, não com dados já corrigidos
        self.btn_dual_cal.setEnabled(not self.dual_active and self.dual_cal is None)
        self.dual_fit = res['text'].replace('<br>', '; ').replace('<b>', '').replace('</b>', '')
        self.lbl_dual_fit.setText(f'<span style="color:#b35c00;">{res["text"]}</span>' + excl_txt)

    def _set_dual_points(self, x, y, idx, keep):
        '''Pontos do gráfico principal do Modo Duplo: incluídos cheios, excluídos do ajuste vazados.
        'idx' (índice em dual_results) vai como dado de cada ponto, para o clique saber qual é.'''
        self.c_dual_a.setData(x, y, data=list(idx),
                              symbolBrush=[pg.mkBrush('royalblue') if k else pg.mkBrush(255, 255, 255, 0) for k in keep],
                              symbolPen=[pg.mkPen('royalblue') if k else pg.mkPen('#909090', width=1.5) for k in keep])

    def _on_dual_point_clicked(self, _item, points, ev=None, *_):
        '''Clique num ponto do gráfico principal: tira do ajuste ou devolve a ele. Com pontos sobrepostos
        (ex.: PWM abaixo do limiar do laser, todos perto da origem), vale o mais próximo do cursor.'''
        if not len(points):
            return
        pt = points[0]
        if ev is not None and len(points) > 1:
            sx, sy = self.pw_dual_a.getPlotItem().vb.viewPixelSize()
            c = ev.pos()
            pt = min(points, key=lambda q: ((q.pos().x() - c.x()) / sx) ** 2 + ((q.pos().y() - c.y()) / sy) ** 2)
        i = int(pt.data())
        self.dual_excluded ^= {i}
        self._show_dual_results()

    def _dual_include_all(self):
        self.dual_excluded.clear()
        self._show_dual_results()

    def _dual_excluded_text(self):
        '''Aviso com os pontos excluídos do ajuste ('' se nenhum).'''
        if not self.dual_excluded:
            return ''
        unit = '%' if self.dual_kind == 'P' else 'Hz'
        vals = ', '.join(f'{self.dual_results[i][0]:g}' for i in sorted(self.dual_excluded) if i < len(self.dual_results))
        return (f'<br><span style="color:#606060;">{len(self.dual_excluded)} ponto(s) excluído(s) do ajuste '
                f'com clique: {vals} {unit}</span>')

    def refresh_mic_cal(self, *_, select_latest=False):
        '''Lista as calibrações da pasta Medidas no seletor da linha superior (mais recente primeiro).
        Mantém a escolha do usuário enquanto o arquivo existir; senão (ou com select_latest), a mais recente.'''
        cmb = self.cmb_mic_cal
        current = cmb.currentData()
        paths = list_mic_calibrations()
        cmb.blockSignals(True)
        cmb.clear()
        for p in paths:
            # Sem as partes comuns a todas (CAL_, microfone_, .csv): cabe na linha superior
            cmb.addItem(os.path.basename(p)[4:-4].replace('microfone_', ''), p)
            cmb.setItemData(cmb.count() - 1, p, QtCore.Qt.ItemDataRole.ToolTipRole)
        if not paths:
            cmb.addItem('(nenhuma calibração na pasta Medidas)', None)
        cmb.setCurrentIndex(paths.index(current) if current in paths and not select_latest else 0)
        cmb.blockSignals(False)
        cmb.setEnabled(bool(paths))
        self.chk_mic_cal.setEnabled(bool(paths))
        if not paths:
            self.chk_mic_cal.setChecked(False)
            cmb.setToolTip('Nenhuma calibração encontrada (CAL_*microfone_*.csv na pasta Medidas).\n'
                           'Gere uma na aba Modo Duplo: varredura em frequência → Fitar padrão → '
                           'Gerar calibração do microfone.')
        else:
            cmb.setToolTip(f'{cmb.currentData()}\nA lista é relida da pasta Medidas ao abrir.')
        if cmb.currentData() != current:
            self._show_dual_results()

    def _calibration_files(self, path):
        '''CSV da calibração e o PNG de mesmo nome (se existir).'''
        png = path[:-4] + '.png'
        return (path, png) if os.path.isfile(png) else (path,)

    def _make_dual_calibration(self):
        '''Curva de sensibilidade relativa do microfone + célula a partir da varredura do padrão de alumínio:
        a folha fina livre dá S ∝ f^-1,5 (Rosencwaig-Gersho), então M(f) = S(f)·f^1,5 é a resposta do sistema.'''
        d = self.dual_std
        if d is None:
            return
        res, f = d['res'], d['f']
        good = res['good']
        k = np.argsort(f)
        f, good = f[k], good[k]
        m = d['s'][k] * f ** 1.5
        ff = np.geomspace(float(f.min()), float(f.max()), 300)
        model = res['amp'](ff) * ff ** 1.5             # fit padrão × f^1,5 = curva suave da sensibilidade
        m_ref = float(model.max())                     # normaliza: máximo da curva ajustada = 1
        tol = self.sp_dual_flat_tol.value()
        flat = find_flat_band(f, m / m_ref, good, tol)
        if flat is not None and flat[1] > flat[0]:
            m_ref *= flat[2]                           # com faixa plana: média da faixa plana = 1
            f_lo, f_hi = float(f[flat[0]]), float(f[flat[1]])
            in_flat = (f >= f_lo) & (f <= f_hi)
            flat_txt = f'Faixa plana (±{tol:g} dB): {f_lo:g} a {f_hi:g} Hz'
        else:
            flat = None
            in_flat = np.zeros(f.size, dtype=bool)
            flat_txt = f'Faixa plana (±{tol:g} dB): não encontrada (menos de 2 pontos seguidos dentro da tolerância)'
        model = res['amp'](ff) * ff ** 1.5 / m_ref
        sens, sens_e = m / m_ref, m / m_ref * d['s_rel'][k]
        p = res['params']
        use_phase = res['phase'] is not None
        ph = d['dphi'][k] - (p[4] if use_phase else float(np.median(d['dphi'][k][good])))
        ph -= 360.0 * np.round(np.median(ph[good]) / 360.0)
        ph_e = d['dphi_e'][k]
        fc = float(np.exp(p[2]))

        q = self.dual_params
        now_dt = datetime.now()
        # Calibração: CAL vem antes do nome da amostra (CAL_<amostra>_microfone_...)
        stem = 'CAL_' + self._stem(f"microfone_{f.min():g}_{f.max():g}Hz_{now_dt.strftime('%Y%m%d_%H%M%S')}")
        os.makedirs(MEDIDAS_DIR, exist_ok=True)
        csv_path = os.path.join(MEDIDAS_DIR, stem + '.csv')

        win = pg.GraphicsLayoutWidget()
        win.setBackground('w')
        win.resize(900, 650)
        pa_ = win.addPlot(row=0, col=0, title=f'Sensibilidade relativa do microfone + célula (M = S·f¹·⁵)<br>'
                                              f'<span style="color:#2e7d32;">{flat_txt}</span>')
        pa_.setLogMode(x=True, y=True)
        pa_.showGrid(x=True, y=True, alpha=0.3)
        pa_.setLabel('left', 'M(f) relativa')
        pa_.setLabel('bottom', 'Frequência (Hz)')
        pa_.plot(f[good], sens[good], pen=pg.mkPen('#1f4e9c', width=1.5), symbol='o', symbolSize=6,
                 symbolBrush='#1f4e9c', symbolPen='#1f4e9c')
        if (~good).any():
            pa_.plot(f[~good], sens[~good], pen=None, symbol='x', symbolSize=9,
                     symbolBrush='#d00000', symbolPen=pg.mkPen('#d00000', width=2))
        pa_.plot(ff, model, pen=pg.mkPen('#e67e22', width=2, style=QtCore.Qt.PenStyle.DashLine))
        pb_ = win.addPlot(row=1, col=0, title='Fase do sistema (Δφ − φ0)')
        pb_.setLogMode(x=True, y=False)
        pb_.showGrid(x=True, y=True, alpha=0.3)
        pb_.setLabel('left', 'graus')
        pb_.setLabel('bottom', 'Frequência (Hz)')
        pb_.plot(f, ph, pen=pg.mkPen('firebrick', width=1.5), symbol='s', symbolSize=6,
                 symbolBrush='firebrick', symbolPen='firebrick')
        if use_phase:
            pb_.plot(ff, res['phase'](ff) - p[4] - 360.0 * np.round(np.median(ph[good]) / 360.0),
                     pen=pg.mkPen('#e67e22', width=2, style=QtCore.Qt.PenStyle.DashLine))
        pb_.setXLink(pa_)
        if flat is not None:
            for plt in (pa_, pb_):
                reg = pg.LinearRegionItem((np.log10(f_lo), np.log10(f_hi)), movable=False,
                                          brush=pg.mkBrush(46, 125, 50, 40), pen=pg.mkPen(46, 125, 50, 120))
                reg.setZValue(-10)
                plt.addItem(reg)
            for y in (10 ** (-tol / 20.0), 10 ** (tol / 20.0)):
                pa_.addLine(y=np.log10(y), pen=pg.mkPen((46, 125, 50), width=1, style=QtCore.Qt.PenStyle.DotLine))
        try:
            with open(csv_path, 'w', newline='', encoding='utf-8') as fh:
                fh.write(f"# Calibração relativa do microfone + célula - {now_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
                         f"# Padrão: folha de alumínio fina livre, S teórico ∝ f^-1.5; M(f) = S(f)*f^1.5, normalizada pela média da faixa plana (ou pelo máximo do fit, se não houver)\n"
                         f"# Varredura {f.min():g} a {f.max():g} Hz ({f.size} pontos), PWM {q['pwm']:g} %; {q['mode']}\n"
                         f"# Fase_Sistema = Δφ(INMP441 - OPT101) - φ0 do fit; Valido = 0 para pontos fora da faixa confiável\n"
                         f"# Corte do microfone/célula (fc) = {fc:.4g} Hz\n# {flat_txt}\n")
                if self.dual_excluded:
                    fh.write('# Pontos excluídos do ajuste com clique (Valido = 0): '
                             + ', '.join(f'{self.dual_results[i][0]:g}' for i in sorted(self.dual_excluded)) + ' Hz\n')
                for txt in (self.dual_opt_tau['text'] if self.dual_opt_tau else None,
                            getattr(self, 'dual_sensor_fit_txt', None)):
                    if txt:
                        fh.write(f"# {self._plain(txt)}\n")
                # Lido por load_mic_calibration: τ do sensor descontado do OPT101 (0 = sem correção). A chave
                # também marca a calibração como feita com o marcador de modulação corrigido no firmware.
                fh.write(f"# OPT101_tau_sensor_s = {self.dual_tau_sensor:.6g}\n")
                if self.dual_fit:
                    fh.write(f'# {self.dual_fit}\n')
                fh.write('Frequencia_Hz,Sensibilidade_Rel,Sensibilidade_Rel_DP,Sensibilidade_Fit,Fase_Sistema_Graus,Fase_DP,Valido,Faixa_Plana\n')
                fit_at = res['amp'](f) * f ** 1.5 / m_ref
                for i in range(f.size):
                    fh.write(f'{f[i]:.3f},{sens[i]:.6g},{sens_e[i]:.4g},{fit_at[i]:.6g},{ph[i]:.3f},{ph_e[i]:.3f},'
                             f'{int(good[i])},{int(in_flat[i])}\n')
            win.grab().save(os.path.join(MEDIDAS_DIR, stem + '.png'))
            self._session_add(csv_path, os.path.join(MEDIDAS_DIR, stem + '.png'))
            self.flash(f'Calibração do microfone salva: {csv_path}', 6.0)
            self.refresh_mic_cal(select_latest=True)        # a nova passa a ser a selecionada
            self.lbl_dual_status.setText(f'Calibração salva: {csv_path} — {flat_txt}')
        except Exception as e:
            print(f'Erro ao salvar a calibração: {e}')
            return
        win.setWindowTitle('Calibração do microfone')
        win.show()
        self._cal_win = win                                  # mantém a janela viva

    def _tau_sensor(self):
        '''τ do sensor (s) descontado do OPT101 na varredura em frequência; 0 = sem correção.'''
        return self.sp_dual_tau_sensor.value() * 1e-6 if self.chk_dual_opt_tau.isChecked() else 0.0

    def measure_sensor_tau(self):
        '''Preenche o τ do sensor comparando a varredura em frequência atual com outra já salva, feita com a
        mesma luz e outro resistor de realimentação (fit_sensor_tau).'''
        if self.dual_active or self.dual_kind != 'F' or not self.dual_results:
            self.flash('Medir τ do sensor: rode antes uma varredura em frequência do Modo Duplo com o resistor atual.', 6.0)
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Varredura de referência (mesma luz, outro resistor)', MEDIDAS_DIR, 'Modo Duplo em frequência (*DUPLO_freq_*.csv)')
        if not path:
            return
        try:
            with open(path, encoding='utf-8') as fh:
                rows = [ln.strip().split(',') for ln in fh if ln.strip() and not ln.startswith('#')]
            head, data = rows[0], np.array([[float(v) for v in r] for r in rows[1:]])
            col = {name: data[:, head.index(name)] for name in
                   ('Frequencia_Hz', 'OPT101_R', 'OPT101_Fase_Graus', 'OPT101_Fase_DP')}
        except (OSError, ValueError, IndexError):
            self.flash(f'Medir τ do sensor: arquivo inválido ({os.path.basename(path)}).', 6.0)
            return
        x, ro, _, _, _, _, _, po, po_e = self._dual_arrays()
        res = fit_sensor_tau(x, po, po_e, ro, col['Frequencia_Hz'], col['OPT101_Fase_Graus'],
                             col['OPT101_Fase_DP'], col['OPT101_R'])
        if res is None:
            self.flash('Medir τ do sensor: menos de 4 frequências em comum, ou o ajuste não convergiu.', 6.0)
            return
        self.dual_sensor_fit_txt = f'{res["text"]} — referência: {os.path.basename(path)}'
        if res['tau'] is not None:
            self.chk_dual_opt_tau.setChecked(True)
            self._set_spin(self.sp_dual_tau_sensor, res['tau'] * 1e6)
        self._show_dual_results()

    def _export_dual(self, resave=False):
        '''Grava CSV + PNG da varredura do Modo Duplo. resave=True ("Salvar de novo"): arquivos novos com
        sufixo _editado, com o ajuste, as exclusões e a calibração atuais; o original nunca é sobrescrito.'''
        if not self.dual_results:
            return
        q = self.dual_params
        now_dt = datetime.now()
        v = q['values']
        if q['kind'] == 'P':
            stem = self._stem(f"DUPLO_casada_pwm{v[0]:g}_{v[-1]:g}_f{q['freq']:g}Hz_{now_dt.strftime('%Y%m%d_%H%M%S')}")
            what = f"Varredura casada em PWM {v[0]:g} a {v[-1]:g} % ({len(v)} pontos), modulação {q['freq']:g} Hz"
            col = 'PWM_Pct'
        else:
            stem = self._stem(f"DUPLO_freq_{v[0]:g}_{v[-1]:g}Hz_pwm{q['pwm']:g}_{now_dt.strftime('%Y%m%d_%H%M%S')}")
            what = f"Varredura em frequência {v[0]:g} a {v[-1]:g} Hz ({len(v)} pontos), PWM {q['pwm']:g} %"
            col = 'Frequencia_Hz'
        if resave:
            orig = getattr(self, 'dual_last_csv', None)
            if orig:
                # herda o nome do original (amostra incluída), sem acumular sufixos em edições sucessivas
                base = re.sub(r'_editado(_\d{6})?$', '', os.path.splitext(os.path.basename(orig))[0])
                stem = f"{base}_editado_{now_dt.strftime('%H%M%S')}"
            else:
                stem += '_editado'
        os.makedirs(MEDIDAS_DIR, exist_ok=True)
        csv_path = os.path.join(MEDIDAS_DIR, stem + '.csv')
        tau = f"tau = {q['tau']:g} s (integração longa)" if q['tau'] else 'tau dos filtros dos lock-ins'
        try:
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                f.write(f"# Modo Duplo - {now_dt.strftime('%Y-%m-%d %H:%M:%S')}\n# {what}\n"
                        f"# Medida: {q['mode']}; {tau}\n")
                if resave and getattr(self, 'dual_last_csv', None):
                    f.write(f'# Versão editada ("Salvar de novo") de: {os.path.basename(self.dual_last_csv)}\n')
                if q['kind'] == 'F':
                    if self.dual_opt_tau is not None:
                        f.write(f"# {self._plain(self.dual_opt_tau['text'])}\n")
                    f.write(f"# OPT101: tau do sensor descontado em S e no gráfico = {self.dual_tau_sensor * 1e6:.3g} us "
                            f"(os dados abaixo são brutos)\n")
                if self.dual_fit:
                    f.write(f'# {self.dual_fit}\n')
                if q['kind'] == 'F' and self.dual_model_txt:
                    f.write(f'# Ajuste com modelo: {self.dual_model_txt}\n')
                if self.dual_excluded:
                    f.write(f'# Pontos excluídos do ajuste com clique ({col}): '
                            + ', '.join(f'{self.dual_results[i][0]:g}' for i in sorted(self.dual_excluded))
                            + ' (continuam nos dados abaixo)\n')
                if self.dual_cal is not None:
                    f.write(f"# Arquivo de calibração do microfone: {os.path.basename(self.dual_cal['path'])} "
                            f"(aplicada no gráfico/fit; os dados abaixo são brutos)\n")
                f.write(f'{col},OPT101_R,OPT101_R_DP,INMP441_R,INMP441_R_DP,INMP441_Fase_Graus,'
                        'INMP441_Fase_DP,OPT101_Fase_Graus,OPT101_Fase_DP\n')
                for row in self.dual_results:
                    f.write(f'{row[0]:.3f},{row[1]:.6g},{row[2]:.4g},{row[3]:.6g},{row[4]:.4g},'
                            f'{row[5]:.3f},{row[6]:.3f},{row[7]:.3f},{row[8]:.3f}\n')
            self.dual_plots.grab().save(os.path.join(MEDIDAS_DIR, stem + '.png'))
            self._session_add(csv_path, os.path.join(MEDIDAS_DIR, stem + '.png'))
            if self.dual_cal is not None:
                self._session_add(*self._calibration_files(self.dual_cal['path']))
            if resave:
                self.flash(f'Varredura do Modo Duplo salva de novo: {csv_path}', 6.0)
                self.lbl_dual_status.setText(f'Salva de novo: {csv_path}')
            else:
                self.dual_last_csv = csv_path
                self.flash(f'Varredura do Modo Duplo concluída: {csv_path}', 6.0)
                self.lbl_dual_status.setText(f'Concluída: {csv_path}')
        except Exception as e:
            print(f'Erro ao salvar a varredura do Modo Duplo: {e}')

    @staticmethod
    def _plain(html):
        '''Texto de um rótulo rich text em uma linha (cabeçalho de CSV).'''
        return re.sub(r'<[^>]+>', '', html.replace('<br>', '; ')).replace('&nbsp;', ' ')

    @staticmethod
    def _group(title):
        box = QtWidgets.QGroupBox(title)
        box.setStyleSheet('QGroupBox{font-weight:bold;border:1px solid #999;border-radius:4px;'
                          'margin-top:8px;padding-top:6px;}'
                          'QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}')
        return box

    def _dspin(self, lo, hi, val, dec, step, slot, width=90, suffix=''):
        sb = QtWidgets.QDoubleSpinBox()
        sb.setRange(lo, hi)
        if suffix:
            sb.setSuffix(suffix)
        sb.setDecimals(dec)
        sb.setSingleStep(step)
        sb.setValue(val)
        sb.setKeyboardTracking(False)   # só dispara ao confirmar (Enter/perder foco)
        sb.setFixedWidth(width)
        if slot is not None:
            sb.valueChanged.connect(slot)
        return sb

    @staticmethod
    def _set_spin(sb, v):
        sb.blockSignals(True)
        sb.setValue(v)
        sb.blockSignals(False)

    def _make_sweep_box(self, title, fields, on_click, extra=()):
        '''Quadro de varredura padrão (mesmo em todas as abas): campos na 1ª linha (e os de 'extra'
        numa linha própria); botão, tempo e barra de progresso na última. Retorna (quadro, botão,
        rótulo do tempo, barra).'''
        box = self._group(title)
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(6, 2, 6, 4)
        lay.setSpacing(3)
        for row_fields in (fields, extra):
            if not row_fields:
                continue
            row1 = QtWidgets.QHBoxLayout()
            for label, w in row_fields:
                if isinstance(label, QtWidgets.QWidget):
                    row1.addWidget(label)
                elif label:
                    row1.addWidget(QtWidgets.QLabel(label))
                row1.addWidget(w)
            row1.addStretch(1)
            lay.addLayout(row1)
        row2 = QtWidgets.QHBoxLayout()
        btn = QtWidgets.QPushButton('▶ Varredura')
        btn.setStyleSheet('background:#cfe2ff;')
        btn.setMinimumWidth(110)
        btn.clicked.connect(on_click)
        row2.addWidget(btn)
        eta = QtWidgets.QLabel('Tempo estimado: --:--')
        eta.setMinimumWidth(160)
        eta.setStyleSheet('font-family:Consolas,monospace;')
        row2.addWidget(eta)
        bar = QtWidgets.QProgressBar()
        bar.setRange(0, 1000)
        bar.setTextVisible(False)
        bar.setFixedHeight(12)
        bar.setVisible(False)
        row2.addWidget(bar, 3)
        row2.addStretch(1)
        lay.addLayout(row2)
        return box, btn, eta, bar

    def set_display_mode(self, average):
        '''Botões Lock-In / Valor Médio da aba OPT101.'''
        if average != self.average_mode:
            self.toggle_display_mode()
        (self.btn_mode_avg if self.average_mode else self.btn_mode_li).setChecked(True)

    def on_audio_sweeps_panel(self, checked):
        self.audio_sweeps_panel.setVisible(checked)
        self.btn_audio_sweeps.setText('Varreduras ▾' if checked else 'Varreduras ▸')

    def on_dual_sweeps_panel(self, checked):
        '''Painel "Executar varreduras" do Modo Duplo (quadros das varreduras casada e em frequência).'''
        self.dual_sweeps_panel.setVisible(checked)
        self.btn_dual_sweeps_panel.setText('Executar varreduras ' + ('▾' if checked else '▸'))

    def open_dual_sweep(self):
        '''Carrega um CSV do Modo Duplo salvo e o exibe como se a varredura tivesse acabado de rodar.'''
        if self.dual_active or self.sweep_active:
            self.flash('Termine ou cancele a varredura em andamento antes de abrir outra.')
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Abrir varredura do Modo Duplo', MEDIDAS_DIR,
            'Varreduras do Modo Duplo (*DUPLO*.csv);;Todos os CSV (*.csv)')
        if path:
            self.load_dual_sweep(path)

    def load_dual_sweep(self, path):
        try:
            kind, rows, params = load_dual_csv(path)
        except (OSError, ValueError, IndexError) as e:
            QtWidgets.QMessageBox.warning(self, 'Abrir varredura', f'Não foi possível abrir {os.path.basename(path)}:\n{e}')
            return
        self.dual_kind = kind
        self.dual_results = rows
        self.dual_params = params
        self.dual_excluded = set()
        self.dual_ref_cfg = []          # cortes do OPT101 em cada ponto não ficam no CSV: sem diagnóstico do τ óptico
        self.dual_fit = None
        self.dual_last_csv = path
        self._setup_dual_plots(kind)
        self._show_dual_results()
        self.btn_dual_resave.setEnabled(True)
        what = 'em frequência' if kind == 'F' else 'casada em PWM'
        self.lbl_dual_status.setText(f'Varredura aberta ({what}, {len(rows)} pontos): {os.path.basename(path)}')

    def on_dual_model_panel(self, checked):
        '''Painel "Ajuste com modelos" do Modo Duplo; fechado, nenhum modelo é ajustado.'''
        self.dual_model_box.setVisible(checked)
        self.btn_dual_model_panel.setText('Ajuste com modelos ' + ('▾' if checked else '▸'))
        self._show_dual_results()

    def _on_dual_model(self, _=None):
        model = self.cmb_dual_model.currentData()
        self.cmb_dual_model.setToolTip(FREQ_MODEL_TIPS.get(model, 'Escolha um modelo para ajustar à varredura em frequência.'))
        self.cmb_dual_model_target.setEnabled(model not in (None, 'pow', 'pow2'))   # leis de potência: só magnitude
        self._show_dual_results()

    def _fit_dual_model(self, f, s, s_rel, dphi, dphi_e):
        '''Ajusta o modelo escolhido no painel aos pontos da varredura em frequência (já calibrados, se "Usar")
        e desenha as curvas em verde. Recebe só os pontos que entram no ajuste.'''
        self.c_dual_a_model.setData([], [])
        self.c_dual_b_model.setData([], [])
        self.ln_dual_break.setVisible(False)
        self.dual_model_txt = None
        model = self.cmb_dual_model.currentData()
        if not self.btn_dual_model_panel.isChecked() or model is None:
            self.lbl_dual_model.setText('')
            return
        target = 'mag' if model in ('pow', 'pow2') else self.cmb_dual_model_target.currentData()
        lo, hi = self.sp_dual_model_f0.value(), self.sp_dual_model_f1.value()     # 0 = sem limite
        sel = (f >= lo) & ((f <= hi) if hi > 0 else True)
        f, s, s_rel, dphi, dphi_e = f[sel], s[sel], s_rel[sel], dphi[sel], dphi_e[sel]
        need = 5 if model == 'pow2' else 4
        if model == 'pow2':
            r = fit_broken_power(f, s, s_rel) if f.size >= need else None
        else:
            r = fit_freq_model(f, s, s_rel, dphi, dphi_e, model, target) if f.size >= need else None
        if r is None:
            self.lbl_dual_model.setText(f'Ajuste com modelo: são necessários pelo menos {need} pontos válidos.'
                                        if f.size < need else 'Ajuste com modelo: não convergiu.')
            return
        ff = np.geomspace(float(f.min()), float(f.max()), 300)
        z = r['func'](ff)
        if target in ('mag', 'both'):
            self.c_dual_a_model.setData(ff, np.abs(z))
        if target in ('phase', 'both'):
            pz = np.degrees(np.unwrap(np.angle(z)))
            # o modelo é definido a menos de 360°: alinha com a fase desenrolada dos dados
            pz += 360.0 * np.round(np.mean(dphi - np.interp(np.log(f), np.log(ff), pz)) / 360.0)
            self.c_dual_b_model.setData(ff, pz)
        what = {'phase': 'fase', 'mag': 'magnitude', 'both': 'fase e magnitude'}[target]
        parts = [f'<b>{FREQ_MODELS[model]}</b> (ajuste da {what}, {r["n"]} pontos, '
                 f'{f.min():g}–{f.max():g} Hz):']
        if model == 'pow':
            parts.append(f'n = {r["shape"]:.3f} ± {r["shape_err"]:.2g}')
        elif model == 'pow2':
            parts.append(f'n1 = {r["n1"]:.3f} ± {r["n1_err"]:.2g} (abaixo da quebra)')
            parts.append(f'n2 = {r["n2"]:.3f} ± {r["n2_err"]:.2g} (acima)')
            parts.append(f'<b>quebra fb = {r["fb"]:.3g} ± {r["fb_err"]:.2g} Hz</b>')
            self.ln_dual_break.setPos(np.log10(r['fb']))      # eixo X em escala log
            self.ln_dual_break.setVisible(True)
        else:
            f1, e1 = r['shape'], r['shape_err']
            parts.append(f'f1 = α/(πL²) = {f1:.3g} ± {e1:.2g} Hz')
            parts.append(f'L²/α = 1/(π·f1) = {1e3 / (np.pi * f1):.3g} ms')
            L = self.sp_dual_thick.value() * 1e-6
            if L > 0:
                a = np.pi * f1 * L * L
                parts.append(f'<b>α = {a:.3g} ± {a * e1 / f1:.2g} m²/s</b> (L = {L * 1e6:g} µm; '
                             'sem incluir o erro de L, que conta em dobro)')
            else:
                parts.append('informe L para obter α')
        if target in ('mag', 'both'):
            parts.append(f'resíduo rms da magnitude {100 * r["rms_mag"]:.0f} %')
        if target in ('phase', 'both'):
            parts.append(f'resíduo rms da fase {r["rms_phase"]:.1f}°')
        txt = ' &nbsp; '.join(parts)
        if self.dual_cal is None:
            txt += ('<br><span style="color:#d00000;">⚠ Sem calibração aplicada ("Usar" desmarcado): magnitude e fase '
                    'incluem a resposta do microfone/célula e o atraso do sistema.</span>')
        self.lbl_dual_model.setText(f'<span style="color:#2e7d32;">{txt}</span>')
        self.dual_model_txt = self._plain(txt.replace(' &nbsp; ', '; ').replace('<br>', ' '))

    def on_dual_cal_panel(self, checked):
        '''Painel "Calibração de papel alumínio" do Modo Duplo; fechado, o fit do padrão não é aplicado.'''
        self.dual_cal_box.setVisible(checked)
        self.btn_dual_cal_panel.setText('Calibração de papel alumínio ' + ('▾' if checked else '▸'))
        self._show_dual_results()

    def _on_dual_fspace(self, idx):
        '''Logarítmico: número de pontos; Linear: passo em Hz.'''
        log = idx == 0
        self.lbl_dual_fn.setText('N pontos:' if log else 'Passo:')
        self.sp_dual_fn.setSuffix('' if log else ' Hz')
        self.sp_dual_fn.setDecimals(0 if log else 2)

    def flash(self, text, seconds=3.0):
        self.flash_text = text
        self.flash_until = time.perf_counter() + seconds
        # Também na barra de status da janela, para aparecer em qualquer aba
        self.statusBar().showMessage(text, int(seconds * 1000))

    def update_window_status(self):
        '''Barra de status da janela: conexão (à direita) e varredura em andamento em qualquer aba.'''
        if self.link.connected:
            conn = f"<span style='color:#1a7f1a;'>●</span> STM32 conectado ({self.link.port})"
            tip = ''
        elif self.simulating:
            conn = "<span style='color:#1f5fbf;'>●</span> Simulação (sem STM32)"
            tip = ''
        else:
            conn = "<span style='color:#d07000;'>●</span> STM32 desconectado, procurando..."
            tip = self.link.last_error or 'Nenhuma porta do STM32 (USB VID 0x0483) encontrada.'
        task = ''
        if self.sweep_active:
            alvo = 'OPT101' if self.sweep_target == 'OPT' else 'INMP441'
            tipo = 'frequência' if self.sweep_kind == 'F' else 'PWM'
            task = (f'Varredura {alvo} em {tipo}: ponto {self.sweep_idx + 1}/{len(self.sweep_freqs)}, '
                    f'restante {self._fmt_time(self._sweep_remaining(time.perf_counter()))}')
        elif self.dual_active:
            tipo = 'PWM' if self.dual_kind == 'P' else 'frequência'
            task = (f'Modo Duplo em {tipo}: ponto {self.dual_idx + 1}/{len(self.dual_values)}, '
                    f'restante {self._fmt_time(getattr(self, "dual_rest", 0.0))}')
        state = (conn, tip, task)
        if state != self.last_sb_state:
            self.last_sb_state = state
            self.lbl_sb_conn.setText(conn)
            self.lbl_sb_conn.setToolTip(tip)
            self.lbl_sb_task.setText(task)

    # ----------------------------------------------------------- Controles
    def default_pretrigger(self, freq=None):
        '''25% do tempo em que o laser fica ligado (meio período).'''
        return 0.25 * 0.5 / max(freq or self.ref_freq, 0.1)

    def update_avg_ref_line(self):
        pre = self.average_pretrigger_sec
        half = 0.5 / max(self.ref_freq, 0.1)
        end = max(1.0 / max(self.ref_freq, 0.1), half)
        self.line_ref_avg.setData([-pre, 0, 0, half, half, end], [0, 0, 1, 1, 0, 0])

    def set_pretrigger(self, sec):
        self.average_pretrigger_sec = float(sec)
        self.avg.pre = int(round(sec * FS))
        self.lbl_pre.setText(f'Pré: -{sec:.4f} s')

    def apply_frequency(self, val):
        self.ref_freq = val
        self.cutoff_lp, self.cutoff_hp = get_effective_cutoffs(val)
        self.link.write(f"F{val}\n")
        self.update_raw_window()
        with self.dsp_lock:
            self.dsp.update_params(val, self.cutoff_lp, self.cutoff_hp)
        # O lock-in do INMP441 segue a frequência de excitação comum
        with self.audio_lock:
            self.audio_freq = val
            self.audio_cutoff_lp, self.audio_cutoff_hp = self.cutoff_lp, self.cutoff_hp
            self.audio_li.update_params(val, self.audio_cutoff_lp, self.audio_cutoff_hp)
        self._set_spin(self.sp_audio_lp, self.audio_cutoff_lp)
        self._set_spin(self.sp_audio_hp, self.audio_cutoff_hp)
        self._set_spin(self.sp_lp, self.cutoff_lp)
        self._set_spin(self.sp_hp, self.cutoff_hp)
        self.update_tau_labels()
        self.update_audio_fft_range()
        self.update_opt_fft_range()
        if self.average_mode:
            self.set_pretrigger(self.default_pretrigger(val))
            self.reset_average()
            self.update_avg_ref_line()
            self.plot1.getPlotItem().setXRange(-self.average_pretrigger_sec, 1.0 / val, padding=0)

    def on_freq(self, val):
        if not self.sweep_active:
            self.apply_frequency(val)

    def on_power(self, val):
        self.laser_power = val
        self.link.write(f"P{val}\n")

    def on_simulate(self, checked):
        self.simulating = checked
        self.simulator.reset()
        with self.dsp_lock:
            self.rx_bytes.clear()
        with self.audio_lock:
            self.audio_sim.reset()
            self.audio_last_sequence = None
            self.audio_gap_samples = 0
            self.audio_received_samples = 0
            self.audio_valid_samples = 0
            self.audio_write_index = 0
            self.audio_wait_started = time.perf_counter()
            self._audio_reset_lockin()
        self._clear_audio_wave()
        self.curve_audio_fft.setData([], [])

    def on_window(self, val):
        self.user_window = val
        self.update_raw_window()

    def update_raw_window(self):
        '''Janela do osciloscópio: a escolhida pelo usuário, limitada a MAX_SCOPE_CYCLES ciclos
        quando a modulação passa de REDUCED_VIEW_HZ.'''
        reduced = self.ref_freq > REDUCED_VIEW_HZ
        window = MAX_SCOPE_CYCLES / self.ref_freq if reduced else self.user_window
        self._set_spin(self.sp_window, window)
        self.lbl_reduced.setVisible(reduced)
        if reduced:
            self.lbl_reduced.setPos(window / 2.0, 0.6)
        if abs(window - self.raw.window) < 1e-9:
            return
        self.raw.resize(window)
        self.plot_raw.getPlotItem().setXRange(0, self.raw.window, padding=0)
        for c in (self.c_adc_a, self.c_adc_b, self.c_ref_a, self.c_ref_b):
            c.setData([], [])

    def on_mains(self, checked):
        with self.dsp_lock:
            self.dsp.set_mains_filter(checked)

    def on_lp(self, val):
        self.cutoff_lp = val
        with self.dsp_lock:
            self.dsp.update_params(self.ref_freq, self.cutoff_lp, self.cutoff_hp)
        self.update_tau_labels()

    @staticmethod
    def _filter_row(lay, sp_lp, sp_hp):
        '''Passa-baixas, τ (que depende só dele) e passa-altas de um lock-in, com dicas. Devolve o rótulo do τ.'''
        lbl_tau = QtWidgets.QLabel()
        lbl_tau.setMinimumWidth(90)
        for text, w, tip in (('Passa-Baixas (Hz):', sp_lp, LP_TIP), (None, lbl_tau, TAU_TIP),
                             ('Passa-Altas (Hz):', sp_hp, HP_TIP)):
            if text:
                lbl = QtWidgets.QLabel(text)
                lbl.setToolTip(tip)
                lay.addWidget(lbl)
            w.setToolTip(tip)
            lay.addWidget(w)
        return lbl_tau

    def update_tau_labels(self):
        '''Atualiza o tau exibido ao lado dos parâmetros de cada lock-in.'''
        if hasattr(self, 'lbl_tau'):
            self.lbl_tau.setText(fmt_tau(lp_tau(self.cutoff_lp, FS)))
        if hasattr(self, 'lbl_audio_tau'):
            self.lbl_audio_tau.setText(fmt_tau(lp_tau(self.audio_cutoff_lp, AUDIO_FS_REAL)))

    def on_hp(self, val):
        self.cutoff_hp = val
        with self.dsp_lock:
            self.dsp.update_params(self.ref_freq, self.cutoff_lp, self.cutoff_hp)

    def on_pulses(self, val):
        self.avg.pulses = int(val)
        self.reset_average()

    def on_pause(self, checked):
        '''Congela só a exibição do gráfico inferior; aquisição e processamento continuam.'''
        self.paused = checked
        self.update_fit_ui()
        if not checked:
            self.avg_dirty = self.average_mode
            self.lockin_dirty = True

    def update_fit_ui(self):
        enabled = self.paused and self.average_mode
        was = self.fit_box.isEnabled()
        self.fit_box.setEnabled(enabled)
        self.clear_fit()
        if enabled and not was:
            self.reset_fit_region()
            self.init_fit_params()
        for ln in self.fit_lines:
            ln.setVisible(enabled)

    def reset_fit_region(self):
        '''Posiciona as linhas verdes na janela padrão (laser On ou Off).'''
        half = 0.5 / max(self.ref_freq, 0.1)
        lo, hi = (half, 2.0 * half) if self.sw_t0.down else (0.0, half)
        self._region_lock = True
        self.fit_lines[0].setValue(lo)
        self.fit_lines[1].setValue(hi)
        self._region_lock = False

    def on_fit_region_moved(self, *_):
        if self._region_lock or not self.fit_box.isEnabled():
            return
        if self.fit:
            self.fit_current()

    def on_t0_mode(self, *_):
        self.sw_t0.setDown(not self.sw_t0.down)
        if self.fit_box.isEnabled():
            self.reset_fit_region()
            self.init_fit_params()
            self.clear_fit()

    def clear_fit(self):
        self.fit = None
        self.line_fit.setVisible(False)
        self.line_fit.setData([], [])
        enabled = self.fit_box.isEnabled()
        self.fit_hint_row.setVisible(not enabled)
        self.lbl_fit.setText('Sem ajuste.' if enabled else '')

    @staticmethod
    def _exp_model(t, y_inf, a1, tau1, a2=0.0, tau2=1.0):
        out = y_inf + a1 * np.exp(-t / tau1)
        if a2 != 0.0:
            out = out + a2 * np.exp(-t / tau2)
        return out

    def _fit_data(self):
        '''Forma de onda média de t=0 até o fim do pulso do laser.'''
        x, y = self.line_r.getData()
        if x is None or len(x) == 0:
            self.lbl_fit.setText('Não há dados para ajustar.')
            return None
        x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
        half = 0.5 / max(self.ref_freq, 0.1)
        lo, hi = sorted(ln.value() for ln in self.fit_lines)
        m = (x >= lo) & (x <= hi)
        if self.sw_t0.down:
            self._fit_toff = half
            msg = 'Poucos pontos na janela selecionada (laser Off).'
        else:
            self._fit_toff = 0.0
            msg = 'Poucos pontos na janela selecionada (laser On).'
        if np.count_nonzero(m) < 6:
            self.lbl_fit.setText(msg)
            return None
        # Tempo medido desde o início da janela (borda do laser)
        return x[m] - self._fit_toff, y[m]

    def _fit_params(self):
        '''Parâmetros dos campos (τ em ms -> s); modelo de 1 exp zera o 2º termo.'''
        two = self.cmb_fit.currentIndex() == 1
        p = [self.sp_fy.value(), self.sp_fa1.value(), self.sp_ft1.value() * 1e-3]
        if two:
            p += [self.sp_fa2.value(), self.sp_ft2.value() * 1e-3]
        return p

    def _set_fit_params(self, p):
        self._set_spin(self.sp_fy, p[0])
        self._set_spin(self.sp_fa1, p[1])
        self._set_spin(self.sp_ft1, p[2] * 1e3)
        if len(p) > 3:
            self._set_spin(self.sp_fa2, p[3])
            self._set_spin(self.sp_ft2, p[4] * 1e3)

    def on_fit_model(self, idx):
        two = idx == 1
        for w in (self.sp_fa2, self.sp_ft2):
            w.setEnabled(two)
        if self.fit_box.isEnabled():
            self.init_fit_params()
            self.clear_fit()

    def init_fit_params(self):
        '''Estimativa inicial simples a partir dos dados.'''
        d = self._fit_data()
        if d is None:
            return
        t, v = d
        span = max(t[-1] - t[0], 1e-6)
        amp = float(v[0] - v[-1])
        if self.cmb_fit.currentIndex() == 1:
            self._set_fit_params([float(v[-1]), amp * 0.5, span / 10.0, amp * 0.5, span / 2.0])
        else:
            self._set_fit_params([float(v[-1]), amp, span / 3.0])
        self.lbl_fit.setText('Sem ajuste.')

    def _show_fit(self, p, t, v):
        fit_y = self._exp_model(t, *p)
        ss_tot = float(np.sum((v - v.mean()) ** 2))
        r2 = 1.0 - float(np.sum((v - fit_y) ** 2)) / ss_tot if ss_tot > 0 else float('nan')
        off = self._fit_toff
        self.fit = {'p': list(map(float, p)), 'r2': r2, 't0': float(t[0]) + off, 't1': float(t[-1]) + off}
        self.line_fit.setData(t + off, fit_y)
        self.line_fit.setVisible(True)
        txt = f"y∞={p[0]:.2f} | A1={p[1]:.2f} | τ1={p[2] * 1e3:.3f} ms"
        if len(p) > 3:
            txt += f" | A2={p[3]:.2f} | τ2={p[4] * 1e3:.3f} ms"
        self.lbl_fit.setText(txt + f" | R²={r2:.4f}")

    def fit_current(self):
        '''Plota o modelo com os parâmetros atuais dos campos (sem otimizar).'''
        d = self._fit_data()
        if d is not None:
            self._show_fit(self._fit_params(), *d)

    def fit_optimize(self):
        '''Otimiza (mínimos quadrados) partindo dos valores atuais dos campos.'''
        from scipy.optimize import curve_fit
        d = self._fit_data()
        if d is None:
            return
        t, v = d
        p0 = self._fit_params()
        n = len(p0)
        span = max(t[-1] - t[0], 1e-6)
        lo = [-np.inf, -np.inf, span * 1e-4] + ([-np.inf, span * 1e-4] if n > 3 else [])
        hi = [np.inf, np.inf, span * 1e3] + ([np.inf, span * 1e3] if n > 3 else [])
        p0 = [min(max(x, l), h) if np.isfinite(l) or np.isfinite(h) else x
              for x, l, h in zip(p0, lo, hi)]
        # Com 2 termos, A2 = 0 desativaria o termo no modelo; evita zero exato
        if n > 3 and p0[3] == 0.0:
            p0[3] = 1e-6
        try:
            popt, _ = curve_fit(lambda tt, *q: self._exp_model(tt, *q), t, v, p0=p0,
                                bounds=(lo, hi), maxfev=50000)
        except Exception as e:
            self.lbl_fit.setText(f'Falha no ajuste: {e}')
            return
        self._set_fit_params(list(popt))
        self._show_fit(list(popt), t, v)

    def _sample_name(self):
        '''Nome da amostra pronto para nome de arquivo ('' se vazio).'''
        name = self.ed_sample.text().strip()
        return ''.join('_' if c in '\\/:*?"<>|' or ord(c) < 32 else c for c in name).strip(' .')

    def _stem(self, stem):
        '''Nome-base de um arquivo de Medidas, prefixado com o nome da amostra (se houver).'''
        name = self._sample_name()
        return f'{name}_{stem}' if name else stem

    def _session_add(self, *paths):
        '''Registra arquivos salvos nesta sessão (entram no ZIP do "Finalizar experimento").'''
        for p in paths:
            if p not in self.session_files:
                self.session_files.append(p)

    def finish_experiment(self):
        '''Compacta os arquivos da sessão e a calibração em uso em Medidas/<amostra>_<data>.zip.'''
        if self.sweep_active or self.dual_active:
            self.flash('Termine ou cancele a varredura em andamento antes de finalizar o experimento.')
            return
        files = [p for p in self.session_files if os.path.isfile(p)]
        if not files:
            QtWidgets.QMessageBox.information(
                self, 'Finalizar experimento',
                'Nenhum arquivo foi salvo desde o início da sessão (ou desde o último "Finalizar experimento").')
            return
        if self.chk_mic_cal.isChecked() and self.cmb_mic_cal.currentData():
            files += [p for p in self._calibration_files(self.cmb_mic_cal.currentData()) if p not in files]
        now_dt = datetime.now()
        zip_path = os.path.join(MEDIDAS_DIR, f"{self._sample_name() or 'Experimento'}_"
                                             f"{now_dt.strftime('%Y%m%d_%H%M%S')}.zip")
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
                for p in files:
                    z.write(p, os.path.basename(p))
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, 'Finalizar experimento', f'Erro ao criar o ZIP:\n{e}')
            return
        self.session_files.clear()
        names = '\n'.join(os.path.basename(p) for p in files)
        QtWidgets.QMessageBox.information(
            self, 'Experimento finalizado',
            f'{len(files)} arquivo(s) compactado(s) em:\n{zip_path}\n\n{names}\n\n'
            'Os originais continuam na pasta Medidas. Os próximos arquivos salvos começam um novo experimento.')

    def save_view(self):
        '''Salva em Medidas os dados e a figura exibidos no gráfico inferior.'''
        x, y = self.line_r.getData()
        if x is None or len(x) == 0:
            self.flash('Não há dados para salvar.')
            return
        now_dt = datetime.now()
        os.makedirs(MEDIDAS_DIR, exist_ok=True)
        if self.average_mode:
            stem = self._stem(f"ValorMedio_{self.ref_freq:g}Hz_{now_dt.strftime('%Y%m%d_%H%M%S')}")
            header = (f"# Forma de onda media do ADC - {now_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
                      f"# Freq={self.ref_freq} Hz, Pulsos={self.avg.pulses}, "
                      f"Pre={self.average_pretrigger_sec:.5f} s\nTempo_s,ADC_Medio\n")
            rows = [f"{a:.6f},{b:.4f}\n" for a, b in zip(x, y)]
            if self.fit:
                f_ = self.fit
                p = f_['p']
                two = len(p) > 3
                eq = ("y = y_inf + A1*exp(-t/tau1) + A2*exp(-t/tau2)" if two
                      else "y = y_inf + A1*exp(-t/tau1)")
                prm = f"y_inf={p[0]:.6g}, A1={p[1]:.6g}, tau1={p[2]:.6g} s"
                if two:
                    prm += f", A2={p[3]:.6g}, tau2={p[4]:.6g} s"
                header = header.replace(
                    "\nTempo_s,ADC_Medio\n",
                    f"\n# Fit {'biexponencial' if two else 'exponencial'} {eq} em "
                    f"t=[{f_['t0']:.6f}, {f_['t1']:.6f}] s: {prm}, R2={f_['r2']:.6f}\n"
                    "Tempo_s,ADC_Medio,Fit_Exp\n")
                rows = []
                for a, b in zip(x, y):
                    fit_v = (f"{float(self._exp_model(a, *p)):.4f}"
                             if f_['t0'] <= a <= f_['t1'] else '')
                    rows.append(f"{a:.6f},{b:.4f},{fit_v}\n")
        else:
            _, ph = self.line_phase.getData()
            stem = self._stem(f"LockIn_{self.ref_freq:g}Hz_{now_dt.strftime('%Y%m%d_%H%M%S')}")
            header = (f"# Lock-In no tempo - {now_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
                      f"# Freq={self.ref_freq} Hz, LP={self.cutoff_lp} Hz, HP={self.cutoff_hp} Hz\n"
                      "Tempo_s,Magnitude,Fase_Graus\n")
            rows = (f"{a:.6f},{b:.5f},{c:.3f}\n" for a, b, c in zip(x, y, ph))
        csv_path = os.path.join(MEDIDAS_DIR, stem + '.csv')
        png_path = os.path.join(MEDIDAS_DIR, stem + '.png')
        try:
            with open(csv_path, 'w', encoding='utf-8', newline='') as f:
                f.write(header)
                f.writelines(rows)
            self.plot1.grab().save(png_path)
            self._session_add(csv_path, png_path)
            self.flash(f'Gráfico salvo: {csv_path}', 6.0)
        except Exception as e:
            self.flash(f'Erro ao salvar: {e}')

    def reset_average(self):
        self.avg.reset()
        self.avg_dirty = False
        if self.average_mode and not self.paused:
            self.line_r.setData([], [])

    def adjust_pretrigger(self, direction):
        upper = max(0.5, 0.5 / max(self.ref_freq, 0.1))
        self.set_pretrigger(np.clip(self.average_pretrigger_sec + direction * 0.01, 0.0, upper))
        self.reset_average()
        self.update_avg_ref_line()
        self.plot1.getPlotItem().setXRange(-self.average_pretrigger_sec, 1.0 / max(self.ref_freq, 0.1), padding=0)

    def toggle_display_mode(self):
        self.average_mode = not self.average_mode
        self.sw_pause.setChecked(False)
        self.li_group.setVisible(not self.average_mode)
        self.avg_group.setVisible(self.average_mode)
        self.fit_panel.setVisible(self.average_mode)
        (self.btn_mode_avg if self.average_mode else self.btn_mode_li).setChecked(True)
        self.update_fit_ui()
        if self.average_mode:
            self.set_pretrigger(self.default_pretrigger())
        self.reset_average()
        p1 = self.plot1.getPlotItem()
        if self.average_mode:
            self.line_phase.setVisible(False)
            self.line_ref_avg.setVisible(True)
            self.phase_vb.setYRange(-0.05, 1.25, padding=0)
            self.update_avg_ref_line()
            p1.hideAxis('right')
            p1.getAxis('bottom').lockin_time = False
            self.line_r.setData([], [])
            self.line_r.setSymbol(None)
            p1.setLabel('left', 'ADC médio')
            p1.setLabel('bottom', 'Tempo desde o início do pulso (s)')
            p1.setTitle('Forma de Onda Média do ADC')
            p1.setXRange(-self.average_pretrigger_sec, 1.0 / max(self.ref_freq, 0.1), padding=0)
        else:
            self.line_ref_avg.setVisible(False)
            self.line_phase.setVisible(True)
            self.phase_vb.setYRange(-180, 180, padding=0)
            p1.showAxis('right')
            p1.getAxis('bottom').lockin_time = True
            self.line_r.setSymbol('o')
            self.line_r.setSymbolSize(4)
            self.line_r.setSymbolBrush('b')
            self.line_r.setSymbolPen('b')
            p1.setLabel('left', 'Magnitude (u.a.)')
            p1.setLabel('bottom', f'{TimeAxis.base_label} (s)')
            p1.getAxis('bottom')._unit = 's'
            p1.setTitle(None)
            p1.setXRange(-self.lockin_span, 0, padding=0)
            with self.dsp_lock:
                self.dsp.init(FS, self.ref_freq, self.cutoff_lp, self.cutoff_hp)
            self.r_arr = np.empty(0, dtype=np.float32)
            self.phase_arr = np.empty(0, dtype=np.float32)
            self.lockin_dirty = True

    # ------------------------------------------------------------ Varredura
    @staticmethod
    def _times_for_cutoff(cutoff_lp):
        tau = 1.0 / (2.0 * np.pi * cutoff_lp)
        # O LP é de 2 polos em cascata: erro residual = (1 + t/tau)·exp(-t/tau);
        # 9·tau -> ~1e-3 do degrau. Somado a uma folga para a troca de frequência no firmware.
        return max(1.0, 9.0 * tau) + 0.3, max(1.0, 4.0 * tau)

    def _sweep_times(self):
        self.sweep_settle_time, self.sweep_measure_time = self._times_for_cutoff(self.cutoff_lp)

    @staticmethod
    def _planned_range(a, b, step):
        return np.arange(a, b + step * 0.5, step).tolist()

    def _planned_values(self, kind, target='OPT'):
        if target == 'OPT':
            if kind == 'F':
                return self._planned_range(self.sp_f0.value(), self.sp_f1.value(), self.sp_df.value())
            return self._planned_range(self.sp_p0.value(), self.sp_p1.value(), self.sp_dp.value())
        else:
            if kind == 'F':
                return self._planned_range(self.sp_aud_f0.value(), self.sp_aud_f1.value(), self.sp_aud_df.value())
            return self._planned_range(self.sp_aud_p0.value(), self.sp_aud_p1.value(), self.sp_aud_dp.value())

    def _point_time(self, kind, value):
        if kind == 'F':
            return sum(self._times_for_cutoff(get_effective_cutoffs(value)[0]))
        return sum(self._times_for_cutoff(self.cutoff_lp))

    def _set_eta_style(self, running):
        color = '#d00000' if running else '#000000'
        style = f'font-weight:bold;font-family:Consolas,monospace;color:{color};'
        for kind, lbl in self.eta_labels.items():
            lbl.setStyleSheet(style if (running and kind == self.sweep_kind and self.sweep_target == 'OPT') else 'font-family:Consolas,monospace;color:#808080;')
        for kind, lbl in getattr(self, 'eta_labels_aud', {}).items():
            lbl.setStyleSheet(style if (running and kind == self.sweep_kind and self.sweep_target == 'AUDIO') else 'font-family:Consolas,monospace;color:#808080;')

    def update_eta_idle(self, *_):
        if getattr(self, 'sweep_active', False):
            return
        for kind, lbl in self.eta_labels.items():
            total = sum(self._point_time(kind, v) for v in self._planned_values(kind, 'OPT'))
            lbl.setText('Tempo estimado: ' + self._fmt_time(total))
        for kind, lbl in getattr(self, 'eta_labels_aud', {}).items():
            total = sum(self._point_time(kind, v) for v in self._planned_values(kind, 'AUDIO'))
            lbl.setText('Tempo estimado: ' + self._fmt_time(total))

    def _sweep_remaining(self, now):
        elapsed = now - self.sweep_timer
        if self.sweep_state == 'SETTLING':
            rest = (self.sweep_settle_time - elapsed) + self.sweep_measure_time
        else:
            rest = self.sweep_measure_time - elapsed
        rest = max(rest, 0.0)
        for v in self.sweep_freqs[self.sweep_idx + 1:]:
            rest += self._point_time(self.sweep_kind, v)
        return rest

    @staticmethod
    def _fmt_time(sec):
        sec = int(round(max(sec, 0.0)))
        h, rem = divmod(sec, 3600)
        m, s = divmod(rem, 60)
        return f'{h:d}:{m:02d}:{s:02d}' if h else f'{m:02d}:{s:02d}'

    def _clear_sweep_buffers(self):
        self.sweep_chunks_r.clear()
        self.sweep_chunks_p.clear()
        self.sweep_chunks_dc.clear()
        self.sweep_count = 0
        with getattr(self, 'audio_lock', threading.Lock()):
            self.audio_sweep_r = []
            self.audio_sweep_p = []
            self.audio_sweep_count = 0

    def _excitation_snapshot(self):
        '''Frequência e cortes dos dois lock-ins antes de uma varredura em frequência.'''
        return (self.ref_freq, self.cutoff_lp, self.cutoff_hp, self.audio_cutoff_lp, self.audio_cutoff_hp)

    def _restore_excitation(self, snap):
        '''Volta à frequência de antes da varredura (reenvia F ao STM32) e aos cortes de antes:
        apply_frequency sozinho levaria os filtros aos cortes automáticos, perdendo ajustes manuais.'''
        f, lp, hp, alp, ahp = snap
        self._set_spin(self.sp_freq, f)
        self.apply_frequency(f)
        for sp, v in ((self.sp_lp, lp), (self.sp_hp, hp), (self.sp_audio_lp, alp), (self.sp_audio_hp, ahp)):
            sp.setValue(v)

    def _apply_sweep_value(self, value):
        if self.sweep_kind == 'F':
            self._set_spin(self.sp_freq, value)
            self.apply_frequency(value)
        else:
            self._set_spin(self.sp_power, value)
            self.laser_power = value
            self.link.write(f"P{value}\n")

    def toggle_sweep(self, kind='F', target='OPT'):
        if self.average_mode:
            self.flash('A varredura está disponível apenas no Modo Lock-In.')
            return
        if getattr(self, 'dual_active', False):
            self.flash('A varredura casada (Modo Duplo) está em andamento.')
            return
        if getattr(self, 'sweep_active', False) and (self.sweep_kind != kind or self.sweep_target != target):
            self.flash('Já existe uma varredura em andamento.')
            return

        if not getattr(self, 'sweep_active', False):
            values = self._planned_values(kind, target)
            if not values:
                return
            self.sweep_kind = kind
            self.sweep_target = target
            self.sweep_freqs = values
            self.sweep_results = []
            
            f_start = self.sp_f0.value() if target == 'OPT' else self.sp_aud_f0.value()
            f_stop  = self.sp_f1.value() if target == 'OPT' else self.sp_aud_f1.value()
            f_step  = self.sp_df.value() if target == 'OPT' else self.sp_aud_df.value()
            if kind == 'P':
                f_start = self.sp_p0.value() if target == 'OPT' else self.sp_aud_p0.value()
                f_stop  = self.sp_p1.value() if target == 'OPT' else self.sp_aud_p1.value()
                f_step  = self.sp_dp.value() if target == 'OPT' else self.sp_aud_dp.value()

            if kind == 'F':
                self.sweep_params = {'kind': 'F', 'f_start': f_start, 'f_stop': f_stop, 'f_step': f_step,
                                     'target': target, 'normalize_mode': self.normalize_mode}
            else:
                self.sweep_params = {'kind': 'P', 'f_start': f_start, 'f_stop': f_stop, 'f_step': f_step,
                                     'target': target, 'freq': self.ref_freq, 'normalize_mode': self.normalize_mode}
            self.sweep_idx = 0
            self.sweep_restore = self._excitation_snapshot() if kind == 'F' else None
            self.sweep_active = True
            self.sweep_state = 'SETTLING'
            
            for btn in self.btn_sweeps.values(): btn.setEnabled(False)
            for btn in getattr(self, 'btn_sweeps_aud', {}).values(): btn.setEnabled(False)
            
            btn = self.btn_sweeps[kind] if target == 'OPT' else self.btn_sweeps_aud[kind]
            btn.setEnabled(True)
            btn.setText('⏹ Cancelar')
            btn.setStyleSheet('background:#f8d7da;')

            self.sp_freq.setEnabled(False)
            if kind == 'P': self.sp_power.setEnabled(False)

            self._apply_sweep_value(values[0])
            self._sweep_times()
            self.sweep_timer = time.perf_counter()
            self._clear_sweep_buffers()
            
            lbl = self.eta_labels[kind] if target == 'OPT' else self.eta_labels_aud[kind]
            self.sweep_total_time = max(self._sweep_remaining(self.sweep_timer), 1e-6)
            lbl.setText('Restante: ' + self._fmt_time(self.sweep_total_time))
            bar = self.sweep_bars[(target, kind)]
            bar.setValue(0)
            bar.setVisible(True)
            self._set_eta_style(True)
        elif kind == self.sweep_kind and target == self.sweep_target:
            self._end_sweep_ui()
            self.flash('Varredura cancelada pelo usuário.')

    def _end_sweep_ui(self):
        self.sweep_active = False
        self.sweep_state = 'IDLE'
        for btn in self.btn_sweeps.values():
            btn.setText('▶ Varredura')
            btn.setStyleSheet('background:#cfe2ff;')
            btn.setEnabled(True)
        for btn in getattr(self, 'btn_sweeps_aud', {}).values():
            btn.setText('▶ Varredura')
            btn.setStyleSheet('background:#cfe2ff;')
            btn.setEnabled(True)
        self.sp_freq.setEnabled(True)
        self.sp_power.setEnabled(True)
        if getattr(self, 'sweep_restore', None) is not None:     # varredura em frequência: volta ao início
            self._restore_excitation(self.sweep_restore)
            self.sweep_restore = None
        for bar in self.sweep_bars.values():
            bar.setVisible(False)
        self._set_eta_style(False)
        self.update_eta_idle()

    def sweep_step(self, now):
        v_curr = self.sweep_freqs[self.sweep_idx]
        elapsed = now - self.sweep_timer
        lbl = self.eta_labels[self.sweep_kind] if getattr(self, 'sweep_target', 'OPT') == 'OPT' else self.eta_labels_aud[self.sweep_kind]
        rem = self._sweep_remaining(now)
        lbl.setText('Restante: ' + self._fmt_time(rem))
        self.sweep_bars[(self.sweep_target, self.sweep_kind)].setValue(
            int(1000 * min(1.0, max(0.0, 1.0 - rem / self.sweep_total_time))))
        total = len(self.sweep_freqs)
        target = getattr(self, 'sweep_target', 'OPT')
        target_nome = "OPT101" if target == 'OPT' else "INMP441"
        
        if self.sweep_kind == 'F':
            head = f"Varredura {target_nome} [{self.sweep_idx + 1}/{total}] Freq: {v_curr:.2f} Hz"
        else:
            head = f"Varredura {target_nome} [{self.sweep_idx + 1}/{total}] PWM: {v_curr:.1f} %"
            
        if self.sweep_state == 'SETTLING':
            self.sweep_status_text = f"{head} | Estabilizando ({elapsed:.1f}/{self.sweep_settle_time:.1f}s)..."
            if elapsed >= self.sweep_settle_time:
                self.sweep_state = 'MEASURING'
                self.sweep_timer = now
                self._clear_sweep_buffers()
        elif self.sweep_state == 'MEASURING':
            if target == 'OPT':
                count = self.sweep_count
            else:
                with self.audio_lock: count = self.audio_sweep_count
            self.sweep_status_text = f"{head} | Medindo ({count} amostras)..."
            
            if elapsed >= self.sweep_measure_time:
                if target == 'OPT':
                    if self.sweep_count > 0:
                        r = np.concatenate(self.sweep_chunks_r)
                        p = np.concatenate(self.sweep_chunks_p)
                        dc = np.concatenate(self.sweep_chunks_dc)
                        self.sweep_results.append((v_curr, float(r.mean()), float(r.std()),
                                                   *circ_stats_deg(p), float(dc.mean())))
                else:
                    with self.audio_lock:
                        if self.audio_sweep_count > 0:
                            r = np.concatenate(self.audio_sweep_r)
                            p = np.concatenate(self.audio_sweep_p)
                            self.sweep_results.append((v_curr, float(r.mean()), float(r.std()),
                                                       *circ_stats_deg(p), 0.0))
                self.sweep_idx += 1
                if self.sweep_idx < total:
                    self._apply_sweep_value(self.sweep_freqs[self.sweep_idx])
                    self.sweep_state = 'SETTLING'
                    self.sweep_timer = now
                    self._sweep_times()
                    self._clear_sweep_buffers()
                else:
                    self.finish_and_export_sweep()

    def finish_and_export_sweep(self):
        self._end_sweep_ui()
        if not self.sweep_results: return

        now_dt = datetime.now()
        now_str = now_dt.strftime("%Y%m%d_%H%M%S")
        kind = self.sweep_params.get('kind', 'F')
        target = getattr(self, 'sweep_target', 'OPT')
        target_str = "OPT101" if target == 'OPT' else "INMP441"
        
        f0, f1, df = self.sweep_params.get('f_start', 1.0), self.sweep_params.get('f_stop', 60.0), self.sweep_params.get('f_step', 1.0)
        is_norm = self.sweep_params.get('normalize_mode', False)
        mode_str = "Normalizado (R/DC %)" if (is_norm and target == 'OPT') else "Bruto (u.a.)"
        
        if kind == 'F':
            stem = self._stem(f"{target_str}_F_varredura_f{f0:g}_f{f1:g}_{df:g}_{now_str}")
            title = f"Varredura em Frequencia - {target_str}"
            params = f"F_Start={f0} Hz, F_Stop={f1} Hz, F_Step={df} Hz"
            col, fmt = "Frequencia_Hz", "{:.3f}"
        else:
            fm = self.sweep_params.get('freq', self.ref_freq)
            stem = self._stem(f"{target_str}_P_varredura_p{f0:g}_p{f1:g}_{df:g}_f{fm:g}Hz_{now_str}")
            title = f"Varredura em PWM - {target_str}"
            params = f"P_Start={f0} %, P_Stop={f1} %, P_Step={df} %, Freq={fm} Hz"
            col, fmt = "PWM_Pct", "{:.2f}"
            
        os.makedirs(MEDIDAS_DIR, exist_ok=True)
        filename = os.path.join(MEDIDAS_DIR, stem + ".csv")
        png_filename = os.path.join(MEDIDAS_DIR, stem + ".png")

        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                f.write(f"# {title} - Lock-In TL-Arduino\n# Data/Hora: {now_dt.strftime('%Y-%m-%d %H:%M:%S')}\n# Parametros: {params}\n# Modo: {mode_str}\n")
                f.write(f"{col},Magnitude_Media,Magnitude_DesvioPadrao,Fase_Media_Graus,Fase_DesvioPadrao_Graus,DC_Offset_Medio\n")
                for row in self.sweep_results:
                    f.write(f"{fmt.format(row[0])},{row[1]:.5f},{row[2]:.5f},{row[3]:.3f},{row[4]:.3f},{row[5]:.2f}\n")
            self._session_add(filename)
            print(f"Varredura concluída! Dados em: {filename}")
        except Exception as e:
            print(f"Erro ao salvar arquivo CSV: {e}")

        self.show_sweep_results(kind, f0, f1, df, mode_str, filename, png_filename, target_str)
        self.flash(f'Varredura concluída: {filename}', 6.0)

    def show_sweep_results(self, kind, f0, f1, df, mode_str, filename, png_filename, target_str='OPT101'):
        res = np.array(self.sweep_results, dtype=float)
        freqs, mag, mag_err, ph, ph_err = res[:, 0], res[:, 1], res[:, 2], res[:, 3], res[:, 4]

        win = QtWidgets.QWidget()
        what = 'Frequência' if kind == 'F' else 'PWM'
        win.setWindowTitle(f"Resposta em {what} ({target_str}) - {filename}")
        lay = QtWidgets.QVBoxLayout(win)
        
        # --- Controles de Escala Logarítmica ---
        ctrl_lay = QtWidgets.QHBoxLayout()
        chk_log_x = QtWidgets.QCheckBox(f"Eixo X ({what}) em Escala Logarítmica")
        chk_log_y = QtWidgets.QCheckBox("Eixo Y (Amplitude) em Escala Logarítmica")
        ctrl_lay.addWidget(chk_log_x)
        ctrl_lay.addWidget(chk_log_y)
        ctrl_lay.addSpacing(16)
        ctrl_lay.addWidget(QtWidgets.QLabel('Fit:'))
        cmb_fit = QtWidgets.QComboBox()
        cmb_fit.addItems(['Lei de potência (A·xⁿ)', 'Linear (a + b·x)', 'Sem fit'])
        cmb_fit.setToolTip('Lei de potência: reta em log-log (n = -1 para 1/f). Ajustada nos dados, independe da escala.\n'
                           'Linear: reta nos eixos lineares.')
        cmb_fit.setCurrentIndex(0 if kind == 'F' else 1)
        ctrl_lay.addWidget(cmb_fit)
        lbl_fit = QtWidgets.QLabel('')
        lbl_fit.setTextFormat(QtCore.Qt.TextFormat.RichText)
        ctrl_lay.addSpacing(8)
        ctrl_lay.addWidget(lbl_fit)
        ctrl_lay.addStretch(1)
        lay.addLayout(ctrl_lay)
        # ----------------------------------------

        pw_r, pw_p = pg.PlotWidget(), pg.PlotWidget()
        lay.addWidget(pw_r)
        lay.addWidget(pw_p)
        pw_p.setXLink(pw_r)
        beam = max(df * 0.15, 1e-6)

        if kind == 'F': 
            pw_r.setTitle(f"Resposta em Frequência ({f0:g} a {f1:g} Hz, passo {df:g} Hz) - {target_str}")
        else:
            fm = self.sweep_params.get('freq', self.ref_freq)
            pw_r.setTitle(f"Resposta em PWM ({f0:g} a {f1:g} %, passo {df:g} %, modulação {fm:g} Hz) - {target_str}")
        
        pw_r.setLabel('left', f"Magnitude ({mode_str})")
        pw_r.showGrid(x=True, y=True, alpha=0.3)
        
        # Plotagem base das curvas e barras de erro
        pw_r.plot(freqs, mag, pen=pg.mkPen('royalblue', width=1.5), symbol='o', symbolSize=6, symbolBrush='royalblue', symbolPen='royalblue')
        err_r = pg.ErrorBarItem(x=freqs, y=mag, height=2 * mag_err, beam=beam, pen=pg.mkPen((120, 120, 120), width=1.5))
        pw_r.addItem(err_r)

        # Curva do fit (tracejada laranja); o resultado fica ao lado da escolha do modelo
        fit_curve = pw_r.plot([], [], pen=pg.mkPen('#e67e22', width=2, style=QtCore.Qt.PenStyle.DashLine))

        def update_fit():
            model = {0: 'pow', 1: 'lin'}.get(cmb_fit.currentIndex())
            res = fit_sweep(freqs, mag, model) if model else None
            if res is None:
                fit_curve.setData([], [])
                lbl_fit.setText('')
                return
            func, text = res
            lo, hi = float(freqs.min()), float(freqs.max())
            xx = (np.geomspace(max(lo, 1e-9), hi, 300) if model == 'pow' and hi > 0
                  else np.linspace(lo, hi, 300))
            fit_curve.setData(xx, func(xx))
            lbl_fit.setText(f'<span style="color:#b35c00;">{text.replace("<br>", " &nbsp; ")}</span>')

        cmb_fit.currentIndexChanged.connect(update_fit)
        update_fit()

        pw_p.setLabel('left', 'Fase (Graus)')
        pw_p.setLabel('bottom', 'Frequência do Laser (Hz)' if kind == 'F' else 'PWM do Laser (%)')
        pw_p.showGrid(x=True, y=True, alpha=0.3)
        pw_p.plot(freqs, ph, pen=pg.mkPen('firebrick', width=1.5), symbol='s', symbolSize=6, symbolBrush='firebrick', symbolPen='firebrick')
        err_p = pg.ErrorBarItem(x=freqs, y=ph, height=2 * ph_err, beam=beam, pen=pg.mkPen((120, 120, 120), width=1.5))
        pw_p.addItem(err_p)

        # --- Lógica Dinâmica (+10% e Escala) ---
        def update_bounds():
            log_x = chk_log_x.isChecked()
            log_y = chk_log_y.isChecked()
            
            # Quando a escala é logarítmica, desconsideramos os valores em zero
            valid_x = freqs > 0 if log_x else np.ones_like(freqs, dtype=bool)
            valid_y = mag > 0 if log_y else np.ones_like(mag, dtype=bool)
            valid = valid_x & valid_y
            
            if not np.any(valid):
                return
                
            # O PyQtGraph ajusta os grids usando log10 da matriz de dados original
            fx = np.log10(freqs[valid]) if log_x else freqs[valid]
            fy = np.log10(mag[valid]) if log_y else mag[valid]
            
            xm_min, xm_max = fx.min(), fx.max()
            ym_min, ym_max = fy.min(), fy.max()
            
            # Margem de 10% aplicada aos limites do que estiver ativo no momento
            x_marg = (xm_max - xm_min) * 0.1 if xm_max > xm_min else max(abs(xm_min) * 0.1, 1e-3)
            y_marg = (ym_max - ym_min) * 0.1 if ym_max > ym_min else max(abs(ym_min) * 0.1, 1e-3)
            
            # Setar os métodos nativos (isso manipula os rótulos do eixo pra formato científico apropriado)
            pw_r.setLogMode(x=log_x, y=log_y)
            pw_p.setLogMode(x=log_x, y=False)
            
            # Esconde ErrorBars se logMode estiver ON (pyqtgraph tem comportamentos instáveis desenhando error bars em eixos log)
            err_r.setVisible(not log_x and not log_y)
            err_p.setVisible(not log_x)
            
            # Ajuste cravado de +10% de preenchimento
            pw_r.setXRange(xm_min - x_marg, xm_max + x_marg, padding=0)
            pw_r.setYRange(ym_min - y_marg, ym_max + y_marg, padding=0)
            
            pw_p.setXRange(xm_min - x_marg, xm_max + x_marg, padding=0)
            pw_p.setYRange(-180, 180, padding=0) # Fixando fase para ocupar altura de -180 a 180

        chk_log_x.toggled.connect(update_bounds)
        chk_log_y.toggled.connect(update_bounds)
        
        # Invoca o cálculo primário assim que cria a janela
        update_bounds()
        # ----------------------------------------

        win.resize(900, 650)
        win.show()
        QtWidgets.QApplication.processEvents()
        try:
            win.grab().save(png_filename)
            self._session_add(png_filename)
        except Exception as e:
            print(f"Erro ao salvar imagem PNG: {e}")
        self.result_windows.append(win)

    # ------------------------------------------------------------ Laço GUI
    def _optical_step(self):
        '''Thread do OPT101: consome os bytes da serial, roda o lock-in e enfileira o lote.'''
        data = self.link.take_optical()
        with self.dsp_lock:
            if data:
                self.rx_bytes.extend(data)
                if len(self.rx_bytes) > MAX_RX_BYTES:
                    del self.rx_bytes[:-MAX_RX_BYTES]
            if len(self.rx_bytes) < 5:
                return
            res = self.dsp.process(self.rx_bytes, DECIMATION, not self.average_mode, self.normalize_mode)
            if res.consumed > 0:
                del self.rx_bytes[:res.consumed]
        if len(res.adc) or len(res.r):
            self.opt_results.append(res)

    def _audio_step(self):
        '''Thread do INMP441: lock-in de áudio independente do OPT101.'''
        chunks, drops = self.link.take_audio()
        with self.audio_lock:
            if self.simulating and not self.link.connected:
                chunks = chunks + self.audio_sim.generate(time.perf_counter(), self.ref_freq, self.laser_power)
            if chunks or drops:
                self._process_audio(chunks, drops)

    def on_audio_views(self, _=None):
        '''Caixas Lock-In / Ruído-SNR / FFT. O lock-in roda se qualquer um dos dois primeiros estiver ligado.'''
        show_li = self.chk_audio_lockin.isChecked()
        show_noise = self.chk_audio_noise.isChecked()
        use_fft = self.chk_audio_fft.isChecked()
        use_lockin = show_li or show_noise
        with self.audio_lock:
            if use_lockin != self.audio_lockin_enabled:
                self.audio_lockin_enabled = use_lockin
                self._audio_reset_lockin()
            if use_fft != self.audio_fft_enabled:
                self.audio_fft_enabled = use_fft
                self.audio_valid_samples = 0
                self.audio_write_index = 0
            self.audio_dirty = True
        self.plot_audio_wave.setVisible(show_li)
        self.audio_noise_panel.setVisible(show_noise)
        self.audio_fft_panel.setVisible(use_fft)
        self.audio_li_group.setEnabled(use_lockin)
        self.audio_xy_group.setEnabled(show_li)
        self.lbl_audio_noise.setVisible(use_lockin)
        # Com o ruído embaixo, o eixo de tempo (rótulo) fica só no gráfico de baixo
        self.plot_audio_wave.getPlotItem().getAxis('bottom').setLabel('' if show_noise else 'Tempo relativo (s)')
        if not use_lockin:
            self._clear_audio_wave()
        if not use_fft:
            self.curve_audio_fft.setData([], [])

    def on_audio_fft_full(self, checked):
        self.audio_fft_full = checked
        self.last_fft_t = 0.0
        self.update_audio_fft_range()

    def on_audio_fft_fit(self, checked):
        if not checked:
            self.curve_audio_fft_fit.setData([], [])
            self.txt_audio_fft_fit.setVisible(False)
            self.lbl_audio_fft_missing.setVisible(False)
            self.audio_fft_fit_html = None
            self.audio_fft_missing = None
        self.last_fft_t = 0.0

    def update_audio_fft_range(self):
        '''Eixo X da FFT: faixa completa ou região em torno da frequência de referência.'''
        item = self.plot_audio_fft.getPlotItem()
        f = self.audio_freq
        self.audio_fft_ref_line.setPos(f)
        self.audio_fft_ref_line.setVisible(f > 0)
        if self.audio_fft_full or f <= 0:
            item.setXRange(0, AUDIO_FS / 2, padding=0)
            item.setTitle('INMP441 - espectro (FFT)')
        else:
            w = max(0.5 * f, 20.0 / AUDIO_FFT_HISTORY_SEC)
            item.setXRange(max(0.0, f - w), min(AUDIO_FS / 2, f + w), padding=0)
            item.setTitle(f'INMP441 - espectro (FFT) em torno de {f:g} Hz')

    # ------------------------------------------------------------ FFT do ADC do OPT101
    def on_opt_sweeps_panel(self, checked):
        self.opt_sweeps_panel.setVisible(checked)
        self.btn_opt_sweeps.setText('Varreduras ▾' if checked else 'Varreduras ▸')

    def on_opt_fft(self, checked):
        self.opt_fft_enabled = checked
        self.opt_valid_samples = 0
        self.opt_write_index = 0
        self.last_opt_fft_t = 0.0
        self.opt_fft_panel.setVisible(checked)
        # Com a FFT visível ela ocupa a sobra da coluna; sem ela, o espaço vazio fica embaixo
        side = self.side_layout
        side.setStretch(side.indexOf(self.opt_fft_panel), 1 if checked else 0)
        side.setStretch(side.count() - 1, 0 if checked else 1)
        if not checked:
            self.curve_opt_fft.setData([], [])
            self.curve_opt_fft_fit.setData([], [])
            self.txt_opt_fft_fit.setVisible(False)
            self.lbl_opt_fft_missing.setVisible(False)
            self.opt_fft_fit_html = None
            self.opt_fft_missing = None

    def on_opt_fft_full(self, checked):
        self.opt_fft_full = checked
        self.last_opt_fft_t = 0.0
        self.update_opt_fft_range()

    def on_opt_fft_fit(self, checked):
        if not checked:
            self.curve_opt_fft_fit.setData([], [])
            self.txt_opt_fft_fit.setVisible(False)
            self.lbl_opt_fft_missing.setVisible(False)
            self.opt_fft_fit_html = None
            self.opt_fft_missing = None
        self.last_opt_fft_t = 0.0

    def update_opt_fft_range(self):
        '''Eixo X da FFT do OPT101: faixa completa ou região em torno da frequência de referência.'''
        item = self.plot_opt_fft.getPlotItem()
        f = self.ref_freq
        self.opt_fft_ref_line.setPos(f)
        self.opt_fft_ref_line.setVisible(f > 0)
        if self.opt_fft_full or f <= 0:
            item.setXRange(0, FS / 2, padding=0)
            item.setTitle('OPT101 - espectro do ADC (FFT)')
        else:
            w = max(0.5 * f, 20.0 / OPT_FFT_HISTORY_SEC)
            item.setXRange(max(0.0, f - w), min(FS / 2, f + w), padding=0)
            item.setTitle(f'OPT101 - espectro do ADC (FFT) em torno de {f:g} Hz')

    def _store_opt_samples(self, values):
        capacity = len(self.opt_history)
        if len(values) >= capacity:
            self.opt_history[:] = values[-capacity:]
            self.opt_write_index = 0
            self.opt_valid_samples = capacity
            return
        first = min(len(values), capacity - self.opt_write_index)
        self.opt_history[self.opt_write_index:self.opt_write_index + first] = values[:first]
        rest = len(values) - first
        if rest:
            self.opt_history[:rest] = values[first:]
        self.opt_write_index = (self.opt_write_index + len(values)) % capacity
        self.opt_valid_samples = min(capacity, self.opt_valid_samples + len(values))

    def _update_opt_fft(self, now):
        if not (self.opt_fft_enabled and self.plot_opt_fft.isVisible()
                and self.opt_valid_samples >= OPT_FFT_SIZE and now - self.last_opt_fft_t >= AUDIO_FFT_INTERVAL):
            return
        self.last_opt_fft_t = now
        # Com zoom usa todo o histórico disponível (resolução fina perto da referência)
        n = OPT_FFT_SIZE if self.opt_fft_full else self.opt_valid_samples
        idx = (self.opt_write_index - n + np.arange(n)) % len(self.opt_history)
        x = self.opt_history[idx].astype(np.float64) / ADC_FULL_SCALE
        window = np.hanning(n)
        spectrum = np.abs(np.fft.rfft(x * window)) / window.sum()
        spectrum[1:-1] *= 2.0
        frequency = np.fft.rfftfreq(n, 1.0 / FS)
        db = 20.0 * np.log10(np.maximum(spectrum, 1e-7))
        self.curve_opt_fft.setData(frequency, db)
        # Escala Y em passos de 10 dB pela faixa exibida (o fundo do ADC varia muito com o ganho do OPT101)
        (x0, x1), _ = self.plot_opt_fft.getPlotItem().vb.viewRange()
        sel = db[(frequency >= x0) & (frequency <= x1)]
        if sel.size:
            hi = 10.0 * np.ceil((float(sel.max()) + 5.0) / 10.0)
            lo = 10.0 * np.floor((float(np.median(sel)) - 20.0) / 10.0)
            self.plot_opt_fft.getPlotItem().setYRange(max(lo, -160.0), min(hi, 10.0), padding=0)
        if self.chk_opt_fft_fit.isChecked():
            self._fit_opt_fft(frequency, spectrum)

    def _fit_opt_fft(self, frequency, spectrum):
        '''Fit em f0 fixo (excitação); o texto vai para a tela a cada 2 s (tick).'''
        self.opt_fft_fit_html, self.opt_fft_missing = self._fit_fft_at(
            frequency, spectrum, self.ref_freq, OPT_FFT_HISTORY_SEC, self.curve_opt_fft_fit,
            lambda amp: f'&nbsp;&nbsp;&nbsp;= {amp * ADC_FULL_SCALE:.1f} contagens do ADC<br>')

    def _fit_fft_at(self, frequency, spectrum, f_ref, history_sec, curve, extra=None):
        '''Fit comum às duas FFTs: amplitude em f0 = frequência real do timer. Desenha a curva e devolve
        (html da caixa do fit, mensagem de pico ausente ou None).'''
        if f_ref <= 0:
            curve.setData([], [])
            return None, None
        f0 = actual_mod_freq(f_ref)
        df = frequency[1] - frequency[0]
        w = max(0.5 * f_ref, 20.0 / history_sec)          # mesma largura da faixa do zoom
        state, amp, floor = fit_hann_at(frequency, spectrum, f0, max(20, int(round(w / df))))
        if state != 'ok':
            curve.setData([], [])
            if state == 'dc':
                why = f'f0 = {f0:.2f} Hz perto do DC nesta resolução (desligue Espectro completo)'
            elif state == 'fora':
                why = f'f0 = {f0:.2f} Hz fora da faixa da FFT'
            else:
                why = f'sinal muito baixo em {f0:.2f} Hz'
            return None, why
        ff = np.linspace(f0 - 2.5 * df, f0 + 2.5 * df, 101)
        curve.setData(ff, 20.0 * np.log10(np.maximum(amp * hann_kernel((ff - f0) / df), 1e-7)))
        html = (f'<span style="color:#1f5fbf;"><b>Fit</b><br>f0 = {f0:.4f} Hz (fixo)<br>'
                f'A = {amp:.3e} FS ({20.0 * np.log10(max(amp, 1e-12)):.1f} dBFS)<br>'
                + (extra(amp) if extra else '') +
                f'SNR pico/piso = {20.0 * np.log10(amp / floor):.1f} dB<br>'
                f'Δf (bin) = {df:.3g} Hz</span>')
        return html, None

    def _make_fft_missing_label(self, item):
        '''Aviso de pico ausente, centralizado em pixels no ViewBox (vale com zoom e espectro completo).'''
        lbl = pg.TextItem(anchor=(0.5, 0.5), fill=pg.mkBrush(255, 255, 255, 200))
        lbl.setParentItem(item.vb)
        lbl.setZValue(100)
        lbl.setVisible(False)

        def center():
            r = item.vb.rect()
            lbl.setPos(r.width() / 2.0, r.height() / 2.0)
        item.vb.sigResized.connect(center)
        center()
        return lbl

    @staticmethod
    def _show_fft_fit(box, missing_lbl, fit_checked, html, missing):
        '''Caixa do fit ou aviso de pico ausente (chamado na cadência de 2 s).'''
        show_missing = fit_checked and missing is not None
        if show_missing:
            missing_lbl.setHtml('<div style="text-align:center;color:#d00000;">'
                                '<span style="font-size:18pt;font-weight:bold;">Pico em f0 não encontrado</span><br>'
                                f'<span style="font-size:11pt;">{missing}</span></div>')
        missing_lbl.setVisible(show_missing)
        fit_on = fit_checked and not show_missing and html is not None
        if fit_on:
            box.setHtml(html)
        box.setVisible(fit_on)

    def on_audio_xy(self, checked):
        '''Alterna o gráfico do lock-in entre R/Fase e X/Y; ao entrar em X/Y aplica a auto-fase.'''
        self.audio_xy = checked
        item = self.plot_audio_wave.getPlotItem()
        if checked:
            item.setTitle('INMP441 - Lock-In (X e Y)')
            item.setLabel('left', 'X, Y (escala completa 24 bits)', color='k')
            item.getAxis('left').setPen('k')
            item.getAxis('left').setTextPen('k')
            item.getAxis('right').setLabel('')
            item.getAxis('right').setStyle(showValues=False)
            item.getAxis('right').setPen(pg.mkPen(0, 0, 0, 0))
        else:
            item.setTitle('INMP441 - Lock-In (Magnitude e Fase)')
            item.setLabel('left', 'Magnitude (escala completa 24 bits)', color='b')
            item.getAxis('left').setPen('b')
            item.getAxis('left').setTextPen('b')
            item.getAxis('right').setLabel('Fase (Graus)', color='r')
            item.getAxis('right').setStyle(showValues=True)
            item.getAxis('right').setPen('r')
            item.getAxis('right').setTextPen('r')
        self.audio_phase_vb.setVisible(not checked)
        self.curve_audio_y.setVisible(checked)
        self.audio_zero_line.setVisible(checked)
        self.audio_wave_legend.setVisible(checked)
        if checked:
            self.audio_auto_phase()
        with self.audio_lock:
            self.audio_dirty = True

    def audio_auto_phase(self):
        '''Offset = fase média (ponderada pela amplitude) do último AUTO_PHASE_SPAN s: o sinal passa para X.'''
        n = max(1, int(round(AUTO_PHASE_SPAN / self.audio_block_sec)))
        with self.audio_lock:
            z = self.audio_z[-n:].copy()
            self.audio_dirty = True
        if z.size == 0 or not np.any(z):
            self.flash('Auto-fase: sem dados do lock-in ainda')
            return
        self.audio_phase_offset = float(np.degrees(np.angle(z.sum())))
        self._set_spin(self.sp_audio_phase_off, self.audio_phase_offset)

    def on_audio_phase_offset(self, val):
        self.audio_phase_offset = float(val)
        with self.audio_lock:
            self.audio_dirty = True

    def on_audio_span(self, val):
        self.audio_span = float(val)
        self.audio_max_points = int(round(self.audio_span / self.audio_block_sec)) + 1
        self.plot_audio_wave.getPlotItem().setXRange(-self.audio_span, 0, padding=0)
        self.plot_audio_noise.getPlotItem().setXRange(-self.audio_span, 0, padding=0)
        self.audio_noise_window = min(self.audio_span, AUDIO_NOISE_SPAN / 2)
        with self.audio_lock:
            self.audio_dirty = True

    def on_audio_snr_alert(self, val):
        self.audio_snr_alert = float(val)
        self.audio_snr_alert_line.setPos(self.audio_snr_alert)

    def _clear_audio_wave(self):
        self.curve_audio_wave.setData([], [])
        self.curve_audio_phase.setData([], [])
        self.curve_audio_y.setData([], [])
        self.curve_audio_snr.setData([], [])
        self.lbl_audio_noise.setText('Ruído/SNR: aguardando dados')
        self.audio_noise_text = None

    def on_audio_lp(self, val):
        self.audio_cutoff_lp = val
        with self.audio_lock:
            self.audio_li.update_params(self.audio_freq, self.audio_cutoff_lp, self.audio_cutoff_hp)
        self.update_tau_labels()

    def on_audio_hp(self, val):
        self.audio_cutoff_hp = val
        with self.audio_lock:
            self.audio_li.update_params(self.audio_freq, self.audio_cutoff_lp, self.audio_cutoff_hp)

    def on_audio_mains(self, checked):
        self.audio_mains = checked
        with self.audio_lock:
            self.audio_li.set_mains_filter(checked)

    def _store_audio_samples(self, samples):
        values = np.asarray(samples, dtype=np.int32)
        capacity = len(self.audio_history)
        if len(values) >= capacity:
            self.audio_history[:] = values[-capacity:]
            self.audio_write_index = 0
            self.audio_valid_samples = capacity
            return

        first = min(len(values), capacity - self.audio_write_index)
        self.audio_history[self.audio_write_index:self.audio_write_index + first] = values[:first]
        rest = len(values) - first
        if rest:
            self.audio_history[:rest] = values[first:]
        self.audio_write_index = (self.audio_write_index + len(values)) % capacity
        self.audio_valid_samples = min(capacity, self.audio_valid_samples + len(values))

    def _process_audio(self, chunks, queue_drops):
        if queue_drops:
            self.audio_queue_drops += queue_drops
        for sequence, samples in chunks:
            if samples is None:
                # Marcador: a onda quadrada do laser (re)começou na amostra 'sequence'
                self.audio_phase_origin = sequence
                self.audio_li.phase_origin = sequence
                continue
            if self.audio_last_sequence is not None:
                gap = (sequence - self.audio_last_sequence) & 0xFFFFFFFF
                if gap:
                    if gap < 0x80000000:
                        self.audio_gap_samples += gap
                    self.audio_valid_samples = 0
                    self.audio_write_index = 0
            self.audio_last_sequence = (sequence + len(samples)) & 0xFFFFFFFF
            if self.audio_fft_enabled:
                self._store_audio_samples(samples)
            if self.audio_lockin_enabled:
                self._audio_lockin(sequence, samples)
            self.audio_received_samples += len(samples)

    def _audio_reset_lockin(self):
        '''Reinicia o lock-in do INMP441 e o histórico plotado (chamar com audio_lock).'''
        self.audio_li = AudioLockIn(AUDIO_FS_REAL, self.audio_freq, self.audio_cutoff_lp, self.audio_cutoff_hp)
        self.audio_li.set_mains_filter(self.audio_mains)
        self.audio_li.phase_origin = getattr(self, 'audio_phase_origin', 0)
        self.audio_z = np.empty(0, dtype=np.complex128)   # saída X + jY, últimos AUDIO_NOISE_SPAN s
        self.audio_snr_db = None
        self.audio_dirty = False

    def _audio_lockin(self, sequence, samples):
        '''Um ponto (R e fase) a cada AUDIO_LOCKIN_BLOCK amostras, com a mesma cadeia do OPT101.'''
        r, ph = self.audio_li.process(sequence, samples, AUDIO_LOCKIN_BLOCK)
        if r.size:
            z = r * np.exp(1j * np.radians(ph))
            self.audio_z = np.append(self.audio_z, z)[-AUDIO_NOISE_POINTS:]
            self.audio_dirty = True
            
            if getattr(self, 'sweep_active', False) and getattr(self, 'sweep_target', 'OPT') == 'AUDIO' and getattr(self, 'sweep_state', 'IDLE') == 'MEASURING':
                self.audio_sweep_r.append(r)
                self.audio_sweep_p.append(ph)
                self.audio_sweep_count += r.size
            if getattr(self, 'dual_state', 'IDLE') == 'MEASURING':
                self.dual_aud.append((r, ph))

    def _update_audio_plots(self, now):
        wave_visible = self.plot_audio_wave.isVisible()
        noise_visible = self.audio_noise_panel.isVisible()
        fft_visible = self.plot_audio_fft.isVisible()
        if not (wave_visible or noise_visible or fft_visible):
            return
        z_all = None
        with self.audio_lock:
            if (wave_visible or noise_visible) and self.audio_dirty:
                self.audio_dirty = False
                z_all = self.audio_z.copy()
            do_fft = (fft_visible and self.audio_fft_enabled and self.audio_valid_samples >= AUDIO_FFT_SIZE
                      and now - self.last_fft_t >= AUDIO_FFT_INTERVAL)
            if do_fft:
                self.last_fft_t = now
                # Com zoom usa todo o histórico disponível (resolução fina perto da referência)
                fft_n = AUDIO_FFT_SIZE if self.audio_fft_full else self.audio_valid_samples
                indices = (self.audio_write_index - fft_n +
                           np.arange(fft_n)) % len(self.audio_history)
                pcm = self.audio_history[indices].astype(np.float64) / 8388608.0
        if z_all is not None and wave_visible:
            z = z_all[-self.audio_max_points:] * np.exp(-1j * np.radians(self.audio_phase_offset))
            n = len(z)
            if n:
                x = (np.arange(n) - (n - 1)) * self.audio_block_sec
                item = self.plot_audio_wave.getPlotItem()
                if self.audio_xy:
                    self.curve_audio_wave.setData(x, z.real)
                    self.curve_audio_y.setData(x, z.imag)
                    lim = max(1e-6, float(np.abs(z).max()) * 1.10)
                    item.setYRange(-lim, lim, padding=0)
                else:
                    r = np.abs(z)
                    self.curve_audio_wave.setData(x, r)
                    self.curve_audio_phase.setData(x, np.degrees(np.angle(z)))
                    item.setYRange(0, max(1e-6, float(r.max()) * 1.10), padding=0)
        if z_all is not None:
            # Estatística calculada sempre que o lock-in roda: alimenta o alerta de sinal baixo
            self._update_audio_noise(z_all, noise_visible)

        if do_fft:
            window = np.hanning(fft_n)
            spectrum = np.abs(np.fft.rfft(pcm * window)) / window.sum()
            spectrum[1:-1] *= 2.0
            magnitude_dbfs = 20.0 * np.log10(np.maximum(spectrum, 1e-6))
            frequency = np.fft.rfftfreq(fft_n, 1.0 / AUDIO_FS_REAL)
            self.curve_audio_fft.setData(frequency, magnitude_dbfs)
            if self.chk_audio_fft_fit.isChecked():
                self._fit_audio_fft(frequency, spectrum)

    def _fit_audio_fft(self, frequency, spectrum):
        '''Fit em f0 fixo (excitação); o texto acompanha a barra de status (2 s).'''
        self.audio_fft_fit_html, self.audio_fft_missing = self._fit_fft_at(
            frequency, spectrum, self.audio_freq, AUDIO_FFT_HISTORY_SEC, self.curve_audio_fft_fit)

    def _update_audio_noise(self, z, plot=True):
        '''SNR móvel e números de ruído da janela mais recente.'''
        w = max(2, int(round(self.audio_noise_window / self.audio_block_sec)))
        sig, sigma = rolling_noise(z, w)
        if sig.size == 0:
            self.audio_snr_db = None
            self.curve_audio_snr.setData([], [])
            self.audio_noise_text = (f'Ruído/SNR: acumulando {self.audio_noise_window:g} s de dados '
                                         f'({len(z) * self.audio_block_sec:.1f} s)')
            return
        snr_db = 20.0 * np.log10(np.maximum(sig, 1e-30) / np.maximum(sigma, 1e-30))
        self.audio_snr_db = float(snr_db[-1])
        if plot:
            t = (np.arange(sig.size) - (sig.size - 1)) * self.audio_block_sec
            self.curve_audio_snr.setData(t, snr_db)
        tau = lp_tau(self.audio_cutoff_lp, AUDIO_FS_REAL)
        enbw = 1.0 / (8.0 * tau)                      # banda equivalente de ruído, 2 polos em cascata
        density = sigma[-1] / np.sqrt(2.0 * enbw)     # ruído de entrada (rms) por raiz de Hz
        warn = (' <span style="color:#b36b00;">(janela &lt; 10τ: estimativa imprecisa)</span>'
                if self.audio_noise_window < 10.0 * tau else '')
        # O texto só vai para a tela junto com a barra de status (a cada 2 s), para dar tempo de ler
        self.audio_noise_text = (
            f'<b>Sinal</b> |⟨Z⟩| = {sig[-1]:.3e} FS &nbsp; <b>Ruído</b> σ(X,Y) = {sigma[-1]:.3e} FS &nbsp; '
            f'<b>SNR</b> = {snr_db[-1]:.1f} dB &nbsp; <b>Densidade</b> ≈ {density:.2e} FS/√Hz '
            f'(ENBW = {enbw:.3g} Hz){warn}')

    def _update_audio_status(self, now):
        received = self.audio_received_samples
        diff = received - getattr(self, 'last_audio_received_samples_stat', 0)
        self.last_audio_received_samples_stat = received
        dt = now - getattr(self, 'last_audio_status_now', now - 1.0)
        self.last_audio_status_now = now
        rate = diff / dt if dt > 0 else 0

        color = OK_COLOR
        # NOVO: Exibe o status da varredura do INMP441, se ativa
        if getattr(self, 'sweep_active', False) and getattr(self, 'sweep_target', 'OPT') == 'AUDIO':
            text = self.sweep_status_text
            color = OK_COLOR
        elif self.simulating and not self.link.connected:
            text = f"Status INMP441 (Simulado) | Taxa: {rate:.0f} amostras/s | 24 bits"
        elif not self.link.connected:
            text = f"Status INMP441: Aguardando conexão com o STM32 (I2S2, {AUDIO_FS // 1000} kHz, PCM 24 bits)"
            color = WARN_COLOR
        elif received == 0 and now - self.audio_wait_started > 2.0:
            text = "Status INMP441: Nenhum pacote recebido; verifique a inicialização I2S e fios PB13/PB12/PB15"
            color = WARN_COLOR
        elif received == 0:
            text = "Status INMP441: Aguardando pacotes I2S..."
            color = WARN_COLOR
        else:
            text = f"Status INMP441: Conectado | Taxa de dados: {rate:.0f} amostras/s | 24 bits"
        if (color == OK_COLOR and received and self.audio_lockin_enabled and self.audio_snr_db is not None
                and self.audio_snr_db < self.audio_snr_alert):
            text += f" | ⚠ SINAL BAIXO: SNR = {self.audio_snr_db:.1f} dB (limiar {self.audio_snr_alert:g} dB)"
            color = ALERT_COLOR

        if getattr(self, 'last_audio_status_text', None) != text:
            self.last_audio_status_text = text
            self.audio_status.setText(text)
        if getattr(self, 'last_audio_status_color', None) != color:
            self.last_audio_status_color = color
            self.audio_status.setStyleSheet(
                f'background:{color}; border:1px solid gray; border-radius:6px; padding:4px;')

    def _check_modulation_sync(self, now, connected):
        '''O PLL do OPT101 trava nas bordas reais do laser (bit REF). Se ele passa vários períodos sem
        travar, o STM32 está modulando em outra frequência (F perdido na conexão, placa reiniciada no
        padrão de 5 Hz...). O lock-in do INMP441 não tem PLL e daria resultado errado sem aviso:
        reenvia F, o que reinicia a onda quadrada e manda um novo marcador de fase.'''
        f = self.ref_freq
        if not connected or f <= 0 or self.average_mode or self.dsp.pll_locked:
            self._pll_bad_since = None
            return
        if self._pll_bad_since is None:
            self._pll_bad_since = now
            return
        if now - self._pll_bad_since >= max(5.0, 5.0 / f):
            self._pll_bad_since = now
            self.link.write(f"F{f}\n")
            self.flash(f'PLL do OPT101 sem travar: frequência {f:g} Hz reenviada ao STM32.', 5.0)
            print(f'PLL sem travar: F{f} reenviado')

    def tick(self):
        now = time.perf_counter()

        # 1. Conexão e simulação (o processamento roda nas threads do OPT101 e do INMP441)
        # Caixa de simulação só aparece sem STM32; se o STM32 conectar, a simulação é desligada.
        connected = self.link.connected
        if connected != self.audio_link_connected:
            self.audio_link_connected = connected
            with self.audio_lock:
                self.audio_wait_started = now
                self.audio_last_sequence = None
                self.audio_gap_samples = 0
                self.audio_received_samples = 0
                self.audio_queue_drops = 0
                self.audio_valid_samples = 0
                self.audio_write_index = 0
                self._audio_reset_lockin()
            self._clear_audio_wave()
            self.curve_audio_fft.setData([], [])
        self._check_modulation_sync(now, connected)
        if connected and self.chk_sim.isChecked():
            self.chk_sim.setChecked(False)
        if self.chk_sim.isHidden() != connected:
            self.chk_sim.setVisible(not connected)
        if self.simulating and not connected:
            optical_data = self.simulator.generate(now, self.ref_freq, self.laser_power)
            with self.dsp_lock:
                self.rx_bytes.extend(optical_data)
                
        # 5. Atualização dos gráficos e status do áudio
        self._update_audio_plots(now)
        if now - getattr(self, 'last_audio_status_t', 0.0) >= 2.0:
            self.last_audio_status_t = now
            self._update_audio_status(now)
            text = getattr(self, 'audio_noise_text', None)
            if text and self.lbl_audio_noise.text() != text:
                self.lbl_audio_noise.setText(text)
            self._show_fft_fit(self.txt_audio_fft_fit, self.lbl_audio_fft_missing,
                               self.audio_fft_enabled and self.chk_audio_fft_fit.isChecked(),
                               self.audio_fft_fit_html, self.audio_fft_missing)
            self._show_fft_fit(self.txt_opt_fft_fit, self.lbl_opt_fft_missing,
                               self.opt_fft_enabled and self.chk_opt_fft_fit.isChecked(),
                               self.opt_fft_fit_html, self.opt_fft_missing)

        # 2. Resultados do lock-in do OPT101 e atualização dos buffers
        raw_dirty = False
        while self.opt_results:
            res = self.opt_results.popleft()
            n_dec = len(res.r)
            n_raw = len(res.adc)

            if n_raw > 0:
                adc, ref = res.adc / np.float32(ADC_OVS_FACTOR), res.ref
                wrapped = self.raw.push(adc, ref)
                if self.opt_fft_enabled:
                    self._store_opt_samples(adc)
                if wrapped:
                    m = float(self.raw.adc.max())
                    if m > 0:
                        self.plot_raw.getPlotItem().setYRange(0, max(10.0, m * 1.10), padding=0)
                if self.average_mode and self.avg.push(adc, ref):
                    self.avg_dirty = True
                self.peak_hist.append((now, float(np.max(adc))))
                while now - self.peak_hist[0][0] > 1.0:
                    self.peak_hist.popleft()
                raw_dirty = True

            if n_dec > 0 and not self.average_mode:
                r_new = np.array(res.r, dtype=np.float64)
                p_new = np.array(res.phase, dtype=np.float64)
                self.r_arr = np.concatenate((self.r_arr, r_new.astype(np.float32)))[-MAX_POINTS:]
                self.phase_arr = np.concatenate((self.phase_arr, p_new.astype(np.float32)))[-MAX_POINTS:]
                self.lockin_dirty = True
                if self.sweep_active and getattr(self, 'sweep_target', 'OPT') == 'OPT' and self.sweep_state == 'MEASURING':
                    dc_new = np.array(res.dc, dtype=np.float64)
                    self.sweep_chunks_r.append(r_new)
                    self.sweep_chunks_p.append(p_new)
                    self.sweep_chunks_dc.append(dc_new)
                    self.sweep_count += n_dec
                if self.dual_state == 'MEASURING':
                    self.dual_opt.append((r_new, p_new, np.array(res.dc, dtype=np.float64)))

        # 3. Máquina de estados da varredura
        if self.sweep_active:
            self.sweep_step(now)
        if self.dual_active:
            self.dual_step(now)
        elif now - getattr(self, 'last_dual_eta_t', 0.0) >= 0.5:
            self.last_dual_eta_t = now
            self.update_dual_eta()     # acompanha mudanças nos filtros dos lock-ins

        # 4. Curvas (só o que mudou)
        if raw_dirty:
            ring = self.raw
            sa, sb = ring.segments()
            self.c_adc_a.setData(ring.t[sa], ring.adc[sa])
            self.c_ref_a.setData(ring.t[sa], ring.ref[sa])
            if sb is not None:
                self.c_adc_b.setData(ring.t[sb], ring.adc[sb])
                self.c_ref_b.setData(ring.t[sb], ring.ref[sb])
            else:
                self.c_adc_b.setData([], [])
                self.c_ref_b.setData([], [])
            self.cursor.setPos(ring.cursor_x())

        if not self.paused:
            self._update_opt_fft(now)

        if self.paused:
            pass
        elif self.average_mode:
            if self.avg_dirty:
                self.avg_dirty = False
                vals, tax = self.avg.values, self.avg.time
                if len(vals) > 0:
                    self.line_r.setData(tax, vals)
                    p1 = self.plot1.getPlotItem()
                    p1.setXRange(-self.average_pretrigger_sec,
                                 max(1.0 / max(self.ref_freq, 0.1), float(tax[-1])), padding=0)
                    lo, hi = float(vals.min()), float(vals.max())
                    margin = max(1.0, (hi - lo) * 0.1)
                    p1.setYRange(lo - margin, hi + margin, padding=0)
        elif self.lockin_dirty:
            self.lockin_dirty = False
            n = len(self.r_arr)
            x = (np.arange(n) - (n - 1)) * (DECIMATION / FS)
            self.line_r.setData(x, self.r_arr)
            self.line_phase.setData(x, self.phase_arr)
            if now - self.last_range_t >= RANGE_INTERVAL and len(self.r_arr) > 0:
                self.last_range_t = now
                self.plot1.getPlotItem().setYRange(0, max(0.01, float(self.r_arr.max()) * 1.10), padding=0)

        if now - self.last_status_t >= STATUS_INTERVAL:
            self.last_status_t = now
            self.update_status(now)
            self.update_window_status()

    def update_status(self, now):
        self.txt_sat.setVisible(False)
        if not self.link.connected and not self.simulating:
            text = "Status: STM32 NÃO conectado - tentando reconectar automaticamente..."
            color = WARN_COLOR
        elif self.flash_text and now < self.flash_until:
            text, color = self.flash_text, OK_COLOR
        # ATUALIZADO: Só exibe varredura no OPT101 se o alvo for o próprio 'OPT'
        elif getattr(self, 'sweep_active', False) and getattr(self, 'sweep_target', 'OPT') == 'OPT':
            text, color = self.sweep_status_text, OK_COLOR
        elif self.average_mode:
            text = (f'Modo Valor Médio: {len(self.avg.cycles)}/{self.avg.pulses} pulsos | '
                    f'Ciclo atual: {self.avg.current_len() / FS:.3f} s')
            color = OK_COLOR
        else:
            while self.peak_hist and now - self.peak_hist[0][0] > 1.0:
                self.peak_hist.popleft()
            dc = self.dsp.dc_offset / ADC_OVS_FACTOR
            peak = max((v for _, v in self.peak_hist), default=0.0)
            pct = peak / ADC_FULL_SCALE * 100.0
            if dc > 0.95 * ADC_FULL_SCALE or pct >= 99.5:
                status = "<b>[SATURAÇÃO DO ADC]</b>"
                color = ALERT_COLOR
            elif dc < 0.05 * ADC_FULL_SCALE:
                status = "[Sinal baixo: nível médio &lt; 5 % do ADC]"
                color = WARN_COLOR
            else:
                status = "[Sinal OK]"
                color = OK_COLOR
            vcolor = '#006400' if pct < 50.0 else ('#e07000' if pct <= 70.0 else '#d00000')
            over = pct > 70.0
            self.txt_sat.setVisible(over)
            if over:
                (x0, x1), (y0, y1) = self.plot_raw.getPlotItem().vb.viewRange()
                self.txt_sat.setPos((x0 + x1) / 2, (y0 + y1) / 2)
            text = (f"Status: {status} | %ADC: <span style='color:{vcolor};font-weight:bold;'>"
                    f"{pct:.1f} %</span> | " + (f"Freq Real (PLL): {self.dsp.measured_freq:.2f} Hz"
                                                if self.dsp.pll_locked or self.ref_freq <= 0 else
                                                "<b>PLL destravado</b>"))

        if text != self.last_status_text:
            self.last_status_text = text
            self.lbl_status.setText(text)
        if color != self.last_status_color:
            self.last_status_color = color
            self.lbl_status.setStyleSheet(
                f'background:{color}; border:1px solid gray; border-radius:6px; padding:4px;')

    def warn_not_found(self):
        if self.link.connected:
            return
        if self.link.last_error:
            QtWidgets.QMessageBox.warning(
                self, 'Falha ao abrir a porta serial',
                f'A porta foi encontrada, mas não pôde ser aberta:\n{self.link.last_error}\n\n'
                'Feche outros programas que usem a porta (monitor serial, outra instância '
                'deste script) e reconecte o USB. A interface tentará reconectar sozinha.')
            return

    # ------------------------------------------------------------ Preferências (14)
    # O PWM do laser não é restaurado de propósito: a interface sempre abre com o valor padrão (baixo).
    def _settings_widgets(self):
        spins = ('sp_freq', 'sp_window', 'sp_pulses', 'sp_f0', 'sp_f1', 'sp_df', 'sp_p0', 'sp_p1', 'sp_dp',
                 'sp_audio_span', 'sp_audio_snr_alert', 'sp_audio_phase_off',
                 'sp_aud_f0', 'sp_aud_f1', 'sp_aud_df', 'sp_aud_p0', 'sp_aud_p1', 'sp_aud_dp',
                 'sp_dual_p0', 'sp_dual_p1', 'sp_dual_dp', 'sp_dual_f0', 'sp_dual_f1', 'sp_dual_fn',
                 'sp_dual_tau_p', 'sp_dual_tau_f', 'sp_dual_flat_tol', 'sp_dual_tau_sensor',
                 'sp_dual_thick', 'sp_dual_model_f0', 'sp_dual_model_f1')
        checks = ('chk_mains', 'chk_audio_lockin', 'chk_audio_noise', 'chk_audio_fft', 'chk_audio_fft_fit',
                  'chk_audio_fft_full', 'chk_audio_mains', 'btn_audio_sweeps',
                  'chk_opt_fft', 'chk_opt_fft_fit', 'chk_opt_fft_full', 'btn_opt_sweeps', 'btn_dual_cal_panel', 'btn_dual_model_panel', 'btn_dual_sweeps_panel', 'chk_dual_std_phase',
                  'chk_dual_opt_tau')
        combos = ('cmb_dual_mode_p', 'cmb_dual_mode_f', 'cmb_dual_fspace', 'cmb_dual_model', 'cmb_dual_model_target')
        return spins, checks, combos

    def _fit_to_screen(self):
        '''Limita tamanho e posição à área útil da tela: a geometria salva pode ter vindo de outro monitor
        ou de outra escala do Windows, e uma janela maior que a tela gera aviso do Qt (setGeometry).'''
        scr = self.screen() or QtWidgets.QApplication.primaryScreen()
        if scr is None:
            return
        a = scr.availableGeometry()
        w = min(self.width(), a.width() - 20)          # folga para a moldura da janela
        h = min(self.height(), a.height() - 50)        # e para a barra de título
        self.resize(w, h)
        self.move(min(max(self.x(), a.left()), a.right() - w), min(max(self.y(), a.top()), a.bottom() - h))

    def load_settings(self):
        st = QtCore.QSettings('LCTM', 'SOI Controller')
        spins, checks, combos = self._settings_widgets()

        def num(key):
            v = st.value(key)
            try:
                return None if v is None else float(v)
            except (TypeError, ValueError):
                return None
        try:
            # Combos antes dos valores (o espaçamento muda o sentido de "N pontos / Passo")
            for name in combos:
                v = num(name)
                if v is not None:
                    getattr(self, name).setCurrentIndex(int(v))
            for name in checks:
                v = st.value(name)
                if v is not None:
                    getattr(self, name).setChecked(str(v).lower() in ('true', '1'))
            for name in spins:
                v = num(name)
                if v is not None:
                    w = getattr(self, name)
                    w.setValue(int(v) if isinstance(w, QtWidgets.QSpinBox) else v)
            # Filtros por último: a frequência redefine os cortes automáticos
            for name in ('sp_lp', 'sp_hp', 'sp_audio_lp', 'sp_audio_hp'):
                v = num(name)
                if v is not None:
                    getattr(self, name).setValue(v)
            v = st.value('sample_name')
            if v is not None:
                self.ed_sample.setText(str(v))
            geo = st.value('geometry')
            if geo is not None:
                self.restoreGeometry(geo)
            self._fit_to_screen()
            v = num('tab')
            if v is not None:
                self.tabs.setCurrentIndex(int(v))
        except Exception as e:
            print(f'Preferências ignoradas ({e})')

    def save_settings(self):
        st = QtCore.QSettings('LCTM', 'SOI Controller')
        spins, checks, combos = self._settings_widgets()
        for name in spins + ('sp_lp', 'sp_hp', 'sp_audio_lp', 'sp_audio_hp'):
            st.setValue(name, float(getattr(self, name).value()))
        for name in checks:
            st.setValue(name, bool(getattr(self, name).isChecked()))
        for name in combos:
            st.setValue(name, int(getattr(self, name).currentIndex()))
        st.setValue('sample_name', self.ed_sample.text())
        st.setValue('geometry', self.saveGeometry())
        st.setValue('tab', self.tabs.currentIndex())

    def closeEvent(self, event):
        try:
            # Durante uma varredura os campos guardam o ponto atual, não a escolha do usuário
            if not self.sweep_active and not self.dual_active:
                self.save_settings()
        except Exception as e:
            print(f'Preferências não salvas ({e})')
        self.timer.stop()
        self.opt_thread.stop()
        self.audio_thread.stop()
        self.link.stop()
        for w in self.result_windows:
            w.close()
        super().closeEvent(event)


def main():
    app = pg.mkQApp("SOI Controller - LCTM")
    win = LockInWindow()
    win.show()
    # Aviso único se o Arduino não estiver ligado na abertura (não bloqueia a GUI).
    QtCore.QTimer.singleShot(2500, win.warn_not_found)
    sys.exit(app.exec())


if __name__ == '__main__':
    main()