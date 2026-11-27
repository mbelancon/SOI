# -*- coding: utf-8 -*-
'''Aba OPT101: teste de resolução, sobreamostragem, τ, ajuste do transiente, varreduras e FFT.

Métodos da janela principal (LockInWindow em soi_controller.py), separados por assunto.'''
from soi_comum import *  # noqa: F401,F403


class OptMixin:
    def set_osr(self, osr):
        '''Troca a sobreamostragem (média de osr amostras cruas): refaz FS, DECIMATION e tudo que depende
        da taxa (lock-in, osciloscópio, FFT, modo valor médio). Não mexe no STM32.'''
        osr = int(osr)
        if osr == self.osr:
            return
        if self.sweep_active or self.dual_active:
            self.cmb_osr.blockSignals(True)
            self.cmb_osr.setCurrentIndex(OSR_CHOICES.index(self.osr))
            self.cmb_osr.blockSignals(False)
            self.flash('A sobreamostragem não pode mudar durante uma varredura.')
            return
        with self.dsp_lock:
            self.osr = osr
            RATE.FS = RAW_FS / osr
            RATE.DECIMATION = max(1, int(round(RATE.FS / LOCKIN_OUT_HZ)))
            # descarta o resto que não fecha um bloco do OSR antigo (mantém o alinhamento em palavras)
            self.cutoff_lp = tau_cutoff(self.sp_tau.value(), RATE.FS)
            mains = self.dsp.mains_enabled
            self.dsp.init(RATE.FS, self.ref_freq, self.cutoff_lp, self.cutoff_hp)
            self.dsp.set_mains_filter(mains)
            self.opt_results.clear()
            self.ext_ref.reset()
        self.raw.set_fs(RATE.FS)
        for c in (self.c_adc_a, self.c_adc_b, self.c_ref_a, self.c_ref_b):
            c.setData([], [])
        self.opt_history = np.zeros(int(RATE.FS * OPT_FFT_HISTORY_SEC), dtype=np.float32)
        self.opt_write_index = 0
        self.opt_valid_samples = 0
        self.last_opt_fft_t = 0.0
        self.avg.fs = RATE.FS
        self.set_pretrigger(self.average_pretrigger_sec)
        self.reset_average()
        self.r_arr = np.empty(0, dtype=np.float32)
        self.snr_opt_z = np.empty(0, dtype=np.complex128)
        self.phase_arr = np.empty(0, dtype=np.float32)
        self.lockin_span = MAX_POINTS * RATE.DECIMATION / RATE.FS
        if not self.average_mode:
            self.plot1.getPlotItem().setXRange(-self.lockin_span, 0, padding=0)
        self.line_r.setData([], [])
        self.line_phase.setData([], [])
        self.update_tau_labels()
        self.update_opt_fft_range()
        self.flash(f'Sobreamostragem {osr}x: {RATE.FS / 1000:g} kS/s no OPT101 (lock-in, osciloscópio, FFT e Valor Médio). O INMP441 não muda.', 4.0)

    def on_tau(self, tau):
        self.cutoff_lp = tau_cutoff(tau, RATE.FS)
        with self.dsp_lock:
            self.dsp.update_params(self.ref_freq, self.cutoff_lp, self.cutoff_hp)
        self.update_tau_labels()

    @staticmethod
    def _filter_row(lay, sp_tau, sp_hp):
        '''τ do passa-baixas, valores derivados dele (−3 dB, ENBW, espera) e passa-altas de um lock-in, com
        dicas. Devolve o rótulo dos valores derivados.'''
        lbl_tau = QtWidgets.QLabel()
        if isinstance(lay, QtWidgets.QGridLayout):
            # 2.5.0 (Marcos, 25/11): no painel lateral só o τ. O passa-altas continua agindo, automático (2 % de f,
            # 0,01–0,05 Hz), sem campo na tela; −3 dB, ENBW e espera vão para a dica do τ (update_tau_labels)
            lbl = QtWidgets.QLabel('τ:')
            lbl.setToolTip(TAU_TIP)
            sp_tau.setToolTip(TAU_TIP)
            sp_tau.tau_info_tip = True
            lay.addWidget(lbl, 0, 0)
            lay.addWidget(sp_tau, 0, 1)
            lay.setColumnStretch(1, 1)
            sp_hp.setToolTip(HP_TIP)
            return lbl_tau
        lbl_tau.setMinimumWidth(250)
        for text, w, tip in (('τ:', sp_tau, TAU_TIP), (None, lbl_tau, LP_INFO_TIP),
                             ('Passa-Altas (Hz):', sp_hp, HP_TIP)):
            if text:
                lbl = QtWidgets.QLabel(text)
                lbl.setToolTip(tip)
                lay.addWidget(lbl)
            w.setToolTip(tip)
            lay.addWidget(w)
            if w is lbl_tau:
                lay.addSpacing(12)
        return lbl_tau

    def update_tau_labels(self):
        '''Atualiza o corte −3 dB, a ENBW e a espera exibidos ao lado do τ de cada lock-in.'''
        from soi_i18n import tr
        for lbl, sp, cut, fs in (('lbl_tau', 'sp_tau', 'cutoff_lp', RATE.FS),
                                 ('lbl_audio_tau', 'sp_audio_tau', 'audio_cutoff_lp', AUDIO_FS_REAL)):
            if not hasattr(self, lbl):
                continue
            info = fmt_lp_info(lp_tau(getattr(self, cut), fs))
            getattr(self, lbl).setText(info)
            w = getattr(self, sp, None)
            if getattr(w, 'tau_info_tip', False):            # 2.5.0: valores derivados na dica do τ
                w.setToolTip(tr(TAU_TIP) + '\n\n' + tr(info))

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
            ax = p1.getAxis('bottom')
            ax.base_label, ax._unit = 'Tempo desde o início do pulso', 's'
            self.line_r.setData([], [])
            self.line_r.setSymbol(None)
            p1.setLabel('left', 'ADC médio')
            p1.setLabel('bottom', 'Tempo desde o início do pulso (s)')
            p1.getAxis('bottom').lockin_time = True
            p1.setTitle('Forma de Onda Média do ADC')
            p1.setXRange(-self.average_pretrigger_sec, 1.0 / max(self.ref_freq, 0.1), padding=0)
        else:
            self.line_ref_avg.setVisible(False)
            self.line_phase.setVisible(True)
            self.phase_vb.setYRange(-180, 180, padding=0)
            p1.showAxis('right')
            p1.getAxis('bottom').lockin_time = True
            p1.getAxis('bottom').base_label = TimeAxis.base_label
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
                self.dsp.init(RATE.FS, self.ref_freq, self.cutoff_lp, self.cutoff_hp)
            self.r_arr = np.empty(0, dtype=np.float32)
            self.snr_opt_z = np.empty(0, dtype=np.complex128)
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
        if self._sweep_new():
            self.sweep_settle_time, self.sweep_measure_time = self._opt_times(
                self.sweep_kind, self.sweep_freqs[self.sweep_idx], 'est')
            return
        self.sweep_settle_time, self.sweep_measure_time = self._times_for_cutoff(self.cutoff_lp)

    def _sweep_new(self):
        '''Varredura do OPT101 no padrão novo (2.5.1)? Falso no INMP441 e nas Medidas em Série (comportamento antigo).'''
        return (getattr(self, 'sweep_target', 'OPT') == 'OPT' and not getattr(self, 'sweep_legacy', True)
                and getattr(self, 'sweep_kind', 'F') in ('F', 'P'))

    @staticmethod
    def _planned_range(a, b, step):
        return np.arange(a, b + step * 0.5, step).tolist()

    def _planned_values(self, kind, target='OPT'):
        if target == 'OPT':
            if not self._opt_legacy():
                return self._opt_planned(kind)
            if kind == 'F':
                return self._planned_range(self.sp_f0.value(), self.sp_f1.value(), self.sp_df.value())
            return self._planned_range(self.sp_p0.value(), self.sp_p1.value(), self.sp_dp.value())
        else:
            if kind == 'F':
                return self._planned_range(self.sp_aud_f0.value(), self.sp_aud_f1.value(), self.sp_aud_df.value())
            return self._planned_range(self.sp_aud_p0.value(), self.sp_aud_p1.value(), self.sp_aud_dp.value())

    def _point_time(self, kind, value, target=None):
        target = target or getattr(self, 'sweep_target', 'OPT')
        running = getattr(self, 'sweep_active', False)
        if target == 'OPT' and kind in ('F', 'P') and not (self._opt_legacy() if not running
                                                          else getattr(self, 'sweep_legacy', True)):
            return sum(self._opt_times(kind, value, 'est' if running else None))
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
            if kind == 'T':
                dur = self.sp_ot_dur.value() * 60.0
                self._eta_set(lbl, 'Duração: ' + self._fmt_time(dur) if dur else 'Até clicar em Parar')
                continue
            values = self._planned_values(kind, 'OPT')
            total = sum(self._point_time(kind, v, 'OPT') for v in values)
            if kind == 'F':
                reps = self.sp_opt_reps.value()
                if self.chk_opt_adapt.isChecked():
                    tmin = reps * sum(sum(self._opt_times('F', v, 'min')) for v in values)
                    self._eta_set(lbl, f'Tempo estimado: {self._fmt_time(tmin)}\u00a0a\u00a0{self._fmt_time(reps * total)}')
                    lbl.setToolTip(f'{len(values)} pontos. τ adaptativo: do τ mínimo em todos os pontos ao τ max em todos.')
                else:
                    self._eta_set(lbl, 'Tempo estimado: ' + self._fmt_time(reps * total))
                    lbl.setToolTip(f'{len(values)} pontos' + (f' × {reps} repetições' if reps > 1 else ''))
                continue
            self._eta_set(lbl, 'Tempo estimado: ' + self._fmt_time(total))
        for kind, lbl in getattr(self, 'eta_labels_aud', {}).items():
            total = sum(self._point_time(kind, v, 'AUDIO') for v in self._planned_values(kind, 'AUDIO'))
            self._eta_set(lbl, 'Tempo estimado: ' + self._fmt_time(total))

    def _sweep_remaining(self, now):
        elapsed = now - self.sweep_timer
        if self.sweep_state == 'SETTLING':
            rest = (self.sweep_settle_time - elapsed) + self.sweep_measure_time
        else:
            rest = self.sweep_measure_time - elapsed
        rest = max(rest, 0.0)
        for v in self.sweep_freqs[self.sweep_idx + 1:]:
            rest += self._point_time(self.sweep_kind, v, self.sweep_target)
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
        '''Frequência, τ e cortes do passa-altas dos dois lock-ins antes de uma varredura em frequência.'''
        return (self.ref_freq, self.sp_tau.value(), self.cutoff_hp, self.sp_audio_tau.value(), self.audio_cutoff_hp)

    def _restore_excitation(self, snap):
        '''Volta à frequência de antes da varredura (reenvia F ao STM32) e aos cortes de antes:
        apply_frequency sozinho levaria os filtros aos cortes automáticos, perdendo ajustes manuais.'''
        f, tau, hp, atau, ahp = snap
        self._set_spin(self.sp_freq, f)
        self.apply_frequency(f)
        for sp, v in ((self.sp_tau, tau), (self.sp_hp, hp), (self.sp_audio_tau, atau), (self.sp_audio_hp, ahp)):
            sp.setValue(v)

    def _apply_sweep_value(self, value):
        if self.sweep_kind == 'F':
            self._set_spin(self.sp_freq, value)
            self.apply_frequency(value)
            if self._sweep_new():
                self._opt_set_point_tau(value)       # τ da varredura (adaptativo ou fixo) no lock-in do OPT101
        else:
            self._set_spin(self.sp_power, value)
            self.laser_power = value
            self.link.write(f"P{value}\n")

    def toggle_sweep(self, kind='F', target='OPT', _rep=False):
        if self.average_mode:
            self.flash('A varredura está disponível apenas no Modo Lock-In.')
            return
        if getattr(self, 'dual_active', False):
            self.flash('A varredura casada (Modo Duplo) está em andamento.')
            return
        if _rep and getattr(self, 'opt_rep', None) is None:
            return                  # repetições canceladas entre uma varredura e a seguinte
        if getattr(self, 'sweep_active', False) and (self.sweep_kind != kind or self.sweep_target != target):
            self.flash('Já existe uma varredura em andamento.')
            return

        if not getattr(self, 'sweep_active', False):
            values = self._planned_values(kind, target)
            if not values:
                return
            self.sweep_legacy = target != 'OPT' or self._opt_legacy()
            if not self.sweep_legacy:
                values = self._opt_begin_run(kind, values, _rep)
            else:
                self.opt_rep = None
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
                if not self.sweep_legacy:       # f_start/f_stop: faixa pedida; f_step: N pontos (log) ou passo (linear)
                    f_start, f_stop = sorted((f_start, f_stop))
                self.sweep_params = {'kind': 'F', 'f_start': f_start, 'f_stop': f_stop, 'f_step': f_step,
                                     'target': target, 'normalize_mode': self.normalize_mode}
            else:
                self.sweep_params = {'kind': 'P', 'f_start': f_start, 'f_stop': f_stop, 'f_step': f_step,
                                     'target': target, 'freq': self.ref_freq, 'normalize_mode': self.normalize_mode}
            self.sweep_idx = 0
            self.sweep_adapt_info = ''
            if kind == 'F' and not _rep:
                self._beam_on_for_sweep()
            elif kind == 'F':
                pass            # repetição: o feixe continua ligado desde a anterior
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
            self.opt_rep = None
            self._end_sweep_ui()
            self.flash('Varredura cancelada pelo usuário.')

    def _end_sweep_ui(self):
        self.sweep_active = False
        self.sweep_state = 'IDLE'
        for kind, btn in self.btn_sweeps.items():
            btn.setText('▶ Iniciar' if kind == 'T' else '▶ Varredura')
            btn.setStyleSheet('background:#cfe2ff;')
            btn.setEnabled(True)
        for w in (self.sp_tau, self.sp_ot_f, self.sp_ot_pwm, self.sp_ot_tau, self.sp_ot_dt, self.sp_ot_dur):
            w.setEnabled(True)
        self._on_opt_adapt(self.chk_opt_adapt.isChecked())
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
        self._beam_off_after_sweep()
        self.update_eta_idle()
        self._apply_mod_ui()

    def sweep_step(self, now):
        if self.sweep_kind == 'T':
            self._opt_time_step(now)
            return
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
        new = self._sweep_new()
        if new:
            rp = getattr(self, 'opt_rep', None)
            if rp:
                head = f"Repetição {rp['k']}/{rp['n']} · " + head
            if self.sweep_kind == 'F':
                head += f" | τ = {self._fmt_tau(self.sweep_tau_now)}"

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
            self.sweep_status_text = (f"{head} | Medindo ({elapsed:.1f}/{self.sweep_measure_time:.1f} s)"
                                      + getattr(self, 'sweep_adapt_info', '') if new else
                                      f"{head} | Medindo ({count} amostras)...")
            
            if elapsed >= self.sweep_measure_time:
                if new and self.sweep_kind == 'F' and self.chk_opt_adapt.isChecked() and self._opt_adapt_point(v_curr, now):
                    return              # ponto refeito com τ maior
                if target == 'OPT':
                    if self.sweep_count > 0:
                        r = np.concatenate(self.sweep_chunks_r)
                        p = np.concatenate(self.sweep_chunks_p)
                        dc = np.concatenate(self.sweep_chunks_dc)
                        if new:
                            self._opt_record_point(v_curr, r, p, dc)
                        else:
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
        self._exporting = True          # Medidas em Série esperam o fim do salvamento (há processEvents abaixo)
        try:
            self._finish_and_export_sweep()
        finally:
            self._exporting = False

    def _finish_and_export_sweep(self):
        self._end_sweep_ui()
        if self.sweep_kind == 'T':
            self.opt_rep = None
            if self.sweep_results:
                self._opt_export_time()
            return
        if not self.sweep_results:
            self.opt_rep = None
            return
        if self._sweep_new():
            self._opt_finish_new()
            return

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
            
        os.makedirs(self._save_dir(), exist_ok=True)
        filename = os.path.join(self._save_dir(), stem + ".csv")
        png_filename = os.path.join(self._save_dir(), stem + ".png")

        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                f.write(f"# {title} - Lock-In TL-Arduino\n# Data/Hora: {now_dt.strftime('%Y-%m-%d %H:%M:%S')}\n# Parametros: {params}\n# Modo: {mode_str}\n")
                f.write(f"{col},Magnitude_Media,Magnitude_DesvioPadrao,Fase_Media_Graus,Fase_DesvioPadrao_Graus,DC_Offset_Medio\n")
                for row in self.sweep_results:
                    f.write(f"{fmt.format(row[0])},{row[1]:.5f},{row[2]:.5f},{row[3]:.3f},{row[4]:.3f},{row[5]:.2f}\n")
            self._session_add(filename)
            self.sweep_last_csv = filename
            print(f"Varredura concluída! Dados em: {filename}")
        except Exception as e:
            print(f"Erro ao salvar arquivo CSV: {e}")

        self.show_sweep_results(kind, f0, f1, df, mode_str, filename, png_filename, target_str)
        self.flash(f'Varredura concluída: {filename}', 6.0)

    @staticmethod
    def _fit_time_exp(t, y):
        '''Sinal x t: y = A + B·e^(−t/T). Devolve (função, texto) ou None (poucos pontos ou ajuste sem sentido).'''
        t, y = np.asarray(t, float), np.asarray(y, float)
        if len(t) < 8:
            return None
        try:
            from scipy.optimize import curve_fit
            t0 = float(t[0])
            span = max(float(t[-1] - t0), 1.0)
            f_exp = lambda x, A, B, T: A + B * np.exp(-(x - t0) / T)
            popt, pcov = curve_fit(f_exp, t, y, p0=(float(y[-1]), float(y[0] - y[-1]), span / 3.0), maxfev=4000)
        except Exception:
            return None
        if not (np.all(np.isfinite(pcov)) and 0.0 < popt[2] < 20.0 * span):
            return None
        return (lambda x: f_exp(x, *popt)), (f'y = A + B·e<sup>−t/T</sup><br>T = {popt[2]:.0f} ± {np.sqrt(pcov[2, 2]):.0f} s<br>'
                                             f'A = {popt[0]:.4g}<br>B/A = {100 * popt[1] / popt[0]:+.1f} %')

    def show_sweep_results(self, kind, f0, f1, df, mode_str, filename, png_filename, target_str='OPT101'):
        res = np.array(self.sweep_results, dtype=float)
        freqs, mag, mag_err, ph, ph_err = res[:, 0], res[:, 1], res[:, 2], res[:, 3], res[:, 4]

        win = QtWidgets.QWidget()
        what = {'F': 'Frequência', 'T': 'Tempo'}.get(kind, 'PWM')
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
        cmb_fit.addItems(['Lei de potência (A·xⁿ)', 'Linear (a + b·x)', 'Sem fit'] if kind != 'T' else
                         ['Exponencial (A + B·e^(−t/T))', 'Linear (a + b·x)', 'Sem fit'])
        cmb_fit.setToolTip('Lei de potência: reta em log-log (n = -1 para 1/f). Ajustada nos dados, independe da escala.\n'
                           'Linear: reta nos eixos lineares.')
        cmb_fit.setCurrentIndex(0 if kind in ('F', 'T') else 1)
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
        beam = max(df * 0.15, 1e-6) if kind != 'F' or self.cmb_opt_fspace.currentIndex() == 1 else 0.0
        if kind == 'T':
            beam = 0.0
        if kind == 'F': 
            pw_r.setTitle(f"Resposta em Frequência ({f0:g} a {f1:g} Hz, {len(freqs)} pontos) - {target_str}")
        elif kind == 'T':
            pr = self.sweep_params
            pw_r.setTitle(f"Sinal x t ({pr['freq']:g} Hz, PWM {pr['pwm']:g} %, τ {pr['tau']:g} s, ponto a cada {df:g} s) - {target_str}")
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
            model = {0: 'exp' if kind == 'T' else 'pow', 1: 'lin'}.get(cmb_fit.currentIndex())
            res = self._fit_time_exp(freqs, mag) if model == 'exp' else (fit_sweep(freqs, mag, model) if model else None)
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
        pw_p.setLabel('bottom', {'F': 'Frequência do Laser (Hz)', 'T': 'Tempo (s)'}.get(kind, 'PWM do Laser (%)'))
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

        if kind == 'F' and target_str == 'OPT101' and not getattr(self, 'sweep_legacy', True) \
                and self.sweep_params.get('f_step', 0) and self.cmb_opt_fspace.currentIndex() == 0:
            chk_log_x.setChecked(True)          # pontos em escala log: eixo X em log (a mediana usa o mesmo caminho)
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
        if getattr(self, 'series_active', False):     # medidas em série: sem acumular janelas na madrugada
            win.close()
            return
        self.result_windows.append(win)

    # ------------------------------------------------------------ Laço GUI

    def on_opt_sweeps_panel(self, checked):
        self.btn_opt_sweeps.setText('Varreduras ▾' if checked else 'Varreduras ▸')

    def on_scope_toggle(self, shown):
        '''Mostra ou recolhe o osciloscópio do OPT101 (2.5.0). Recolhido, sobra só o cabeçalho e a divisória
        devolve a altura ao gráfico de baixo; ao mostrar de novo, volta a divisão anterior.'''
        from soi_i18n import tr
        self.btn_scope.setText(('▾ ' if shown else '▸ ') + tr('Osciloscópio (sinal bruto do ADC)'))
        split = getattr(self, 'opt_split', None)
        self.plot_raw.setVisible(shown)
        if split is None:
            return
        if shown:
            self.scope_box.setMaximumHeight(16777215)
            sizes = getattr(self, '_scope_sizes', None)
            if sizes:
                split.setSizes(sizes)
        else:
            if self.plot_raw.height() > 0 and split.sizes()[0] > self.btn_scope.sizeHint().height() + 4:
                self._scope_sizes = split.sizes()
            self.scope_box.setMaximumHeight(self.btn_scope.sizeHint().height())

    def on_opt_fft(self, checked):
        self.opt_fft_enabled = checked
        self.opt_valid_samples = 0
        self.opt_write_index = 0
        self.last_opt_fft_t = 0.0
        self.opt_fft_panel.setVisible(checked)
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
        if hasattr(self, 'opt_fft_cursor'):
            self.opt_fft_cursor['manual'] = False
            self.last_opt_fft_t = 0.0
        f = self.ref_freq
        self.opt_fft_ref_line.setPos(f)
        self.opt_fft_ref_line.setVisible(f > 0)
        if self.opt_fft_full or f <= 0:
            item.setXRange(0, RATE.FS / 2, padding=0)
            item.setTitle('OPT101 - espectro do ADC (FFT)')
        else:
            w = max(0.5 * f, 20.0 / OPT_FFT_HISTORY_SEC)
            item.setXRange(max(0.0, f - w), min(RATE.FS / 2, f + w), padding=0)
            item.setTitle(f'OPT101 - espectro do ADC (FFT) em torno de {f:g} Hz')

    _hann_cache = {}

    @classmethod
    def _hanning(cls, n):
        w = cls._hann_cache.get(n)
        if w is None:
            if len(cls._hann_cache) > 4:
                cls._hann_cache.clear()
            w = cls._hann_cache[n] = np.hanning(n)
        return w

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
                and self.opt_valid_samples >= opt_fft_size() and now - self.last_opt_fft_t >= AUDIO_FFT_INTERVAL):
            return
        self.last_opt_fft_t = now
        # Com zoom usa todo o histórico disponível (resolução fina perto da referência), até OPT_FFT_ZOOM_MAX
        n = opt_fft_size() if self.opt_fft_full else min(self.opt_valid_samples, OPT_FFT_ZOOM_MAX)
        idx = (self.opt_write_index - n + np.arange(n)) % len(self.opt_history)
        x = self.opt_history[idx].astype(np.float64) / ADC_FULL_SCALE
        window = self._hanning(n)
        spectrum = np.abs(np.fft.rfft(x * window)) / window.sum()
        spectrum[1:-1] *= 2.0
        frequency = np.fft.rfftfreq(n, 1.0 / RATE.FS)
        db = 20.0 * np.log10(np.maximum(spectrum, 1e-7))
        self.curve_opt_fft.setData(frequency, db)
        self._fft_cursor_refresh(self.opt_fft_cursor)
        # Escala Y em passos de 10 dB pela faixa exibida (o fundo do ADC varia muito com o ganho do OPT101)
        (x0, x1), _ = self.plot_opt_fft.getPlotItem().vb.viewRange()
        sel = db[(frequency >= x0) & (frequency <= x1)]
        if sel.size and not self.opt_fft_cursor['manual']:
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
            lbl.setTextWidth(max(120.0, r.width() - 16.0))     # quebra no gráfico estreito (2.5.0)
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
                                '<span style="font-size:15pt;font-weight:bold;">Pico em f0 não encontrado</span><br>'
                                f'<span style="font-size:11pt;">{missing}</span></div>')
        missing_lbl.setVisible(show_missing)
        fit_on = fit_checked and not show_missing and html is not None
        if fit_on:
            box.setHtml(html)
        box.setVisible(fit_on)
