"""Detectar ruídos de fundo (aba INMP441): espectro de alguns segundos do INMP441, tons acima do fundo e séries
harmônicas (ex.: ventoinha do laser em ~170 Hz e múltiplos), excluídos (com uma faixa em volta) das varreduras.
O OPT101 é analisado junto, só para os tons da rede (60 Hz e múltiplos): o fundo da rede é elétrico, no OPT101.

Análise (funções puras, testáveis sem janela):
- psd_db: Welch com janelas Hann de 4 s (resolução 0,25 Hz), 50 % de sobreposição, em dB.
- background_db: fundo = mediana móvel do espectro em dB, ±20 Hz.
- find_tones: máximos locais com PSD - fundo > limiar (padrão 10 dB), de 20 Hz a 5 kHz.
- find_series: f0 com >= 3 picos em k·f0 (tolerância 0,5 %, k <= 10); 60 Hz e múltiplos marcados "rede".
- compare_tones: modo comparativo (como a calibração com dois metais): tons da 2ª gravação (com a fonte) que ficam
  >= 6 dB acima da 1ª (sem a fonte) no mesmo lugar.
"""
import os
import struct
import time
from datetime import datetime

import numpy as np
from scipy.ndimage import median_filter
from scipy.signal import welch

FS_DEC = None                # taxa do áudio guardado (definida pelo controlador: AUDIO_FS_REAL / 4)
SEG_S = 4.0                  # janela do Welch (s): resolução 0,25 Hz
BG_HALF_HZ = 20.0            # fundo: mediana móvel ±20 Hz
TONE_DB = 10.0               # tom: PSD > fundo + 10 dB
CMP_DB = 6.0                 # comparativo: tom da fonte >= 6 dB acima da gravação sem a fonte
FMIN_HZ, FMAX_HZ = 20.0, 5000.0
SERIES_TOL = 0.005           # 0,5 %
SERIES_KMAX = 10
SERIES_MIN = 3
MAINS_TOL_HZ = 0.6
DUR_DEF_S = 20.0


def psd_db(x, fs):
    x = np.asarray(x, dtype=np.float64)
    x = x - x.mean()
    nper = int(round(SEG_S * fs))
    if len(x) < nper:
        nper = max(256, len(x))
    f, p = welch(x, fs=fs, window='hann', nperseg=nper, noverlap=nper // 2, detrend='constant', scaling='density')
    return f, 10.0 * np.log10(np.maximum(p, 1e-30))


def background_db(f, p_db, half_hz=BG_HALF_HZ):
    df = f[1] - f[0] if len(f) > 1 else 1.0
    size = max(3, int(round(2 * half_hz / df)) | 1)
    return median_filter(p_db, size=size, mode='nearest')


def _refine(f, p_db, i):
    if 0 < i < len(p_db) - 1:
        a, b, c = p_db[i - 1], p_db[i], p_db[i + 1]
        den = a - 2 * b + c
        if den < 0:
            d = 0.5 * (a - c) / den
            return float(f[i] + d * (f[1] - f[0]))
    return float(f[i])


def find_tones(f, p_db, bg_db, thr=TONE_DB, fmin=FMIN_HZ, fmax=FMAX_HZ, exclude=()):
    """[(f, dB acima do fundo, PSD dB)], do mais forte ao mais fraco. exclude: [(f, tol)] a ignorar."""
    ex = p_db - bg_db
    sel = (f >= fmin) & (f <= fmax)
    i = np.where(sel[1:-1] & (ex[1:-1] > thr) & (p_db[1:-1] >= p_db[:-2]) & (p_db[1:-1] > p_db[2:]))[0] + 1
    tones = []
    for k in i:
        fk = _refine(f, p_db, k)
        if any(abs(fk - fe) <= tol for fe, tol in exclude):
            continue
        tones.append((fk, float(ex[k]), float(p_db[k])))
    tones.sort(key=lambda t: -t[1])
    out = []
    for t in tones:                 # junta picos a menos de 1 Hz (fica o mais forte)
        if all(abs(t[0] - o[0]) > 1.0 for o in out):
            out.append(t)
    return out


def is_mains(fx, tol=MAINS_TOL_HZ):
    k = int(round(fx / 60.0))
    return k >= 1 and abs(fx - 60.0 * k) <= tol


def find_series(tones, tol=SERIES_TOL, kmax=SERIES_KMAX, nmin=SERIES_MIN):
    """Séries harmônicas: [{'f0', 'hits': [(k, f, dB)], 'rede': bool}], da com mais picos à com menos.
    Candidatos f0 = tom/k (k = 1..3, para achar a série mesmo sem a fundamental); empate: f0 maior."""
    fs = [t[0] for t in tones]
    cands = sorted({round(t / k, 3) for t in fs for k in (1, 2, 3) if t / k >= FMIN_HZ})
    scored = []
    for f0 in cands:
        hits = {}
        for t in tones:
            k = int(round(t[0] / f0))
            if 1 <= k <= kmax and abs(t[0] - k * f0) <= tol * k * f0:
                if k not in hits or t[1] > hits[k][2]:
                    hits[k] = (k, t[0], t[1])
        if len(hits) >= nmin:
            scored.append((len(hits), f0, sorted(hits.values())))
    scored.sort(key=lambda s: (-s[0], -s[1]))
    used, out = set(), []
    for n, f0, hits in scored:
        free = [h for h in hits if round(h[1], 3) not in used]
        if len(free) < nmin or any(abs(f0 - o['f0']) <= 2 * tol * f0 for o in out):
            continue
        # f0 refinado pelos picos (média ponderada de f/k)
        f0r = float(np.average([h[1] / h[0] for h in free], weights=[max(h[2], 0.1) for h in free]))
        out.append({'f0': f0r, 'hits': free, 'rede': abs(f0r - 60.0) <= MAINS_TOL_HZ or
                    (abs(f0r / 60.0 - round(f0r / 60.0)) * 60.0 <= MAINS_TOL_HZ and round(f0r / 60.0) >= 1)})
        used.update(round(h[1], 3) for h in free)
    return out


def compare_tones(f, p_off, p_on, bg_on, thr=TONE_DB, dthr=CMP_DB, exclude=()):
    """Tons da gravação com a fonte que sobem >= dthr dB em relação à gravação sem a fonte (máximo em ±0,5 Hz)."""
    tones = find_tones(f, p_on, bg_on, thr=thr, exclude=exclude)
    df = f[1] - f[0]
    w = max(1, int(round(0.5 / df)))
    out = []
    for t in tones:
        i = int(round((t[0] - f[0]) / df))
        lo, hi = max(0, i - w), min(len(f), i + w + 1)
        d = float(np.max(p_on[lo:hi]) - np.max(p_off[lo:hi]))
        if d >= dthr:
            out.append((t[0], t[1], t[2], d))
    return out


def analyze(x, fs, thr=TONE_DB, exclude=()):
    f, p = psd_db(x, fs)
    bg = background_db(f, p)
    tones = find_tones(f, p, bg, thr=thr, exclude=exclude)
    return {'f': f, 'p': p, 'bg': bg, 'tones': tones, 'series': find_series(tones)}


def analyze_compare(x_off, x_on, fs, thr=TONE_DB, dthr=CMP_DB, exclude=()):
    f, p_off = psd_db(x_off, fs)
    f2, p_on = psd_db(x_on, fs)
    n = min(len(f), len(f2))
    f, p_off, p_on = f[:n], p_off[:n], p_on[:n]
    bg = background_db(f, p_on)
    ct = compare_tones(f, p_off, p_on, bg, thr=thr, dthr=dthr, exclude=exclude)
    tones = [c[:3] for c in ct]
    return {'f': f, 'p': p_on, 'p_off': p_off, 'bg': bg, 'tones': tones, 'delta': {round(c[0], 3): c[3] for c in ct},
            'series': find_series(tones)}


def opt_mains(x, fs, thr=TONE_DB, exclude=()):
    """Tons da rede (60 Hz e múltiplos) no sinal do OPT101: [(f, dB acima do fundo)], em ordem de frequência."""
    if len(x) < SEG_S * fs:
        return []
    f, p = psd_db(x, fs)
    bg = background_db(f, p)
    return sorted((t[0], t[1]) for t in find_tones(f, p, bg, thr=thr, exclude=exclude) if is_mains(t[0]))


def rows(res):
    """Linhas da tabela: (f, dB acima do fundo, f0 ou None, k ou None, tipo); tipo 'rede OPT101' = tom da rede
    visto só no OPT101."""
    where = {}
    for s in res['series']:
        for k, fk, _ in s['hits']:
            where[round(fk, 3)] = (s['f0'], k, s['rede'])
    out = []
    for fx, db, _p in sorted(res['tones'], key=lambda t: t[0]):
        f0, k, rede = where.get(round(fx, 3), (None, None, False))
        kind = 'rede' if (rede or is_mains(fx)) else ('série' if f0 else 'tom')
        out.append((fx, db, f0, k, kind))
    for fx, db in res.get('opt_mains', []):
        if all(abs(fx - r[0]) > 1.0 for r in out):
            out.append((fx, db, None, None, 'rede OPT101'))
    return sorted(out, key=lambda r: r[0])


def avoid_list_for(res, selected, whole_series=True, fmax=FMAX_HZ):
    """Frequências a excluir da varredura: os tons escolhidos e, com whole_series, todos os k·f0 (k <= 10, até
    fmax) das séries deles. Tons da rede (INMP441 ou OPT101) entram só eles mesmos (os múltiplos de 60 Hz achados)."""
    out = []
    by_f = {round(r[0], 3): r for r in rows(res)}
    for fx in selected:
        r = by_f.get(round(fx, 3))
        if r is None:
            continue
        if r[4].startswith('rede'):
            out.append(round(60.0 * round(fx / 60.0), 1))
        elif whole_series and r[2]:
            out += [round(k * r[2], 1) for k in range(1, SERIES_KMAX + 1) if k * r[2] <= fmax]
        else:
            out.append(round(fx, 1))
    res_out = []
    for v in sorted(out):
        if all(abs(v - o) > 1.0 for o in res_out):
            res_out.append(v)
    return res_out


def summary(res, limit=8):
    parts = []
    for s in res['series']:
        if not s['rede']:
            parts.append(f"série {s['f0']:.1f} Hz (k = {', '.join(str(h[0]) for h in s['hits'])})")
    in_series = {round(h[1], 3) for s in res['series'] for h in s['hits']}
    loose = [t for t in res['tones'] if round(t[0], 3) not in in_series and not is_mains(t[0])]
    parts += [f'{t[0]:.1f} Hz (+{t[1]:.0f} dB)' for t in loose[:limit]]
    mains = sorted({int(round(r[0] / 60.0)) * 60 for r in rows(res) if r[4].startswith('rede')})
    if mains:
        parts.append('rede ' + ', '.join(f'{m:d}' for m in mains) + ' Hz')
    return '; '.join(parts) if parts else 'nenhum'


def save_csv(path, res, header=()):
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        for h in header:
            fh.write(f'# {h}\n')
        fh.write(f'# Ruidos detectados = {summary(res)}\n')
        for fx, db, f0, k, kind in rows(res):
            fh.write(f'# Tom {fx:.2f} Hz: +{db:.1f} dB' + (f', serie f0 = {f0:.2f} Hz, k = {k}' if f0 else '')
                     + (f' ({kind})' if kind.startswith('rede') else '')
                     + (f", +{res['delta'][round(fx, 3)]:.1f} dB com a fonte" if 'delta' in res and
                        round(fx, 3) in res['delta'] else '') + '\n')
        cmp_ = 'p_off' in res
        fh.write('Frequencia_Hz,PSD_dB,Fundo_dB' + (',PSD_sem_fonte_dB' if cmp_ else '') + '\n')
        f, p, bg = res['f'], res['p'], res['bg']
        sel = f <= FMAX_HZ + 100
        for i in np.where(sel)[0]:
            fh.write(f'{f[i]:.2f},{p[i]:.2f},{bg[i]:.2f}' + (f",{res['p_off'][i]:.2f}" if cmp_ else '') + '\n')


def save_bin(path, x, t0=None):
    """Mesmo formato do AudioRecorder: bloco uint32 sequence, uint32 n, float64 t_pc + n float32."""
    x = np.asarray(x, dtype='<f4')
    with open(path, 'wb') as fh:
        fh.write(struct.pack('<IId', 0, len(x), t0 or time.time()))
        fh.write(x.tobytes())


def stamp():
    return datetime.now().strftime('%Y%m%d_%H%M%S')


def file_stem(sample, what='Ruido_fundo'):
    import re
    s = re.sub(r'[^\w.-]+', '_', (sample or '').strip())
    return (f'{s}_' if s else '') + f'{what}_{stamp()}'


def synth(fs, dur, f0=170.2, amps=(3e-4, 1e-4, 2e-4, 1.5e-4, 8e-5), noise=3e-5, hum=2e-5, seed=1):
    """Áudio sintético para testes: ruído branco + rede + série harmônica em f0 (amps[k-1] em k·f0)."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(dur * fs)) / fs
    x = noise * rng.standard_normal(len(t)) + hum * np.sin(2 * np.pi * 60 * t)
    for k, a in enumerate(amps, 1):
        x += a * np.sin(2 * np.pi * k * f0 * t + k)
    return x.astype(np.float32)


# ---------------------------------------------------------------- janela (Qt)
def make_dialog(win):
    """Janela "Detectar ruídos de fundo" (criada uma vez pelo controlador)."""
    import pyqtgraph as pg
    from pyqtgraph.Qt import QtCore, QtWidgets
    from soi_i18n import tr as _tr

    class NoiseDialog(QtWidgets.QDialog):
        def __init__(self):
            super().__init__(win)
            self.setWindowTitle('Detectar ruídos de fundo (INMP441)')
            self.resize(1050, 720)
            self.res = None
            self._view = None          # (log10 f0, log10 f1, y0, y1) do espectro inteiro, para o duplo clique
            self.x_off = None
            self.mode = None
            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self._tick)
            lay = QtWidgets.QVBoxLayout(self)
            info = QtWidgets.QLabel(
                'Grava alguns segundos do INMP441 e do OPT101 com o laser parado (PWM 0) e procura frequências com sinal '
                'acima do fundo, e as que se repetem nos harmônicos (ex.: ventoinha do laser em ~170 Hz); no OPT101, só '
                'os tons da rede (60 Hz e múltiplos). Rápido: uma gravação. Comparativo (como a calibração com duas '
                'amostras): grave sem a fonte de ruído e depois com ela; ficam os tons que sobem com a fonte. Os tons '
                'encontrados são excluídos das próximas varreduras do Modo Duplo (caixa "Excluir ruídos detectados").')
            info.setWordWrap(True)
            lay.addWidget(info)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel('Duração:'))
            self.sp_dur = QtWidgets.QDoubleSpinBox()
            self.sp_dur.setRange(5.0, 300.0)
            self.sp_dur.setValue(DUR_DEF_S)
            self.sp_dur.setSuffix(' s')
            self.sp_dur.setDecimals(0)
            row.addWidget(self.sp_dur)
            row.addSpacing(10)
            row.addWidget(QtWidgets.QLabel('Limiar:'))
            self.sp_thr = QtWidgets.QDoubleSpinBox()
            self.sp_thr.setRange(3.0, 40.0)
            self.sp_thr.setValue(TONE_DB)
            self.sp_thr.setSuffix(' dB')
            self.sp_thr.setDecimals(0)
            self.sp_thr.setToolTip('Tom = PSD acima do fundo (mediana móvel do espectro, ±20 Hz) por mais que isto.')
            row.addWidget(self.sp_thr)
            row.addSpacing(10)
            row.addWidget(QtWidgets.QLabel('Comparativo: com a fonte ≥'))
            self.sp_cmp = QtWidgets.QDoubleSpinBox()
            self.sp_cmp.setRange(2.0, 40.0)
            self.sp_cmp.setValue(CMP_DB)
            self.sp_cmp.setSuffix(' dB')
            self.sp_cmp.setDecimals(0)
            row.addWidget(self.sp_cmp)
            row.addStretch(1)
            lay.addLayout(row)
            row = QtWidgets.QHBoxLayout()
            self.btn_quick = QtWidgets.QPushButton('▶ Detectar (rápido)')
            self.btn_quick.clicked.connect(lambda: self._start('rapido'))
            self.btn_off = QtWidgets.QPushButton('1. Gravar sem a fonte')
            self.btn_off.clicked.connect(lambda: self._start('sem'))
            self.btn_on = QtWidgets.QPushButton('2. Gravar com a fonte')
            self.btn_on.clicked.connect(lambda: self._start('com'))
            self.btn_on.setEnabled(False)
            for b in (self.btn_quick, self.btn_off, self.btn_on):
                b.setStyleSheet('background:#cfe2ff;')
                row.addWidget(b)
            self.bar = QtWidgets.QProgressBar()
            self.bar.setRange(0, 1000)
            self.bar.setVisible(False)
            row.addWidget(self.bar, 1)
            self.lbl = QtWidgets.QLabel('')
            row.addWidget(self.lbl, 2)
            lay.addLayout(row)
            split = QtWidgets.QSplitter(QtCore.Qt.Vertical)
            self.pw = pg.PlotWidget()
            self.pw.setBackground('w')
            self.pw.setLogMode(x=True, y=False)
            self.pw.showGrid(x=True, y=True, alpha=0.3)
            self.pw.setLabel('bottom', 'Frequência (Hz)')
            self.pw.setLabel('left', 'PSD (dB)')
            # Eixo esquerdo com largura fixa: com o zoom levado a valores enormes os rótulos ficavam compridos e
            # alargavam o gráfico (e a janela) além da tela
            self.pw.getPlotItem().getAxis('left').setWidth(60)
            self.pw.addLegend(offset=(-10, 10))
            # Duplo clique na área do gráfico volta ao espectro inteiro (como nos outros gráficos)
            self.pw.scene().sigMouseClicked.connect(self._plot_clicked)
            self.c_off = self.pw.plot([], [], pen=pg.mkPen((170, 170, 170), width=1), name='sem a fonte')
            self.c_p = self.pw.plot([], [], pen=pg.mkPen('dodgerblue', width=1), name='espectro')
            self.c_bg = self.pw.plot([], [], pen=pg.mkPen((90, 90, 90), width=1, style=QtCore.Qt.DashLine),
                                     name='fundo')
            self.c_t = self.pw.plot([], [], pen=None, symbol='o', symbolSize=8, symbolBrush=pg.mkBrush('coral'),
                                    name='tons')
            self.c_sel = self.pw.plot([], [], pen=None, symbol='o', symbolSize=12, symbolBrush=None,
                                      symbolPen=pg.mkPen('red', width=2))
            split.addWidget(self.pw)
            self.tbl = QtWidgets.QTableWidget(0, 5)
            self.tbl.setHorizontalHeaderLabels([_tr(h) for h in ('Frequência (Hz)', 'Acima do fundo (dB)',
                                                                'Série f0 (Hz)', 'k', 'Tipo')])
            self.tbl.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            self.tbl.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            self.tbl.horizontalHeader().setStretchLastSection(True)
            self.tbl.itemSelectionChanged.connect(self._sel_changed)
            split.addWidget(self.tbl)
            split.setSizes([420, 220])
            lay.addWidget(split, 1)
            row = QtWidgets.QHBoxLayout()
            self.chk_series = QtWidgets.QCheckBox('Série inteira (k·f0, k ≤ 10)')
            self.chk_series.setChecked(True)
            self.chk_series.setToolTip('Num tom que faz parte de uma série harmônica, envia todos os múltiplos k·f0 '
                                       '(k = 1 a 10, até 5 kHz), não só o tom escolhido.')
            row.addWidget(self.chk_series)
            self.btn_send = QtWidgets.QPushButton('Gravar em Faixas excluídas (Hz)')
            self.btn_send.setToolTip('Os tons desta detecção já são excluídos das próximas varreduras do Modo Duplo, sem '
                                     'clicar aqui (caixa "Excluir ruídos detectados",\nmarcada por padrão; valem até a '
                                     'próxima detecção ou até fechar a interface).\n'
                                     'Este botão grava as frequências das linhas selecionadas (todas, se nenhuma estiver '
                                     'selecionada)\nno campo "Faixas excluídas (Hz)", que fica salvo e vale sempre. '
                                     'Nenhum ponto é medido a até ±2 % delas (mínimo 3 Hz).')
            self.btn_send.clicked.connect(self._send)
            self.btn_send.setEnabled(False)
            row.addWidget(self.btn_send)
            self.lbl_file = QtWidgets.QLabel('')
            self.lbl_file.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            row.addWidget(self.lbl_file, 1)
            btn_close = QtWidgets.QPushButton('Fechar')
            btn_close.clicked.connect(self.close)
            row.addWidget(btn_close)
            lay.addLayout(row)

        # ---- gravação
        def _start(self, mode):
            if self.mode is not None:
                self._stop('Gravação cancelada.')
                return
            if not win.audio_available():
                self.lbl.setText('Sem áudio do INMP441: conecte o SOI ou ligue "Simular amostragem".')
                return
            if getattr(win, 'dual_active', False) or getattr(win, 'sweep_active', False) or \
                    getattr(win, 'warm_state', None) is not None:
                self.lbl.setText('Há uma varredura ou warm-up em andamento: espere terminar.')
                return
            self.mode = mode
            self.pwm_saved = win.sp_power.value()
            win.set_pwm(0.0)
            self.dur = self.sp_dur.value()
            self.t0 = time.perf_counter() + 1.0          # 1 s para o laser parar
            self.capturing = False
            btn = {'rapido': self.btn_quick, 'sem': self.btn_off, 'com': self.btn_on}[mode]
            self.btn_txt = btn.text()
            self.btn_act = btn
            btn.setText('⏹ Cancelar')
            for b in (self.btn_quick, self.btn_off, self.btn_on):
                if b is not btn:
                    b.setEnabled(False)
            self.bar.setValue(0)
            self.bar.setVisible(True)
            self.timer.start(200)

        def _tick(self):
            now = time.perf_counter()
            if not self.capturing:
                if now < self.t0:
                    self.lbl.setText('Parando o laser (PWM 0)...')
                    return
                win.noise_capture_begin()
                self.capturing = True
                self.t_cap = now
            n = win.noise_capture_len()
            fs = win.noise_fs()
            got = n / fs
            self.bar.setValue(int(1000 * min(1.0, got / self.dur)))
            self.lbl.setText(f'Gravando… {got:.0f}/{self.dur:.0f} s')
            if got >= self.dur:
                x = win.noise_capture_end()
                self._finish(x)
            elif now - self.t_cap > 2 * self.dur + 5:
                win.noise_capture_end()
                self._stop('O áudio do INMP441 não chegou (placa conectada?).')

        def _stop(self, msg):
            self.timer.stop()
            if self.capturing:
                win.noise_capture_end()
            self.capturing = False
            if self.mode is not None:
                self.btn_act.setText(self.btn_txt)
                win.set_pwm(self.pwm_saved)
            self.mode = None
            self.bar.setVisible(False)
            for b in (self.btn_quick, self.btn_off):
                b.setEnabled(True)
            self.btn_on.setEnabled(self.x_off is not None)
            self.lbl.setText(msg)

        def _finish(self, x):
            mode = self.mode
            self.capturing = False
            self._stop('')
            fs = win.noise_fs()
            if mode == 'sem':
                self.x_off = x
                self.btn_on.setEnabled(True)
                self.lbl.setText('Gravado sem a fonte. Ligue a fonte de ruído e clique em "2. Gravar com a fonte".')
                f, p = psd_db(x, fs)
                self.c_off.setData(f[f >= 10.0], p[f >= 10.0])
                return
            if mode == 'com' and self.x_off is not None:
                res = analyze_compare(self.x_off, x, fs, thr=self.sp_thr.value(), dthr=self.sp_cmp.value())
            else:
                res = analyze(x, fs, thr=self.sp_thr.value())
            xo, fso = win.noise_last_opt if getattr(win, 'noise_last_opt', None) else (None, 0.0)
            res['opt_mains'] = opt_mains(xo, fso, thr=self.sp_thr.value()) if xo is not None else []
            res['opt_ok'] = xo is not None and len(xo) >= SEG_S * fso
            self.res = res
            self._show()
            used = win.set_noise_detection(res, self.dur) if hasattr(win, 'set_noise_detection') else None
            stem = file_stem(win.ed_sample.text(), 'Ruido_fundo' + ('_comparativo' if mode == 'com' else ''))
            folder = win._save_dir()
            os.makedirs(folder, exist_ok=True)
            hdr = [f"Detectar ruidos de fundo - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                   f"Modo = {'comparativo (sem/com a fonte)' if mode == 'com' else 'rapido'}; laser em PWM 0; "
                   f"{self.dur:g} s por gravacao; INMP441 a {fs:.0f} S/s (media de 4 amostras)",
                   f'Welch Hann {SEG_S:g} s (resolucao {1 / SEG_S:g} Hz); fundo = mediana movel +-{BG_HALF_HZ:g} Hz; '
                   f'limiar {self.sp_thr.value():g} dB' + (f'; com a fonte >= {self.sp_cmp.value():g} dB acima'
                                                           if mode == 'com' else ''),
                   f'Celula = {win.cmb_cell.currentData()}']
            try:
                save_csv(os.path.join(folder, stem + '.csv'), res, hdr)
                save_bin(os.path.join(folder, stem + '.bin'), x)
                if mode == 'com':
                    save_bin(os.path.join(folder, stem + '_sem_fonte.bin'), self.x_off)
                self.lbl_file.setText(f'Salvo: {stem}.csv')
                self.lbl_file.setToolTip(os.path.join(folder, stem + '.csv'))
            except OSError as e:
                self.lbl_file.setText(f'Erro ao salvar: {e}')
            n = len(res['tones'])
            self.lbl.setText((f'{n} tom(ns) acima do fundo: {summary(res)}' if n else 'Nenhum tom acima do fundo.')
                             + (f' | {len(used)} faixa(s) excluída(s) das próximas varreduras' if used else ''))
            self.lbl.setToolTip(('Excluídas das próximas varreduras (caixa "Excluir ruídos detectados"): '
                                 + ', '.join(f'{v:g}' for v in used) + ' Hz') if used else '')
            if mode == 'com':
                self.x_off = None
                self.btn_on.setEnabled(False)

        def _plot_clicked(self, ev):
            if not ev.double() or ev.button() != QtCore.Qt.MouseButton.LeftButton:
                return
            vb = self.pw.getPlotItem().vb
            if vb.sceneBoundingRect().contains(ev.scenePos()):
                self._full_range()
                ev.accept()

        def _full_range(self):
            '''Espectro inteiro (de 10 Hz ao fim) e faixa de PSD dos dados mostrados.'''
            vb = self.pw.getPlotItem().vb
            if self._view is None:
                vb.enableAutoRange()
                return
            x0, x1, y0, y1 = self._view
            vb.setRange(xRange=(x0, x1), yRange=(y0, y1), padding=0.02)

        def _show(self):
            res = self.res
            f = res['f']
            sel = (f >= 10.0) & (f <= FMAX_HZ * 1.2)
            # Bins quase nulos viram -300 dB (piso do log): cortados 30 dB abaixo do 1o percentil para não esticar
            # o eixo y até lá
            curves = [res['p'][sel], res['bg'][sel]] + ([res['p_off'][sel]] if 'p_off' in res else [])
            allp = np.concatenate(curves)
            allp = allp[np.isfinite(allp)]
            if sel.any() and allp.size:
                lo = float(np.percentile(allp, 1)) - 30.0
                hi = float(allp.max())
                clip = lambda a: np.clip(a, lo, None)
                self.c_p.setData(f[sel], clip(res['p'][sel]))
                self.c_bg.setData(f[sel], clip(res['bg'][sel]))
                # Limites do zoom/arraste (x em log10 por causa do eixo log): não sai para escalas absurdas
                x0, x1 = np.log10(f[sel][0]), np.log10(f[sel][-1])
                self._view = (x0, x1, lo, hi + 5.0)
                self.pw.getPlotItem().vb.setLimits(xMin=x0 - 0.1, xMax=x1 + 0.1, yMin=lo - 40.0, yMax=hi + 40.0,
                                                   minXRange=0.002, minYRange=1.0)
                self._full_range()
            else:
                clip = lambda a: a
                self.c_p.setData([], [])
                self.c_bg.setData([], [])
            if 'p_off' in res:
                self.c_off.setData(f[sel], clip(res['p_off'][sel]))
            else:
                self.c_off.setData([], [])
            tr = rows(res)
            tm = [r for r in tr if r[4] != 'rede OPT101']          # no espectro do INMP441, só os tons dele
            self.c_t.setData([r[0] for r in tm], [res['p'][int(round((r[0] - f[0]) / (f[1] - f[0])))] for r in tm])
            self.c_sel.setData([], [])
            self.tbl.setRowCount(len(tr))
            names = {'rede': 'rede (60 Hz)', 'rede OPT101': 'rede (OPT101)', 'série': 'série', 'tom': 'tom'}
            for i, (fx, db, f0, k, kind) in enumerate(tr):
                vals = (f'{fx:.2f}', f'{db:.1f}', f'{f0:.2f}' if f0 else '', str(k) if k else '', _tr(names[kind]))
                for j, v in enumerate(vals):
                    it = QtWidgets.QTableWidgetItem(v)
                    if kind.startswith('rede'):
                        it.setForeground(pg.mkColor(130, 130, 130))
                    self.tbl.setItem(i, j, it)
            self.tbl.resizeColumnsToContents()
            self.btn_send.setEnabled(bool(tr))

        def _selected_f(self):
            tr = rows(self.res) if self.res else []
            idx = sorted({i.row() for i in self.tbl.selectedIndexes()})
            return [tr[i][0] for i in idx if i < len(tr)]

        def _sel_changed(self):
            if not self.res:
                return
            f = self.res['f']
            fs_ = self._selected_f()
            self.c_sel.setData(fs_, [self.res['p'][int(round((x - f[0]) / (f[1] - f[0])))] for x in fs_])

        def _send(self):
            if not self.res:
                return
            sel = self._selected_f() or [r[0] for r in rows(self.res)]
            vals = avoid_list_for(self.res, sel, self.chk_series.isChecked())
            if not vals:
                self.lbl.setText('Nada para gravar.')
                return
            added = win.add_avoid(vals)
            self.lbl.setText(f'Faixas excluídas (Hz) agora: {win.ed_dual_avoid.text()}' if added else
                             'Essas frequências já estavam no campo Faixas excluídas (Hz).')

        def closeEvent(self, ev):
            if self.mode is not None:
                self._stop('')
            super().closeEvent(ev)

    return NoiseDialog()
