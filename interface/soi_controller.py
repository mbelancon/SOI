# -*- coding: utf-8 -*-
'''
SOI Controller - LCTM (lock-in com Software PLL em Python + interface PyQt/pyqtgraph)

Dependências:  pip install pyqtgraph numpy scipy pyserial PySide6   (ou PyQt5/PyQt6)
Este é o arquivo que se roda. O código está dividido em módulos (só reorganização, 24/11/2026):
  soi_const (constantes), soi_analise (calibração, ajustes, diagnóstico), soi_dsp (lock-ins PyLockIn e AudioLockIn,
  referência externa), soi_serial (STM32), soi_sim (modo simulado), soi_widgets, soi_headless (modo sem janela),
  soi_comum (importa todos) e soi_win_* (métodos da janela por assunto, como mixins de LockInWindow).
  Aqui ficam __version__, LockInWindow (início, timer, status, configurações), o log e main().

Principais diferenças em relação à versão com Matplotlib:
  * pyqtgraph no lugar de Matplotlib (redesenho incremental, muito mais leve);
  * leitura serial em thread própria (nenhum byte é perdido se a GUI atrasar);
  * GUI dirigida por QTimer (sem while/sleep/flush_events);
  * processamento em lote com NumPy (sem laços Python por amostra);
  * osciloscópio com ring buffer e duas fatias (sem o laço de ERASE_GAP);
  * Modo Valor Médio vetorizado;
  * sem tkinter/matplotlib (executável PyInstaller menor).
'''
__version__ = '2.5.1'      # versão do SOI Controller (ver CHANGELOG.md)

import binascii
import bisect
import os
import re
import sys
import threading
import time
import warnings
import zipfile
from collections import deque, namedtuple
from datetime import datetime

import numpy as np
from scipy.signal import iirnotch, lfilter, sosfilt, sosfilt_zi
import serial
from serial.tools import list_ports

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from soi_comum import *  # noqa: F401,F403
import soi_headless
from soi_win_ui import UiMixin
from soi_win_dual_ui import DualUiMixin
from soi_win_cal import CalMixin
from soi_win_dual import DualMixin
from soi_win_dual_sweep import DualSweepMixin
from soi_win_comum import CommonMixin
from soi_win_dual_fit import DualPanelsMixin
from soi_win_opt import OptMixin
from soi_win_opt_sweep import OptSweepMixin
from soi_win_series import SeriesMixin
from soi_win_audio import AudioMixin


class LockInWindow(UiMixin, DualUiMixin, CalMixin, DualMixin, DualSweepMixin, CommonMixin, DualPanelsMixin, OptMixin, OptSweepMixin, SeriesMixin, AudioMixin,
                   QtWidgets.QMainWindow):
    version = __version__
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'SOI Controller {__version__} - LCTM')
        self.resize(1280, 1000)
        self.start_maximized = False          # load_settings: a janela foi fechada maximizada
        self.dual_prechecked = None           # varredura cujos avisos já foram confirmados antes do warm-up

        # --- Parâmetros ---
        self.ref_freq = 5.0
        self.laser_power = 0.4
        self.cutoff_hp = get_effective_cutoffs(self.ref_freq)[1]
        self.cutoff_lp = tau_cutoff(auto_tau(self.ref_freq), RATE.FS)
        self.normalize_mode = False

        # --- DSP do OPT101 (PyLockIn, definido neste arquivo) ---
        self.osr = OSR_DEFAULT                # sobreamostragem feita na interface (FS = RAW_FS / osr)
        self.dsp = PyLockIn(RATE.FS, self.ref_freq, self.cutoff_lp, self.cutoff_hp)
        self.rx_bytes = bytearray()
        self.rx_pos = 0                       # índice no fluxo óptico da primeira palavra de rx_bytes
        self.dsp_lock = threading.Lock()      # protege dsp e rx_bytes (thread do OPT101)
        # Modulação óptica (chopper): PLL no próprio OPT101 e alinhamento ADC↔I2S pelo farol do bit 15
        self.ext_mode = False
        self.ext_ref = ExternalReference()
        self.ext_sync = ExtTimeSync()
        self.audio_ext_pending = deque()      # áudio esperando a fase do OPT101 (thread do INMP441)
        self.audio_ext_drops = 0
        self.chopper_sim = None               # ChopperSimulator na simulação do modo óptico
        self._ext_resync_t = 0.0
        self._ext_tuned_f = None              # frequência em que os cortes automáticos foram aplicados
        self.opt_results = deque()

        # --- Lock-in do INMP441 (parâmetros próprios, independentes do OPT101) ---
        self.audio_freq = self.ref_freq
        self.audio_block_sec = AUDIO_LOCKIN_BLOCK / AUDIO_FS   # intervalo entre pontos plotados
        self.audio_max_points = AUDIO_MAX_POINTS
        self.audio_span = AUDIO_LOCKIN_SPAN
        self.audio_snr_db = None              # SNR da janela mais recente (alerta de sinal baixo)
        self.audio_snr_alert = LOW_SIGNAL_SNR_DB
        # Filtros do lock-in do INMP441: começam iguais aos do OPT101, mas são independentes
        self.audio_cutoff_lp = tau_cutoff(auto_tau(self.ref_freq), AUDIO_FS_REAL)
        self.audio_cutoff_hp = self.cutoff_hp
        self.audio_mains = False
        self.audio_lock = threading.Lock()    # protege o estado do áudio (thread do INMP441)

        # --- Dados ---
        self.raw = RawRing(5.0, RATE.FS)
        self.user_window = 5.0
        # FFT do sinal bruto do ADC (aba OPT101): histórico circular, só alimentado com a opção ligada
        self.opt_history = np.zeros(int(RATE.FS * OPT_FFT_HISTORY_SEC), dtype=np.float32)
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
        self.snr_opt_z = np.empty(0, dtype=np.complex128)
        self.phase_arr = np.empty(0, dtype=np.float32)
        self.lockin_dirty = False

        self.average_mode = False
        self.peak_hist = deque()
        self.avg = AverageAccumulator(RATE.FS)
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
        self.link = SerialLink(self._link_params)
        self.simulator = SignalSimulator()
        self.audio_sim = AudioSimulator()
        self.simulating = False
        self._sim_auto_t0 = time.perf_counter()   # o simulado automático espera a placa conectar por SIM_AUTO_DELAY_S
        self._pll_bad_since = None            # desde quando o PLL do OPT101 não trava (conectado)
        self.session_files = []               # arquivos salvos nesta sessão (ZIP do "Finalizar experimento")

        self._build_ui()
        self._install_double_click_reset()
        self.load_settings()
        # Só depois das preferências: a conexão envia F/P com a frequência restaurada, não com a padrão
        self.link.start()

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        # Medida em curso (varreduras, Modo Duplo, Medidas em Série): o Windows não suspende por inatividade
        self.keep_awake = False
        self.awake_timer = QtCore.QTimer(self)
        self.awake_timer.timeout.connect(self._update_keep_awake)
        self.awake_timer.start(2000)
        # Modo leve (Configurações): menos quadros por segundo, osciloscópio com menos pontos e o lock-in do INMP441
        # parado enquanto nada o usa. Só afeta o desenho e o consumo de CPU, não os dados medidos.
        v = QtCore.QSettings('LCTM', 'SOI Controller').value('light_mode')
        self.light_mode = str(v).lower() in ('true', '1')
        self.timer.start(LIGHT_GUI_INTERVAL_MS if self.light_mode else GUI_INTERVAL_MS)

        self._start_audio_rec()
        self.opt_thread = StepThread(self._optical_step)
        self.audio_thread = StepThread(self._audio_step)
        self.opt_thread.start()
        self.audio_thread.start()

    # ------------------------------------------------------------------ UI

    def event(self, ev):
        # Rede de segurança do Windows: janela maximizada cujo conteúdo muda de tamanho (painel aberto, aviso) às vezes
        # fica maior que a tela até o usuário restaurar e maximizar de novo. Confere 0,4 s depois de cada mudança de
        # layout e, se a moldura passou da área útil da tela, faz o mesmo restaurar + maximizar.
        if ev.type() == QtCore.QEvent.Type.LayoutRequest and self.isMaximized():
            t = getattr(self, '_max_fit_timer', None)
            if t is None:
                t = self._max_fit_timer = QtCore.QTimer(self)
                t.setSingleShot(True)
                t.timeout.connect(self._check_max_fit)
            t.start(400)
        return super().event(ev)

    def _check_max_fit(self):
        if not self.isMaximized() or self.isFullScreen():
            return
        scr = self.screen() or QtWidgets.QApplication.primaryScreen()
        if scr is None:
            return
        a, f = scr.availableGeometry(), self.frameGeometry()
        over = f.width() > a.width() + 16 or f.height() > a.height() + 16
        fits = self.minimumSizeHint().width() <= a.width() and self.minimumSizeHint().height() <= a.height()
        now = time.monotonic()
        if over and fits and now - getattr(self, '_last_remax', 0.0) > 3.0:
            self._last_remax = now
            print(f'Janela maximizada maior que a tela ({f.width()}x{f.height()} > {a.width()}x{a.height()}): '
                  'restaurando e maximizando de novo.')
            self.showNormal()
            self.showMaximized()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        # A largura muda a quebra dos textos do painel Calibração e, com ela, a altura do quadro
        if getattr(self, 'dual_cal_scroll', None) is not None and self.dual_cal_scroll.isVisible():
            QtCore.QTimer.singleShot(0, self._fit_dual_cal_scroll)

    def tick(self):
        now = time.perf_counter()

        # 1. Conexão e simulação (o processamento roda nas threads do OPT101 e do INMP441)
        # Caixa de simulação só aparece sem STM32; se o STM32 conectar, a simulação é desligada.
        connected = self.link.connected
        if connected != self.audio_link_connected:
            self.audio_link_connected = connected
            if self.ext_mode:
                self._ext_restart()
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
        # Modo simulado automático (2.5.0, sem a caixa "Simular amostragem"): sem STM32 a interface simula; com a
        # placa, usa a placa. Não entra no simulado durante uma medida (uma queda da USB não vira dado simulado) nem
        # no modo sem janela (lá só com --simulado).
        if connected and self.chk_sim.isChecked():
            self.chk_sim.setChecked(False)
        elif (not connected and not self.chk_sim.isChecked() and not getattr(self, 'headless', False)
              and now - self._sim_auto_t0 >= SIM_AUTO_DELAY_S and not self._measuring()):
            self.chk_sim.setChecked(True)
        if self.simulating and not connected:
            chop = self.chopper_sim if self.ext_mode else None
            with self.dsp_lock:
                first = self.simulator.n
                optical_data = self.simulator.generate(now, self.ref_freq, self.laser_power, chop)
                if optical_data:
                    if not self.rx_bytes:
                        self.rx_pos = first
                    self.rx_bytes.extend(optical_data)
                
        # 5. Atualização dos gráficos e status do áudio
        self._update_audio_plots(now)
        if now - getattr(self, 'last_audio_status_t', 0.0) >= 2.0:
            self.last_audio_status_t = now
            self._update_audio_status(now)
            text = getattr(self, 'audio_noise_text', None)
            if text and self.lbl_audio_noise.text() != soi_i18n.tr(text):
                self.lbl_audio_noise.setText(text)
            # 2.5.0 (Marcos, 25/11): sem o quadro de valores do fit nas FFTs do INMP441 e do OPT101 (o SNR pico/piso dele não é o
            # do lock-in e confundia); ficam a curva do fit e o aviso de pico ausente
            self._show_fft_fit(self.txt_audio_fft_fit, self.lbl_audio_fft_missing,
                               self.audio_fft_enabled and self.chk_audio_fft_fit.isChecked(),
                               None, self.audio_fft_missing)
            self._show_fft_fit(self.txt_opt_fft_fit, self.lbl_opt_fft_missing,
                               self.opt_fft_enabled and self.chk_opt_fft_fit.isChecked(),
                               None, self.opt_fft_missing)      # 2.5.0: sem o quadro de valores (como no INMP441)

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
                if getattr(self, 'noise_cap_opt', None) is not None:      # Detectar ruídos: OPT101 junto
                    self.noise_cap_opt.append(np.array(adc, dtype=np.float32))
                if wrapped and not self.chk_scope_fixed.isChecked():
                    self._autoscale_raw()
                if self.average_mode and self.avg.push(adc, ref):
                    self.avg_dirty = True
                    self.avg_ready_n = getattr(self, 'avg_ready_n', 0) + 1   # médias prontas (Medidas em Série)
                self.peak_hist.append((now, float(np.max(adc))))
                while now - self.peak_hist[0][0] > 1.0:
                    self.peak_hist.popleft()
                raw_dirty = True

            if n_dec > 0 and not self.average_mode:
                r_new = np.array(res.r, dtype=np.float64)
                p_new = np.array(res.phase, dtype=np.float64)
                self.r_arr = np.concatenate((self.r_arr, r_new.astype(np.float32)))[-MAX_POINTS:]
                z_new = r_new * np.exp(1j * np.radians(p_new))
                self.snr_opt_z = np.concatenate((getattr(self, 'snr_opt_z', np.empty(0, np.complex128)),
                                                 z_new))[-int(SNR_TOP_MAX_S * LOCKIN_OUT_HZ):]
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
            if self.light_mode:
                # Só o desenho: um ponto a cada 'k' (a referência 0/1 e o sinal usam o mesmo passo)
                def cut(s):
                    k = max(1, (s.stop - s.start) // LIGHT_SCOPE_POINTS)
                    return slice(s.start, s.stop, k)
                sa = cut(sa)
                if sb is not None:
                    sb = cut(sb)
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
            x = (np.arange(n) - (n - 1)) * (RATE.DECIMATION / RATE.FS)
            self.line_r.setData(x, self.r_arr)
            self.line_phase.setData(x, self.phase_arr)
            if now - self.last_range_t >= RANGE_INTERVAL and len(self.r_arr) > 0:
                self.last_range_t = now
                self.plot1.getPlotItem().setYRange(0, max(0.01, float(self.r_arr.max()) * 1.10), padding=0)

        if now - self.last_status_t >= STATUS_INTERVAL:
            self.last_status_t = now
            self.update_status(now)
            self.update_window_status()
            if self.ext_mode:
                self._ext_follow(now)

    def mod_warning(self):
        '''Aviso quando a modulação passa do limite seguro para a taxa atual (FS = 200 kHz/OSR).
        Até FS/4 (>= 4 amostras por período, média do OSR atenua < 10 %) é seguro; até 0,4·FS a medida
        ainda sai corrigida, mas com pouca margem; acima disso a média do OSR quase anula a fundamental
        (zero em FS) e o PLL tem poucas amostras por período. Devolve (texto, nível 0/1/2).'''
        f = self.ref_freq
        if f <= 0:
            return '', 0
        safe = [o for o in OSR_CHOICES if f <= RAW_FS / o / 4.0]
        hint = f'use OSR {max(safe)}x ou menor' if safe else 'reduza a frequência'
        if f > 0.4 * RATE.FS:
            return f'Modulação acima do limite para OSR {self.osr}x (seguro até {RATE.FS / 4:.0f} Hz): {hint}', 2
        if f > RATE.FS / 4.0:
            return f'Modulação perto do limite para OSR {self.osr}x (seguro até {RATE.FS / 4:.0f} Hz): {hint}', 1
        if f > 1000.0 and self.laser_power < 100.0:
            return 'Acima de 1 kHz use PWM 100 % (a portadora de 5 kHz tem poucos ciclos por meio período)', 1
        return '', 0

    def _ext_status_short(self):
        r = self.ext_ref
        if r.state == 'TRACK' and r.f_mean is not None:
            return (f"Ref. óptica: {r.f_mean:.2f} Hz " + ('(travada)' if r.locked else '<b>(travando)</b>'))
        return '<b>Ref. óptica: procurando</b>'

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
                    f'Ciclo atual: {self.avg.current_len() / RATE.FS:.3f} s')
            color = OK_COLOR
        else:
            while self.peak_hist and now - self.peak_hist[0][0] > 1.0:
                self.peak_hist.popleft()
            dc = self.dsp.dc_offset / ADC_OVS_FACTOR
            peak = max((v for _, v in self.peak_hist), default=0.0)
            sat = self._sat_counts()
            pct = peak / sat * 100.0                       # % do teto (OPT101 com 3,3 V, ADC com 5 V)
            over = pct >= OPT_PCT_RED
            if dc > 0.95 * ADC_FULL_SCALE or peak >= 0.995 * ADC_FULL_SCALE:
                status = "<b>[SATURAÇÃO DO ADC]</b>"
                color = ALERT_COLOR
            elif over:
                status = ("<b>[SATURAÇÃO DO OPT101]</b>" if pct >= 100.0 and self.opt_supply < 4 else
                          "<b>[Perto da saturação do OPT101]</b>" if self.opt_supply < 4 else
                          "<b>[Perto do limite do ADC]</b>")
                color = ALERT_COLOR if pct >= 100.0 else WARN_COLOR
            elif dc < 0.05 * sat:
                status = "[Sinal baixo: nível médio &lt; 5 % do teto]"
                color = WARN_COLOR
            else:
                status = "[Sinal OK]"
                color = OK_COLOR
            vcolor = '#006400' if pct < OPT_PCT_ORANGE else ('#e07000' if not over else '#d00000')
            self.txt_sat.setVisible(over)
            if over:
                (x0, x1), (y0, y1) = self.plot_raw.getPlotItem().vb.viewRange()
                self.txt_sat.setPos((x0 + x1) / 2, (y0 + y1) / 2)
            v_peak = f'{peak / ADC_FULL_SCALE * ADC_VREF:.2f}'.replace('.', ',')
            text = (f"Status: {status} | Pico: <span style='color:{vcolor};font-weight:bold;'>"
                    f"{pct:.1f} %</span> ({v_peak} V) | " + (self._ext_status_short() if self.ext_mode else
                                                f"Freq Real (PLL): {self.dsp.measured_freq:.2f} Hz"
                                                if self.dsp.pll_locked or self.ref_freq <= 0 else
                                                "<b>PLL destravado</b>")
                    + f" | {RATE.FS / 1000:g} kS/s (OSR {self.osr})")
            lost = self.link.opt_lost_samples if self.link.connected else 0
            if lost:
                text += (f" | <span style='color:#d00000;'>Perdas USB: {lost} amostras "
                         f"({self.link.opt_gap_events}x)</span>")

        warn, level = self.mod_warning()
        if warn and (self.link.connected or self.simulating):
            wcolor = '#d00000' if level == 2 else '#b05000'
            text += f" | <span style='color:{wcolor};font-weight:bold;'>{warn}</span>"
            if color == OK_COLOR or level == 2:
                color = ALERT_COLOR if level == 2 else WARN_COLOR
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
                 'sp_dual_p0', 'sp_dual_p1', 'sp_dual_dp',
                 'sp_dual_m_f0', 'sp_dual_m_f1', 'sp_dual_m_fn',
                 'sp_dual_tau_p', 'sp_dual_flat_tol', 'sp_dual_tau_sensor',
                 'sp_dual_thick', 'sp_dual_model_f0', 'sp_dual_model_f1', 'sp_dual_model_n',
                 'sp_cal_L', 'sp_cal_alpha', 'sp_cal_n', 'sp_dual_std_fmax', 'sp_dual_std_fmin',
                 'sp_cal_a_L', 'sp_cal_b_L', 'sp_dual_adapt_tol', 'sp_dual_reps', 'sp_dt_f', 'sp_dt_pwm', 'sp_dt_tau', 'sp_dt_dt',
                 'sp_dt_dur', 'sp_opt_tau', 'sp_opt_tol', 'sp_opt_reps', 'sp_ot_f', 'sp_ot_pwm', 'sp_ot_tau', 'sp_ot_dt',
                 'sp_ot_dur')
        checks = ('chk_audio_lockin', 'chk_audio_noise', 'chk_audio_fft', 'chk_audio_fft_fit',
                  'chk_audio_fft_full', 'btn_audio_sweeps',
                  'chk_opt_fft', 'chk_opt_fft_fit', 'chk_opt_fft_full', 'btn_opt_sweeps', 'btn_dual_sweeps_panel', 'btn_dual_pwm_panel', 'btn_dual_p_panel', 'btn_dual_t_panel', 'chk_dual_std_phase',
                  'chk_dual_norm', 'chk_dual_sensors', 'chk_dual_adapt', 'chk_opt_adapt',
                  'chk_dual_cal_err', 'chk_dual_out_red', 'chk_dual_nb', 'chk_dual_warm_noise')
        # cmb_cal_ref antes de cmb_cell: a referência escolhe a célula, e a célula salva prevalece
        combos = ('cmb_osr', 'cmb_dual_mode_p', 'cmb_dual_m_fspace', 'cmb_dual_model', 'cmb_dual_model_target',
                  'cmb_dual_p_deg', 'cmb_dual_p_target', 'cmb_dual_order', 'cmb_opt_fspace', 'cmb_opt_order',
                  'cmb_cal_ref', 'cmb_cal_a', 'cmb_cal_b')   # cmb_cell fora (2.5.0: só a Câmara)
        return spins, checks, combos

    def _fit_to_screen(self):
        '''Limita tamanho e posição à área útil da tela: a geometria salva pode ter vindo de outro monitor
        ou de outra escala do Windows, e uma janela maior que a tela gera aviso do Qt (setGeometry).'''
        if self.isMaximized() or self.isFullScreen():
            return                                      # resize() numa janela maximizada corta o lado direito
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
            # 2.5.0: passa-altas sem campo na tela; fica no automático da frequência (um valor manual antigo não volta)
            for name in ('sp_tau', 'sp_audio_tau'):
                v = num(name)
                if v is not None:
                    getattr(self, name).setValue(v)
            # Sem o botão Avançado: um τ do sensor salvo (≠ 0) deixa a linha à vista, para não corrigir escondido
            if self.sp_dual_tau_sensor.value() > 0:
                self.btn_dual_adv.setChecked(True)
            # τ da varredura (τ / τ max, ligado ao do INMP441): abre com o último valor usado (Marcos, 17/11); sem
            # valor salvo, o recomendado
            tau0 = num('dual_sweep_tau')
            if tau0 is None or tau0 <= 0:
                tau0 = ADAPT_TAU0_DEF if self.chk_dual_adapt.isChecked() else SWEEP_TAU_DEF
            if st.value('sweep_defaults_20261119') is None:   # padrão aprovado em 19/11: embaralhada, τ 1 s, 3× (uma vez)
                self.cmb_dual_order.setCurrentIndex(2)
                self.sp_dual_reps.setValue(SWEEP_REPS_DEF)
                self.chk_dual_adapt.setChecked(False)
                tau0 = SWEEP_TAU_DEF
                st.setValue('sweep_defaults_20261119', 1)
            if st.value('sweep_defaults_20261126') is None:   # padrões da célula nova (bateria de 26/11; uma vez)
                self.chk_dual_adapt.setChecked(True)
                self.cmb_dual_order.setCurrentIndex(0)        # crescente
                self.sp_dual_reps.setValue(SWEEP_REPS_DEF)
                for sp in (self.sp_dual_p0, self.sp_p0, self.sp_aud_p0):
                    sp.setValue(max(sp.value(), PWM_SWEEP_START_DEF))
                tau0 = ADAPT_TAU0_DEF
                st.setValue('sweep_defaults_20261126', 1)
            if st.value('sweep_f0_4hz_20261126') is None:     # início padrão em 4 Hz (Marcos 26/11; uma vez)
                for sp in (self.sp_dual_f0, self.sp_dual_m_f0, self.sp_f0, self.sp_aud_f0):
                    sp.setValue(SWEEP_F0_DEF)
                st.setValue('sweep_f0_1hz_20261125', 1)
                st.setValue('sweep_f0_4hz_20261126', 1)
            if st.value('nb_default_off_20261119') is None:   # descarte por vizinhas: desligado por padrão (uma vez)
                self.chk_dual_nb.setChecked(False)
                st.setValue('nb_default_off_20261119', 1)
            if st.value('sweep_defaults_20261118') is None:   # padrão da campanha de ruído (uma vez)
                self.chk_dual_adapt.setChecked(False)
                self.sp_dual_reps.setValue(SWEEP_REPS_DEF)
                tau0 = SWEEP_TAU_DEF
                st.setValue('sweep_defaults_20261118', 1)
            self._set_spin(self.sp_dual_tau_f, tau0)
            self._on_sweep_tau_edit('F', tau0)
            v = st.value('show_nb')
            self.set_show_nb(str(v).lower() in ('1', 'true') if v is not None else False)
            v = st.value('dual_avoid')
            if v is not None:
                self.ed_dual_avoid.setText(str(v))
            v = st.value('opt_avoid')
            if v is not None:
                self.ed_opt_avoid.setText(str(v))
            if st.value('opt_sweeps_20261127') is None:       # varreduras do OPT101 no padrão do Modo Duplo (uma vez)
                self.cmb_opt_fspace.setCurrentIndex(0)
                self.sp_df.setValue(float(CAL_SWEEP_N))
                self.sp_f0.setValue(SWEEP_F0_DEF)
                self.sp_f1.setValue(CAL_SWEEP_F1)
                self.cmb_opt_order.setCurrentIndex(0)
                self.chk_opt_adapt.setChecked(True)
                self.sp_opt_tau.setValue(ADAPT_TAU_CAP)
                self.sp_opt_reps.setValue(SWEEP_REPS_DEF)
                st.setValue('opt_sweeps_20261127', 1)
            if st.value('pwm_start_40_20261127') is None:     # início padrão 30 -> 40 %; valores editados ficam (uma vez)
                for sp in (self.sp_dual_p0, self.sp_p0, self.sp_aud_p0):
                    if abs(sp.value() - 30.0) < 1e-6:
                        sp.setValue(PWM_SWEEP_START_DEF)
                st.setValue('pwm_start_40_20261127', 1)
            self._on_opt_adapt(self.chk_opt_adapt.isChecked())
            v = st.value('sample_name')
            if v is not None:
                self.ed_sample.setText(str(v))
            v = num('opt_supply')
            if v is not None:
                self.opt_supply = 5.0 if v > 4 else 3.3
            v = st.value('scope_fixed_33v')
            if v is not None:
                self.chk_scope_fixed.setChecked(str(v).lower() in ('true', '1'))
            self._apply_scope_scale()
            self._apply_adapt_ui()
            lv = st.value('dual_layout')
            if lv in ('side', 'stacked', 'overlay'):
                self.set_dual_layout(lv)
            fr = st.value('dual_float_rel')
            try:
                fx, fy = (float(x) for x in str(fr).split(','))
                self.dual_float.rel = (min(max(fx, 0.0), 1.0), min(max(fy, 0.0), 1.0))
            except (TypeError, ValueError):
                pass
            for key, sec in self.side_sections.items():
                v = st.value('sec_' + key)
                if v is not None:
                    sec.set_open(str(v).lower() in ('1', 'true'))
            for name in ('main_split', 'opt_split'):
                v = st.value(name)
                if v is not None:
                    getattr(self, name).restoreState(v)
            v = st.value('scope_open')
            if v is not None:
                self.btn_scope.setChecked(str(v).lower() in ('1', 'true'))
            geo = st.value('geometry')
            if geo is not None:
                self.restoreGeometry(geo)
            # Maximizada: guarda só a intenção e abre normal; main() chama showMaximized() depois do show().
            # Restaurar já maximizada (antes de a janela existir) fazia o Windows com escala alta desenhar o
            # conteúdo com o tamanho errado até o usuário restaurar e maximizar de novo.
            self.start_maximized = self.isMaximized()
            if self.start_maximized:
                self.setWindowState(self.windowState() & ~QtCore.Qt.WindowState.WindowMaximized)
            self._fit_to_screen()
            v = num('tab')
            if v is not None:
                self.tabs.setCurrentIndex(int(v))
            if st.value('adapt_tol_2pct') is None:      # 2.3.0: Precisão padrão passou de 1 % para 2 % (uma vez)
                self.sp_dual_adapt_tol.setValue(ADAPT_TOL_DEF)
                st.setValue('adapt_tol_2pct', 1)
        except Exception as e:
            print(f'Preferências ignoradas ({e})')

    def save_settings(self):
        st = QtCore.QSettings('LCTM', 'SOI Controller')
        spins, checks, combos = self._settings_widgets()
        for name in spins + ('sp_tau', 'sp_hp', 'sp_audio_tau', 'sp_audio_hp'):
            st.setValue(name, float(getattr(self, name).value()))
        for name in checks:
            st.setValue(name, bool(getattr(self, name).isChecked()))
        for name in combos:
            st.setValue(name, int(getattr(self, name).currentIndex()))
        st.setValue('dual_sweep_tau', float(self.sp_dual_tau_f.value()))
        st.setValue('sample_name', self.ed_sample.text())
        st.setValue('dual_avoid', self.ed_dual_avoid.text())
        st.setValue('opt_avoid', self.ed_opt_avoid.text())
        st.setValue('show_nb', int(self.show_nb))
        st.setValue('opt_supply', self.opt_supply)
        st.setValue('scope_fixed_33v', bool(self.chk_scope_fixed.isChecked()))
        st.setValue('geometry', self.saveGeometry())
        st.setValue('dual_layout', self.dual_layout)
        st.setValue('dual_float_rel', '%.4f,%.4f' % self.dual_float.rel)
        st.setValue('tab', self.tabs.currentIndex())
        # 2.5.0: seções do painel lateral, osciloscópio recolhido, largura do painel e divisão da aba OPT101
        for key, sec in self.side_sections.items():
            st.setValue('sec_' + key, int(sec.is_open()))
        st.setValue('scope_open', int(self.btn_scope.isChecked()))
        st.setValue('main_split', self.main_split.saveState())
        if self.btn_scope.isChecked():
            st.setValue('opt_split', self.opt_split.saveState())

    def _measuring(self):
        '''Há uma medida em curso que a suspensão do PC interromperia?'''
        st = getattr(self, 'series_tab', None)
        return bool(getattr(self, 'sweep_active', False) or getattr(self, 'dual_active', False)
                    or getattr(self, 'dual_rep', None)                    # entre duas repetições
                    or getattr(self, 'opt_rep', None)
                    or getattr(self, 'warm_state', None) is not None      # warm-up antes da varredura
                    or (st is not None and st.runner.active))             # Medidas em Série (também entre etapas)

    def _update_keep_awake(self):
        busy = self._measuring()
        if busy == self.keep_awake:
            return
        self.keep_awake = busy
        ok = keep_system_awake(busy)
        if busy and ok:
            self.flash('Medida em curso: o Windows não vai suspender nem apagar a tela até ela terminar '
                       '(não feche a tampa do notebook).', 6.0)
        print('Medida em curso: suspensão e desligamento da tela bloqueados.' if busy else
              'Fim das medidas: suspensão do Windows liberada.', flush=True)

    def closeEvent(self, event):
        if getattr(self, 'series_tab', None) is not None and self.series_tab.runner.active:
            ans = QtWidgets.QMessageBox.question(
                self, 'Medidas em Série', 'Uma medida em série está em andamento. Parar a série (salvando o que já '
                'foi medido) e fechar?', QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No)
            if ans != QtWidgets.QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.series_tab.on_close()
        try:
            # Durante uma varredura os campos guardam o ponto atual, não a escolha do usuário
            if not self.sweep_active and not self.dual_active:
                self.save_settings()
        except Exception as e:
            print(f'Preferências não salvas ({e})')
        self.timer.stop()
        self.awake_timer.stop()
        keep_system_awake(False)
        self.opt_thread.stop()
        self.audio_thread.stop()
        if self.audio_rec is not None:
            self.audio_rec.close()
        self.link.stop()
        for w in self.result_windows:
            w.close()
        super().closeEvent(event)


LOG_DIR = os.path.join(os.path.dirname(MEDIDAS_DIR), 'logs')
LOG_MAX_BYTES = 2_000_000       # soi.log passa a soi.log.1 (… até .3) ao abrir, se já tiver este tamanho


class _LogTee:
    """Cópia de stdout/stderr no arquivo de log, com data e hora em cada linha. Sem terminal (pythonw),
    sys.stdout é None e só o arquivo recebe o texto."""
    def __init__(self, stream, fh, tag=''):
        self.stream, self.fh, self.tag = stream, fh, tag
        self.lock = threading.Lock()
        self.bol = True

    def write(self, text):
        if self.stream is not None:
            try:
                self.stream.write(text)
            except Exception:
                pass
        with self.lock:
            try:
                out = []
                for part in text.splitlines(True):
                    if self.bol:
                        out.append(datetime.now().strftime('%Y-%m-%d %H:%M:%S ') + self.tag)
                    out.append(part)
                    self.bol = part.endswith('\n')
                self.fh.write(''.join(out))
                self.fh.flush()
            except Exception:
                pass
        return len(text)

    def flush(self):
        for f in (self.stream, self.fh):
            try:
                f and f.flush()
            except Exception:
                pass

    def isatty(self):
        return False

    def reconfigure(self, **kw):
        if self.stream is not None and hasattr(self.stream, 'reconfigure'):
            self.stream.reconfigure(**kw)


def setup_log():
    """Arquivo de log interface/logs/soi.log: tudo o que ia para o terminal (prints, avisos, erros com traceback,
    mensagens do Qt). Gira ao abrir quando passa de 2 MB (guarda soi.log.1 a .3)."""
    import traceback
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        path = os.path.join(LOG_DIR, 'soi.log')
        if os.path.exists(path) and os.path.getsize(path) > LOG_MAX_BYTES:
            for i in (3, 2, 1):
                src = path + (f'.{i - 1}' if i > 1 else '')
                if os.path.exists(src):
                    os.replace(src, f'{path}.{i}')
        fh = open(path, 'a', encoding='utf-8', errors='replace')
    except OSError:
        return None
    sys.stdout = _LogTee(sys.stdout, fh)
    sys.stderr = _LogTee(sys.stderr, fh, 'ERRO: ')

    def hook(et, ev, tb):
        print('Exceção não tratada:\n' + ''.join(traceback.format_exception(et, ev, tb)), file=sys.stderr)
    sys.excepthook = hook                       # também evita que o PyQt feche o programa num erro em um slot
    threading.excepthook = lambda a: hook(a.exc_type, a.exc_value, a.exc_traceback)

    def qt_msg(mode, ctx, msg):
        if 'propagateSizeHints' not in msg:
            print(f'Qt: {msg}', file=sys.stderr if mode != QtCore.QtMsgType.QtInfoMsg else sys.stdout)
    QtCore.qInstallMessageHandler(qt_msg)
    print(f"===== SOI Controller {__version__} ({'executável' if getattr(sys, 'frozen', False) else sys.executable}"
          f"{' ' + ' '.join(sys.argv[1:]) if sys.argv[1:] else ''}) =====")
    return path


def main():
    import multiprocessing
    multiprocessing.freeze_support()      # executável (PyInstaller): o processo leitor da serial
    setup_log()
    if any(k in sys.argv[1:] for k in ('--varredura', '--sinal-t', '--serie', '--detectar-ruido', '-h', '--help')):
        sys.exit(soi_headless.run_headless(sys.argv[1:], LockInWindow))
    if sys.platform == 'win32':
        # Sem isto, rodando pelo python.exe, a barra de tarefas mostra o ícone do Python.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f'LCTM.SOIController.{__version__}')
        except Exception:
            pass
    app = pg.mkQApp("SOI Controller - LCTM")
    icon = app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)           # janela principal, diálogos e barra de tarefas
    win = LockInWindow()
    win.show()                            # primeiro normal (geometria já cabe na tela), depois maximiza
    if win.start_maximized:
        win.showMaximized()
    # Aviso único se o Arduino não estiver ligado na abertura (não bloqueia a GUI).
    QtCore.QTimer.singleShot(2500, win.warn_not_found)
    sys.exit(app.exec())


if __name__ == '__main__':
    main()