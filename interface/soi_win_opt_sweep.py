# -*- coding: utf-8 -*-
'''Aba OPT101: varreduras no padrão do Modo Duplo (Sinal x f, Sinal x PWM e Sinal x t), só com o OPT101.

Métodos da janela principal (LockInWindow em soi_controller.py), separados por assunto. O laço de pontos continua
em soi_win_opt.py (toggle_sweep / sweep_step); aqui ficam a lista de pontos, os tempos, o τ adaptativo, as
repetições com mediana, o Sinal x t e a gravação dos CSV. Nas Medidas em Série (series_active) as varreduras do
OPT101 seguem o comportamento antigo (passo linear, τ automático da frequência): sweep_legacy.'''
from soi_comum import *  # noqa: F401,F403


class OptSweepMixin:
    # ------------------------------------------------------------ Campos
    def _on_opt_fspace(self, idx):
        '''Logarítmico: número de pontos; Linear: passo em Hz. Cada modo lembra o último valor.'''
        sp = self.sp_df
        old = getattr(self, 'opt_fspace_idx', 0)
        self.opt_df_last[old] = float(sp.value())
        self.opt_fspace_idx = idx
        log = idx == 0
        sp.blockSignals(True)
        self.lbl_opt_fn.setText('N pontos:' if log else 'Passo:')
        sp.setSuffix('' if log else ' Hz')
        sp.setDecimals(0 if log else 2)
        sp.setRange(2.0 if log else 0.01, 5000.0)
        sp.setSingleStep(1.0 if log else 0.5)
        sp.setValue(self.opt_df_last[idx])
        sp.blockSignals(False)

    def _on_opt_adapt(self, on):
        '''τ adaptativo: o campo vira "τ max"; a Precisão só vale com ele ligado.'''
        self.lbl_opt_tau.setText('τ max:' if on else 'τ:')
        self.sp_opt_tau.setToolTip(
            'τ max da varredura (τ adaptativo ligado): a varredura começa nele e o τ muda conforme a flutuação,\n'
            'sem passar desse valor.' if on else
            'τ do lock-in do OPT101 durante a varredura: espera 9τ e faz a média por 1τ em cada ponto.')
        self.sp_opt_tol.setEnabled(bool(on) and not self.sweep_active)

    def _opt_legacy(self):
        '''Comportamento antigo (Medidas em Série): passo linear, τ automático da frequência, sem repetições.'''
        return bool(getattr(self, 'series_active', False))

    def _opt_adaptive(self, kind=None):
        return (kind in (None, 'F')) and self.chk_opt_adapt.isChecked()

    def _opt_avoid_extra(self):
        out = []
        for p in re.split(r'[;\s]+', self.ed_opt_avoid.text()):
            try:
                v = float(p.strip(',').replace(',', '.'))
            except ValueError:
                continue
            if 0 < v <= 20000:
                out.append(v)
        return out

    def _opt_planned(self, kind, raw=False):
        if kind == 'P':
            return self._planned_range(self.sp_p0.value(), self.sp_p1.value(), self.sp_dp.value())
        f0, f1 = sorted((self.sp_f0.value(), self.sp_f1.value()))
        if self.cmb_opt_fspace.currentIndex() == 0:
            n = max(2, int(round(self.sp_df.value())))
            vals = [round(float(v), 3) for v in np.geomspace(f0, f1, n)]
        else:
            vals = self._planned_range(f0, f1, self.sp_df.value())
        if raw:
            return vals
        vals = soi_serie.avoid_mains(vals)[0]
        return soi_serie.avoid_list(vals, self._opt_avoid_extra())[0]

    # ------------------------------------------------------------ Tempos e τ
    def _opt_times(self, kind, value, bound=None):
        '''(espera, medida) do ponto. τ adaptativo: com o τ atual da varredura ('est'), o τ max (padrão) ou o mínimo
        da frequência ('min'). Varredura em PWM: o τ do lock-in, 7τ de espera e média max(1 s, 3τ) (só a amplitude
        muda entre os pontos).'''
        if kind == 'P':
            return adapt_times(lp_tau(self.cutoff_lp, RATE.FS))
        if self.chk_opt_adapt.isChecked():
            tmin = adapt_tau_min(value)
            cur = getattr(self, 'opt_tau_cur', None)
            if bound == 'est' and cur:
                tau = max(tmin, cur)
            elif bound == 'min':
                tau = tmin
            else:
                tau = max(tmin, float(self.sp_opt_tau.value()))
            return adapt_times(tau)
        tau = float(self.sp_opt_tau.value())
        return 9.0 * tau + 0.3, max(0.5, tau)

    def _opt_point_tau(self, value):
        '''τ do ponto numa varredura em frequência em andamento.'''
        if self.chk_opt_adapt.isChecked():
            cur = getattr(self, 'opt_tau_cur', None) or float(self.sp_opt_tau.value())
            return max(adapt_tau_min(value), cur)
        return float(self.sp_opt_tau.value())

    def _opt_set_point_tau(self, value):
        '''Depois de apply_frequency (que volta ao τ automático), aplica o τ da varredura ao lock-in do OPT101.'''
        self.sweep_tau_now = self._opt_point_tau(value)
        self.opt_redo = 0
        self.sp_tau.setValue(self.sweep_tau_now)

    def _opt_adapt_point(self, v, now):
        '''Fim da medida de um ponto com τ adaptativo: mede a flutuação de R e da fase do OPT101; se passa de 2× a
        Precisão, refaz o ponto com τ maior (devolve True). Senão escolhe o τ do ponto seguinte (False).'''
        if not self.sweep_chunks_r:
            return False
        r = np.concatenate(self.sweep_chunks_r)
        p = np.concatenate(self.sweep_chunks_p)
        if len(r) < 4:
            return False
        tol = self.sp_opt_tol.value() / 100.0
        sm = max(abs(float(r.mean())), 1e-30)
        std_p = float(np.radians(circ_stats_deg(p)[1]))
        q = max(float(r.std()) / sm, std_p) / tol
        h = len(r) // 2
        q_drift = max(abs(float(r[:h].mean() - r[h:].mean())) / sm, 0.0) / tol
        tau = self.sweep_tau_now
        cap = float(self.sp_opt_tau.value())
        fl = f'flutuação R {100.0 * float(r.std()) / sm:.2g} %, fase {np.degrees(std_p):.2g}°'.replace('.', ',')
        if q > ADAPT_Q_REDO and tau < cap * 0.999 and self.opt_redo < ADAPT_MAX_REDO:
            self.opt_redo += 1
            self.opt_tau_cur = min(cap, tau * min(4.0, max(2.0, (q / ADAPT_Q_TARGET) ** 2)))
            self.sweep_tau_now = self.opt_tau_cur
            self.sp_tau.setValue(self.sweep_tau_now)
            self.sweep_settle_time, self.sweep_measure_time = adapt_times(self.sweep_tau_now)
            self.sweep_state = 'SETTLING'
            self.sweep_timer = now
            self._clear_sweep_buffers()
            self.sweep_adapt_info = f' | {fl}: refazendo com τ maior'
            return True
        self.opt_q_hist.append((q, tau))
        q_eff = float(np.median([qi * np.sqrt(ti / tau) for qi, ti in self.opt_q_hist[-3:]]))
        k = min(2.0, max(1.0 / 3.0, (q_eff / ADAPT_Q_TARGET) ** 2)) if q_eff > 0 else 1.0 / 3.0
        self.opt_tau_cur = min(cap, tau * k)
        self.sweep_adapt_info = f' | último: τ = {self._fmt_tau(tau)}, {fl}' + (
            f', deriva {q_drift * tol * 100:.2g} %'.replace('.', ',') if q_drift > 1.0 else '')
        return False

    # ------------------------------------------------------------ Início/fim de uma varredura nova
    def _opt_begin_run(self, kind, values, _rep):
        '''Estado de uma varredura nova (F/P, fora das Medidas em Série): ordem, repetições, τ adaptativo.'''
        order, seed = 'crescente', None
        if kind == 'F':
            order = self.cmb_opt_order.currentData()
            n_rep = self.sp_opt_reps.value()
            if not _rep:
                self.opt_rep = ({'n': n_rep, 'k': 1, 'runs': [], 'csvs': [], 'seeds': [], 'order': order,
                                 't0': datetime.now()} if n_rep > 1 else None)
                self.opt_seed0 = int.from_bytes(os.urandom(3), 'big')
                chk_w, sp_w, _p, _e = self.warm_w.get(self.btn_sweeps[kind], (None, None, None, None))
                self.opt_warm_s = float(sp_w.value()) if (chk_w is not None and chk_w.isChecked()) else 0.0
            rp = getattr(self, 'opt_rep', None)
            if order == 'embaralhada':
                seed = getattr(self, 'opt_seed0', 0) + ((rp['k'] - 1) if rp else 0)
                if rp:
                    rp['seeds'].append(seed)
            if order != 'crescente':
                values = sorted(values)
                values = [values[i] for i in soi_serie.measure_order(values, order, seed)]
        else:
            self.opt_rep = None
            self.opt_warm_s = 0.0
        self.sweep_order = (order, seed)
        self.sweep_ordpos = []
        self.opt_tau_cur = float(self.sp_opt_tau.value()) if kind == 'F' else None
        self.opt_q_hist = []
        self.opt_redo = 0
        self.sweep_adapt_info = ''
        return values

    def _opt_fmt_head(self, v):
        if self.sweep_kind == 'F':
            return f'[{self.sweep_idx + 1}/{len(self.sweep_freqs)}] {v:.2f} Hz'
        return f'[{self.sweep_idx + 1}/{len(self.sweep_freqs)}] PWM {v:.1f} %'

    def _opt_record_point(self, v_curr, r, p, dc):
        tau = (float(getattr(self, 'sweep_tau_now', float('nan'))) if self.sweep_kind == 'F'
               else float(lp_tau(self.cutoff_lp, RATE.FS)))
        row = (v_curr, float(r.mean()), float(r.std()), *circ_stats_deg(p), float(dc.mean()), tau, self.sweep_idx + 1)
        self.sweep_results.append(row)

    def _opt_header(self, kind, rep=None, median=False):
        '''Linhas de cabeçalho do CSV (além das de sempre): espaçamento, ordem, τ, warm-up, repetição, exclusões.'''
        lines = []
        rp_seeds = (rep or {}).get('seeds') if median else None
        if kind == 'F':
            sp = 'Logaritmico' if self.cmb_opt_fspace.currentIndex() == 0 else 'Linear'
            lines.append(f'# Espacamento = {sp}')
            order, seed = getattr(self, 'sweep_order', ('crescente', None))
            if rp_seeds:
                seed = ', '.join(str(x) for x in rp_seeds)
            lines.append(f'# Ordem = {order}' + (f' (semente {seed})' if seed is not None else ''))
            if self.chk_opt_adapt.isChecked():
                lines.append(f'# Tau = adaptativo, tau max {self.sp_opt_tau.value():g} s, '
                             f'Precisao {self.sp_opt_tol.value():g} %')
            else:
                lines.append(f'# Tau = {self.sp_opt_tau.value():g} s (fixo)')
            ex = self._opt_avoid_extra()
            if ex:
                lines.append('# Faixas excluidas = ' + '; '.join(f'{e:g}' for e in ex) + ' Hz')
            moved = soi_serie.avoid_mains(self._opt_planned('F', raw=True))[1]
            if moved:
                lines.append('# Pontos deslocados da rede = ' + '; '.join(f'{a:g}->{b:g}' for a, b in moved) + ' Hz')
        else:
            lines.append(f'# Tau = {1e3 * lp_tau(self.cutoff_lp, RATE.FS):.4g} ms (lock-in do OPT101)')
        lines.append(f'# Warm-up = {getattr(self, "opt_warm_s", 0.0):g} s')
        if rep:
            lines.append(f"# Repeticao = {rep['k']}/{rep['n']}" if not median else f"# Repeticoes = {rep['n']} (mediana)")
        return lines

    def _opt_finish_new(self):
        '''Fim de uma varredura nova (F/P): CSV, repetições com mediana e janela de resultados.'''
        kind = self.sweep_kind
        rows = sorted(self.sweep_results, key=lambda r: r[0])
        rp = getattr(self, 'opt_rep', None)
        now_dt = datetime.now()
        now_str = now_dt.strftime('%Y%m%d_%H%M%S')
        f0, f1, df = self.sweep_params['f_start'], self.sweep_params['f_stop'], self.sweep_params['f_step']
        sfx = f"_rep{rp['k']}" if rp else ''
        if kind == 'F':
            stem = self._stem(f'OPT101_F_varredura_f{f0:g}_f{f1:g}_{now_str}{sfx}')
            title, col, fmt = 'Varredura em Frequencia - OPT101', 'Frequencia_Hz', '{:.3f}'
            params = (f"F_Start={f0} Hz, F_Stop={f1} Hz, "
                      + (f'N={df:g} pontos' if self.cmb_opt_fspace.currentIndex() == 0 else f'F_Step={df} Hz'))
        else:
            fm = self.sweep_params.get('freq', self.ref_freq)
            stem = self._stem(f'OPT101_P_varredura_p{f0:g}_p{f1:g}_{df:g}_f{fm:g}Hz_{now_str}')
            title, col, fmt = 'Varredura em PWM - OPT101', 'PWM_Pct', '{:.2f}'
            params = f'P_Start={f0} %, P_Stop={f1} %, P_Step={df} %, Freq={fm} Hz'
        mode_str = 'Normalizado (R/DC %)' if self.sweep_params.get('normalize_mode') else 'Bruto (u.a.)'
        os.makedirs(self._save_dir(), exist_ok=True)
        filename = os.path.join(self._save_dir(), stem + '.csv')
        png_filename = os.path.join(self._save_dir(), stem + '.png')
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                f.write(f"# {title} - Lock-In TL-Arduino\n# Data/Hora: {now_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"# Parametros: {params}\n# Modo: {mode_str}\n")
                for ln in self._opt_header(kind, rp):
                    f.write(ln + '\n')
                f.write(f'{col},Magnitude_Media,Magnitude_DesvioPadrao,Fase_Media_Graus,Fase_DesvioPadrao_Graus,'
                        'DC_Offset_Medio,Tau_s,Ordem_medida\n')
                for r in rows:
                    f.write(f'{fmt.format(r[0])},{r[1]:.5f},{r[2]:.5f},{r[3]:.3f},{r[4]:.3f},{r[5]:.2f},'
                            f'{r[6]:.4g},{int(r[7])}\n')
            self._session_add(filename)
            self.sweep_last_csv = filename
            print(f'Varredura concluída! Dados em: {filename}')
        except Exception as e:
            print(f'Erro ao salvar arquivo CSV: {e}')
        if rp:
            rp['runs'].append(rows)
            rp['csvs'].append(filename)
            if rp['k'] < rp['n']:
                rp['k'] += 1
                print(f"Repetição {rp['k']} de {rp['n']} da varredura...", flush=True)
                QtCore.QTimer.singleShot(0, lambda: self.toggle_sweep('F', 'OPT', _rep=True))
                return
            self.opt_rep = None
            self._opt_finish_median(rp, f0, f1, df, mode_str)
            return
        self.sweep_results = rows
        self.show_sweep_results(kind, f0, f1, df, mode_str, filename, png_filename, 'OPT101')
        self.flash(f'Varredura concluída: {filename}', 6.0)

    def _opt_finish_median(self, rp, f0, f1, df, mode_str):
        '''Fim das repetições: mediana ponto a ponto (casada pela frequência), incerteza u = 1,25·DP/√N, CSV _mediana.'''
        by = {}
        for run in rp['runs']:
            for r in run:
                by.setdefault(round(r[0], 6), []).append(r)
        med = []
        for fq in sorted(by):
            g = np.array([x[:6] for x in by[fq]], dtype=float)
            n = len(g)
            ph = np.radians(g[:, 3])
            c = float(np.angle(np.exp(1j * ph).mean()))
            dph = np.degrees((ph - c + np.pi) % (2 * np.pi) - np.pi)
            ph_med = float(np.degrees(c) + np.median(dph))
            r_med = float(np.median(g[:, 1]))
            u_r = 100.0 * 1.25 * float(g[:, 1].std(ddof=1)) / np.sqrt(n) / max(abs(r_med), 1e-30) if n > 1 else float('nan')
            u_p = 1.25 * float(dph.std(ddof=1)) / np.sqrt(n) if n > 1 else float('nan')
            med.append((fq, r_med, float(np.median(g[:, 2])), ((ph_med + 180.0) % 360.0) - 180.0,
                        float(np.median(g[:, 4])), float(np.median(g[:, 5])), u_r, u_p, n))
        now_dt = datetime.now()
        stem = self._stem(f"OPT101_F_varredura_f{f0:g}_f{f1:g}_{now_dt.strftime('%Y%m%d_%H%M%S')}_mediana")
        filename = os.path.join(self._save_dir(), stem + '.csv')
        png_filename = os.path.join(self._save_dir(), stem + '.png')
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                f.write(f"# Varredura em Frequencia - OPT101 (mediana de {rp['n']} repeticoes) - Lock-In TL-Arduino\n"
                        f"# Data/Hora: {now_dt.strftime('%Y-%m-%d %H:%M:%S')}\n# Modo: {mode_str}\n")
                for ln in self._opt_header('F', rp, median=True):
                    f.write(ln + '\n')
                f.write('# Arquivos = ' + '; '.join(os.path.basename(c) for c in rp['csvs'] if c) + '\n')
                f.write('Frequencia_Hz,Magnitude_Media,Magnitude_DesvioPadrao,Fase_Media_Graus,Fase_DesvioPadrao_Graus,'
                        'DC_Offset_Medio,Incerteza_R_Pct,Incerteza_Fase_Graus,N_Repeticoes\n')
                for r in med:
                    f.write(f'{r[0]:.3f},{r[1]:.5f},{r[2]:.5f},{r[3]:.3f},{r[4]:.3f},{r[5]:.2f},{r[6]:.3g},{r[7]:.3g},{r[8]}\n')
            self._session_add(filename)
            self.sweep_last_csv = filename
            print(f'Mediana das repetições gravada em: {filename}')
        except Exception as e:
            print(f'Erro ao salvar arquivo CSV: {e}')
        self.sweep_results = [r[:6] for r in med]
        self.show_sweep_results('F', f0, f1, df, mode_str, filename, png_filename, 'OPT101')
        self.flash(f'Varredura concluída (mediana de {rp["n"]}): {filename}', 6.0)

    # ------------------------------------------------------------ Sinal x t
    def toggle_opt_time(self):
        '''Sinal x t do OPT101: frequência e PWM fixos; cada ponto é a média do lock-in no intervalo escolhido.'''
        if getattr(self, 'sweep_active', False):
            if self.sweep_kind == 'T':
                self._finish_opt_time()
            else:
                self.flash('Termine ou cancele a varredura em andamento antes.')
            return
        if self.average_mode:
            self.flash('O Sinal x t precisa do OPT101 no Modo Lock-In.')
            return
        if self.ext_mode:
            self.flash('Sinal x t usa a modulação eletrônica (o STM32 fixa a frequência).')
            return
        if getattr(self, 'dual_active', False):
            self.flash('A varredura do Modo Duplo está em andamento.')
            return
        f, pwm, tau = self.sp_ot_f.value(), self.sp_ot_pwm.value(), self.sp_ot_tau.value()
        self.sweep_restore = self._excitation_snapshot()
        self.sweep_kind, self.sweep_target = 'T', 'OPT'
        self.sweep_legacy = False
        self.sweep_freqs, self.sweep_idx, self.sweep_results = [0.0], 0, []
        self.sweep_params = {'kind': 'T', 'freq': f, 'pwm': pwm, 'tau': tau, 'dt': self.sp_ot_dt.value(),
                             'normalize_mode': self.normalize_mode, 'f_start': 0.0, 'f_stop': 0.0,
                             'f_step': self.sp_ot_dt.value()}
        chk_w, sp_w, _p, _e = self.warm_w.get(self.btn_sweeps['T'], (None, None, None, None))
        self.opt_warm_s = float(sp_w.value()) if (chk_w is not None and chk_w.isChecked()) else 0.0
        self._set_spin(self.sp_freq, f)
        self.apply_frequency(f)
        self.sp_tau.setValue(tau)
        self.sp_power.setValue(pwm)
        self.on_power(self.sp_power.value())
        self.sweep_active = True
        self.sweep_state = 'MEASURING'
        self._clear_sweep_buffers()
        now = time.perf_counter()
        self.ot_t0 = self.ot_timer = now
        self.sweep_settle_time = 7.0 * tau
        for b in self.btn_sweeps.values():
            b.setEnabled(False)
        btn = self.btn_sweeps['T']
        btn.setEnabled(True)
        btn.setText('⏹ Parar')
        btn.setStyleSheet('background:#f8d7da;')
        for w in (self.sp_freq, self.sp_power, self.sp_tau, self.sp_ot_f, self.sp_ot_pwm, self.sp_ot_tau,
                  self.sp_ot_dt, self.sp_ot_dur):
            w.setEnabled(False)
        bar = self.sweep_bars[('OPT', 'T')]
        bar.setValue(0)
        bar.setVisible(self.sp_ot_dur.value() > 0)
        self._set_eta_style(True)
        print(f'Sinal x t (OPT101): {f:g} Hz, PWM {pwm:g} %, τ = {tau:g} s, ponto a cada {self.sp_ot_dt.value():g} s, '
              + (f'{self.sp_ot_dur.value():g} min' if self.sp_ot_dur.value() else 'até parar'))

    def _opt_time_step(self, now):
        t = now - self.ot_t0
        dt = self.sweep_params['dt']
        dur = self.sp_ot_dur.value() * 60.0
        n = len(self.sweep_results)
        lbl = self.eta_labels['T']
        if dur:
            self.sweep_bars[('OPT', 'T')].setValue(int(1000 * min(1.0, t / dur)))
            lbl.setText(f'Restante: {self._fmt_time(dur - t)}')
        else:
            lbl.setText(f'Decorrido: {self._fmt_time(t)}')
        fp = f"{self.sweep_params['freq']:g} Hz, PWM {self.sweep_params['pwm']:g} %"
        settle = self.sweep_settle_time
        if t < settle:
            self._clear_sweep_buffers()
            self.ot_timer = now
            self.sweep_status_text = f'Sinal x t OPT101: {self._fmt_time(t)} | lock-in assentando ({t:.0f}/{settle:.0f} s), {fp}'
            return
        self.sweep_status_text = (f'Sinal x t OPT101: {self._fmt_time(t)}' + (f' de {self._fmt_time(dur)}' if dur else '')
                                  + f' | {fp} | {n} ponto(s)')
        if now - self.ot_timer >= dt:
            if self.sweep_count > 0:
                r = np.concatenate(self.sweep_chunks_r)
                p = np.concatenate(self.sweep_chunks_p)
                dc = np.concatenate(self.sweep_chunks_dc)
                tm = 0.5 * (self.ot_timer + now) - self.ot_t0
                self.sweep_results.append((tm, float(r.mean()), float(r.std()), *circ_stats_deg(p), float(dc.mean())))
            self._clear_sweep_buffers()
            self.ot_timer = now
        if dur and t >= dur:
            self._finish_opt_time()

    def _finish_opt_time(self):
        self.finish_and_export_sweep()

    def _opt_export_time(self):
        rows = list(self.sweep_results)
        pr = self.sweep_params
        now_dt = datetime.now()
        stem = self._stem(f"OPT101_T_sinal_t_f{pr['freq']:g}Hz_pwm{pr['pwm']:g}_{now_dt.strftime('%Y%m%d_%H%M%S')}")
        os.makedirs(self._save_dir(), exist_ok=True)
        filename = os.path.join(self._save_dir(), stem + '.csv')
        png_filename = os.path.join(self._save_dir(), stem + '.png')
        mode_str = 'Normalizado (R/DC %)' if pr.get('normalize_mode') else 'Bruto (u.a.)'
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                f.write(f"# Sinal x t - OPT101 - Lock-In TL-Arduino\n# Data/Hora: {now_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"# Parametros: Freq={pr['freq']} Hz, PWM={pr['pwm']} %, Tau={pr['tau']} s, "
                        f"Ponto_a_cada={pr['dt']} s\n# Modo: {mode_str}\n# Warm-up = {getattr(self, 'opt_warm_s', 0.0):g} s\n")
                f.write('Tempo_s,Magnitude_Media,Magnitude_DesvioPadrao,Fase_Media_Graus,Fase_DesvioPadrao_Graus,DC_Offset_Medio\n')
                for r in rows:
                    f.write(f'{r[0]:.2f},{r[1]:.5f},{r[2]:.5f},{r[3]:.3f},{r[4]:.3f},{r[5]:.2f}\n')
            self._session_add(filename)
            self.sweep_last_csv = filename
            print(f'Sinal x t concluído! Dados em: {filename}')
        except Exception as e:
            print(f'Erro ao salvar arquivo CSV: {e}')
        self.show_sweep_results('T', 0.0, rows[-1][0] if rows else 0.0, pr['dt'], mode_str, filename, png_filename, 'OPT101')
        self.flash(f'Sinal x t concluído: {filename}', 6.0)
