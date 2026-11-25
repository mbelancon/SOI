# -*- coding: utf-8 -*-
'''Integração com Medidas em Série (soi_serie.py), sessão e Finalizar experimento.

Métodos da janela principal (LockInWindow em soi_controller.py), separados por assunto.'''
from soi_comum import *  # noqa: F401,F403


class SeriesMixin:
    # ------------------------------------------------------------ Medidas em Série (soi_serie.py)

    def _save_dir(self):
        """Pasta onde as medidas do Modo Duplo são gravadas: a da série em andamento ou Medidas."""
        return getattr(self, 'save_dir_override', None) or MEDIDAS_DIR

    def _grab_dual_plots(self):
        return self._grab_hidden(self.dual_plots)

    def _grab_hidden(self, w):
        """Imagem de um widget para o PNG. Com a aba dele escondida (ex.: durante uma série, na aba Medidas em
        Série), mostra a aba por um instante para o widget ter o tamanho da tela."""
        if w.isVisible():
            return w.grab()
        cur = self.tabs.currentIndex()
        idx = next((i for i in range(self.tabs.count()) if self.tabs.widget(i).isAncestorOf(w)), None)
        if idx is None:
            return w.grab()
        self.tabs.setCurrentIndex(idx)
        # só os eventos de layout (nada de processEvents: os timers da medida e da série rodariam no meio do salvamento)
        for _ in range(3):
            QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.LayoutRequest)
        img = w.grab()
        self.tabs.setCurrentIndex(cur)
        return img

    def _series_sweep_estimate(self, p):
        """(mínimo, máximo) em s de uma varredura em frequência de uma série, com os parâmetros da etapa
        (as mesmas contas de _dual_times, sem mexer nos campos do quadro)."""
        f0, f1 = sorted((float(p['fmin']), float(p['fmax'])))
        vals = np.geomspace(f0, f1, max(2, int(p['n'])))
        tau = float(p['tau'])
        lo = hi = 0.0
        for v in vals:
            if p.get('tau_fixo'):
                t = sum(adapt_times(max(tau, LOWF_TAU_FIXED))) if v < LOWF_FMAX else 9.0 * tau + 0.3 + max(0.5, tau)
                lo, hi = lo + t, hi + t
            elif not p.get('adapt_tudo') and lowf_band_tau(v) is not None:
                st, me = adapt_times(tau)
                t = st + me                         # 2.5.0: sem médias por ponto
                lo, hi = lo + t, hi + t
            else:
                lo += sum(adapt_times(adapt_tau_min(v)))
                hi += sum(adapt_times(max(adapt_tau_min(v), tau)))
        nrep = max(1, int(p.get('repeticoes', 1)))
        w = float(p.get('aquecer', 0.0) or 0.0) + soi_serie.SeriesRunner.SETTLE_S
        return nrep * lo + w, nrep * hi + w

    def _series_widgets(self):
        sp0, sp1, space, spn, _ = self.dual_fw['F']
        return (self.sp_f0, self.sp_f1, self.sp_df, self.sp_p0, self.sp_p1, self.sp_dp, self.sp_aud_f0,
                self.sp_aud_f1, self.sp_aud_df, self.sp_aud_p0, self.sp_aud_p1, self.sp_aud_dp, self.sp_dual_p0,
                self.sp_dual_p1, self.sp_dual_dp, self.dual_mode_w['P'], self.dual_tau_w['P'],
                self.cmb_mod, space, sp0, sp1, spn, self.chk_dual_adapt, self.chk_dual_adapt40, self.chk_dual_blocks,
                self.sp_dual_blocks, self.dual_tau_w['F'], self.sp_dual_adapt_tol, self.sp_dt_f, self.sp_dt_pwm,
                self.sp_dt_tau, self.sp_dt_dt, self.sp_dt_dur, self.sp_dual_reps)

    def _series_snapshot(self):
        """Valores dos campos que a série muda (restaurados no fim), mais a frequência e o PWM."""
        out = []
        for w in self._series_widgets():
            if isinstance(w, QtWidgets.QComboBox):
                out.append(w.currentIndex())
            elif isinstance(w, QtWidgets.QAbstractButton):
                out.append(w.isChecked())
            else:
                out.append(w.value())
        return out, self.sp_freq.value(), self.sp_power.value()

    def _series_restore(self, snap):
        vals, f, pwm = snap
        for w, v in zip(self._series_widgets(), vals):
            if isinstance(w, QtWidgets.QComboBox):
                w.setCurrentIndex(v)
            elif isinstance(w, QtWidgets.QAbstractButton):
                w.setChecked(v)
            else:
                w.setValue(v)
        self._apply_adapt_ui()
        self._set_spin(self.sp_freq, f)
        self.apply_frequency(f)
        self.sp_power.setValue(pwm)
        self.on_power(self.sp_power.value())

    def _series_sweep_fields(self, tipo):
        """(início, fim, passo) do quadro de varredura de uma etapa opt101-*/inmp441-*/duplo-pwm."""
        return {'opt101-f': (self.sp_f0, self.sp_f1, self.sp_df), 'opt101-pwm': (self.sp_p0, self.sp_p1, self.sp_dp),
                'inmp441-f': (self.sp_aud_f0, self.sp_aud_f1, self.sp_aud_df),
                'inmp441-pwm': (self.sp_aud_p0, self.sp_aud_p1, self.sp_aud_dp),
                'duplo-pwm': (self.sp_dual_p0, self.sp_dual_p1, self.sp_dual_dp)}[tipo]

    def _series_simple_estimate(self, tipo, p):
        """Tempo (s) de uma varredura de uma etapa opt101-*/inmp441-*/duplo-pwm (as contas dos quadros)."""
        vals = self._planned_range(min(p['inicio'], p['fim']), max(p['inicio'], p['fim']), max(p['passo'], 1e-6))
        if tipo == 'duplo-pwm':
            if p.get('tau', 0) > 0:
                t = 9.0 * p['tau'] + 0.3 + max(0.5, p['tau'])
            else:
                t = sum(self._times_for_cutoff(self.cutoff_lp))
            return len(vals) * t
        kind = 'F' if tipo.endswith('-f') else 'P'
        return sum(self._point_time(kind, v) for v in vals)

    def _series_apply(self, tipo, p):
        """Põe os parâmetros de uma etapa da série nos quadros das abas (como o modo sem janela)."""
        self.cmb_mod.setCurrentIndex(0)               # modulação eletrônica (o STM32 fixa/varre a frequência)
        if tipo in ('opt101-f', 'opt101-pwm', 'inmp441-f', 'inmp441-pwm', 'duplo-pwm'):
            a, b, d = self._series_sweep_fields(tipo)
            a.setValue(p['inicio'])
            b.setValue(p['fim'])
            d.setValue(p['passo'])
            if tipo.endswith('-f'):
                self.sp_power.setValue(p['pwm'])
                self.on_power(self.sp_power.value())
            else:
                self._set_spin(self.sp_freq, p['f'])
                self.apply_frequency(p['f'])
            if tipo == 'duplo-pwm':
                self.dual_mode_w['P'].setCurrentIndex(1 if p.get('tau', 0) > 0 else 0)
                if p.get('tau', 0) > 0:
                    self.dual_tau_w['P'].setValue(p['tau'])
            return
        if tipo == 'sinal-t':
            self.sp_dt_f.setValue(p['f'])
            self.sp_dt_pwm.setValue(p['pwm'])
            self.sp_dt_tau.setValue(p['tau'])
            self.sp_dt_dt.setValue(p['dt'])
            self.sp_dt_dur.setValue(p['duracao'])
            return
        sp0, sp1, space, spn, _ = self.dual_fw['F']
        space.setCurrentIndex(0)                       # pontos em escala log
        sp0.setValue(p['fmin'])
        sp1.setValue(p['fmax'])
        spn.setValue(p['n'])
        self.chk_dual_adapt.setChecked(not p['tau_fixo'])
        self.sp_dual_reps.setValue(max(1, int(p.get('repeticoes', 1))))
        self.chk_dual_adapt40.setChecked(not p.get('adapt_tudo', False))
        self.chk_dual_blocks.setChecked(False)         # 2.5.0: "--medias" de séries antigas é ignorado
        self._apply_adapt_ui()
        self.dual_tau_w['F'].setValue(p['tau'])
        if not p['tau_fixo']:
            self.sp_dual_adapt_tol.setValue(p['precisao'])

    def _series_stop_sweep(self):
        """Encerra a varredura em andamento e salva os pontos já medidos (Parar/Pular da série)."""
        if getattr(self, 'sweep_active', False):          # varreduras das abas OPT101/INMP441
            self.finish_and_export_sweep()
            return
        rp = getattr(self, 'dual_rep', None)
        if not self.dual_active:
            if rp:                       # entre duas repetições: mediana das que já terminaram
                self.dual_rep = None
                self._dual_finish_median(rp)
            return
        if self.dual_state in ('SETTLING', 'MEASURING'):
            self.flash('Ponto em andamento descartado.')
        self._end_dual_sweep()
        if self.dual_results:
            self.dual_params['values'] = [r[0] for r in self.dual_results]
            self._show_dual_results()
            self._export_dual()
        self.dual_rep = None
        if rp and len(rp['runs']) >= 2:  # repetição incompleta fica de fora da mediana
            self._dual_finish_median(rp)

    def _series_lock(self, on):
        """Durante uma série: as outras abas e a barra de cima ficam bloqueadas (a placa está em uso). Pode ser
        chamada de novo a cada etapa (as medidas reabilitam campos quando terminam)."""
        ws = []
        for i in range(self.tabs.count()):
            page = self.tabs.widget(i)
            if page is not self.series_tab:
                for cls in (QtWidgets.QAbstractButton, QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox,
                            QtWidgets.QLineEdit):
                    ws += page.findChildren(cls)
        for name in ('sp_freq', 'sp_power', 'ed_sample', 'cmb_mic_cal', 'chk_mic_cal', 'cmb_cell', 'chk_sim',
                     'btn_settings', 'cmb_mod'):
            w = getattr(self, name, None)
            if w is not None:
                ws.append(w)
        ws += [b for b in getattr(self, 'pwm_quick_btns', [])]
        for w in ws:
            was = w.property('_series_was')
            if on:
                if was is None:
                    w.setProperty('_series_was', w.isEnabled())
                w.setEnabled(False)
            elif was is not None:
                w.setEnabled(bool(was))
                w.setProperty('_series_was', None)

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
                      f"# Freq={self.ref_freq} Hz, OSR={self.osr} ({RATE.FS:g} S/s), tau={lp_tau(self.cutoff_lp, RATE.FS):.6g} s, "
                      f"LP={self.cutoff_lp:.6g} Hz, "
                      f"HP={self.cutoff_hp} Hz\n"
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
